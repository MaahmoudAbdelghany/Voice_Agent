"""
Unit, Integration, and Edge-Case Tests for ModelGateway (Feature 4.1).

Tests run 100% offline using scripted mock providers simulating:
- Token streaming, TTFT, and total latency
- Tool calls streamed in fragmented deltas
- Timeouts, 429s, 500s, 401s
- Circuit breaker trip and HALF_OPEN recovery
- Graceful 4-tier degradation (Search-only & Receptionist escalation)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import litellm.exceptions
import pytest

from src.ai_core.circuit_breaker import BreakerState
from src.ai_core.gateway import (
    DegradationTier,
    GatewayResult,
    LiteLLMProvider,
    ModelGateway,
    Stage,
    classify_error,
)
from src.config import Settings

# ==============================================================================
# Scripted Mock Provider for Offline Deterministic Testing
# ==============================================================================


class ScriptedMockProvider:
    """Mock LLMProvider allowing exact script of chunks, tool deltas, delays, and errors."""

    def __init__(
        self,
        name: str,
        configured: bool = True,
        chunks: list[str] | None = None,
        tool_deltas: list[list[dict[str, Any]]] | None = None,
        ttft_delay_s: float = 0.0,
        chunk_delay_s: float = 0.0,
        fail_before_chunk: Exception | None = None,
        fail_after_chunks: tuple[int, Exception] | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        self.name = name
        self.configured = configured
        self.chunks = chunks if chunks is not None else ["مرحباً", " بك", " في", " عيادات", " النور"]
        self.tool_deltas = tool_deltas
        self.ttft_delay_s = ttft_delay_s
        self.chunk_delay_s = chunk_delay_s
        self.fail_before_chunk = fail_before_chunk
        self.fail_after_chunks = fail_after_chunks
        self.usage = usage or {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25}

        # Track invocations for assertions
        self.calls: list[dict[str, Any]] = []

    def is_configured(self) -> bool:
        return self.configured

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
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tools,
            }
        )

        if self.fail_before_chunk is not None:
            raise self.fail_before_chunk

        if self.ttft_delay_s > 0:
            if self.ttft_delay_s > ttft_timeout_s:
                await asyncio.sleep(ttft_timeout_s + 0.01)
                raise asyncio.TimeoutError("Simulated TTFT Timeout")
            await asyncio.sleep(self.ttft_delay_s)

        total_chunks = max(len(self.chunks), len(self.tool_deltas) if self.tool_deltas else 0)

        for i in range(total_chunks):
            if self.fail_after_chunks is not None:
                fail_at, exc = self.fail_after_chunks
                if i >= fail_at:
                    raise exc

            text = self.chunks[i] if i < len(self.chunks) else None
            td = self.tool_deltas[i] if self.tool_deltas and i < len(self.tool_deltas) else None
            is_last = i == total_chunks - 1

            meta = {
                "ttft_ms": 15.0 if i == 0 else None,
                "finish_reason": "stop" if is_last else None,
                "usage": self.usage if is_last else None,
            }

            if self.chunk_delay_s > 0:
                await asyncio.sleep(self.chunk_delay_s)

            yield text, td, meta


# ==============================================================================
# Tier 1: Unit & Helpers Verification
# ==============================================================================


def test_stage_binding():
    settings = Settings(
        groq_model="llama-3.3-70b-versatile",
        llm_stage_model="llama-3.1-8b-instant",
        gemini_fallback_model="gemini-2.0-flash",
    )
    gw = ModelGateway(settings=settings)

    assert gw.resolve_model("groq", Stage.CLASSIFICATION) == "groq/llama-3.1-8b-instant"
    assert gw.resolve_model("groq", Stage.EXTRACTION) == "groq/llama-3.1-8b-instant"
    assert gw.resolve_model("groq", Stage.DIALOGUE) == "groq/llama-3.3-70b-versatile"
    assert gw.resolve_model("gemini", Stage.DIALOGUE) == "gemini/gemini-2.0-flash"
    assert gw.resolve_model("gemini", Stage.EXTRACTION) == "gemini/gemini-2.0-flash"


def test_max_tokens_clamp():
    settings = Settings(voice_max_tokens=150, stage_max_tokens=256)
    gw = ModelGateway(settings=settings)

    # Dialogue clamp
    assert gw.resolve_max_tokens(Stage.DIALOGUE, None) == 150
    assert gw.resolve_max_tokens(Stage.DIALOGUE, 50) == 50
    assert gw.resolve_max_tokens(Stage.DIALOGUE, 300) == 150

    # Non-dialogue clamp
    assert gw.resolve_max_tokens(Stage.CLASSIFICATION, None) == 256
    assert gw.resolve_max_tokens(Stage.EXTRACTION, 100) == 100
    assert gw.resolve_max_tokens(Stage.EXTRACTION, 500) == 256


def test_error_classification():
    # Retryable errors
    assert classify_error(asyncio.TimeoutError()) == (True, "timeout")
    assert classify_error(litellm.exceptions.Timeout("Timeout", "groq", "m")) == (True, "timeout")
    assert classify_error(litellm.exceptions.APIConnectionError("Conn", "groq", "m")) == (
        True,
        "connection_error",
    )
    assert classify_error(litellm.exceptions.RateLimitError("429", "groq", "m")) == (
        True,
        "rate_limit",
    )
    assert classify_error(litellm.exceptions.InternalServerError("500", "groq", "m")) == (
        True,
        "server_error",
    )
    assert classify_error(litellm.exceptions.ServiceUnavailableError("503", "groq", "m")) == (
        True,
        "server_error",
    )

    # Non-retryable client errors
    assert classify_error(litellm.exceptions.BadRequestError("400", "groq", "m")) == (
        False,
        "bad_request",
    )
    assert classify_error(litellm.exceptions.AuthenticationError("401", "groq", "m")) == (
        False,
        "auth_error",
    )

    class Custom403(Exception):
        status_code = 403

    class Custom404(Exception):
        status_code = 404

    class Custom422(Exception):
        status_code = 422

    assert classify_error(Custom403("Forbidden")) == (False, "client_error")
    assert classify_error(Custom404("Not Found")) == (False, "client_error")
    assert classify_error(Custom422("Unprocessable")) == (False, "client_error")


def test_unconfigured_provider_detection():
    p1 = LiteLLMProvider("groq", "")
    assert not p1.is_configured()

    p2 = LiteLLMProvider("groq", "your_groq_api_key")
    assert not p2.is_configured()

    p3 = LiteLLMProvider("groq", "gsk_valid_key_123456")
    assert p3.is_configured()


def test_litellm_call_hardening():
    """Verify litellm global telemetry is disabled."""
    import litellm

    assert litellm.telemetry is False
    assert litellm.success_callback == []
    assert litellm.failure_callback == []
    assert litellm.drop_params is True


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_primary_success_tier1():
    p1 = ScriptedMockProvider(name="groq", chunks=["أهلاً", " بحضرتك"])
    p2 = ScriptedMockProvider(name="gemini")
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}])

    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_1_PRIMARY
    assert res.provider == "groq"
    assert res.text == "أهلاً بحضرتك"
    assert res.prompt_tokens == 15
    assert res.completion_tokens == 10
    assert len(p1.calls) == 1
    assert len(p2.calls) == 0


@pytest.mark.asyncio
async def test_dialogue_sends_clamped_max_tokens_and_bound_model():
    p1 = ScriptedMockProvider(name="groq")
    gw = ModelGateway(primary_provider=p1)

    await gw.agenerate(
        stage=Stage.DIALOGUE,
        messages=[{"role": "user", "content": "سؤال"}],
        max_tokens=400,
    )

    assert p1.calls[0]["model"] == "groq/llama-3.3-70b-versatile"
    assert p1.calls[0]["max_tokens"] == 150  # Clamped to voice_max_tokens


@pytest.mark.asyncio
async def test_extraction_uses_8b_model():
    p1 = ScriptedMockProvider(name="groq")
    gw = ModelGateway(primary_provider=p1)

    await gw.agenerate(
        stage=Stage.EXTRACTION,
        messages=[{"role": "user", "content": "دكتور عظام"}],
    )

    assert p1.calls[0]["model"] == "groq/llama-3.1-8b-instant"
    assert p1.calls[0]["max_tokens"] == 256


@pytest.mark.asyncio
async def test_failover_on_429_tier2():
    p1 = ScriptedMockProvider(
        name="groq",
        fail_before_chunk=litellm.exceptions.RateLimitError("429", "groq", "m"),
    )
    p2 = ScriptedMockProvider(name="gemini", chunks=["رد من جيميني"])
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}])

    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_2_BACKUP
    assert res.provider == "gemini"
    assert res.text == "رد من جيميني"
    assert gw.primary_breaker.consecutive_failures == 1
    assert len(res.attempts) == 2
    assert res.attempts[0].outcome == "failed"
    assert res.attempts[0].error_class == "rate_limit"
    assert res.attempts[1].outcome == "success"


@pytest.mark.asyncio
async def test_failover_on_5xx_tier2():
    p1 = ScriptedMockProvider(
        name="groq",
        fail_before_chunk=litellm.exceptions.ServiceUnavailableError("503", "groq", "m"),
    )
    p2 = ScriptedMockProvider(name="gemini", chunks=["رد بديل"])
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}])

    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_2_BACKUP
    assert res.provider == "gemini"


@pytest.mark.asyncio
async def test_failover_on_ttft_timeout():
    settings = Settings(llm_ttft_timeout_s=0.05)
    p1 = ScriptedMockProvider(name="groq", ttft_delay_s=0.1)  # Exceeds TTFT timeout
    p2 = ScriptedMockProvider(name="gemini", chunks=["رد بديل سريع"])
    gw = ModelGateway(settings=settings, primary_provider=p1, fallback_provider=p2)

    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}])

    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_2_BACKUP
    assert res.provider == "gemini"
    assert gw.primary_breaker.consecutive_failures == 1


@pytest.mark.asyncio
async def test_non_retryable_fails_over_without_tripping_breaker():
    p1 = ScriptedMockProvider(
        name="groq",
        fail_before_chunk=litellm.exceptions.AuthenticationError("401", "groq", "m"),
    )
    p2 = ScriptedMockProvider(name="gemini", chunks=["رد جيميني"])
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    for _ in range(6):
        res = await gw.agenerate(
            stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}]
        )
        assert res.degradation_tier == DegradationTier.TIER_2_BACKUP

    # Breaker should still be CLOSED because 401 is non-retryable
    assert gw.primary_breaker.state == BreakerState.CLOSED
    assert gw.primary_breaker.consecutive_failures == 0


@pytest.mark.asyncio
async def test_breaker_open_skips_primary_instantly():
    p1 = ScriptedMockProvider(
        name="groq",
        fail_before_chunk=litellm.exceptions.RateLimitError("429", "groq", "m"),
    )
    p2 = ScriptedMockProvider(name="gemini", chunks=["رد جيميني"])
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    # Trigger 5 failures to trip breaker
    for _ in range(5):
        await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}])

    assert gw.primary_breaker.state == BreakerState.OPEN
    initial_p1_calls = len(p1.calls)

    # 6th request: primary breaker is OPEN -> skips primary without invoking it!
    t0 = asyncio.get_event_loop().time()
    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مرحبا"}])
    elapsed = asyncio.get_event_loop().time() - t0

    assert len(p1.calls) == initial_p1_calls  # Primary was NOT called!
    assert res.attempts[0].outcome == "skipped_open"
    assert res.degradation_tier == DegradationTier.TIER_2_BACKUP
    assert elapsed < 0.05  # Instant skip (<5ms logic)


@pytest.mark.asyncio
async def test_tool_calls_assembled_from_stream_deltas():
    # Fragmented arguments across 2 chunks
    deltas = [
        [
            {
                "index": 0,
                "id": "call_123",
                "type": "function",
                "function": {"name": "check_doctor_availability", "arguments": '{"specialty_id":'},
            }
        ],
        [
            {
                "index": 0,
                "id": "call_123",
                "type": "function",
                "function": {"name": "", "arguments": " 1}"},
            }
        ],
    ]
    p1 = ScriptedMockProvider(name="groq", chunks=["", ""], tool_deltas=deltas)
    gw = ModelGateway(primary_provider=p1)

    res = await gw.agenerate(
        stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "دكتور باطنة"}]
    )

    assert res.success is True
    assert len(res.tool_calls) == 1
    assert res.tool_calls[0]["id"] == "call_123"
    assert res.tool_calls[0]["function"]["name"] == "check_doctor_availability"
    assert res.tool_calls[0]["function"]["arguments"] == '{"specialty_id": 1}'


@pytest.mark.asyncio
async def test_astream_yields_chunks_then_result():
    p1 = ScriptedMockProvider(name="groq", chunks=["مرحبا", " بكم"])
    gw = ModelGateway(primary_provider=p1)

    chunks_received: list[str] = []
    final_res: GatewayResult | None = None

    async for chunk, res in gw.astream(
        stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "hi"}]
    ):
        if chunk:
            chunks_received.append(chunk)
        if res:
            final_res = res

    assert chunks_received == ["مرحبا", " بكم"]
    assert final_res is not None
    assert final_res.success is True
    assert final_res.text == "مرحبا بكم"
    assert final_res.degradation_tier == DegradationTier.TIER_1_PRIMARY


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_both_providers_down_dialogue_search_tier3():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=RuntimeError("Groq Down"))
    p2 = ScriptedMockProvider(name="gemini", fail_before_chunk=RuntimeError("Gemini Down"))

    async def fake_search(query: str) -> str | None:
        return "مواعيد العيادة يومياً من 9 صباحاً إلى 10 مساءً."

    gw = ModelGateway(
        primary_provider=p1,
        fallback_provider=p2,
        search_fallback=fake_search,
    )

    res = await gw.agenerate(
        stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مواعيدكم إيه؟"}]
    )

    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_3_SEARCH_ONLY
    assert res.escalate is False
    assert "مواعيد العيادة يومياً" in (res.text or "")
    assert len(res.attempts) == 2


@pytest.mark.asyncio
async def test_both_down_no_snippet_tier4():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=RuntimeError("Groq Down"))
    p2 = ScriptedMockProvider(name="gemini", fail_before_chunk=RuntimeError("Gemini Down"))

    async def empty_search(query: str) -> str | None:
        return None

    gw = ModelGateway(
        primary_provider=p1,
        fallback_provider=p2,
        search_fallback=empty_search,
    )

    res = await gw.agenerate(
        stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "سؤال غير موجود"}]
    )

    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION
    assert res.escalate is True
    assert "موظف الاستقبال" in (res.text or "")


@pytest.mark.asyncio
async def test_both_down_search_timeout_tier4():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=RuntimeError("Groq Down"))
    p2 = ScriptedMockProvider(name="gemini", fail_before_chunk=RuntimeError("Gemini Down"))

    async def slow_search(query: str) -> str | None:
        await asyncio.sleep(1.0)  # Exceeds 400ms timeout
        return "نتيجة بطيئة"

    gw = ModelGateway(
        primary_provider=p1,
        fallback_provider=p2,
        search_fallback=slow_search,
    )

    t0 = asyncio.get_event_loop().time()
    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "سؤال"}])
    elapsed = asyncio.get_event_loop().time() - t0

    assert res.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION
    assert res.escalate is True
    assert elapsed < 0.6


@pytest.mark.asyncio
async def test_both_down_emergency_goes_tier4_without_search():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=RuntimeError("Groq Down"))
    p2 = ScriptedMockProvider(name="gemini", fail_before_chunk=RuntimeError("Gemini Down"))

    search_called = False

    async def spy_search(query: str) -> str | None:
        nonlocal search_called
        search_called = True
        return "معلومات"

    gw = ModelGateway(
        primary_provider=p1,
        fallback_provider=p2,
        search_fallback=spy_search,
    )

    # Caller presents emergency chest pain
    res = await gw.agenerate(
        stage=Stage.DIALOGUE,
        messages=[{"role": "user", "content": "عندي ألم شديد في صدري ومش قادر أتنفس"}],
    )

    assert not search_called  # Emergency must bypass search!
    assert res.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION
    assert res.escalate is True
    assert "123" in (res.text or "")


@pytest.mark.asyncio
async def test_both_down_extraction_returns_failure():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=RuntimeError("Groq Down"))
    p2 = ScriptedMockProvider(name="gemini", fail_before_chunk=RuntimeError("Gemini Down"))
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    res = await gw.agenerate(
        stage=Stage.EXTRACTION,
        messages=[{"role": "user", "content": "دكتور باطنة"}],
    )

    assert res.success is False
    assert res.text is None
    assert res.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION


@pytest.mark.asyncio
async def test_mid_stream_failure_truncates_no_failover():
    # Primary yields 2 chunks then raises connection error
    p1 = ScriptedMockProvider(
        name="groq",
        chunks=["الكشف متاح", " غداً الساعة", " خمسة"],
        fail_after_chunks=(2, ConnectionResetError("Connection lost")),
    )
    p2 = ScriptedMockProvider(name="gemini", chunks=["رد بديل من جيميني"])
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    chunks: list[str] = []
    final_res: GatewayResult | None = None

    async for c, r in gw.astream(
        stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "ميعاد الكشف"}]
    ):
        if c:
            chunks.append(c)
        if r:
            final_res = r

    # Must NOT fail over to Gemini because audio was already sent to caller
    assert chunks == ["الكشف متاح", " غداً الساعة"]
    assert len(p2.calls) == 0
    assert final_res is not None
    assert final_res.truncated is True
    assert final_res.success is False
    assert gw.primary_breaker.consecutive_failures == 1


@pytest.mark.asyncio
async def test_empty_messages_rejected_gracefully():
    gw = ModelGateway()
    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[])

    assert res.success is False
    assert res.error_class == "invalid_request"


@pytest.mark.asyncio
async def test_fallback_messages_voice_safe():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=RuntimeError())
    p2 = ScriptedMockProvider(name="gemini", fail_before_chunk=RuntimeError())

    async def snippet_search(q: str) -> str | None:
        return "عيادتنا مفتوحة طول الأسبوع."

    gw = ModelGateway(primary_provider=p1, fallback_provider=p2, search_fallback=snippet_search)

    # Check Tier 3 text
    r3 = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "مواعيد"}])
    assert r3.text is not None
    assert len(r3.text) <= 300
    for bad_char in ["*", "#", "|", "```"]:
        assert bad_char not in r3.text

    # Check Tier 4 emergency text
    r4 = await gw.agenerate(
        stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "ألم في الصدر"}]
    )
    assert r4.text is not None
    assert len(r4.text) <= 300
    for bad_char in ["*", "#", "|", "```"]:
        assert bad_char not in r4.text


@pytest.mark.asyncio
async def test_gateway_never_raises():
    p1 = ScriptedMockProvider(name="groq", fail_before_chunk=KeyError("Unexpected KeyError"))
    p2 = ScriptedMockProvider(
        name="gemini", fail_before_chunk=ZeroDivisionError("Division by zero")
    )
    gw = ModelGateway(primary_provider=p1, fallback_provider=p2)

    # Must return a GatewayResult, never crash caller
    res = await gw.agenerate(stage=Stage.DIALOGUE, messages=[{"role": "user", "content": "test"}])
    assert isinstance(res, GatewayResult)
    assert res.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION
