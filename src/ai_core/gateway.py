"""
Enterprise Model Gateway with Stage-Based Routing, Circuit Breaker, and 4-Tier Degradation.

Centralized entry point for all LLM reasoning in the Voice AI Agent platform.
Enforces:
1. Stage-based deterministic model selection (Groq Llama 3.1 8B vs 3.3 70B).
2. Per-provider Circuit Breaker with instant failover to Google Gemini.
3. Strict Time-to-First-Token (TTFT 3.5s) timeout and voice max_tokens clamping (150).
4. 4-tier graceful degradation (Primary -> Backup -> Search-Only -> Receptionist).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from enum import Enum
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

import litellm
from litellm.exceptions import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
)
from pydantic import BaseModel, Field

from src.ai_core.circuit_breaker import CircuitBreaker
from src.config import Settings, get_settings
from src.tools.human_handoff import detect_emergency

logger = logging.getLogger(__name__)

# Harden litellm globals at module load
litellm.telemetry = False
litellm.success_callback = []
litellm.failure_callback = []
litellm.drop_params = True


# ==============================================================================
# Domain Types and Enums
# ==============================================================================


class Stage(str, Enum):
    """Workflow stage requesting LLM reasoning."""

    CLASSIFICATION = "classification"  # Intent classification (8B)
    EXTRACTION = "extraction"  # Parameter/entity extraction (8B)
    DIALOGUE = "dialogue"  # Caller-facing conversational voice turn (70B)


class DegradationTier(str, Enum):
    """Graceful degradation tiers."""

    TIER_1_PRIMARY = "TIER_1_PRIMARY"  # High-speed primary LLM (Groq)
    TIER_2_BACKUP = "TIER_2_BACKUP"  # Independent backup LLM (Google Gemini)
    TIER_3_SEARCH_ONLY = "TIER_3_SEARCH_ONLY"  # Grounded retrieval snippet from KB
    TIER_4_HUMAN_ESCALATION = "TIER_4_HUMAN_ESCALATION"  # Front-desk / Emergency receptionist


class ProviderAttempt(BaseModel):
    """Log of an individual provider attempt in the gateway."""

    provider: str
    model: str
    outcome: str  # "success", "failed", "skipped_open", "skipped_unconfigured"
    latency_ms: float = 0.0
    error_class: str | None = None
    error_message: str | None = None


class GatewayResult(BaseModel):
    """Unified result contract returned by the Model Gateway."""

    success: bool
    text: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    stage: Stage
    provider: str | None = None
    model: str | None = None
    degradation_tier: DegradationTier
    escalate: bool = False
    truncated: bool = False
    finish_reason: str | None = None
    ttft_ms: float | None = None
    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_class: str | None = None
    attempts: list[ProviderAttempt] = Field(default_factory=list)


# ==============================================================================
# Error Classification Helper
# ==============================================================================


def classify_error(exc: Exception) -> tuple[bool, str]:
    """
    Classify an exception into (is_retryable, error_class_name).

    Retryable errors count toward tripping the circuit breaker (timeouts, 429, 5xx, connection).
    Non-retryable client errors (400, 401, 403, 404, 422) do not trip the breaker.
    """
    if isinstance(exc, (Timeout, asyncio.TimeoutError)):
        return True, "timeout"
    if isinstance(exc, APIConnectionError):
        return True, "connection_error"
    if isinstance(exc, RateLimitError):
        return True, "rate_limit"
    if isinstance(exc, (InternalServerError, ServiceUnavailableError)):
        return True, "server_error"
    if isinstance(exc, (BadRequestError, UnprocessableEntityError)):
        return False, "bad_request"
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return False, "auth_error"
    if isinstance(exc, NotFoundError):
        return False, "not_found"

    # Status-code based inspection fallback
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        try:
            code = int(status_code)
            if code == 429:
                return True, "rate_limit"
            if code >= 500:
                return True, "server_error"
            if 400 <= code < 500:
                return False, "client_error"
        except (ValueError, TypeError):
            pass

    # Generic unhandled exception: default to retryable to protect voice SLA
    return True, "unknown_error"


# ==============================================================================
# LLM Provider Protocol & Implementation
# ==============================================================================


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for pluggable LLM backends."""

    name: str

    def is_configured(self) -> bool:
        """Check if provider credentials are valid and present."""
        ...

    def astream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        ttft_timeout_s: float = 3.5,
        total_timeout_s: float = 10.0,
    ) -> AsyncGenerator[tuple[str | None, list[dict[str, Any]] | None, dict[str, Any]], None]:
        """
        Stream chunks from the provider.
        Yields: (text_chunk, tool_calls_delta, metadata_dict)
        """
        ...


class LiteLLMProvider:
    """LiteLLM adapter executing streaming Chat Completions."""

    def __init__(self, name: str, api_key: str) -> None:
        self.name = name
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(self.api_key and "your_" not in self.api_key)

    async def astream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        ttft_timeout_s: float = 3.5,
        total_timeout_s: float = 10.0,
    ) -> AsyncGenerator[tuple[str | None, list[dict[str, Any]] | None, dict[str, Any]], None]:
        """Stream chunks with TTFT and total timeouts."""
        start_time = time.monotonic()
        first_chunk_received = False
        ttft_ms: float | None = None

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            "num_retries": 0,
            "api_key": self.api_key,
            "drop_params": True,
        }
        if tools:
            kwargs["tools"] = tools

        response_stream = await litellm.acompletion(**kwargs)

        async def _get_next_chunk(aiter_obj: Any) -> Any:
            return await aiter_obj.__anext__()

        stream_iter = response_stream.__aiter__()

        while True:
            elapsed = time.monotonic() - start_time
            remaining_total = total_timeout_s - elapsed
            if remaining_total <= 0:
                raise Timeout("Total request timeout exceeded in LiteLLM stream")

            if not first_chunk_received:
                timeout_for_chunk = min(ttft_timeout_s, remaining_total)
            else:
                timeout_for_chunk = remaining_total

            try:
                chunk = await asyncio.wait_for(
                    _get_next_chunk(stream_iter), timeout=timeout_for_chunk
                )
            except StopAsyncIteration:
                break

            now = time.monotonic()
            if not first_chunk_received:
                first_chunk_received = True
                ttft_ms = (now - start_time) * 1000.0

            text_chunk: str | None = None
            tool_calls_delta: list[dict[str, Any]] | None = None
            finish_reason: str | None = None
            usage_dict: dict[str, int] | None = None

            # Parse chunk choices
            choices = getattr(chunk, "choices", None)
            if choices and len(choices) > 0:
                choice = choices[0]
                finish_reason = getattr(choice, "finish_reason", None)
                delta = getattr(choice, "delta", None)
                if delta:
                    content = getattr(delta, "content", None)
                    if content:
                        text_chunk = content

                    t_calls = getattr(delta, "tool_calls", None)
                    if t_calls:
                        tool_calls_delta = [
                            tc.model_dump() if hasattr(tc, "model_dump") else dict(tc)
                            for tc in t_calls
                        ]

            # Parse usage (returned in last chunk by OpenAI / LiteLLM when stream_options.include_usage=True)
            usage = getattr(chunk, "usage", None)
            if usage:
                usage_dict = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                }

            meta = {
                "ttft_ms": ttft_ms,
                "finish_reason": finish_reason,
                "usage": usage_dict,
                "elapsed_ms": (now - start_time) * 1000.0,
            }

            yield text_chunk, tool_calls_delta, meta


# ==============================================================================
# Model Gateway Core
# ==============================================================================


class ModelGateway:
    """
    Central AI Model Gateway implementing stage routing, circuit breaker failover,
    and 4-tier degradation.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        primary_provider: LLMProvider | None = None,
        fallback_provider: LLMProvider | None = None,
        primary_breaker: CircuitBreaker | None = None,
        fallback_breaker: CircuitBreaker | None = None,
        search_fallback: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()

        # Primary provider: Groq
        self.primary_provider = primary_provider or LiteLLMProvider(
            name="groq",
            api_key=self.settings.groq_api_key,
        )
        self.primary_breaker = primary_breaker or CircuitBreaker(
            name="groq",
            failure_threshold=self.settings.circuit_breaker_failure_threshold,
            window_s=self.settings.circuit_breaker_window_s,
            cooldown_s=self.settings.circuit_breaker_cooldown_s,
        )

        # Fallback provider: Google Gemini
        self.fallback_provider = fallback_provider or LiteLLMProvider(
            name="gemini",
            api_key=self.settings.gemini_api_key,
        )
        self.fallback_breaker = fallback_breaker or CircuitBreaker(
            name="gemini",
            failure_threshold=self.settings.circuit_breaker_failure_threshold,
            window_s=self.settings.circuit_breaker_window_s,
            cooldown_s=self.settings.circuit_breaker_cooldown_s,
        )

        self._search_fallback = search_fallback

    def resolve_model(self, provider_name: str, stage: Stage) -> str:
        """Resolve model identifier for provider and workflow stage."""
        if provider_name == "groq":
            if stage in (Stage.CLASSIFICATION, Stage.EXTRACTION):
                model_name = self.settings.llm_stage_model
            else:
                model_name = self.settings.groq_model
            return f"groq/{model_name}" if not model_name.startswith("groq/") else model_name

        if provider_name == "gemini":
            model_name = self.settings.gemini_fallback_model
            return f"gemini/{model_name}" if not model_name.startswith("gemini/") else model_name

        raise ValueError(f"Unknown provider: {provider_name}")

    def resolve_max_tokens(self, stage: Stage, requested: int | None) -> int:
        """Resolve and clamp max_tokens based on stage rules."""
        if stage == Stage.DIALOGUE:
            limit = self.settings.voice_max_tokens
            if requested is not None:
                return min(requested, limit)
            return limit
        else:
            limit = self.settings.stage_max_tokens
            if requested is not None:
                return min(requested, limit)
            return limit

    async def _execute_search_fallback(self, query: str) -> str | None:
        """Execute Tier 3 knowledge base retrieval fallback within 400ms."""
        if self._search_fallback is not None:
            try:
                res = self._search_fallback(query)
                if inspect.isawaitable(res):
                    return await asyncio.wait_for(res, timeout=0.4)
                return str(res) if res else None
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Tier 3 custom search fallback error: {e}")
                return None

        # Default fallback to existing clinic knowledge search tool
        try:
            from src.tools.knowledge_search import async_search_clinic_knowledge

            tool_res = await asyncio.wait_for(
                async_search_clinic_knowledge(query=query, limit=1),
                timeout=0.4,
            )
            if tool_res.success and tool_res.message:
                return tool_res.message
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Tier 3 knowledge search fallback error: {e}")
            return None

    def _extract_last_user_query(self, messages: list[dict[str, Any]]) -> str:
        """Extract content of last user utterance for fallback search and emergency detection."""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    # Multimodal or block content
                    parts = [
                        p.get("text", "") for p in content if isinstance(p, dict) and "text" in p
                    ]
                    return " ".join(parts)
        return ""

    async def astream(
        self,
        stage: Stage,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[tuple[str | None, GatewayResult | None], None]:
        """
        Stream output tokens for a request, failing over transparently if needed.
        Yields: (text_chunk, final_result_or_none)
        When streaming completes, the final item yielded has text_chunk=None and the full GatewayResult.
        """
        start_overall = time.monotonic()
        temp = temperature if temperature is not None else self.settings.llm_temperature
        clamped_tokens = self.resolve_max_tokens(stage, max_tokens)

        # Validate input
        if not messages:
            res = GatewayResult(
                success=False,
                stage=stage,
                degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION,
                error_class="invalid_request",
                latency_ms=0.0,
            )
            yield None, res
            return

        attempts: list[ProviderAttempt] = []
        providers = [
            (self.primary_provider, self.primary_breaker, DegradationTier.TIER_1_PRIMARY),
            (self.fallback_provider, self.fallback_breaker, DegradationTier.TIER_2_BACKUP),
        ]

        # Try providers in order
        for provider, breaker, tier in providers:
            model = self.resolve_model(provider.name, stage)

            if not provider.is_configured():
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        outcome="skipped_unconfigured",
                    )
                )
                continue

            allowed = await breaker.allow_request()
            if not allowed:
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        outcome="skipped_open",
                    )
                )
                continue

            # Attempt stream with this provider
            start_attempt = time.monotonic()
            chunks_yielded = 0
            accumulated_text: list[str] = []
            tool_calls_map: dict[int, dict[str, Any]] = {}
            ttft_ms: float | None = None
            finish_reason: str | None = None
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            stream_failed = False

            try:
                stream_generator = provider.astream(
                    model=model,
                    messages=messages,
                    temperature=temp,
                    max_tokens=clamped_tokens,
                    tools=tools,
                    ttft_timeout_s=self.settings.llm_ttft_timeout_s,
                    total_timeout_s=self.settings.llm_request_timeout_s,
                )

                async for text_chunk, t_deltas, meta in stream_generator:
                    if meta.get("ttft_ms") is not None and ttft_ms is None:
                        ttft_ms = meta["ttft_ms"]

                    if meta.get("finish_reason"):
                        finish_reason = meta["finish_reason"]

                    if meta.get("usage"):
                        u = meta["usage"]
                        prompt_tokens = u.get("prompt_tokens", prompt_tokens)
                        completion_tokens = u.get("completion_tokens", completion_tokens)
                        total_tokens = u.get("total_tokens", total_tokens)

                    # Accumulate text
                    if text_chunk:
                        accumulated_text.append(text_chunk)
                        chunks_yielded += 1
                        yield text_chunk, None

                    # Accumulate tool calls
                    if t_deltas:
                        for td in t_deltas:
                            idx = td.get("index", 0)
                            if idx not in tool_calls_map:
                                tool_calls_map[idx] = {
                                    "id": td.get("id") or f"call_{idx}",
                                    "type": "function",
                                    "function": {
                                        "name": td.get("function", {}).get("name") or "",
                                        "arguments": "",
                                    },
                                }
                            else:
                                if td.get("id"):
                                    tool_calls_map[idx]["id"] = td["id"]
                                if td.get("function", {}).get("name"):
                                    tool_calls_map[idx]["function"]["name"] = td["function"]["name"]

                            arg_chunk = td.get("function", {}).get("arguments")
                            if arg_chunk:
                                tool_calls_map[idx]["function"]["arguments"] += arg_chunk

            except Exception as e:  # noqa: BLE001
                stream_failed = True
                is_retryable, err_cls = classify_error(e)
                attempt_latency = (time.monotonic() - start_attempt) * 1000.0

                logger.warning(
                    f"Gateway provider [{provider.name}] failed (chunks_yielded={chunks_yielded}, "
                    f"retryable={is_retryable}, err_class={err_cls}): {e}"
                )
                await breaker.record_failure(is_retryable=is_retryable)

                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        outcome="failed",
                        latency_ms=attempt_latency,
                        error_class=err_cls,
                        error_message=str(e),
                    )
                )

                # D8 Semantics: Mid-stream failure (after first token was yielded) does NOT fail over
                if chunks_yielded > 0:
                    overall_lat = (time.monotonic() - start_overall) * 1000.0
                    final_text = "".join(accumulated_text)
                    stitched_tools = [tool_calls_map[k] for k in sorted(tool_calls_map.keys())]

                    final_res = GatewayResult(
                        success=False,
                        text=final_text if final_text else None,
                        tool_calls=stitched_tools,
                        stage=stage,
                        provider=provider.name,
                        model=model,
                        degradation_tier=tier,
                        escalate=False,
                        truncated=True,
                        finish_reason="error",
                        ttft_ms=ttft_ms,
                        latency_ms=overall_lat,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        error_class=err_cls,
                        attempts=attempts,
                    )
                    yield None, final_res
                    return

                # If no chunks were yielded yet, loop proceeds to next provider in failover ladder!
                continue

            if not stream_failed:
                # Provider succeeded!
                await breaker.record_success()
                attempt_latency = (time.monotonic() - start_attempt) * 1000.0
                attempts.append(
                    ProviderAttempt(
                        provider=provider.name,
                        model=model,
                        outcome="success",
                        latency_ms=attempt_latency,
                    )
                )

                overall_lat = (time.monotonic() - start_overall) * 1000.0
                final_text = "".join(accumulated_text)
                stitched_tools = [tool_calls_map[k] for k in sorted(tool_calls_map.keys())]

                final_res = GatewayResult(
                    success=True,
                    text=final_text if final_text else None,
                    tool_calls=stitched_tools,
                    stage=stage,
                    provider=provider.name,
                    model=model,
                    degradation_tier=tier,
                    escalate=False,
                    truncated=False,
                    finish_reason=finish_reason or "stop",
                    ttft_ms=ttft_ms,
                    latency_ms=overall_lat,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    attempts=attempts,
                )
                yield None, final_res
                return

        # ==============================================================================
        # Degradation Tiers 3 & 4 (Both LLMs failed or skipped)
        # ==============================================================================
        overall_lat = (time.monotonic() - start_overall) * 1000.0

        if stage != Stage.DIALOGUE:
            # Extraction/Classification cannot be satisfied by snippets
            yield (
                None,
                GatewayResult(
                    success=False,
                    text=None,
                    tool_calls=[],
                    stage=stage,
                    degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION,
                    escalate=False,
                    latency_ms=overall_lat,
                    error_class="all_providers_unavailable",
                    attempts=attempts,
                ),
            )
            return

        user_query = self._extract_last_user_query(messages)

        # Check for emergency symptoms first (R6.3)
        if user_query and detect_emergency(user_query):
            em_msg = (
                f"حالتك تستدعي رعاية طبية عاجلة. يرجى الاتصال بالإسعاف على رقم {self.settings.emergency_phone} فوراً، "
                "وجاري تحويلك لموظف الاستقبال لمساعدتك."
            )
            yield em_msg, None
            yield (
                None,
                GatewayResult(
                    success=True,
                    text=em_msg,
                    tool_calls=[],
                    stage=stage,
                    degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION,
                    escalate=True,
                    latency_ms=overall_lat,
                    error_class="emergency_detected",
                    attempts=attempts,
                ),
            )
            return

        # Tier 3: Search fallback (R6.4)
        snippet = await self._execute_search_fallback(user_query) if user_query else None
        if snippet:
            t3_msg = f"عفواً، بنواجه ضغط على النظام حالياً، لكن حسب معلومات العيادة: {snippet}"
            if len(t3_msg) > 300:
                t3_msg = t3_msg[:297] + "..."

            yield t3_msg, None
            yield (
                None,
                GatewayResult(
                    success=True,
                    text=t3_msg,
                    tool_calls=[],
                    stage=stage,
                    degradation_tier=DegradationTier.TIER_3_SEARCH_ONLY,
                    escalate=False,
                    latency_ms=overall_lat,
                    error_class="degraded_search_only",
                    attempts=attempts,
                ),
            )
            return

        # Tier 4: Human receptionist escalation (R6.4 fallback)
        t4_msg = "عفواً، بنواجه عطل تقني مؤقت في الخدمة، جاري تحويلك لموظف الاستقبال لمساعدتك حالاً."
        yield t4_msg, None
        yield (
            None,
            GatewayResult(
                success=True,
                text=t4_msg,
                tool_calls=[],
                stage=stage,
                degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION,
                escalate=True,
                latency_ms=overall_lat,
                error_class="all_providers_failed",
                attempts=attempts,
            ),
        )

    async def agenerate(
        self,
        stage: Stage,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> GatewayResult:
        """
        Non-streaming generation returning the complete GatewayResult.
        """
        final_result: GatewayResult | None = None
        async for _, res in self.astream(
            stage=stage,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        ):
            if res is not None:
                final_result = res

        assert final_result is not None, "Gateway stream yielded no final result"
        return final_result


# ==============================================================================
# Singleton Factory
# ==============================================================================

_gateway_instance: ModelGateway | None = None


def get_gateway() -> ModelGateway:
    """Return singleton instance of ModelGateway."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = ModelGateway()
    return _gateway_instance
