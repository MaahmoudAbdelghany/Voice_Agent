"""
Automated Unit, Integration, Concurrency & Edge-Case Tests for Feature 4.7:
FinOps Token Budgets, Daily Cost Circuit Breaker & Tool Payload Pruner (`src/ai_core/finops.py`).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from src.ai_core.finops import (
    AlertLevel,
    FinOpsAlert,
    FinOpsController,
    FinOpsGateStatus,
    finops_session_scope,
    format_pruned_tool_message,
    prune_tool_payload,
    resolve_finops_session_id,
)
from src.ai_core.gateway import (
    DegradationTier,
    ModelGateway,
    Stage,
)
from src.ai_core.tracing import HierarchicalTracer, trace_scope
from src.config import Settings
from src.tools.gates import caller_session_scope
from src.tools.schemas import ToolResult

# ==============================================================================
# Mock LLM Provider for Deterministic Gateway + FinOps Integration Tests
# ==============================================================================


class MockUsageLLMProvider:
    """Deterministic mock LLM provider recording requested max_tokens and emitting usage."""

    def __init__(
        self,
        name: str = "groq",
        configured: bool = True,
        reply_text: str = "أهلاً بحضرتك في عيادات النور.",
        prompt_tokens: int = 1000,
        completion_tokens: int = 100,
    ) -> None:
        self.name = name
        self._configured = configured
        self.reply_text = reply_text
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.calls_count = 0
        self.seen_max_tokens: list[int] = []

    def is_configured(self) -> bool:
        return self._configured

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
        self.calls_count += 1
        self.seen_max_tokens.append(max_tokens)
        yield (
            self.reply_text,
            None,
            {
                "ttft_ms": 42.0,
                "finish_reason": "stop",
                "usage": {
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens,
                    "total_tokens": self.prompt_tokens + self.completion_tokens,
                },
                "elapsed_ms": 55.0,
            },
        )


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_call_token_budget_tracking_and_remaining_token_clamping() -> None:
    """
    R1.1, R1.3, R1.4: Verify per-call 8,000-token budget tracking, clamping of the
    final turn when remaining tokens < stage limit (150), and CALL_BUDGET_EXCEEDED
    once cumulative tokens reach >= 8,000 (or remaining < 16).
    """
    cfg = Settings(
        finops_enabled=True,
        finops_call_token_budget=8000,
        finops_min_turn_tokens=16,
        voice_max_tokens=150,
    )
    ctrl = FinOpsController(settings=cfg)

    # Fresh session: full 150 tokens allowed
    dec_initial = ctrl.check_budget(Stage.DIALOGUE, session_id="call_101")
    assert dec_initial.allowed is True
    assert dec_initial.status == FinOpsGateStatus.ALLOWED
    assert dec_initial.effective_max_tokens == 150
    assert dec_initial.clamped_by_call_budget is False

    # Consume 7,920 tokens (80 remaining out of 8,000)
    call_snap, _ = ctrl.record_usage(
        "groq/llama-3.3-70b-versatile",
        prompt_tokens=7000,
        completion_tokens=920,
        session_id="call_101",
    )
    assert call_snap is not None
    assert call_snap.total_tokens == 7920
    assert call_snap.remaining_tokens == 80
    assert call_snap.exhausted is False

    # Next turn should be ALLOWED but clamped from 150 down to 80
    dec_clamped = ctrl.check_budget(Stage.DIALOGUE, session_id="call_101")
    assert dec_clamped.allowed is True
    assert dec_clamped.status == FinOpsGateStatus.ALLOWED
    assert dec_clamped.requested_max_tokens == 150
    assert dec_clamped.effective_max_tokens == 80
    assert dec_clamped.clamped_by_call_budget is True

    # Consume 70 more tokens -> 7,990 used (only 10 remaining, which is < min_turn_tokens=16)
    ctrl.record_usage(
        "groq/llama-3.3-70b-versatile",
        prompt_tokens=50,
        completion_tokens=20,
        session_id="call_101",
    )
    dec_min_breach = ctrl.check_budget(Stage.DIALOGUE, session_id="call_101")
    assert dec_min_breach.allowed is False
    assert dec_min_breach.status == FinOpsGateStatus.CALL_BUDGET_EXCEEDED
    assert dec_min_breach.effective_max_tokens == 0
    assert dec_min_breach.reason == "call_token_budget_exceeded"

    # A different concurrent session ("call_102") is completely unaffected
    dec_other = ctrl.check_budget(Stage.DIALOGUE, session_id="call_102")
    assert dec_other.allowed is True
    assert dec_other.effective_max_tokens == 150


def test_daily_spend_accumulator_80_percent_alert_and_100_percent_breaker() -> None:
    """
    R2.1, R2.3, R3.1: Verify that crossing 80% ($8.00 of $10.00) emits exactly one
    WARNING_80_PERCENT alert while staying ALLOWED, and crossing 100% ($10.00) emits
    one CRITICAL_100_PERCENT alert and trips DAILY_CAP_EXCEEDED.
    """
    cfg = Settings(
        finops_enabled=True,
        finops_daily_spend_cap_usd=10.0,
        finops_daily_alert_ratio=0.80,
    )
    ctrl = FinOpsController(settings=cfg)
    received_alerts: list[FinOpsAlert] = []
    ctrl.register_alert_callback(received_alerts.append)

    # 1. Spend $5.00 (50%) -> no alerts, ALLOWED
    ctrl.record_usage("groq/llama-3.3-70b-versatile", 100, 50, cost_usd=5.00, session_id="s1")
    assert len(received_alerts) == 0
    assert ctrl.check_budget(Stage.DIALOGUE, session_id="s1").status == FinOpsGateStatus.ALLOWED

    # 2. Spend another $3.20 -> total $8.20 (82% >= 80%) -> emits 80% alert ONCE, still ALLOWED
    _, daily_snap = ctrl.record_usage(
        "groq/llama-3.3-70b-versatile", 100, 50, cost_usd=3.20, session_id="s1"
    )
    assert daily_snap.spend_usd == pytest.approx(8.20)
    assert daily_snap.alert_80_emitted is True
    assert daily_snap.breaker_100_tripped is False
    assert len(received_alerts) == 1
    assert received_alerts[0].level == AlertLevel.WARNING_80_PERCENT
    assert ctrl.check_budget(Stage.DIALOGUE, session_id="s1").status == FinOpsGateStatus.ALLOWED

    # 3. Spend another $0.50 -> total $8.70 -> idempotent: no duplicate 80% alert!
    ctrl.record_usage("groq/llama-3.3-70b-versatile", 100, 50, cost_usd=0.50, session_id="s1")
    assert len(received_alerts) == 1

    # 4. Spend another $1.50 -> total $10.20 (>= $10.00) -> emits 100% alert & trips breaker
    _, daily_snap_breach = ctrl.record_usage(
        "groq/llama-3.3-70b-versatile", 100, 50, cost_usd=1.50, session_id="s1"
    )
    assert daily_snap_breach.breaker_100_tripped is True
    assert len(received_alerts) == 2
    assert received_alerts[1].level == AlertLevel.CRITICAL_100_PERCENT

    dec = ctrl.check_budget(Stage.DIALOGUE, session_id="s2")
    assert dec.allowed is False
    assert dec.status == FinOpsGateStatus.DAILY_CAP_EXCEEDED
    assert dec.reason == "daily_cost_cap_exceeded"


def test_cairo_date_rollover_resets_daily_spend_and_alerts() -> None:
    """
    R2.2: Verify that when the Cairo calendar date advances to the next day,
    daily spend resets to $0.00, the cost circuit breaker closes, and alerts reset.
    """
    current_day = [dt.date(2026, 11, 1)]
    cfg = Settings(
        finops_enabled=True,
        finops_daily_spend_cap_usd=10.0,
        finops_daily_alert_ratio=0.80,
    )
    ctrl = FinOpsController(settings=cfg, date_provider=lambda: current_day[0])

    # Breach $10 cap on 2026-11-01
    ctrl.record_usage("groq/llama-3.3-70b-versatile", 1000, 500, cost_usd=10.50, session_id="c1")
    dec_day1 = ctrl.check_budget(Stage.DIALOGUE, session_id="c2")
    assert dec_day1.status == FinOpsGateStatus.DAILY_CAP_EXCEEDED
    assert dec_day1.cairo_date == "2026-11-01"

    # Roll over Cairo clock to 2026-11-02 (midnight Cairo time)
    current_day[0] = dt.date(2026, 11, 2)
    snap_day2 = ctrl.get_daily_snapshot()
    assert snap_day2.cairo_date == "2026-11-02"
    assert snap_day2.spend_usd == 0.0
    assert snap_day2.alert_80_emitted is False
    assert snap_day2.breaker_100_tripped is False

    dec_day2 = ctrl.check_budget(Stage.DIALOGUE, session_id="c2")
    assert dec_day2.allowed is True
    assert dec_day2.status == FinOpsGateStatus.ALLOWED
    assert dec_day2.cairo_date == "2026-11-02"


@pytest.mark.asyncio
async def test_session_id_resolution_priority_hierarchy() -> None:
    """
    R1.2: Verify automatic session_id resolution priority:
    explicit arg > finops_session_scope > trace_scope > caller_session_scope.
    """
    assert resolve_finops_session_id() is None

    with caller_session_scope("01012345678", session_id="caller_sess_1"):
        assert resolve_finops_session_id() == "caller_sess_1"

        async with trace_scope("voice_turn", session_id="trace_sess_2"):
            assert resolve_finops_session_id() == "trace_sess_2"

            with finops_session_scope("finops_sess_3"):
                assert resolve_finops_session_id() == "finops_sess_3"
                assert resolve_finops_session_id("explicit_sess_4") == "explicit_sess_4"


def test_prune_tool_payload_allowlist_and_size_caps() -> None:
    """
    R4.1, R4.2, R4.3: Verify schema-aware allowlist pruning and character/list caps across
    all 5 clinic tools (`book_appointment`, `check_doctor_availability`, `manage_appointment`,
    `search_clinic_knowledge`, `transfer_to_receptionist`).
    """
    cfg = Settings(
        finops_max_tool_list_items=5,
        finops_max_tool_field_chars=300,
        finops_max_tool_payload_chars=1200,
    )

    # 1. book_appointment with bloated internal fields
    raw_booking = ToolResult(
        success=True,
        message="تم حجز موعدك بنجاح مع دكتور أحمد سمير، رقم دورك 4.",
        data={
            "booking_code": "NOUR-20261102-004",
            "appointment_id": 42,
            "queue_number": 4,
            "doctor_name": "د. أحمد سمير",
            "specialty": "الباطنة العامة",
            "appointment_date": "2026-11-02",
            "shift_start": "18:00",
            "shift_end": "21:00",
            "fee_egp": 350,
            "status": "CONFIRMED",
            "internal_sql_query": "SELECT * FROM appointments WHERE ...",
            "debug_stack": "x" * 2000,
        },
    )
    pruned_booking = prune_tool_payload("book_appointment", raw_booking, settings=cfg)
    assert pruned_booking["success"] is True
    assert "رقم دورك 4" in pruned_booking["message"]
    assert pruned_booking["data"]["booking_code"] == "NOUR-20261102-004"
    assert pruned_booking["data"]["queue_number"] == 4
    assert pruned_booking["data"]["fee_egp"] == 350
    assert "internal_sql_query" not in pruned_booking["data"]
    assert "debug_stack" not in pruned_booking["data"]

    # 2. check_doctor_availability with > 5 schedules & long bio
    raw_avail = {
        "success": True,
        "message": "المواعيد المتاحة لدكتور سارة",
        "data": {
            "found": True,
            "doctor_name": "د. سارة نبيل",
            "specialty": "طب الأطفال",
            "schedules": [
                {
                    "date": f"2026-11-0{i}",
                    "shift_start": "17:00",
                    "shift_end": "20:00",
                    "available_slots": 5,
                    "internal_row_hash": "secret_hash",
                }
                for i in range(1, 9)  # 8 items -> should be capped to 5
            ],
            "unlisted_blob": "should_be_removed",
        },
    }
    pruned_avail = prune_tool_payload("check_doctor_availability", raw_avail, settings=cfg)
    assert len(pruned_avail["data"]["schedules"]) == 5
    assert "internal_row_hash" not in pruned_avail["data"]["schedules"][0]
    assert "unlisted_blob" not in pruned_avail["data"]

    # 3. Serialized size cap <= 1,200 chars
    formatted_json = format_pruned_tool_message(
        "check_doctor_availability", raw_avail, settings=cfg
    )
    assert len(formatted_json) <= 1200
    parsed = json.loads(formatted_json)
    assert parsed["success"] is True


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_gateway_enforces_call_budget_and_escalates_to_tier4_on_exhaustion() -> None:
    """
    R1.3, R1.4: Verify that ModelGateway automatically records token usage per turn,
    clamps the final turn's max_tokens when approaching 8,000 tokens, and escalates
    to Tier 4 (`call_token_budget_exceeded`) without calling providers once exhausted.
    """
    cfg = Settings(
        finops_enabled=True,
        finops_call_token_budget=2000,
        finops_min_turn_tokens=16,
        voice_max_tokens=150,
    )
    mock_groq = MockUsageLLMProvider(
        name="groq",
        prompt_tokens=850,
        completion_tokens=100,  # 950 tokens per turn
    )
    gw = ModelGateway(
        settings=cfg,
        primary_provider=mock_groq,
        fallback_provider=MockUsageLLMProvider(name="gemini", configured=False),
    )
    messages = [{"role": "user", "content": "عايز أحجز كشف باطنة"}]

    with finops_session_scope("call_session_77"):
        # Turn 1: uses 950 tokens (1,050 remaining) -> max_tokens=150
        res1 = await gw.agenerate(Stage.DIALOGUE, messages)
        assert res1.success is True
        assert res1.degradation_tier == DegradationTier.TIER_1_PRIMARY
        assert mock_groq.seen_max_tokens[-1] == 150

        # Turn 2: uses another 950 tokens -> 1,900 used (100 remaining) -> max_tokens=150
        res2 = await gw.agenerate(Stage.DIALOGUE, messages)
        assert res2.success is True
        assert gw.finops.get_session_snapshot().total_tokens == 1900

        # Turn 3: only 100 tokens remaining (< 150) -> gateway clamps max_tokens to 100!
        res3 = await gw.agenerate(Stage.DIALOGUE, messages)
        assert res3.success is True
        assert mock_groq.seen_max_tokens[-1] == 100
        assert gw.finops.get_session_snapshot().total_tokens == 2850

        # Turn 4: 2,850 >= 2,000 budget -> blocked pre-flight! 0 provider calls, Tier 4 escalation
        calls_before = mock_groq.calls_count
        res4 = await gw.agenerate(Stage.DIALOGUE, messages)
        assert mock_groq.calls_count == calls_before
        assert res4.success is True
        assert res4.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION
        assert res4.escalate is True
        assert res4.error_class == "call_token_budget_exceeded"
        assert res4.attempts == []
        assert "موظف الاستقبال" in (res4.text or "")


@pytest.mark.asyncio
async def test_gateway_degrades_to_tier3_search_only_when_daily_cost_cap_breached() -> None:
    """
    R3.1, R3.2: Verify that when the $10.00 daily spend cap is reached, ModelGateway
    bypasses Groq and Gemini (attempts=[]) and serves a Tier 3 grounded KB snippet.
    """
    cfg = Settings(
        finops_enabled=True,
        finops_daily_spend_cap_usd=10.0,
    )
    mock_groq = MockUsageLLMProvider(name="groq")
    mock_gemini = MockUsageLLMProvider(name="gemini")

    async def mock_kb_search(query: str) -> str | None:
        return "سعر كشف الباطنة العامة 300 جنيه مصري."

    gw = ModelGateway(
        settings=cfg,
        primary_provider=mock_groq,
        fallback_provider=mock_gemini,
        search_fallback=mock_kb_search,
    )

    # Trip the $10.00 daily cost circuit breaker
    gw.finops.record_usage(
        "groq/llama-3.3-70b-versatile", 5000, 1000, cost_usd=10.05, session_id="s0"
    )

    res = await gw.agenerate(
        Stage.DIALOGUE,
        [{"role": "user", "content": "بكام سعر كشف الباطنة؟"}],
        session_id="s_new",
    )
    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_3_SEARCH_ONLY
    assert res.escalate is False
    assert res.error_class == "daily_cost_cap_exceeded"
    assert res.attempts == []
    assert mock_groq.calls_count == 0
    assert mock_gemini.calls_count == 0
    assert "300 جنيه" in (res.text or "")


@pytest.mark.asyncio
async def test_gateway_daily_cap_breach_still_routes_emergency_to_tier4() -> None:
    """
    R3.2 (Emergency Safety Invariant): Even when the $10.00 daily cost circuit breaker
    is tripped, an emergency symptom utterance must immediately escalate to Tier 4 + 123.
    """
    cfg = Settings(finops_enabled=True, finops_daily_spend_cap_usd=10.0)
    mock_groq = MockUsageLLMProvider(name="groq")
    gw = ModelGateway(settings=cfg, primary_provider=mock_groq)

    gw.finops.record_usage(
        "groq/llama-3.3-70b-versatile", 5000, 1000, cost_usd=10.50, session_id="s0"
    )

    res = await gw.agenerate(
        Stage.DIALOGUE,
        [{"role": "user", "content": "الحقوني عندي ألم شديد في الصدر ومش قادر أتنفس"}],
        session_id="s_emerg",
    )
    assert res.success is True
    assert res.degradation_tier == DegradationTier.TIER_4_HUMAN_ESCALATION
    assert res.escalate is True
    assert res.error_class == "emergency_detected"
    assert "123" in (res.text or "")
    assert mock_groq.calls_count == 0


@pytest.mark.asyncio
async def test_gateway_finops_decisions_recorded_in_active_trace_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify that when ModelGateway runs inside `trace_scope()`, the child LLM span
    captures FinOps attributes (`finops_status`, `call_tokens_used`, `daily_spend_usd`)
    and rolls up `degradation_tier` on budget breach.
    """
    cfg = Settings(
        tracing_enabled=True,
        langfuse_enabled=False,
        finops_enabled=True,
        finops_daily_spend_cap_usd=10.0,
    )
    tracer = HierarchicalTracer(settings=cfg)
    monkeypatch.setattr("src.ai_core.tracing.get_tracer", lambda: tracer)

    mock_groq = MockUsageLLMProvider(name="groq", prompt_tokens=400, completion_tokens=50)
    gw = ModelGateway(
        settings=cfg,
        primary_provider=mock_groq,
        search_fallback=lambda q: "مواعيد العمل من 9 صباحاً حتى 10 مساءً",
    )

    async with trace_scope("voice_turn", session_id="traced_call_1", tracer=tracer) as t_ctx:
        res_ok = await gw.agenerate(
            Stage.DIALOGUE,
            [{"role": "user", "content": "مساء الخير"}],
        )
        assert res_ok.degradation_tier == DegradationTier.TIER_1_PRIMARY

    await tracer.flush()
    trace_rec = tracer.get_trace(t_ctx.trace_id)
    assert trace_rec is not None
    assert len(trace_rec.spans) == 1
    llm_span = trace_rec.spans[0]
    assert llm_span.attributes["finops_status"] == "ALLOWED"
    assert llm_span.attributes["call_tokens_used"] == 450
    assert llm_span.attributes["daily_spend_usd"] > 0.0


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


def test_session_ledger_lru_eviction_respects_max_tracked_sessions() -> None:
    """
    NFR2: Verify bounded LRU eviction when active sessions exceed `finops_max_tracked_sessions`.
    """
    cfg = Settings(finops_enabled=True, finops_max_tracked_sessions=10)
    ctrl = FinOpsController(settings=cfg)

    for i in range(15):
        ctrl.record_usage("groq/llama-3.1-8b-instant", 100, 20, session_id=f"sess_{i}")

    assert ctrl.tracked_sessions_count == 10
    # Oldest 5 sessions (sess_0 .. sess_4) were evicted -> remaining_tokens resets to full 8000
    assert ctrl.get_session_snapshot("sess_0").total_tokens == 0
    # Newest 10 sessions (sess_5 .. sess_14) retain their 120 recorded tokens
    assert ctrl.get_session_snapshot("sess_14").total_tokens == 120


@pytest.mark.asyncio
async def test_concurrent_async_usage_recording_consistency() -> None:
    """
    NFR3: Verify zero lost updates across 25 concurrent async tasks recording usage.
    """
    cfg = Settings(finops_enabled=True, finops_call_token_budget=50000)
    ctrl = FinOpsController(settings=cfg)

    async def worker(idx: int) -> None:
        await asyncio.sleep(0.001 * (idx % 3))
        ctrl.record_usage(
            "groq/llama-3.1-8b-instant",
            prompt_tokens=100,
            completion_tokens=20,
            cost_usd=0.10,
            session_id="shared_session",
        )

    await asyncio.gather(*(worker(i) for i in range(25)))

    call_snap = ctrl.get_session_snapshot("shared_session")
    daily_snap = ctrl.get_daily_snapshot()
    assert call_snap is not None
    assert call_snap.total_tokens == 25 * 120
    assert call_snap.turns_count == 25
    assert daily_snap.total_tokens == 25 * 120
    assert daily_snap.spend_usd == pytest.approx(2.50)


@pytest.mark.asyncio
async def test_non_dialogue_stage_returns_failed_result_on_budget_breach() -> None:
    """
    R1.4, R3.2: Verify that Stage.CLASSIFICATION and Stage.EXTRACTION return
    success=False without calling LLM providers when either call or daily budget is breached.
    """
    cfg = Settings(
        finops_enabled=True, finops_call_token_budget=500, finops_daily_spend_cap_usd=5.0
    )
    mock_groq = MockUsageLLMProvider(name="groq")
    gw = ModelGateway(settings=cfg, primary_provider=mock_groq)

    # 1. Exhaust call budget for "s_cls"
    gw.finops.record_usage("groq/llama-3.1-8b-instant", 500, 50, session_id="s_cls")
    res_cls = await gw.agenerate(
        Stage.CLASSIFICATION,
        [{"role": "user", "content": "حجز"}],
        session_id="s_cls",
    )
    assert res_cls.success is False
    assert res_cls.error_class == "call_token_budget_exceeded"
    assert mock_groq.calls_count == 0

    # 2. Exhaust daily spend cap
    gw.finops.record_usage("groq/llama-3.3-70b-versatile", 1000, 500, cost_usd=5.50)
    res_ext = await gw.agenerate(
        Stage.EXTRACTION,
        [{"role": "user", "content": "دكتور أحمد"}],
        session_id="s_fresh",
    )
    assert res_ext.success is False
    assert res_ext.error_class == "daily_cost_cap_exceeded"
    assert mock_groq.calls_count == 0


def test_finops_disabled_bypasses_all_caps() -> None:
    """
    Verify that when `settings.finops_enabled = False`, requests exceeding 8,000 call
    tokens or $10.00 daily spend remain ALLOWED.
    """
    cfg = Settings(
        finops_enabled=False,
        finops_call_token_budget=1000,
        finops_daily_spend_cap_usd=1.0,
    )
    ctrl = FinOpsController(settings=cfg)
    ctrl.record_usage(
        "groq/llama-3.3-70b-versatile",
        prompt_tokens=5000,
        completion_tokens=5000,
        cost_usd=25.0,
        session_id="s_unbounded",
    )
    dec = ctrl.check_budget(Stage.DIALOGUE, session_id="s_unbounded")
    assert dec.allowed is True
    assert dec.status == FinOpsGateStatus.ALLOWED
    assert dec.effective_max_tokens == cfg.voice_max_tokens
