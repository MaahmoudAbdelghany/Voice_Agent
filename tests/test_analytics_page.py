"""
3-Tier Validation Suite for Clinic Voice Latency Charts & Call Volume Analytics.

Covers:
- Tier 1: Unit Verification (KPI math, SLA calculations, volume bucketing, clinic tool aggregations, i18n keys)
- Tier 2: Integration Verification (compute_dashboard_analytics on persisted clinic fixtures, Streamlit AppTest empty & populated rendering)
- Tier 3: Error & Edge-Case Verification (Empty dataset resilience without ZeroDivisionError, null latency values, 100% SLA breach, N=1 session percentile safety)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.agent.session_manager import (
    BookingRef,
    CallSession,
    CallStatus,
    EscalationInfo,
    MessageRole,
    SessionManager,
)
from src.dashboard.analytics_data import (
    aggregate_daily_volume,
    aggregate_hourly_volume,
    aggregate_language_distribution,
    aggregate_latency_breakdown,
    aggregate_sentiment_distribution,
    aggregate_tool_invocations,
    calculate_analytics_kpis,
    compute_dashboard_analytics,
)
from src.dashboard.calls_data import load_call_sessions
from src.dashboard.i18n import TRANSLATIONS

ANALYTICS_PAGE_FILE = str(
    Path(__file__).parent.parent / "src" / "dashboard" / "pages" / "02_analytics.py"
)


def _persist_clinic_analytics_fixtures(storage_dir: Path) -> list[CallSession]:
    """Persist multi-day clinic CallSession fixtures for analytics integration tests."""
    mgr = SessionManager(storage_dir=storage_dir)
    now = datetime.now(timezone.utc)

    s1 = mgr.create_session(
        session_id="analytics-clinic-1",
        room_name="clinic-room-1",
        participant_identity="patient-1",
        language="ar",
        customer_phone="+201001112233",
    )
    s1.start_time = (now - timedelta(days=1)).replace(hour=13, minute=10)
    s1.context.patient_name = "هدى سامي"
    s1.context.sentiment = "positive"
    s1.context.bookings.append(
        BookingRef(
            booking_code="APP-501",
            action="book",
            doctor_name="د. منى عبد العزيز",
            specialty_name="الأطفال",
            appointment_date="2026-11-16",
            queue_number=2,
        )
    )
    s1.add_turn(role=MessageRole.USER, content="مواعيد دكتورة منى أطفال", stt_latency_ms=150.0)
    s1.add_turn(
        role=MessageRole.TOOL,
        content="Available shifts found",
        tool_name="check_doctor_availability",
        tool_arguments={"specialty": "الأطفال"},
        tool_result={"available": True},
    )
    s1.add_turn(
        role=MessageRole.TOOL,
        content="Booked APP-501",
        tool_name="book_appointment",
        tool_arguments={"doctor_id": 3, "appointment_date": "2026-11-16"},
        tool_result={"booking_code": "APP-501", "queue_number": 2},
    )
    s1.add_turn(
        role=MessageRole.ASSISTANT,
        content="تم حجز موعدك مع دكتورة منى برقم APP-501.",
        latency_ms=600.0,
        llm_latency_ms=240.0,
        tts_latency_ms=210.0,
    )
    s1.status = CallStatus.ENDED
    s1.metrics.duration_seconds = 65.0
    mgr.save_session(s1.session_id)

    s2 = mgr.create_session(
        session_id="analytics-clinic-2",
        room_name="clinic-room-2",
        participant_identity="patient-2",
        language="en",
        customer_phone="+201112223344",
    )
    s2.start_time = now.replace(hour=20, minute=25)
    s2.context.patient_name = "Karim Adel"
    s2.context.sentiment = "negative"
    s2.context.escalated = True
    s2.context.escalation = EscalationInfo(
        ticket_id="ESC-77",
        department="reception",
        urgency="high",
        reason="Billing dispute",
    )
    s2.add_turn(role=MessageRole.USER, content="Please cancel my appointment and connect reception", stt_latency_ms=180.0)
    s2.add_turn(
        role=MessageRole.TOOL,
        content="Cancelled APP-400",
        tool_name="manage_appointment",
        tool_arguments={"action": "cancel", "booking_code": "APP-400"},
        tool_result={"booking_code": "APP-400", "status": "cancelled"},
    )
    s2.add_turn(
        role=MessageRole.TOOL,
        content="Transferred",
        tool_name="transfer_to_receptionist",
        tool_arguments={"department": "reception"},
        tool_result={"ticket_id": "ESC-77", "status": "queued"},
    )
    s2.add_turn(
        role=MessageRole.ASSISTANT,
        content="Your appointment is cancelled and I am transferring you to reception now.",
        latency_ms=880.0,
        llm_latency_ms=420.0,
        tts_latency_ms=280.0,
    )
    s2.status = CallStatus.ESCALATED
    s2.metrics.duration_seconds = 95.0
    mgr.save_session(s2.session_id)

    return [s1, s2]


# ==============================================================================
# Tier 1: Unit Verification Tests
# ==============================================================================

class TestAnalyticsTier1Unit:
    """Isolated unit tests for analytical calculations and clinic tool aggregators."""

    def test_calculate_kpis_empty(self):
        """T3.3: Verify safe default metrics when session list is empty."""
        kpis = compute_dashboard_analytics([])
        assert kpis["total_calls"] == 0
        assert kpis["avg_latency_ms"] == 0.0
        assert kpis["p95_latency_ms"] == 0.0
        assert kpis["sla_compliance_rate"] == 100.0
        assert kpis["escalation_rate"] == 0.0
        assert kpis["total_turns"] == 0
        assert kpis["sla_breach_count"] == 0
        assert kpis["sla_pass_count"] == 0

    def test_calculate_kpis_with_sessions(self):
        """Validate exact arithmetic for avg latency, p95, SLA compliance, and escalation rate."""
        now = datetime.now(timezone.utc)

        s1 = CallSession(session_id="s1", start_time=now, status=CallStatus.ENDED)
        s1.context.escalated = False
        s1.metrics.duration_seconds = 60.0
        s1.add_turn(role=MessageRole.USER, content="أريد حجز كشف", stt_latency_ms=150.0)
        s1.add_turn(
            role=MessageRole.ASSISTANT,
            content="أهلاً بحضرتك في عيادة النور",
            latency_ms=600.0,
            llm_latency_ms=250.0,
            tts_latency_ms=200.0,
        )

        s2 = CallSession(session_id="s2", start_time=now, status=CallStatus.ESCALATED)
        s2.context.escalated = True
        s2.metrics.duration_seconds = 120.0
        s2.add_turn(role=MessageRole.USER, content="عايز موظف الاستقبال", stt_latency_ms=180.0)
        s2.add_turn(
            role=MessageRole.ASSISTANT,
            content="جاري التحويل للاستقبال",
            latency_ms=900.0,
            llm_latency_ms=450.0,
            tts_latency_ms=270.0,
        )

        kpis = calculate_analytics_kpis([s1, s2])
        assert kpis["total_calls"] == 2
        assert kpis["avg_latency_ms"] == 750.0
        assert kpis["sla_compliance_rate"] == 50.0
        assert kpis["escalation_rate"] == 50.0
        assert kpis["sla_pass_count"] == 1
        assert kpis["sla_breach_count"] == 1
        assert kpis["avg_duration_seconds"] == 90.0

    def test_aggregate_latency_breakdown(self):
        """Confirm average decomposition into STT, LLM, and TTS milliseconds."""
        now = datetime.now(timezone.utc)
        s = CallSession(session_id="test-lat", start_time=now)
        s.add_turn(role=MessageRole.USER, content="Query", stt_latency_ms=160.0)
        s.add_turn(
            role=MessageRole.ASSISTANT,
            content="Response",
            latency_ms=620.0,
            llm_latency_ms=240.0,
            tts_latency_ms=220.0,
        )

        breakdown = aggregate_latency_breakdown([s])
        assert breakdown["avg_stt_ms"] == 160.0
        assert breakdown["avg_llm_ms"] == 240.0
        assert breakdown["avg_tts_ms"] == 220.0
        assert breakdown["avg_total_ms"] == 620.0
        assert len(breakdown["all_turns"]) == 1
        assert breakdown["all_turns"][0]["is_sla_compliant"] is True

    def test_aggregate_hourly_and_daily_volume(self):
        """Verify correct time bucketing (24-hour distribution and daily grouping)."""
        now = datetime.now(timezone.utc)
        s1 = CallSession(session_id="s1", start_time=now.replace(hour=13, minute=15))
        s1.status = CallStatus.ENDED

        s2 = CallSession(session_id="s2", start_time=now.replace(hour=20, minute=45))
        s2.status = CallStatus.ESCALATED
        s2.context.escalated = True

        daily = aggregate_daily_volume([s1, s2])
        assert len(daily) == 1
        assert daily[0]["total"] == 2
        assert daily[0]["completed"] == 1
        assert daily[0]["escalated"] == 1

        hourly = aggregate_hourly_volume([s1, s2])
        assert len(hourly) == 24
        assert hourly[13]["count"] == 1
        assert hourly[13]["is_peak"] is True
        assert hourly[20]["count"] == 1
        assert hourly[20]["is_peak"] is True
        assert hourly[3]["count"] == 0
        assert hourly[3]["is_peak"] is False

    def test_aggregate_clinic_tool_invocations(self):
        """Verify counting and ranking of clinic tool names from session turns."""
        s = CallSession(session_id="s-clinic-tools")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="check_doctor_availability")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="check_doctor_availability")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="book_appointment")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="manage_appointment")

        tools = aggregate_tool_invocations([s])
        assert len(tools) == 3
        assert tools[0]["tool_name"] == "check_doctor_availability"
        assert tools[0]["count"] == 2
        assert tools[0]["percentage"] == pytest.approx(50.0, rel=0.1)
        ranked_names = {t_item["tool_name"] for t_item in tools}
        assert ranked_names == {"check_doctor_availability", "book_appointment", "manage_appointment"}

    def test_aggregate_sentiment_and_language_distribution(self):
        """Confirms positive, neutral, negative sentiment and language counts."""
        s1 = CallSession(session_id="s1")
        s1.context.sentiment = "positive"
        s1.context.language = "ar"

        s2 = CallSession(session_id="s2")
        s2.context.sentiment = "negative"
        s2.context.language = "en"

        s3 = CallSession(session_id="s3")
        s3.context.sentiment = "neutral"
        s3.context.language = "ar"

        sent = aggregate_sentiment_distribution([s1, s2, s3])
        assert sent["positive"] == 1
        assert sent["neutral"] == 1
        assert sent["negative"] == 1

        lang = aggregate_language_distribution([s1, s2, s3])
        assert lang["ar"] == 2
        assert lang["en"] == 1

    def test_persisted_clinic_sessions_analytics_pipeline(self, tmp_path: Path):
        """T2.2: Verify persisted clinic sessions compute accurate KPIs and tool counts."""
        _persist_clinic_analytics_fixtures(tmp_path)
        loaded = load_call_sessions(storage_dir=tmp_path)
        assert len(loaded) == 2

        kpis = compute_dashboard_analytics(loaded)
        assert kpis["total_calls"] == 2
        assert kpis["avg_latency_ms"] == 740.0
        assert kpis["sla_compliance_rate"] == 50.0
        assert kpis["escalation_rate"] == 50.0

        tool_counts = {item["tool_name"]: item["count"] for item in aggregate_tool_invocations(loaded)}
        assert tool_counts == {
            "check_doctor_availability": 1,
            "book_appointment": 1,
            "manage_appointment": 1,
            "transfer_to_receptionist": 1,
        }

    def test_analytics_i18n_keys(self):
        """Verify presence of all analytics keys in both English and Arabic."""
        keys = [
            "analytics_page_title",
            "analytics_page_subtitle",
            "filter_time_range_label",
            "analytics_kpi_total_calls",
            "analytics_kpi_avg_latency",
            "analytics_kpi_sla_rate",
            "sec_sla_breakdown_title",
            "sec_volume_trends_title",
            "sec_conversational_insights_title",
            "chart_component_latency_title",
            "chart_daily_volume_title",
            "chart_hourly_volume_title",
            "chart_sentiment_title",
            "chart_tools_title",
            "chart_language_title",
        ]
        for k in keys:
            assert k in TRANSLATIONS["en"], f"Missing EN translation for {k}"
            assert k in TRANSLATIONS["ar"], f"Missing AR translation for {k}"


# ==============================================================================
# Tier 2: Integration Verification Tests (Streamlit AppTest)
# ==============================================================================

class TestAnalyticsTier2Integration:
    """Streamlit simulation tests verifying empty-state and clinic fixture chart rendering."""

    def test_analytics_page_renders_empty_state_without_errors(self, tmp_path: Path):
        """T3.3: Verify 02_analytics.py renders empty state with 5 zeroed KPI metrics and warning."""
        empty_dir = tmp_path / "empty_analytics"
        empty_dir.mkdir(parents=True, exist_ok=True)

        app = AppTest.from_file(ANALYTICS_PAGE_FILE)
        app.session_state["calls_storage_dir"] = str(empty_dir)
        app.run(timeout=10)
        assert len(app.exception) == 0, f"AppTest raised: {[e.value for e in app.exception]}"
        assert len(app.metric) >= 5
        assert len(app.warning) == 1
        assert list(empty_dir.glob("*.json")) == []

    def test_analytics_page_renders_clinic_fixtures_and_filters(self, tmp_path: Path):
        """T2.2: Verify 02_analytics.py renders clinic fixtures, charts, and filter interactions."""
        clinic_dir = tmp_path / "clinic_analytics"
        clinic_dir.mkdir(parents=True, exist_ok=True)
        _persist_clinic_analytics_fixtures(clinic_dir)

        app = AppTest.from_file(ANALYTICS_PAGE_FILE)
        app.session_state["calls_storage_dir"] = str(clinic_dir)
        app.run(timeout=10)
        assert len(app.exception) == 0
        assert len(app.metric) >= 5
        assert len(app.markdown) >= 3

        if app.selectbox:
            range_box = app.selectbox[0]
            if len(range_box.options) > 1:
                range_box.select(range_box.options[0]).run(timeout=10)
                assert len(app.exception) == 0


# ==============================================================================
# Tier 3: Error & Edge-Case Verification Tests
# ==============================================================================

class TestAnalyticsTier3EdgeCases:
    """Resilience tests for empty storage, null parameters, and extreme SLA values."""

    def test_zero_calls_graceful_kpis(self):
        """T3.3: Verify KPI math with zero calls does not raise ZeroDivisionError."""
        kpis = compute_dashboard_analytics([])
        assert kpis["total_calls"] == 0
        assert kpis["avg_latency_ms"] == 0.0
        assert kpis["sla_compliance_rate"] == 100.0

    def test_sessions_with_null_latencies(self):
        """Turns with None latencies are gracefully handled without TypeError."""
        s = CallSession(session_id="s-none")
        s.add_turn(role=MessageRole.ASSISTANT, content="Hi", latency_ms=None)
        s.add_turn(role=MessageRole.USER, content="Hello", stt_latency_ms=None)

        kpis = calculate_analytics_kpis([s])
        assert kpis["total_calls"] == 1
        assert kpis["avg_latency_ms"] == 0.0

        breakdown = aggregate_latency_breakdown([s])
        assert breakdown["avg_stt_ms"] == 0.0
        assert breakdown["avg_total_ms"] == 0.0

    def test_extreme_sla_breach(self):
        """Verify when 100% of calls breach SLA budget, SLA rate is 0.0%."""
        s = CallSession(session_id="s-breach")
        s.add_turn(role=MessageRole.ASSISTANT, content="Late", latency_ms=1500.0)

        kpis = calculate_analytics_kpis([s])
        assert kpis["sla_compliance_rate"] == 0.0
        assert kpis["sla_breach_count"] == 1
        assert kpis["sla_pass_count"] == 0

    def test_single_call_session_percentile(self):
        """Verify percentile calculation does not crash when N=1."""
        s = CallSession(session_id="s-single")
        s.add_turn(role=MessageRole.ASSISTANT, content="Test", latency_ms=450.0)

        kpis = calculate_analytics_kpis([s])
        assert kpis["avg_latency_ms"] == 450.0
        assert kpis["p95_latency_ms"] == 450.0
        assert kpis["p50_latency_ms"] == 450.0
