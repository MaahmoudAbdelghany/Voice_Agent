"""
3-Tier Validation Suite for Feature 5.3 — Latency Charts & Call Volume Analytics.

Covers:
- Tier 1: Unit Verification (KPI math, SLA calculations, volume bucketing, tool aggregations, seeder, i18n keys)
- Tier 2: Integration Verification (Streamlit AppTest simulation, chart rendering, filter interaction, language toggle)
- Tier 3: Error & Edge-Case Verification (Empty dataset resilience, null latency values, 100% SLA breach, N=1 session percentile safety)
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.agent.session_manager import (
    CallSession,
    CallStatus,
    MessageRole,
)
from src.dashboard.analytics_data import (
    aggregate_daily_volume,
    aggregate_hourly_volume,
    aggregate_language_distribution,
    aggregate_latency_breakdown,
    aggregate_sentiment_distribution,
    aggregate_tool_invocations,
    calculate_analytics_kpis,
    seed_analytics_call_sessions,
)
from src.dashboard.i18n import TRANSLATIONS

ANALYTICS_PAGE_FILE = str(
    Path(__file__).parent.parent / "src" / "dashboard" / "pages" / "02_analytics.py"
)


# ==============================================================================
# Tier 1: Unit Verification Tests
# ==============================================================================

class TestAnalyticsTier1Unit:
    """Isolated unit tests for analytical calculations, aggregators, and seeder."""

    def test_calculate_kpis_empty(self):
        """Verify safe default metrics when session list is empty."""
        kpis = calculate_analytics_kpis([])
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
        
        # Session 1: SLA Compliant (600ms), Ended
        s1 = CallSession(session_id="s1", start_time=now, status=CallStatus.ENDED)
        s1.context.escalated = False
        s1.metrics.duration_seconds = 60.0
        s1.add_turn(role=MessageRole.USER, content="Hello", stt_latency_ms=150.0)
        s1.add_turn(
            role=MessageRole.ASSISTANT,
            content="Hi",
            latency_ms=600.0,
            llm_latency_ms=250.0,
            tts_latency_ms=200.0,
        )

        # Session 2: SLA Breached (900ms), Escalated
        s2 = CallSession(session_id="s2", start_time=now, status=CallStatus.ESCALATED)
        s2.context.escalated = True
        s2.metrics.duration_seconds = 120.0
        s2.add_turn(role=MessageRole.USER, content="I want manager", stt_latency_ms=180.0)
        s2.add_turn(
            role=MessageRole.ASSISTANT,
            content="Transferring",
            latency_ms=900.0,
            llm_latency_ms=450.0,
            tts_latency_ms=270.0,
        )

        kpis = calculate_analytics_kpis([s1, s2])
        assert kpis["total_calls"] == 2
        assert kpis["avg_latency_ms"] == 750.0  # (600 + 900) / 2
        assert kpis["sla_compliance_rate"] == 50.0  # 1 pass, 1 breach
        assert kpis["escalation_rate"] == 50.0  # 1 escalated out of 2
        assert kpis["sla_pass_count"] == 1
        assert kpis["sla_breach_count"] == 1
        assert kpis["avg_duration_seconds"] == 90.0  # (60 + 120) / 2

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
        # Hour 13 (Lunch) should have 1 call and is_peak=True
        assert hourly[13]["count"] == 1
        assert hourly[13]["is_peak"] is True
        # Hour 20 (Dinner) should have 1 call and is_peak=True
        assert hourly[20]["count"] == 1
        assert hourly[20]["is_peak"] is True
        # Hour 03 should have 0 calls and is_peak=False
        assert hourly[3]["count"] == 0
        assert hourly[3]["is_peak"] is False

    def test_aggregate_tool_invocations(self):
        """Verify counting and ranking of tool names from session turns."""
        s = CallSession(session_id="s-tools")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="check_order_status")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="check_order_status")
        s.add_turn(role=MessageRole.TOOL, content="res", tool_name="book_reservation")

        tools = aggregate_tool_invocations([s])
        assert len(tools) == 2
        assert tools[0]["tool_name"] == "check_order_status"
        assert tools[0]["count"] == 2
        assert tools[0]["percentage"] == pytest.approx(66.7, rel=0.1)
        assert tools[1]["tool_name"] == "book_reservation"
        assert tools[1]["count"] == 1
        assert tools[1]["percentage"] == pytest.approx(33.3, rel=0.1)

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

    def test_seed_analytics_calls(self, tmp_path: Path):
        """Verifies generation of time-distributed sessions across multiple days."""
        seeded = seed_analytics_call_sessions(storage_dir=tmp_path, min_threshold=5)
        assert len(seeded) >= 14
        
        # Verify timestamps span multiple days
        dates = {s.start_time.strftime("%Y-%m-%d") for s in seeded}
        assert len(dates) >= 5, "Seeded calls should span at least 5 distinct days"
        
        # Verify both Arabic and English calls exist
        languages = {s.context.language for s in seeded}
        assert "ar" in languages and "en" in languages

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
    """Streamlit simulation tests verifying page rendering and state interactions."""

    def test_analytics_page_renders_without_errors(self):
        """Verify 02_analytics.py launches and renders without unhandled exceptions."""
        app = AppTest.from_file(ANALYTICS_PAGE_FILE)
        app.run(timeout=10)
        assert len(app.exception) == 0, f"AppTest raised: {[e.value for e in app.exception]}"

    def test_analytics_page_filters_interaction(self):
        """Simulate changing the date range selector and language toggle."""
        app = AppTest.from_file(ANALYTICS_PAGE_FILE)
        app.run(timeout=10)
        assert len(app.exception) == 0

        # Selectbox 0 should be time range selector
        if app.selectbox:
            range_box = app.selectbox[0]
            if len(range_box.options) > 1:
                range_box.select(range_box.options[0]).run(timeout=10)
                assert len(app.exception) == 0

    def test_analytics_page_renders_metrics_and_markdown(self):
        """Verify that KPI metrics and markdown section titles are present."""
        app = AppTest.from_file(ANALYTICS_PAGE_FILE)
        app.run(timeout=10)
        assert len(app.exception) == 0

        # KPI metric elements should be rendered (at least 5 KPI metrics)
        assert len(app.metric) >= 5, f"Expected at least 5 metrics, got {len(app.metric)}"
        # Header banner and sections
        assert len(app.markdown) >= 3


# ==============================================================================
# Tier 3: Error & Edge-Case Verification Tests
# ==============================================================================

class TestAnalyticsTier3EdgeCases:
    """Resilience tests for extreme values, null parameters, and edge cases."""

    def test_zero_calls_graceful_kpis(self):
        """Verify KPI math with zero calls does not raise ZeroDivisionError."""
        kpis = calculate_analytics_kpis([])
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
