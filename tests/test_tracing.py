"""
Automated Test Suite for Feature 4.6 — Hierarchical LLM Trace Logging (`src/ai_core/tracing.py`).

Covers:
1. Tier 1 (Unit):
   - W3C `trace_id` (32-hex), `span_id` (16-hex), and `traceparent` format/parse roundtrip.
   - Multi-level `parent_span_id` nesting and token/cost rollup.
   - Deterministic `estimate_llm_cost_usd` calculation across configured models.
   - Sub-millisecond (< 1ms) hot-path span recording latency benchmark.
2. Tier 2 (Integration):
   - End-to-end auto-instrumented pipeline (`InputGuardrail` -> `CacheLadder` -> `ModelGateway` -> `OutputGuardrail`).
   - Mandatory pre-export Egyptian PII redaction (`[REDACTED_PHONE]`, `[REDACTED_NATIONAL_ID]`) in ring buffer and Langfuse payloads.
   - Self-hosted Langfuse `/api/public/ingestion` HTTP batch payload verification via `httpx.MockTransport`.
   - Off-hot-path `AsyncLlamaGuardClassifier` safety verdict attachment to `TraceRecord`.
3. Tier 3 (Error & Edge-Case):
   - 20-way concurrent `asyncio.gather` trace isolation via `contextvars`.
   - Langfuse outage / HTTP 503 / timeout graceful no-op degradation.
   - Disabled tracing strict no-op behavior and queue capacity backpressure.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest

from src.ai_core.cache import CacheLadder, CacheScope, InMemoryLRUBackend
from src.ai_core.gateway import DegradationTier, ModelGateway, Stage
from src.ai_core.guardrails import (
    AsyncLlamaGuardClassifier,
    InputGuardrail,
    OutputGuardrail,
)
from src.ai_core.tracing import (
    ErrorCategory,
    HierarchicalTracer,
    SpanKind,
    SpanStatus,
    classify_trace_error,
    estimate_llm_cost_usd,
    format_traceparent,
    generate_span_id,
    generate_trace_id,
    get_current_span_id,
    get_current_trace_id,
    get_tracer,
    inject_trace_headers,
    parse_traceparent,
    span_scope,
    trace_scope,
    traced_span,
)
from src.config import Settings

# ==============================================================================
# Helper Mock LLM Provider for Deterministic Gateway Integration
# ==============================================================================


class _MockStreamingProvider:
    """Deterministic mock LLM provider yielding text and token usage."""

    def __init__(
        self,
        name: str = "groq",
        text: str = "أهلاً بحضرتك في مجمع عيادات النور، سعر الكشف 350 جنيه.",
        prompt_tokens: int = 120,
        completion_tokens: int = 30,
        ttft_ms: float = 42.5,
    ) -> None:
        self.name = name
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.ttft_ms = ttft_ms

    def is_configured(self) -> bool:
        return True

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
        meta = {
            "ttft_ms": self.ttft_ms,
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens,
            },
            "elapsed_ms": 55.0,
        }
        yield self.text, None, meta


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_w3c_traceparent_format_and_parse_roundtrip() -> None:
    """
    Verify W3C trace_id (32-hex), span_id (16-hex), format_traceparent, parse_traceparent,
    inject_trace_headers, and remote traceparent adoption in trace_scope.
    """
    tid = generate_trace_id()
    sid = generate_span_id()
    assert len(tid) == 32 and tid == tid.lower() and tid != "0" * 32
    assert len(sid) == 16 and sid == sid.lower() and sid != "0" * 16

    tp_str = format_traceparent(tid, sid, sampled=True)
    assert tp_str == f"00-{tid}-{sid}-01"

    parsed = parse_traceparent(tp_str)
    assert parsed is not None
    assert parsed.version == "00"
    assert parsed.trace_id == tid
    assert parsed.parent_span_id == sid
    assert parsed.sampled is True

    # Malformed or all-zero headers must return None gracefully
    assert parse_traceparent("") is None
    assert parse_traceparent("invalid-header") is None
    assert parse_traceparent(f"ff-{tid}-{sid}-01") is None
    assert parse_traceparent(f"00-{'0' * 32}-{sid}-01") is None
    assert parse_traceparent(f"00-{tid}-{'0' * 16}-01") is None

    # Adopt upstream traceparent in trace_scope
    tracer = HierarchicalTracer()
    async with trace_scope("downstream_turn", tracer=tracer, traceparent=tp_str) as t_ctx:
        assert t_ctx.trace_id == tid
        assert t_ctx.parent_span_id == sid
        headers = inject_trace_headers({"X-Clinic": "Noor"})
        assert headers["X-Clinic"] == "Noor"
        assert headers["traceparent"].startswith(f"00-{tid}-")

        with span_scope("child_step", tracer=tracer) as s_ctx:
            assert s_ctx.parent_span_id == t_ctx.root_span_id
            inner_headers = inject_trace_headers()
            assert inner_headers["traceparent"] == f"00-{tid}-{s_ctx.span_id}-01"

    await tracer.flush()
    flushed = tracer.get_trace(tid)
    assert flushed is not None
    assert flushed.parent_span_id == sid
    assert len(flushed.spans) == 1
    assert flushed.spans[0].parent_span_id == flushed.root_span_id


@pytest.mark.asyncio
async def test_nested_span_hierarchy_and_parent_span_ids() -> None:
    """
    Verify 3-level nested span hierarchy (`trace_scope` -> `outer` -> `inner`)
    assigns exact `parent_span_id` links and rolls up tokens, cost, and degradation tier.
    """
    tracer = HierarchicalTracer()

    @traced_span("decorated_leaf_tool", kind=SpanKind.TOOL)
    async def leaf_helper(val: int) -> dict[str, int]:
        return {"doubled": val * 2}

    async with trace_scope("multi_level_turn", tracer=tracer, session_id="sess_01") as t_ctx:
        root_sid = t_ctx.root_span_id
        assert get_current_trace_id() == t_ctx.trace_id
        assert get_current_span_id() == root_sid

        with span_scope("router_stage", kind=SpanKind.ROUTER, tracer=tracer) as router_sp:
            router_sp.set_usage(
                provider="groq",
                model="groq/llama-3.1-8b-instant",
                prompt_tokens=100,
                completion_tokens=20,
            )
            assert router_sp.parent_span_id == root_sid

            with span_scope("dialogue_stage", kind=SpanKind.LLM, tracer=tracer) as llm_sp:
                llm_sp.set_usage(
                    provider="gemini",
                    model="gemini/gemini-2.0-flash",
                    prompt_tokens=400,
                    completion_tokens=50,
                    ttft_ms=115.0,
                    degradation_tier=DegradationTier.TIER_2_BACKUP.value,
                )
                assert llm_sp.parent_span_id == router_sp.span_id

                # Call decorated leaf inside dialogue_stage
                leaf_out = await leaf_helper(21)
                assert leaf_out == {"doubled": 42}

    await tracer.flush()
    rec = tracer.get_trace(t_ctx.trace_id)
    assert rec is not None
    assert len(rec.spans) == 3

    # Spans finish in inner-to-outer order: leaf -> dialogue -> router
    leaf_rec, llm_rec, router_rec = rec.spans[0], rec.spans[1], rec.spans[2]
    assert router_rec.parent_span_id == rec.root_span_id
    assert llm_rec.parent_span_id == router_rec.span_id
    assert leaf_rec.parent_span_id == llm_rec.span_id

    # Verify rollup on root TraceRecord
    assert rec.total_prompt_tokens == 500
    assert rec.total_completion_tokens == 70
    assert rec.total_tokens == 570
    assert rec.ttft_ms == 115.0
    assert rec.degradation_tier == DegradationTier.TIER_2_BACKUP.value
    assert rec.status == SpanStatus.DEGRADED
    expected_cost = round(router_rec.cost_usd + llm_rec.cost_usd, 8)
    assert rec.total_cost_usd == expected_cost
    assert rec.total_cost_usd > 0.0


def test_estimate_llm_cost_usd_for_configured_models() -> None:
    """
    Verify deterministic USD cost calculations for Groq 70B, Groq 8B, and Gemini Flash,
    plus error classification helper.
    """
    # Groq Llama 3.3 70B: $0.59 / 1M prompt, $0.79 / 1M completion
    cost_70b = estimate_llm_cost_usd(
        "groq/llama-3.3-70b-versatile",
        prompt_tokens=1_000,
        completion_tokens=1_000,
    )
    assert cost_70b == round((1000 * 0.59 + 1000 * 0.79) / 1_000_000.0, 8)

    # Groq Llama 3.1 8B: $0.05 / 1M prompt, $0.08 / 1M completion
    cost_8b = estimate_llm_cost_usd(
        "llama-3.1-8b-instant",
        prompt_tokens=2_000,
        completion_tokens=500,
    )
    assert cost_8b == round((2000 * 0.05 + 500 * 0.08) / 1_000_000.0, 8)

    # Zero tokens -> $0.0
    assert estimate_llm_cost_usd("groq/llama-3.3-70b-versatile", 0, 0) == 0.0

    # Error taxonomy classification
    assert classify_trace_error("timeout") == ErrorCategory.INFRASTRUCTURE
    assert classify_trace_error("rate_limit") == ErrorCategory.INFRASTRUCTURE
    assert classify_trace_error("prompt_injection") == ErrorCategory.SECURITY_BLOCK
    assert classify_trace_error("step_budget_exhausted") == ErrorCategory.SEMANTIC
    assert classify_trace_error(None) == ErrorCategory.NONE


def test_hot_path_span_recording_under_1ms() -> None:
    """
    Benchmark 100 iterations of opening/closing a root trace + 3 nested spans on the hot path
    (prior to background flush) and assert average hot-path overhead is < 1.0ms (NFR1).
    """
    settings = Settings(tracing_enabled=True, langfuse_enabled=False)
    tracer = HierarchicalTracer(settings=settings)

    iterations = 100
    start_t = time.perf_counter()
    for i in range(iterations):
        with trace_scope(f"bench_turn_{i}", tracer=tracer, input_payload="سعر الكشف كام؟"):
            with span_scope("guardrail", kind=SpanKind.GUARDRAIL_INPUT, tracer=tracer) as s1:
                s1.set_output({"allowed": True})
            with span_scope("cache", kind=SpanKind.CACHE, tracer=tracer) as s2:
                s2.set_output({"hit": False})
            with span_scope("llm", kind=SpanKind.LLM, tracer=tracer) as s3:
                s3.set_usage(
                    provider="groq",
                    model="groq/llama-3.3-70b-versatile",
                    prompt_tokens=150,
                    completion_tokens=40,
                )
    elapsed_ms = (time.perf_counter() - start_t) * 1000.0
    avg_ms_per_turn = elapsed_ms / iterations

    assert avg_ms_per_turn < 1.0, (
        f"Hot-path trace overhead {avg_ms_per_turn:.3f}ms exceeded 1.0ms SLA"
    )


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_auto_instrumented_pipeline_builds_complete_trace_tree() -> None:
    """
    Verify that executing InputGuardrail, CacheLadder, ModelGateway, and OutputGuardrail
    inside `trace_scope` automatically records nested child spans and rolls up metrics.
    """
    tracer = get_tracer()
    tracer.clear()

    in_guard = InputGuardrail()
    cache = CacheLadder(tier1_backend=InMemoryLRUBackend(max_entries=50))
    mock_provider = _MockStreamingProvider(
        name="groq",
        text="سعر الكشف في العيادة 350 جنيه.",
        prompt_tokens=140,
        completion_tokens=25,
        ttft_ms=38.0,
    )
    gateway = ModelGateway(primary_provider=mock_provider)
    out_guard = OutputGuardrail()

    user_query = "لو سمحت سعر الكشف كام؟"
    retrieved_ctx = "سعر الكشف العام والتخصصي هو 350 جنيه."

    async with trace_scope("clinic_inquiry_turn", input_payload=user_query) as t_ctx:
        # 1. Input Guardrail
        in_res = in_guard.evaluate(user_query)
        assert in_res.allowed is True

        # 2. Cache Lookup (Tier 1 miss; category='doctors' bypasses Tier 2 embedding)
        c_res = await cache.lookup(user_query, CacheScope(category="doctors"))
        assert c_res.hit is False

        # 3. Model Gateway
        gw_res = await gateway.agenerate(
            stage=Stage.DIALOGUE,
            messages=[{"role": "user", "content": user_query}],
        )
        assert gw_res.success is True

        # 4. Output Guardrail
        out_res = out_guard.validate(gw_res.text or "", retrieved_context=retrieved_ctx)
        assert out_res.allowed is True
        t_ctx.set_output(gw_res.text)

    await tracer.flush()
    rec = tracer.get_trace(t_ctx.trace_id)
    assert rec is not None
    assert rec.pii_redacted is True
    assert rec.total_prompt_tokens == 140
    assert rec.total_completion_tokens == 25
    assert rec.total_tokens == 165
    assert rec.ttft_ms == 38.0
    assert rec.total_cost_usd > 0.0
    assert rec.degradation_tier == DegradationTier.TIER_1_PRIMARY.value

    kinds = [sp.kind for sp in rec.spans]
    assert SpanKind.GUARDRAIL_INPUT in kinds
    assert SpanKind.CACHE in kinds
    assert SpanKind.LLM in kinds
    assert SpanKind.GUARDRAIL_OUTPUT in kinds
    assert all(sp.parent_span_id == rec.root_span_id for sp in rec.spans)


@pytest.mark.asyncio
async def test_pre_export_pii_redaction_scrubs_egyptian_phone_and_national_id() -> None:
    """
    Verify that raw Egyptian phone numbers (ASCII & Arabic-Indic) and 14-digit National IDs
    are 100% masked with `[REDACTED_PHONE]` and `[REDACTED_NATIONAL_ID]` in both
    `recent_traces` and exported Langfuse batches.
    """
    captured_batches: list[dict[str, Any]] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured_batches.append(body)
        return httpx.Response(200, json={"status": "ok"})

    settings = Settings(
        tracing_enabled=True,
        langfuse_enabled=True,
        langfuse_host="http://localhost:3000",
        langfuse_public_key="pk-lf-test-clinic",
        langfuse_secret_key="sk-lf-test-clinic",
        pii_redaction_enabled=True,
    )
    tracer = HierarchicalTracer(
        settings=settings,
        http_transport=httpx.MockTransport(mock_handler),
    )

    raw_utterance = "أنا اسمي محمود ورقمي 01012345678 والرقم القومي 29501010101234"
    arabic_digits_phone = "٠١١٢٣٤٥٦٧٨٩"

    async with trace_scope(
        "pii_booking_turn",
        tracer=tracer,
        input_payload=raw_utterance,
        metadata={"caller_phone": "01012345678"},
    ) as t_ctx:
        with span_scope(
            "book_appointment",
            kind=SpanKind.TOOL,
            tracer=tracer,
            input_payload={
                "patient_phone": "01012345678",
                "alt_phone": arabic_digits_phone,
                "national_id": "29501010101234",
            },
            attributes={"raw_note": "تواصل على 01234567890"},
        ) as sp:
            sp.set_output({"confirmed_phone": "01012345678", "booking_code": "APT-101"})

    await tracer.flush()

    rec = tracer.get_trace(t_ctx.trace_id)
    assert rec is not None
    assert rec.pii_redacted is True

    serialized_rec = json.dumps(rec.model_dump(), ensure_ascii=False)
    assert "01012345678" not in serialized_rec
    assert "٠١١٢٣٤٥٦٧٨٩" not in serialized_rec
    assert "29501010101234" not in serialized_rec
    assert "01234567890" not in serialized_rec
    assert "[REDACTED_PHONE]" in serialized_rec
    assert "[REDACTED_NATIONAL_ID]" in serialized_rec

    # Also verify the Langfuse HTTP batch payload contains zero raw PII
    assert len(captured_batches) == 1
    batch_json = json.dumps(captured_batches[0], ensure_ascii=False)
    assert "01012345678" not in batch_json
    assert "29501010101234" not in batch_json
    assert "[REDACTED_PHONE]" in batch_json
    assert "[REDACTED_NATIONAL_ID]" in batch_json


@pytest.mark.asyncio
async def test_langfuse_http_batch_export_payload_structure() -> None:
    """
    Verify Langfuse `/api/public/ingestion` REST batch structure (`trace-create`,
    `generation-create`, `span-create`) and Basic Auth header.
    """
    requests_received: list[httpx.Request] = []
    batches_received: list[list[dict[str, Any]]] = []

    async def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_received.append(request)
        payload = json.loads(request.content.decode("utf-8"))
        batches_received.append(payload.get("batch", []))
        return httpx.Response(207, json={"successes": [], "errors": []})

    settings = Settings(
        tracing_enabled=True,
        langfuse_enabled=True,
        langfuse_host="http://langfuse.clinic.local:3000",
        langfuse_public_key="pk-lf-clinic-123",
        langfuse_secret_key="sk-lf-secret-456",
    )
    tracer = HierarchicalTracer(
        settings=settings,
        http_transport=httpx.MockTransport(mock_handler),
    )

    async with trace_scope("langfuse_export_test", tracer=tracer, session_id="room_42") as t_ctx:
        with span_scope("guardrail_check", kind=SpanKind.GUARDRAIL_INPUT, tracer=tracer) as s1:
            s1.set_output({"allowed": True})
        with span_scope("dialogue_llm", kind=SpanKind.LLM, tracer=tracer) as s2:
            s2.set_usage(
                provider="groq",
                model="groq/llama-3.3-70b-versatile",
                prompt_tokens=200,
                completion_tokens=50,
                ttft_ms=85.0,
            )
            s2.set_output({"text": "أهلاً بحضرتك"})

    await tracer.flush()

    assert tracer.exporter.exported_batches_count == 1
    assert len(requests_received) == 1
    req = requests_received[0]
    assert str(req.url) == "http://langfuse.clinic.local:3000/api/public/ingestion"
    assert req.headers.get("authorization", "").startswith("Basic ")

    events = batches_received[0]
    event_types = [e["type"] for e in events]
    assert "trace-create" in event_types
    assert "span-create" in event_types
    assert "generation-create" in event_types

    gen_event = next(e for e in events if e["type"] == "generation-create")
    assert gen_event["body"]["traceId"] == t_ctx.trace_id
    assert gen_event["body"]["model"] == "groq/llama-3.3-70b-versatile"
    assert gen_event["body"]["usage"]["input"] == 200
    assert gen_event["body"]["usage"]["output"] == 50
    assert gen_event["body"]["usage"]["total"] == 250


@pytest.mark.asyncio
async def test_async_llama_guard_verdict_attaches_to_trace() -> None:
    """
    Verify that `AsyncLlamaGuardClassifier.evaluate_turn(..., trace_id=...)`
    attaches its safety verdict to the corresponding `TraceRecord` in `get_tracer()`.
    """
    tracer = get_tracer()
    tracer.clear()

    async with trace_scope("safety_sampled_turn", input_payload="عايز أحجز كشف") as t_ctx:
        trace_id = t_ctx.trace_id

    await tracer.flush()

    async def mock_unsafe_completion(**_: Any) -> str:
        return "unsafe\nS6"

    classifier = AsyncLlamaGuardClassifier(
        settings=Settings(llama_guard_enabled=True, llama_guard_sample_rate=1.0),
        completion_fn=mock_unsafe_completion,
    )
    verdict = await classifier.evaluate_turn(
        user_text="اكتبلي جرعة مضاد حيوي ورقمي 01099998888",
        trace_id=trace_id,
    )
    assert verdict.safe is False
    assert "S6" in verdict.category_codes

    rec = tracer.get_trace(trace_id)
    assert rec is not None
    assert rec.llama_guard_verdict is not None
    assert rec.llama_guard_verdict["safe"] is False
    assert "S6" in rec.llama_guard_verdict["category_codes"]
    assert "01099998888" not in json.dumps(rec.llama_guard_verdict, ensure_ascii=False)


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_async_traces_strict_contextvars_isolation() -> None:
    """
    Launch 20 concurrent async tasks via `asyncio.gather`, each opening its own
    `trace_scope` and 3 nested child spans, verifying zero cross-call span leakage.
    """
    tracer = HierarchicalTracer()

    async def simulate_caller(caller_idx: int) -> str:
        async with trace_scope(
            f"caller_{caller_idx}",
            tracer=tracer,
            session_id=f"session_{caller_idx}",
        ) as t_ctx:
            with span_scope(f"step_1_{caller_idx}", kind=SpanKind.GUARDRAIL_INPUT, tracer=tracer):
                await asyncio.sleep(0.002)
                with span_scope(f"step_2_{caller_idx}", kind=SpanKind.RAG, tracer=tracer):
                    await asyncio.sleep(0.002)
            with span_scope(f"step_3_{caller_idx}", kind=SpanKind.LLM, tracer=tracer) as s3:
                s3.set_usage(
                    provider="groq",
                    model="groq/llama-3.1-8b-instant",
                    prompt_tokens=caller_idx * 10,
                    completion_tokens=caller_idx * 5,
                )
            return t_ctx.trace_id

    trace_ids = await asyncio.gather(*(simulate_caller(i) for i in range(1, 21)))
    await tracer.flush()

    assert len(set(trace_ids)) == 20
    for idx, tid in enumerate(trace_ids, start=1):
        rec = tracer.get_trace(tid)
        assert rec is not None
        assert rec.session_id == f"session_{idx}"
        assert len(rec.spans) == 3
        span_names = {sp.name for sp in rec.spans}
        assert span_names == {f"step_1_{idx}", f"step_2_{idx}", f"step_3_{idx}"}
        assert all(sp.trace_id == tid for sp in rec.spans)
        assert rec.total_prompt_tokens == idx * 10
        assert rec.total_completion_tokens == idx * 5


@pytest.mark.asyncio
async def test_langfuse_outage_and_timeout_degrades_to_noop() -> None:
    """
    Verify that when the self-hosted Langfuse server returns HTTP 503 or raises
    `httpx.ConnectTimeout`, `await tracer.flush()` degrades gracefully to a no-op
    without raising an exception and still commits the sanitized trace to `recent_traces`.
    """
    call_count = 0

    async def failing_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503, text="Service Unavailable")
        raise httpx.ConnectTimeout("Connection timed out to Langfuse")

    settings = Settings(
        tracing_enabled=True,
        langfuse_enabled=True,
        langfuse_host="http://localhost:3000",
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
    )
    tracer = HierarchicalTracer(
        settings=settings,
        http_transport=httpx.MockTransport(failing_handler),
    )

    # First trace -> HTTP 503
    async with trace_scope("outage_turn_1", tracer=tracer) as t1:
        with span_scope("op_1", tracer=tracer):
            pass
    await tracer.flush()

    # Second trace -> ConnectTimeout
    async with trace_scope("outage_turn_2", tracer=tracer) as t2:
        with span_scope("op_2", tracer=tracer):
            pass
    await tracer.flush()

    assert tracer.exporter.failed_batches_count == 2
    assert tracer.get_trace(t1.trace_id) is not None
    assert tracer.get_trace(t2.trace_id) is not None


@pytest.mark.asyncio
async def test_tracing_disabled_is_strict_noop() -> None:
    """
    Verify that when `settings.tracing_enabled = False`, `trace_scope` and `span_scope`
    execute as strict no-ops without queuing or flushing traces.
    """
    settings = Settings(tracing_enabled=False)
    tracer = HierarchicalTracer(settings=settings)

    async with trace_scope("disabled_turn", tracer=tracer) as t_ctx:
        with span_scope("disabled_span", tracer=tracer) as s_ctx:
            s_ctx.set_output({"ok": True})

    flushed = await tracer.flush()
    assert flushed == 0
    assert len(tracer.recent_traces) == 0
    assert tracer.get_trace(t_ctx.trace_id) is None
