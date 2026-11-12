"""
LiveKit-Agnostic Clinic Turn Engine & Verified Caller Identity Orchestrator (Feature 5.4).

Connects real-time caller speech turns to the Phase 4 enterprise AI stack:
1. Hierarchical W3C tracing (`trace_scope`), FinOps session scope (`finops_session_scope`),
   and verified caller scope (`caller_session_scope`).
2. Context-aware `InputGuardrail` (< 20ms CPU) with deterministic medical emergency
   short-circuiting (`async_transfer_to_receptionist(urgency='critical')` + `build_emergency_message`).
3. Pre-flight `FinOpsController.check_budget()` (8,000 tokens/call, $10/day cap).
4. Breakout-safe XML delimiter wrapping (`wrap_caller_utterance`, `wrap_retrieved_context`)
   and `CacheLadder` lookup for public read-only clinic inquiries.
5. Streaming `ModelGateway.astream(Stage.DIALOGUE, ...)` with an explicit 5-tool
   `CALLER_TOOL_ALLOWLIST` and session-scoped OpenAI tool schemas stripped of phone fields.
6. Differentiated tool timeout & filler orchestration:
   - Read tools abort at `session_tool_timeout_ms` (`400ms`) and emit a localized filler.
   - Write tools (`book_appointment`, `manage_appointment` cancel/reschedule, `transfer_to_receptionist`)
     intercept unverified callers before any database write, emit a localized filler at `400ms`
     while continuing shielded (`asyncio.shield`) up to `write_tool_hard_cap_ms` (`3000ms`),
     and escalate to reception if the hard cap is exceeded.
7. Sentence-buffered `OutputGuardrail.validate()`, schema-aware tool payload pruning,
   `CallSession` metric/turn recording, and off-hot-path `AsyncLlamaGuardClassifier` auditing.
"""

from __future__ import annotations

import os

# Prevent LiteLLM from fetching remote model cost maps over HTTP at import time (NFR1 / T1.8)
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import asyncio
import contextlib
import copy
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agent.messages import is_english
from src.agent.prompts import (
    build_dynamic_context,
    build_emergency_message,
    build_error_fallback_message,
    build_handoff_message,
    build_medical_refusal_message,
    build_out_of_scope_message,
    build_static_system_prompt,
    build_tool_filler_message,
)
from src.agent.session_manager import (
    CallActivity,
    CallLifecycle,
    CallSession,
    MessageRole,
)
from src.config import Settings, get_settings
from src.db.schemas import clean_egyptian_phone

if TYPE_CHECKING:
    from src.ai_core.cache import CacheLadder
    from src.ai_core.finops import FinOpsController
    from src.ai_core.gateway import GatewayResult, ModelGateway
    from src.ai_core.guardrails import (
        AsyncLlamaGuardClassifier,
        InputGuardrail,
        OutputGuardrail,
    )
    from src.ai_core.tracing import HierarchicalTracer
    from src.tools.schemas import ToolResult

logger = logging.getLogger(__name__)


async def async_execute_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Lazy wrapper around `src.tools.async_execute_tool` keeping module import fast and offline."""
    from src.tools import async_execute_tool as _impl

    return await _impl(tool_name, arguments)


async def async_transfer_to_receptionist(**kwargs: Any) -> Any:
    """Lazy wrapper around `src.tools.human_handoff.async_transfer_to_receptionist`."""
    from src.tools.human_handoff import async_transfer_to_receptionist as _impl

    return await _impl(**kwargs)


def _detect_emergency(text: str) -> bool:
    """Lazy wrapper around `src.tools.human_handoff.detect_emergency`."""
    from src.tools.human_handoff import detect_emergency as _impl

    return _impl(text)

# ==============================================================================
# 1. Caller Tool Allowlist & Read/Write Classification (R2, R4)
# ==============================================================================

CALLER_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    {
        "check_doctor_availability",
        "book_appointment",
        "manage_appointment",
        "search_clinic_knowledge",
        "transfer_to_receptionist",
    }
)

READ_TOOLS: frozenset[str] = frozenset(
    {
        "check_doctor_availability",
        "search_clinic_knowledge",
    }
)

WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "book_appointment",
        "transfer_to_receptionist",
    }
)

_STRIPPED_SCHEMA_PHONE_FIELDS: frozenset[str] = frozenset(
    {
        "patient_phone",
        "phone",
        "caller_phone",
        "customer_phone",
        "patient_id",
    }
)

_SHORT_CONFIRMATION_UTTERANCES: frozenset[str] = frozenset(
    {
        "ايوه",
        "أيوة",
        "ايوة",
        "اه",
        "آه",
        "نعم",
        "تمام",
        "ماشي",
        "اكيد",
        "أكيد",
        "موافق",
        "موافقه",
        "موافقة",
        "احجز",
        "اكد",
        "أكد",
        "لا",
        "لأ",
        "خلاص",
        "شكرا",
        "شكراً",
        "yes",
        "yep",
        "yeah",
        "sure",
        "ok",
        "okay",
        "confirm",
        "no",
    }
)

# Sentence boundary splitter avoiding common Arabic/English honorific abbreviations ("د.", "أ.", "م.", "Dr.")
_SENTENCE_SPLIT_RE = re.compile(
    r"(?<!\bد)(?<!\bأ)(?<!\bم)(?<!\bDr)(?<!\bMr)(?<!\bMs)(?<!\bMrs)([.!؟?\n]+)\s+"
)


def is_write_tool_call(tool_name: str, arguments: dict[str, Any] | None = None) -> bool:
    """
    Return True if a tool invocation performs a state-mutating write or receptionist handoff:
    - `book_appointment`
    - `transfer_to_receptionist`
    - `manage_appointment` when `action` is `'cancel'` or `'reschedule'`
    Read-only calls (`check_doctor_availability`, `search_clinic_knowledge`, and
    `manage_appointment(action='lookup')`) return False.
    """
    norm_name = (tool_name or "").strip()
    if norm_name in WRITE_TOOLS:
        return True
    if norm_name == "manage_appointment":
        action = str((arguments or {}).get("action", "lookup")).strip().lower()
        return action in ("cancel", "reschedule")
    return False


def requires_verified_caller_phone(
    tool_name: str, arguments: dict[str, Any] | None = None
) -> bool:
    """
    Return True when a tool call mutates patient appointment records and therefore
    requires a verified `caller_phone` from SIP or signed JWT attributes (R3 / D2).
    """
    norm_name = (tool_name or "").strip()
    if norm_name == "book_appointment":
        return True
    if norm_name == "manage_appointment":
        action = str((arguments or {}).get("action", "lookup")).strip().lower()
        return action in ("cancel", "reschedule")
    return False


def get_caller_tool_definitions() -> list[dict[str, Any]]:
    """
    Build OpenAI / Groq function schemas strictly filtered to `CALLER_TOOL_ALLOWLIST`
    with all caller phone/identity fields stripped from parameter schemas (R2 / T1.3).
    """
    from src.tools import get_session_scoped_tool_definitions

    raw_defs = get_session_scoped_tool_definitions()
    filtered: list[dict[str, Any]] = []

    for item in raw_defs:
        fn = item.get("function") or {}
        name = fn.get("name", "")
        if name not in CALLER_TOOL_ALLOWLIST:
            continue

        cloned = copy.deepcopy(item)
        params = cloned.get("function", {}).get("parameters")
        if isinstance(params, dict):
            props = params.get("properties")
            if isinstance(props, dict):
                for field_name in _STRIPPED_SCHEMA_PHONE_FIELDS:
                    props.pop(field_name, None)
            req = params.get("required")
            if isinstance(req, list):
                params["required"] = [
                    r for r in req if r not in _STRIPPED_SCHEMA_PHONE_FIELDS
                ]
        filtered.append(cloned)

    return filtered


def _build_unverified_write_handoff_text(language: str = "ar") -> str:
    """Polite TTS-safe explanation when an unverified caller requests a booking/cancel/reschedule."""
    if is_english(language):
        return (
            "To safely confirm or update your appointment since your mobile number is not verified "
            "on this session, I am transferring you now to our receptionist to complete it right away."
        )
    return (
        "حفاظاً على أمان بيانات الحجز ولأن رقم الموبايل غير موثق تلقائياً في الجلسة الحالية، "
        "هحول حضرتك حالاً لموظف الاستقبال لتأكيد الإجراء مع حضرتك فوراً."
    )


# ==============================================================================
# 2. Verified Caller Identity Model (R3)
# ==============================================================================


class VerifiedCallerIdentity(BaseModel):
    """
    Verified caller identity extracted strictly from SIP trunk attributes
    (`sip.phoneNumber`) or cryptographically signed LiveKit JWT attributes (`caller_phone`).
    Never populated from spoken caller transcript or untrusted LLM arguments.
    """

    model_config = ConfigDict(extra="forbid")

    caller_phone: str | None = Field(
        default=None,
        description="Verified Egyptian mobile/landline number, or None when unverified.",
    )
    caller_name: str | None = Field(
        default=None,
        description="Optional caller display name from participant metadata.",
    )
    tenant_id: str = Field(
        default="default",
        description="Clinic tenant identifier.",
    )
    branch_id: str = Field(
        default="main",
        description="Clinic branch identifier.",
    )
    language: str = Field(
        default="ar",
        description="Resolved single-call language ('ar' or 'en').",
    )
    source: str = Field(
        default="unverified",
        description="Origin of verified identity ('sip', 'jwt', 'room', or 'unverified').",
    )

    @field_validator("caller_phone", mode="before")
    @classmethod
    def _normalize_phone(cls, val: Any) -> str | None:
        if val is None:
            return None
        raw = str(val).strip()
        if not raw:
            return None
        try:
            return clean_egyptian_phone(raw)
        except ValueError:
            return None

    @field_validator("language", mode="before")
    @classmethod
    def _normalize_language(cls, val: Any) -> str:
        return "en" if is_english(str(val) if val is not None else "ar") else "ar"

    @field_validator("tenant_id", mode="before")
    @classmethod
    def _normalize_tenant(cls, val: Any) -> str:
        s = str(val).strip() if val is not None else ""
        if s and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", s):
            return s
        return "default"

    @field_validator("branch_id", mode="before")
    @classmethod
    def _normalize_branch(cls, val: Any) -> str:
        s = str(val).strip() if val is not None else ""
        if s and re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", s):
            return s
        return "main"

    @property
    def is_verified(self) -> bool:
        """Return True iff a non-empty verified caller phone is present."""
        return bool(self.caller_phone and self.caller_phone.strip())


# ==============================================================================
# 3. LiveKit-Agnostic Clinic Turn Engine (R1 – R5, NFR1 – NFR3)
# ==============================================================================


class ClinicTurnEngine:
    """
    Orchestrates each conversational voice turn through the Phase 4 safety,
    caching, FinOps, gateway, and clinic tool-execution stack without coupling
    to LiveKit room/audio primitives.
    """

    def __init__(
        self,
        gateway: ModelGateway | Any | None = None,
        cache_ladder: CacheLadder | Any | None = None,
        input_guardrail: InputGuardrail | Any | None = None,
        output_guardrail: OutputGuardrail | Any | None = None,
        finops: FinOpsController | Any | None = None,
        tracer: HierarchicalTracer | Any | None = None,
        *,
        llama_guard: AsyncLlamaGuardClassifier | Any | None = None,
        tool_executor: Callable[[str, dict[str, Any]], Awaitable[ToolResult | dict[str, Any]]]
        | None = None,
        handoff_executor: Callable[..., Awaitable[ToolResult | dict[str, Any]]] | None = None,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from src.ai_core.cache import CacheLadder
        from src.ai_core.finops import get_finops_controller
        from src.ai_core.gateway import ModelGateway
        from src.ai_core.guardrails import (
            get_input_guardrail,
            get_llama_guard_classifier,
            get_output_guardrail,
        )
        from src.ai_core.tracing import get_tracer

        self.settings: Settings = settings or get_settings()
        self.finops = finops if finops is not None else get_finops_controller()
        self.tracer = tracer if tracer is not None else get_tracer()
        self.input_guardrail = (
            input_guardrail if input_guardrail is not None else get_input_guardrail()
        )
        self.output_guardrail = (
            output_guardrail if output_guardrail is not None else get_output_guardrail()
        )
        self.gateway = (
            gateway
            if gateway is not None
            else ModelGateway(settings=self.settings, finops_controller=self.finops)
        )
        self.cache_ladder = (
            cache_ladder
            if cache_ladder is not None
            else CacheLadder(
                settings=self.settings,
                output_validator=self.output_guardrail,
            )
        )
        self.llama_guard = (
            llama_guard if llama_guard is not None else get_llama_guard_classifier()
        )
        self._tool_executor = tool_executor
        self._handoff_executor = handoff_executor
        self._clock = clock
        # Retain strong references to shielded in-flight write tasks across barge-in cancellations (T3.6)
        self._inflight_write_tasks: set[asyncio.Task[Any]] = set()

    @property
    def inflight_write_tasks(self) -> frozenset[asyncio.Task[Any]]:
        """Snapshot of currently running shielded write tasks."""
        return frozenset(self._inflight_write_tasks)

    def _finalize_write_task(self, task: asyncio.Task[Any]) -> None:
        """Discard completed shielded write task and consume any unhandled exception."""
        self._inflight_write_tasks.discard(task)
        if not task.cancelled():
            try:
                exc = task.exception()
            except Exception:  # noqa: BLE001
                exc = None
            if exc is not None:
                from src.ai_core.guardrails import get_pii_redactor

                redacted_err = get_pii_redactor().redact(str(exc))
                logger.warning(
                    "Background shielded write task %s failed (%s): %s",
                    task.get_name(),
                    type(exc).__name__,
                    redacted_err,
                )

    async def _execute_allowlisted_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult | dict[str, Any]:
        """Dispatch an allowlisted clinic tool via injected executor or `async_execute_tool`."""
        if self._tool_executor is not None:
            return await self._tool_executor(tool_name, arguments)
        return await async_execute_tool(tool_name, arguments)

    async def _invoke_handoff(
        self,
        *,
        reason: str,
        department: str = "reception",
        urgency: str = "medium",
        caller_name: str | None = None,
        caller_phone: str | None = None,
        summary: str | None = None,
        session_id: str | None = None,
        language: str = "ar",
    ) -> dict[str, Any]:
        """Execute receptionist escalation shielded from outer cancellation."""
        fn = self._handoff_executor or async_transfer_to_receptionist
        kwargs: dict[str, Any] = {
            "reason": reason,
            "department": department,
            "urgency": urgency,
            "caller_name": caller_name,
            "caller_phone": caller_phone,
            "summary": summary,
            "session_id": session_id,
        }
        task = asyncio.create_task(fn(**kwargs))
        self._inflight_write_tasks.add(task)
        task.add_done_callback(self._finalize_write_task)
        try:
            res = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=max(0.1, float(self.settings.write_tool_hard_cap_ms) / 1000.0),
            )
            if hasattr(res, "model_dump"):
                return res.model_dump()
            if isinstance(res, dict):
                return res
            return {"success": True, "message": str(res)}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Receptionist handoff helper degraded gracefully in session %s: %s",
                session_id,
                type(exc).__name__,
            )
            return {
                "success": True,
                "message": build_handoff_message(language=language),
                "data": {
                    "status": "transferred",
                    "department": department,
                    "urgency": urgency,
                    "reason": reason,
                },
            }

    @staticmethod
    def _record_tool_timeout_on_session(
        session: CallSession,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tool_call_id: str,
        elapsed_ms: float,
        error_code: str = "tool_timeout",
    ) -> None:
        """Record a timed-out tool call and guarantee `metrics.tool_timeouts` increments once."""
        before_timeouts = session.metrics.tool_timeouts
        session.record_tool_call(
            tool_name=tool_name,
            arguments=arguments,
            result={"success": False, "error": error_code},
            tool_call_id=tool_call_id,
            latency_ms=elapsed_ms,
        )
        if session.metrics.tool_timeouts == before_timeouts:
            session.metrics.tool_timeouts += 1

    @staticmethod
    def _parse_tool_arguments(raw_args: Any) -> dict[str, Any]:
        """Safely parse OpenAI/Groq function call arguments into a dictionary."""
        if isinstance(raw_args, dict):
            return dict(raw_args)
        if isinstance(raw_args, str):
            stripped = raw_args.strip()
            if not stripped:
                return {}
            try:
                parsed = json.loads(stripped)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _sanitize_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        identity: VerifiedCallerIdentity,
        session: CallSession,
    ) -> dict[str, Any]:
        """
        Strip untrusted LLM phone/identity fields when `enforce_session_caller_identity` is enabled,
        and populate verified metadata on `transfer_to_receptionist` (C3 / R2).
        """
        cleaned = dict(arguments)
        if self.settings.enforce_session_caller_identity:
            for key in _STRIPPED_SCHEMA_PHONE_FIELDS:
                if key in cleaned:
                    cleaned.pop(key, None)
                    logger.warning(
                        "Stripped untrusted '%s' argument supplied by LLM for tool '%s' [session_id=%s]",
                        key,
                        tool_name,
                        session.session_id,
                    )

        if tool_name == "transfer_to_receptionist":
            if identity.is_verified and identity.caller_phone:
                cleaned["caller_phone"] = identity.caller_phone
            if not cleaned.get("caller_name") and (
                identity.caller_name or session.context.patient_name
            ):
                cleaned["caller_name"] = identity.caller_name or session.context.patient_name
            cleaned.setdefault("session_id", session.session_id)

        return cleaned

    @staticmethod
    def _build_wrapped_llm_history(session: CallSession, max_turns: int) -> list[dict[str, Any]]:
        """
        Build clean user/assistant turn history for `PromptPrefixBuilder`, wrapping every
        untrusted caller utterance in `<caller_utterance>...</caller_utterance>` (OWASP LLM01).
        Tool outcomes from prior turns are summarized deterministically via `build_context_summary()`.
        """
        from src.ai_core.guardrails import wrap_caller_utterance

        conversational = [
            m
            for m in session.messages
            if m.role in (MessageRole.USER, MessageRole.ASSISTANT)
        ]
        if max_turns > 0 and len(conversational) > max_turns:
            conversational = conversational[-max_turns:]

        formatted: list[dict[str, Any]] = []
        for msg in conversational:
            if msg.role == MessageRole.USER:
                formatted.append(
                    {
                        "role": "user",
                        "content": wrap_caller_utterance(msg.content),
                    }
                )
            else:
                formatted.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                    }
                )
        return formatted

    @staticmethod
    def _should_attempt_cache_lookup(utterance: str, session: CallSession) -> bool:
        """
        Allow `CacheLadder` lookup for standalone public inquiries while skipping
        short conversational confirmations (e.g. 'أيوة', 'تمام', 'yes') in multi-turn flows.
        """
        norm = re.sub(r"[^\w\s\u0600-\u06FF]", "", utterance or "").strip().lower()
        if not norm:
            return False
        if norm in _SHORT_CONFIRMATION_UTTERANCES:
            return False
        return not (len(norm) <= 4 and len(session.messages) > 1)

    @staticmethod
    def _extract_ready_sentences(buffer: str) -> tuple[list[str], str]:
        """
        Split `buffer` into complete sentences ready for OutputGuardrail validation + TTS
        and return `(complete_sentences, trailing_remainder)`.
        """
        sentences: list[str] = []
        last_end = 0
        for match in _SENTENCE_SPLIT_RE.finditer(buffer):
            end_idx = match.end()
            candidate = buffer[last_end:end_idx].strip()
            if len(candidate) >= 8:
                sentences.append(candidate)
                last_end = end_idx
        return sentences, buffer[last_end:]

    async def run_turn(
        self,
        utterance: str,
        call_session: CallSession | None = None,
        caller_identity: VerifiedCallerIdentity | None = None,
        *,
        stt_latency_ms: float | None = None,
        custom_instructions: str | None = None,
        record_user_turn: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        Execute one caller conversational turn and yield TTS-ready plain text chunks.
        """
        from src.ai_core.cache import CacheScope, PromptPrefixBuilder
        from src.ai_core.finops import (
            FinOpsGateStatus,
            finops_session_scope,
            format_pruned_tool_message,
        )
        from src.ai_core.gateway import DegradationTier, Stage
        from src.ai_core.guardrails import InputAction, wrap_retrieved_context
        from src.ai_core.tracing import SpanKind, SpanStatus, span_scope, trace_scope
        from src.tools.gates import caller_session_scope

        cleaned_utterance = (utterance or "").strip()
        if not cleaned_utterance:
            return

        turn_start = time.perf_counter()
        session = call_session or CallSession(session_id=f"turn-{uuid.uuid4().hex[:12]}")
        identity = caller_identity or VerifiedCallerIdentity(
            language=session.context.language or self.settings.deepgram_language
        )
        lang: str = "en" if is_english(identity.language or session.context.language) else "ar"
        session.context.language = lang
        if identity.caller_name and not session.context.patient_name:
            session.context.patient_name = identity.caller_name

        caller_cm = (
            caller_session_scope(
                identity.caller_phone,  # type: ignore[arg-type]
                session_id=session.session_id,
                caller_name=identity.caller_name,
                tenant_id=identity.tenant_id,
                branch_id=identity.branch_id,
            )
            if identity.is_verified and identity.caller_phone
            else contextlib.nullcontext()
        )

        try:
            with finops_session_scope(session.session_id), caller_cm:
                async with trace_scope(
                    "voice_turn",
                    tracer=self.tracer,
                    session_id=session.session_id,
                    branch_id=identity.branch_id,
                    input_payload={"utterance": cleaned_utterance, "language": lang},
                    metadata={
                        "tenant_id": identity.tenant_id,
                        "caller_verified": identity.is_verified,
                        "identity_source": identity.source,
                    },
                ) as t_ctx:
                    if record_user_turn:
                        session.add_user_message(cleaned_utterance, stt_latency_ms=stt_latency_ms)
                    else:
                        session._sync_verified_phone_from_scope()
                        session._capture_active_trace_id()

                    session.set_activity(CallActivity.LISTENING)

                    # --------------------------------------------------------------
                    # Step 1: Input Guardrail & Medical Emergency Short-Circuit (R5)
                    # --------------------------------------------------------------
                    spans_before_guard = len(t_ctx.spans)
                    guard_res = self.input_guardrail.evaluate(cleaned_utterance)
                    if len(t_ctx.spans) == spans_before_guard:
                        with span_scope(
                            "input_guardrail.evaluate",
                            kind=SpanKind.GUARDRAIL_INPUT,
                            tracer=self.tracer,
                            input_payload={"text": cleaned_utterance},
                        ) as g_sp:
                            g_sp.set_output(
                                {
                                    "allowed": guard_res.allowed,
                                    "action": str(guard_res.action),
                                }
                            )
                            if not guard_res.allowed:
                                g_sp.set_status(
                                    SpanStatus.BLOCKED,
                                    error_class=str(getattr(guard_res.category, "value", "blocked")),
                                )

                    is_emergency_turn = (
                        guard_res.action == InputAction.ESCALATE_EMERGENCY
                        or _detect_emergency(cleaned_utterance)
                    )
                    if is_emergency_turn:
                        session.mark_emergency(
                            reason="Medical emergency detected in caller utterance"
                        )
                        session.context.is_emergency = True

                        em_t0 = time.perf_counter()
                        with span_scope(
                            "tool.transfer_to_receptionist",
                            kind=SpanKind.TOOL,
                            tracer=self.tracer,
                            input_payload={
                                "urgency": "critical",
                                "department": "emergency",
                            },
                        ) as em_sp:
                            handoff_res = await self._invoke_handoff(
                                reason="Critical medical emergency reported by caller",
                                department="emergency",
                                urgency="critical",
                                caller_name=identity.caller_name or session.context.patient_name,
                                caller_phone=identity.caller_phone,
                                summary="Emergency symptom triage short-circuit",
                                session_id=session.session_id,
                                language=lang,
                            )
                            em_sp.set_output(handoff_res)

                        em_tool_ms = (time.perf_counter() - em_t0) * 1000.0
                        session.record_tool_call(
                            tool_name="transfer_to_receptionist",
                            arguments={"urgency": "critical", "department": "emergency"},
                            result=handoff_res,
                            latency_ms=em_tool_ms,
                        )
                        # Ensure emergency flag remains True alongside escalation state
                        session.context.is_emergency = True

                        em_text = build_emergency_message(language=lang)
                        e2e_ms = (time.perf_counter() - turn_start) * 1000.0
                        session.set_activity(CallActivity.SPEAKING)
                        yield em_text
                        session.add_assistant_message(em_text, latency_ms=e2e_ms)
                        session.set_activity(CallActivity.IDLE)
                        session.refresh_finops_snapshot()
                        t_ctx.output_payload = {
                            "text": em_text,
                            "action": "ESCALATE_EMERGENCY",
                        }
                        return

                    if not guard_res.allowed:
                        if guard_res.action == InputAction.BLOCK_INJECTION:
                            refusal_text = build_out_of_scope_message(language=lang)
                        elif guard_res.action == InputAction.BLOCK_MEDICAL_ADVICE:
                            refusal_text = build_medical_refusal_message(language=lang)
                        else:
                            refusal_text = (
                                guard_res.response_text
                                if (guard_res.response_text and not is_english(lang))
                                else build_out_of_scope_message(language=lang)
                            )

                        e2e_ms = (time.perf_counter() - turn_start) * 1000.0
                        session.set_activity(CallActivity.SPEAKING)
                        yield refusal_text
                        session.add_assistant_message(refusal_text, latency_ms=e2e_ms)
                        session.set_activity(CallActivity.IDLE)
                        session.refresh_finops_snapshot()
                        t_ctx.output_payload = {
                            "text": refusal_text,
                            "action": str(guard_res.action.value),
                        }
                        self.llama_guard.schedule_check(
                            user_text=cleaned_utterance,
                            assistant_text=refusal_text,
                            trace_id=t_ctx.trace_id,
                        )
                        return

                    # --------------------------------------------------------------
                    # Step 2: Pre-Flight FinOps Budget Check (R1)
                    # --------------------------------------------------------------
                    budget_decision = self.finops.check_budget(
                        stage=Stage.DIALOGUE,
                        requested_max_tokens=self.settings.voice_max_tokens,
                        session_id=session.session_id,
                    )
                    if budget_decision.status == FinOpsGateStatus.CALL_BUDGET_EXCEEDED:
                        tier_hint = DegradationTier.TIER_4_HUMAN_ESCALATION
                    elif budget_decision.status == FinOpsGateStatus.DAILY_CAP_EXCEEDED:
                        tier_hint = DegradationTier.TIER_3_SEARCH_ONLY
                    else:
                        tier_hint = DegradationTier.TIER_1_PRIMARY

                    # --------------------------------------------------------------
                    # Step 3: CacheLadder Lookup for Eligible Read-Only Queries (R1)
                    # --------------------------------------------------------------
                    cache_scope = CacheScope(
                        category="general",
                        language="en" if lang == "en" else "ar",
                        tenant_id=identity.tenant_id,
                        branch_id=identity.branch_id,
                    )
                    if (
                        tier_hint == DegradationTier.TIER_1_PRIMARY
                        and self._should_attempt_cache_lookup(cleaned_utterance, session)
                    ):
                        cache_res = await self.cache_ladder.lookup(
                            cleaned_utterance, scope=cache_scope
                        )
                        if cache_res.hit and cache_res.text:
                            cache_verdict = self.output_guardrail.validate(cache_res.text)
                            if cache_verdict.allowed:
                                e2e_ms = (time.perf_counter() - turn_start) * 1000.0
                                session.set_activity(CallActivity.SPEAKING)
                                yield cache_res.text
                                session.add_assistant_message(cache_res.text, latency_ms=e2e_ms)
                                session.set_activity(CallActivity.IDLE)
                                session.refresh_finops_snapshot()
                                t_ctx.output_payload = {
                                    "text": cache_res.text,
                                    "cache_hit": True,
                                    "cache_tier": cache_res.tier.value,
                                }
                                return

                    # --------------------------------------------------------------
                    # Step 4: Assemble Prefix-Cached Prompt & XML-Wrapped History
                    # --------------------------------------------------------------
                    extra_directives: list[str] = []
                    if custom_instructions and custom_instructions.strip():
                        extra_directives.append(custom_instructions.strip())
                    if guard_res.safety_reminder:
                        extra_directives.append(guard_res.safety_reminder)
                    if identity.is_verified:
                        extra_directives.append(
                            "Caller Mobile Status: VERIFIED via session metadata (server binds caller phone automatically)."
                        )
                    else:
                        extra_directives.append(
                            "Caller Mobile Status: UNVERIFIED (read-only queries work normally; booking/cancel/reschedule will transfer to reception)."
                        )
                    context_summary = session.build_context_summary()
                    if context_summary:
                        extra_directives.append(context_summary)

                    now_dt = self._clock() if self._clock is not None else None
                    dynamic_ctx = build_dynamic_context(
                        language=lang,
                        degradation_tier=tier_hint,
                        now=now_dt,
                        custom_instructions="\n".join(extra_directives) if extra_directives else None,
                    )
                    llm_history = self._build_wrapped_llm_history(
                        session, max_turns=self.settings.session_history_window
                    )
                    prefix_builder = PromptPrefixBuilder(
                        static_instructions=build_static_system_prompt()
                    )
                    working_messages, _ = prefix_builder.build(
                        dynamic_context=dynamic_ctx,
                        history=llm_history,
                    )

                    advertised_tools = (
                        get_caller_tool_definitions()
                        if tier_hint == DegradationTier.TIER_1_PRIMARY
                        else None
                    )

                    # --------------------------------------------------------------
                    # Step 5: Bounded Dialogue + Tool Calling Loop (R1, R2, R3, R4)
                    # --------------------------------------------------------------
                    max_rounds = int(self.settings.max_tool_rounds_per_turn)
                    filler_timeout_s = max(
                        0.01, float(self.settings.session_tool_timeout_ms) / 1000.0
                    )
                    hard_cap_s = max(
                        0.01, float(self.settings.write_tool_hard_cap_ms) / 1000.0
                    )

                    spoken_segments: list[str] = []
                    prior_tool_grounding: list[str] = [
                        m.content
                        for m in session.messages
                        if m.role == MessageRole.TOOL and m.content
                    ]
                    retrieved_rag_contexts: list[str] = list(prior_tool_grounding)
                    any_tool_executed = False
                    first_llm_ttft_ms: float | None = None
                    final_tier = tier_hint

                    for round_idx in range(max_rounds + 1):
                        tools_for_round = advertised_tools if round_idx < max_rounds else None

                        snap_before = self.finops.get_session_snapshot(session.session_id)
                        turns_before = snap_before.turns_count if snap_before else 0
                        spans_before_llm = len(t_ctx.spans)

                        round_text_parts: list[str] = []
                        sentence_buffer = ""
                        output_blocked = False
                        final_gw_res: GatewayResult | None = None

                        stream = self.gateway.astream(
                            stage=Stage.DIALOGUE,
                            messages=working_messages,
                            temperature=self.settings.llm_temperature,
                            max_tokens=self.settings.voice_max_tokens,
                            tools=tools_for_round,
                            session_id=session.session_id,
                        )

                        async for text_chunk, gw_res in stream:
                            if gw_res is not None:
                                final_gw_res = gw_res
                            if text_chunk and not output_blocked:
                                round_text_parts.append(text_chunk)
                                sentence_buffer += text_chunk
                                ready_sentences, sentence_buffer = self._extract_ready_sentences(
                                    sentence_buffer
                                )
                                if ready_sentences:
                                    cumulative_so_far = "".join(round_text_parts)
                                    is_tier3_search = (
                                        tier_hint == DegradationTier.TIER_3_SEARCH_ONLY
                                        or (
                                            final_gw_res is not None
                                            and final_gw_res.degradation_tier
                                            == DegradationTier.TIER_3_SEARCH_ONLY
                                        )
                                    )
                                    grounding_ctx = (
                                        "\n".join(retrieved_rag_contexts)
                                        if retrieved_rag_contexts
                                        else (None if is_tier3_search else "[NO_TOOL_GROUNDING]")
                                    )
                                    verdict = self.output_guardrail.validate(
                                        cumulative_so_far,
                                        retrieved_context=grounding_ctx,
                                    )
                                    if not verdict.allowed:
                                        output_blocked = True
                                        fallback_chunk = (
                                            verdict.safe_fallback_text
                                            if (verdict.safe_fallback_text and not is_english(lang))
                                            else build_error_fallback_message(language=lang)
                                        )
                                        prefix = " " if spoken_segments else ""
                                        spoken_segments.append(fallback_chunk)
                                        session.set_activity(CallActivity.SPEAKING)
                                        yield f"{prefix}{fallback_chunk}"
                                    else:
                                        for sent in ready_sentences:
                                            prefix = " " if spoken_segments else ""
                                            spoken_segments.append(sent)
                                            session.set_activity(CallActivity.SPEAKING)
                                            yield f"{prefix}{sent}"

                        # Ensure FinOps usage & LLM child span are recorded even when gateway is a test mock
                        if final_gw_res is not None:
                            if first_llm_ttft_ms is None:
                                first_llm_ttft_ms = (
                                    final_gw_res.ttft_ms
                                    if final_gw_res.ttft_ms is not None
                                    else final_gw_res.latency_ms
                                )
                            final_tier = final_gw_res.degradation_tier

                            snap_after = self.finops.get_session_snapshot(session.session_id)
                            turns_after = snap_after.turns_count if snap_after else 0
                            if turns_after == turns_before and (
                                final_gw_res.prompt_tokens > 0
                                or final_gw_res.completion_tokens > 0
                                or final_gw_res.total_tokens > 0
                            ):
                                self.finops.record_usage(
                                    model=final_gw_res.model or self.settings.groq_model,
                                    prompt_tokens=final_gw_res.prompt_tokens,
                                    completion_tokens=final_gw_res.completion_tokens,
                                    total_tokens=final_gw_res.total_tokens or None,
                                    session_id=session.session_id,
                                )

                            if len(t_ctx.spans) == spans_before_llm:
                                with span_scope(
                                    f"model_gateway.{Stage.DIALOGUE.value}",
                                    kind=SpanKind.LLM,
                                    tracer=self.tracer,
                                    input_payload={
                                        "round": round_idx,
                                        "messages_count": len(working_messages),
                                    },
                                ) as llm_sp:
                                    llm_sp.set_usage(
                                        provider=final_gw_res.provider,
                                        model=final_gw_res.model,
                                        prompt_tokens=final_gw_res.prompt_tokens,
                                        completion_tokens=final_gw_res.completion_tokens,
                                        total_tokens=final_gw_res.total_tokens,
                                        ttft_ms=final_gw_res.ttft_ms,
                                        degradation_tier=final_gw_res.degradation_tier.value,
                                        settings=self.settings,
                                    )
                                    llm_sp.set_output(
                                        {
                                            "text": final_gw_res.text,
                                            "tool_calls": final_gw_res.tool_calls,
                                        }
                                    )

                        tool_calls = (
                            list(final_gw_res.tool_calls)
                            if (final_gw_res is not None and final_gw_res.tool_calls)
                            else []
                        )

                        # ----------------------------------------------------------
                        # Branch A: Tool Calls Requested by LLM
                        # ----------------------------------------------------------
                        if tool_calls and round_idx < max_rounds:
                            working_messages.append(
                                {
                                    "role": "assistant",
                                    "content": (final_gw_res.text if final_gw_res else None) or "",
                                    "tool_calls": tool_calls,
                                }
                            )

                            for tc in tool_calls:
                                tc_id = str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                                fn_obj = tc.get("function") or {}
                                tool_name = str(
                                    fn_obj.get("name") or tc.get("name") or ""
                                ).strip()
                                raw_args = (
                                    fn_obj.get("arguments")
                                    if "arguments" in fn_obj
                                    else tc.get("arguments", {})
                                )
                                parsed_args = self._parse_tool_arguments(raw_args)

                                # 1. Strict Caller Tool Allowlist Enforcement (R2 / T3.1)
                                if tool_name not in CALLER_TOOL_ALLOWLIST:
                                    logger.warning(
                                        "Blocked non-allowlisted tool call '%s' in session %s",
                                        tool_name,
                                        session.session_id,
                                    )
                                    with span_scope(
                                        f"tool.{tool_name or 'unknown'}",
                                        kind=SpanKind.TOOL,
                                        tracer=self.tracer,
                                        input_payload={"tool": tool_name, "blocked": True},
                                    ) as blk_sp:
                                        blk_sp.set_status(
                                            SpanStatus.BLOCKED,
                                            error_class="tool_not_allowlisted",
                                            error_message=f"Tool '{tool_name}' is not in CALLER_TOOL_ALLOWLIST",
                                        )
                                    session.record_tool_call(
                                        tool_name=tool_name or "unknown",
                                        arguments={},
                                        result={
                                            "success": False,
                                            "error": f"Tool '{tool_name}' is not allowlisted",
                                        },
                                        tool_call_id=tc_id,
                                        latency_ms=0.0,
                                    )
                                    safe_fb = build_error_fallback_message(language=lang)
                                    prefix = " " if spoken_segments else ""
                                    spoken_segments.append(safe_fb)
                                    session.set_activity(CallActivity.SPEAKING)
                                    yield f"{prefix}{safe_fb}"
                                    full_text = " ".join(spoken_segments)
                                    session.add_assistant_message(
                                        full_text,
                                        latency_ms=(time.perf_counter() - turn_start) * 1000.0,
                                        llm_latency_ms=first_llm_ttft_ms,
                                    )
                                    session.set_activity(CallActivity.IDLE)
                                    session.refresh_finops_snapshot()
                                    t_ctx.output_payload = {
                                        "text": full_text,
                                        "blocked_tool": tool_name,
                                    }
                                    return

                                sanitized_args = self._sanitize_tool_arguments(
                                    tool_name, parsed_args, identity, session
                                )

                                # 2. Unverified Caller Write Interception (R3 / T3.2)
                                if (
                                    requires_verified_caller_phone(tool_name, sanitized_args)
                                    and not identity.is_verified
                                ):
                                    logger.warning(
                                        "Blocked unverified caller write intent '%s' in session %s; escalating to receptionist",
                                        tool_name,
                                        session.session_id,
                                    )
                                    with span_scope(
                                        f"tool.{tool_name}",
                                        kind=SpanKind.TOOL,
                                        tracer=self.tracer,
                                        input_payload={
                                            "tool": tool_name,
                                            "caller_verified": False,
                                        },
                                    ) as unv_sp:
                                        unv_sp.set_status(
                                            SpanStatus.BLOCKED,
                                            error_class="unverified_caller_phone",
                                        )

                                    esc_t0 = time.perf_counter()
                                    with span_scope(
                                        "tool.transfer_to_receptionist",
                                        kind=SpanKind.TOOL,
                                        tracer=self.tracer,
                                        input_payload={
                                            "reason": f"Unverified caller requested {tool_name}",
                                            "department": "reception",
                                        },
                                    ) as esc_sp:
                                        esc_res = await self._invoke_handoff(
                                            reason=f"Unverified caller phone for {tool_name}",
                                            department="reception",
                                            urgency="medium",
                                            caller_name=identity.caller_name
                                            or session.context.patient_name,
                                            caller_phone=None,
                                            summary=f"Caller requested {tool_name} without verified session phone",
                                            session_id=session.session_id,
                                            language=lang,
                                        )
                                        esc_sp.set_output(esc_res)

                                    session.record_tool_call(
                                        tool_name="transfer_to_receptionist",
                                        arguments={
                                            "reason": f"Unverified caller phone for {tool_name}",
                                            "department": "reception",
                                            "urgency": "medium",
                                        },
                                        result=esc_res,
                                        tool_call_id=tc_id,
                                        latency_ms=(time.perf_counter() - esc_t0) * 1000.0,
                                    )
                                    explain_text = _build_unverified_write_handoff_text(
                                        language=lang
                                    )
                                    prefix = " " if spoken_segments else ""
                                    spoken_segments.append(explain_text)
                                    session.set_activity(CallActivity.SPEAKING)
                                    yield f"{prefix}{explain_text}"
                                    full_text = " ".join(spoken_segments)
                                    session.add_assistant_message(
                                        full_text,
                                        latency_ms=(time.perf_counter() - turn_start) * 1000.0,
                                        llm_latency_ms=first_llm_ttft_ms,
                                    )
                                    session.set_activity(CallActivity.IDLE)
                                    session.refresh_finops_snapshot()
                                    t_ctx.output_payload = {
                                        "text": full_text,
                                        "action": "UNVERIFIED_WRITE_HANDOFF",
                                        "intercepted_tool": tool_name,
                                    }
                                    return

                                # 3. Execute Read vs. Write Tool with Differentiated Timeouts (R4)
                                session.set_activity(CallActivity.TOOL_CALLING)
                                is_write = is_write_tool_call(tool_name, sanitized_args)
                                t_exec_start = time.perf_counter()

                                if not is_write:
                                    # Read Tool: strict abort at `session_tool_timeout_ms` (400ms) (T3.3)
                                    with span_scope(
                                        f"tool.{tool_name}",
                                        kind=SpanKind.TOOL,
                                        tracer=self.tracer,
                                        input_payload={
                                            "tool": tool_name,
                                            "arguments": sanitized_args,
                                            "mode": "read",
                                        },
                                    ) as read_sp:
                                        try:
                                            tool_res = await asyncio.wait_for(
                                                self._execute_allowlisted_tool(
                                                    tool_name, sanitized_args
                                                ),
                                                timeout=filler_timeout_s,
                                            )
                                        except asyncio.TimeoutError:
                                            elapsed_ms = (
                                                time.perf_counter() - t_exec_start
                                            ) * 1000.0
                                            read_sp.set_status(
                                                SpanStatus.ERROR,
                                                error_class="timeout",
                                                error_message=(
                                                    f"Read tool '{tool_name}' timed out after {elapsed_ms:.1f}ms"
                                                ),
                                            )
                                            self._record_tool_timeout_on_session(
                                                session,
                                                tool_name=tool_name,
                                                arguments=sanitized_args,
                                                tool_call_id=tc_id,
                                                elapsed_ms=elapsed_ms,
                                            )
                                            filler_msg = build_tool_filler_message(
                                                tool_name=tool_name, language=lang
                                            )
                                            fallback_msg = build_error_fallback_message(
                                                language=lang
                                            )
                                            session.set_activity(CallActivity.SPEAKING)
                                            prefix = " " if spoken_segments else ""
                                            spoken_segments.append(filler_msg)
                                            yield f"{prefix}{filler_msg}"
                                            spoken_segments.append(fallback_msg)
                                            yield f" {fallback_msg}"
                                            full_text = " ".join(spoken_segments)
                                            session.add_assistant_message(
                                                full_text,
                                                latency_ms=(time.perf_counter() - turn_start)
                                                * 1000.0,
                                                llm_latency_ms=first_llm_ttft_ms,
                                            )
                                            session.set_activity(CallActivity.IDLE)
                                            session.refresh_finops_snapshot()
                                            t_ctx.output_payload = {
                                                "text": full_text,
                                                "timed_out_tool": tool_name,
                                            }
                                            return

                                        elapsed_ms = (
                                            time.perf_counter() - t_exec_start
                                        ) * 1000.0
                                        res_dict = (
                                            tool_res.model_dump()
                                            if hasattr(tool_res, "model_dump")
                                            else dict(tool_res)
                                        )
                                        read_sp.set_output(
                                            {
                                                "success": res_dict.get("success", True),
                                                "latency_ms": round(elapsed_ms, 2),
                                            }
                                        )
                                else:
                                    # Write Tool: 400ms filler + shielded continuation up to 3s hard cap (T2.3, T3.4, T3.6)
                                    write_task = asyncio.create_task(
                                        self._execute_allowlisted_tool(
                                            tool_name, sanitized_args
                                        ),
                                        name=f"clinic_write_{tool_name}_{session.session_id}",
                                    )
                                    self._inflight_write_tasks.add(write_task)
                                    write_task.add_done_callback(self._finalize_write_task)

                                    first_wait_s = min(filler_timeout_s, hard_cap_s)
                                    hard_cap_exceeded = False
                                    tool_res = None

                                    with span_scope(
                                        f"tool.{tool_name}",
                                        kind=SpanKind.TOOL,
                                        tracer=self.tracer,
                                        input_payload={
                                            "tool": tool_name,
                                            "arguments": sanitized_args,
                                            "mode": "write_shielded",
                                        },
                                    ) as write_sp:
                                        try:
                                            tool_res = await asyncio.wait_for(
                                                asyncio.shield(write_task),
                                                timeout=first_wait_s,
                                            )
                                        except asyncio.TimeoutError:
                                            # Emit 400ms conversational filler while write continues shielded
                                            filler_msg = build_tool_filler_message(
                                                tool_name=tool_name, language=lang
                                            )
                                            prefix = " " if spoken_segments else ""
                                            spoken_segments.append(filler_msg)
                                            session.set_activity(CallActivity.SPEAKING)
                                            yield f"{prefix}{filler_msg}"
                                            session.set_activity(CallActivity.TOOL_CALLING)

                                            remaining_s = hard_cap_s - (
                                                time.perf_counter() - t_exec_start
                                            )
                                            if remaining_s > 0:
                                                try:
                                                    tool_res = await asyncio.wait_for(
                                                        asyncio.shield(write_task),
                                                        timeout=remaining_s,
                                                    )
                                                except asyncio.TimeoutError:
                                                    hard_cap_exceeded = True
                                            elif write_task.done():
                                                tool_res = await write_task
                                            else:
                                                hard_cap_exceeded = True

                                        if hard_cap_exceeded:
                                            if not write_task.done():
                                                write_task.cancel()
                                            elapsed_ms = (
                                                time.perf_counter() - t_exec_start
                                            ) * 1000.0
                                            write_sp.set_status(
                                                SpanStatus.ERROR,
                                                error_class="timeout",
                                                error_message=(
                                                    f"Write tool '{tool_name}' exceeded hard cap {self.settings.write_tool_hard_cap_ms}ms"
                                                ),
                                            )
                                            self._record_tool_timeout_on_session(
                                                session,
                                                tool_name=tool_name,
                                                arguments=sanitized_args,
                                                tool_call_id=tc_id,
                                                elapsed_ms=elapsed_ms,
                                                error_code="write_tool_hard_cap_exceeded",
                                            )

                                            if tool_name != "transfer_to_receptionist":
                                                esc_t0 = time.perf_counter()
                                                with span_scope(
                                                    "tool.transfer_to_receptionist",
                                                    kind=SpanKind.TOOL,
                                                    tracer=self.tracer,
                                                    input_payload={
                                                        "reason": f"Write tool {tool_name} exceeded hard cap",
                                                        "department": "reception",
                                                    },
                                                ) as cap_esc_sp:
                                                    cap_esc_res = await self._invoke_handoff(
                                                        reason=f"Write tool {tool_name} exceeded {self.settings.write_tool_hard_cap_ms}ms hard cap",
                                                        department="reception",
                                                        urgency="urgent",
                                                        caller_name=identity.caller_name
                                                        or session.context.patient_name,
                                                        caller_phone=identity.caller_phone,
                                                        summary=f"Escalated after {tool_name} exceeded hard timeout cap",
                                                        session_id=session.session_id,
                                                        language=lang,
                                                    )
                                                    cap_esc_sp.set_output(cap_esc_res)

                                                session.record_tool_call(
                                                    tool_name="transfer_to_receptionist",
                                                    arguments={
                                                        "reason": f"Write tool {tool_name} exceeded hard cap",
                                                        "department": "reception",
                                                        "urgency": "urgent",
                                                    },
                                                    result=cap_esc_res,
                                                    latency_ms=(
                                                        time.perf_counter() - esc_t0
                                                    )
                                                    * 1000.0,
                                                )

                                            handoff_text = build_handoff_message(language=lang)
                                            prefix = " " if spoken_segments else ""
                                            spoken_segments.append(handoff_text)
                                            session.set_activity(CallActivity.SPEAKING)
                                            yield f"{prefix}{handoff_text}"
                                            full_text = " ".join(spoken_segments)
                                            session.add_assistant_message(
                                                full_text,
                                                latency_ms=(time.perf_counter() - turn_start)
                                                * 1000.0,
                                                llm_latency_ms=first_llm_ttft_ms,
                                            )
                                            session.set_activity(CallActivity.IDLE)
                                            session.refresh_finops_snapshot()
                                            t_ctx.output_payload = {
                                                "text": full_text,
                                                "action": "WRITE_HARD_CAP_ESCALATION",
                                                "timed_out_tool": tool_name,
                                            }
                                            return

                                        elapsed_ms = (
                                            time.perf_counter() - t_exec_start
                                        ) * 1000.0
                                        res_dict = (
                                            tool_res.model_dump()
                                            if hasattr(tool_res, "model_dump")
                                            else dict(tool_res or {})
                                        )
                                        write_sp.set_output(
                                            {
                                                "success": res_dict.get("success", True),
                                                "latency_ms": round(elapsed_ms, 2),
                                            }
                                        )

                                # Record completed tool call on CallSession & append pruned payload
                                session.record_tool_call(
                                    tool_name=tool_name,
                                    arguments=sanitized_args,
                                    result=res_dict,
                                    tool_call_id=tc_id,
                                    latency_ms=elapsed_ms,
                                )
                                pruned_str = format_pruned_tool_message(
                                    tool_name, res_dict, settings=self.settings
                                )
                                if tool_name in (
                                    "search_clinic_knowledge",
                                    "check_doctor_availability",
                                    "book_appointment",
                                    "manage_appointment",
                                ):
                                    retrieved_rag_contexts.append(pruned_str)
                                if tool_name == "search_clinic_knowledge":
                                    tool_content = wrap_retrieved_context(pruned_str)
                                else:
                                    tool_content = pruned_str

                                working_messages.append(
                                    {
                                        "role": "tool",
                                        "tool_call_id": tc_id,
                                        "name": tool_name,
                                        "content": tool_content,
                                    }
                                )
                                any_tool_executed = True

                            session.set_activity(CallActivity.LISTENING)
                            continue

                        # ----------------------------------------------------------
                        # Branch B: Final Spoken Response Round (No Further Tools)
                        # ----------------------------------------------------------
                        round_full_text = "".join(round_text_parts).strip()
                        if not round_full_text and final_gw_res is not None and final_gw_res.text:
                            round_full_text = final_gw_res.text.strip()
                            sentence_buffer = round_full_text

                        if not output_blocked:
                            if round_full_text:
                                is_tier3_search = (
                                    tier_hint == DegradationTier.TIER_3_SEARCH_ONLY
                                    or (
                                        final_gw_res is not None
                                        and final_gw_res.degradation_tier
                                        == DegradationTier.TIER_3_SEARCH_ONLY
                                    )
                                )
                                final_grounding_ctx = (
                                    "\n".join(retrieved_rag_contexts)
                                    if retrieved_rag_contexts
                                    else (None if is_tier3_search else "[NO_TOOL_GROUNDING]")
                                )
                                verdict = self.output_guardrail.validate(
                                    round_full_text,
                                    retrieved_context=final_grounding_ctx,
                                )
                                if not verdict.allowed:
                                    output_blocked = True
                                    safe_fb = (
                                        verdict.safe_fallback_text
                                        if (verdict.safe_fallback_text and not is_english(lang))
                                        else build_error_fallback_message(language=lang)
                                    )
                                    prefix = " " if spoken_segments else ""
                                    spoken_segments.append(safe_fb)
                                    session.set_activity(CallActivity.SPEAKING)
                                    yield f"{prefix}{safe_fb}"
                                elif sentence_buffer.strip():
                                    tail = sentence_buffer.strip()
                                    prefix = " " if spoken_segments else ""
                                    spoken_segments.append(tail)
                                    session.set_activity(CallActivity.SPEAKING)
                                    yield f"{prefix}{tail}"
                            elif not spoken_segments:
                                err_fb = build_error_fallback_message(language=lang)
                                spoken_segments.append(err_fb)
                                session.set_activity(CallActivity.SPEAKING)
                                yield err_fb

                        if (
                            final_gw_res is not None
                            and final_gw_res.escalate
                            and session.lifecycle != CallLifecycle.ESCALATED
                        ):
                            esc_res = await self._invoke_handoff(
                                reason=final_gw_res.error_class or "Gateway escalation",
                                department="reception",
                                urgency="medium",
                                caller_name=identity.caller_name or session.context.patient_name,
                                caller_phone=identity.caller_phone,
                                summary="Escalated by ModelGateway degradation tier",
                                session_id=session.session_id,
                                language=lang,
                            )
                            session.record_tool_call(
                                tool_name="transfer_to_receptionist",
                                arguments={"reason": final_gw_res.error_class or "gateway_escalation"},
                                result=esc_res,
                                latency_ms=0.0,
                            )

                        if (
                            not any_tool_executed
                            and not output_blocked
                            and final_gw_res is not None
                            and final_gw_res.success
                            and final_gw_res.degradation_tier == DegradationTier.TIER_1_PRIMARY
                            and round_full_text
                            and self._should_attempt_cache_lookup(cleaned_utterance, session)
                        ):
                            await self.cache_ladder.store(
                                cleaned_utterance,
                                cache_scope,
                                round_full_text,
                                degradation_tier=final_gw_res.degradation_tier,
                                tool_calls=None,
                                truncated=final_gw_res.truncated,
                            )

                        break

                    # --------------------------------------------------------------
                    # Step 6: Record Turn Completion, Snapshot FinOps & Audit Safety
                    # --------------------------------------------------------------
                    full_spoken = " ".join(
                        seg.strip() for seg in spoken_segments if seg and seg.strip()
                    )
                    e2e_ms = (time.perf_counter() - turn_start) * 1000.0
                    session.add_assistant_message(
                        full_spoken,
                        latency_ms=e2e_ms,
                        llm_latency_ms=first_llm_ttft_ms,
                    )
                    session.set_activity(CallActivity.IDLE)
                    session.refresh_finops_snapshot()
                    t_ctx.output_payload = {
                        "text": full_spoken,
                        "degradation_tier": final_tier.value,
                        "tool_executed": any_tool_executed,
                    }
                    self.llama_guard.schedule_check(
                        user_text=cleaned_utterance,
                        assistant_text=full_spoken,
                        trace_id=t_ctx.trace_id,
                    )
        finally:
            snap = self.finops.get_session_snapshot(session.session_id)
            if snap is not None:
                session.metrics.finops_snapshot = snap.model_dump()
            else:
                session.refresh_finops_snapshot()


__all__ = [
    "CALLER_TOOL_ALLOWLIST",
    "READ_TOOLS",
    "WRITE_TOOLS",
    "ClinicTurnEngine",
    "VerifiedCallerIdentity",
    "get_caller_tool_definitions",
    "is_write_tool_call",
    "requires_verified_caller_phone",
]
