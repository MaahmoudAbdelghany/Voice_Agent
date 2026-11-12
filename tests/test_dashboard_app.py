"""
3-Tier Test Suite for Feature 5.1: Main Dashboard Entry & Design System.

Covers:
- Tier 1: Unit Tests (i18n catalogs, health checker utility, CSS assets)
- Tier 2: Integration Tests (Streamlit AppTest simulation, language switching, rendering)
- Tier 3: Edge Cases & Error Resilience (Mocked exceptions, missing credentials, missing assets)
"""

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.config import Settings, settings
from src.dashboard.health import check_services_health
from src.dashboard.i18n import TRANSLATIONS, t

APP_FILE = str(Path(__file__).parent.parent / "src" / "dashboard" / "app.py")


# ==============================================================================
# Tier 1: Unit Tests
# ==============================================================================

class TestDashboardTier1Unit:
    """Isolated unit tests for dashboard utilities and assets."""

    def test_i18n_translation_keys_completeness(self):
        """Verify that English and Arabic dictionaries have complete matching key sets."""
        en_keys = set(TRANSLATIONS["en"].keys())
        ar_keys = set(TRANSLATIONS["ar"].keys())

        missing_in_ar = en_keys - ar_keys
        missing_in_en = ar_keys - en_keys

        assert not missing_in_ar, f"Arabic translation is missing keys: {missing_in_ar}"
        assert not missing_in_en, f"English translation is missing keys: {missing_in_en}"

    def test_i18n_fallback_behavior(self):
        """Verify querying an unknown key or unknown language falls back safely."""
        unknown_key = "non_existent_key_xyz"
        # Unknown key returns the key itself
        assert t(unknown_key, "en") == unknown_key
        assert t(unknown_key, "ar") == unknown_key
        # Unknown language defaults to English
        assert t("app_title", "fr") == TRANSLATIONS["en"]["app_title"]

    def test_health_checker_structure(self):
        """Verify check_services_health returns all 5 required services with expected fields."""
        health = check_services_health()
        expected_services = {"livekit", "qdrant", "groq", "elevenlabs", "deepgram"}

        assert set(health.keys()) == expected_services
        for svc_data in health.values():
            assert "name_key" in svc_data
            assert "sub_key" in svc_data
            assert "status" in svc_data
            assert "badge_key" in svc_data
            assert "badge_class" in svc_data
            assert "details" in svc_data
            assert svc_data["status"] in {"operational", "degraded", "unconfigured", "offline"}

    def test_css_asset_exists_and_valid(self):
        """Verify that style.css exists and defines critical aesthetic classes."""
        css_file = Path("src/dashboard/assets/style.css")
        assert css_file.exists(), "src/dashboard/assets/style.css does not exist"

        content = css_file.read_text(encoding="utf-8")
        assert ".header-container" in content
        assert ".kpi-card" in content
        assert ".service-health-card" in content
        assert ".nav-card" in content
        assert ".rtl-mode" in content


# ==============================================================================
# Tier 2: Integration Tests (Streamlit AppTest)
# ==============================================================================

class TestDashboardTier2Integration:
    """Integration tests running the full Streamlit app via the AppTest simulator."""

    def test_dashboard_app_renders_cleanly(self, tmp_path: Path):
        """Verify the Streamlit dashboard renders clinic_name with zero unhandled exceptions."""
        at = AppTest.from_file(APP_FILE)
        at.session_state["calls_storage_dir"] = str(tmp_path)
        at.run()

        assert not at.exception, f"App raised unhandled exceptions: {at.exception}"
        sidebar_md = " ".join(m.value for m in at.sidebar.markdown)
        assert settings.clinic_name in sidebar_md

    def test_dashboard_kpi_metrics_rendered(self, tmp_path: Path):
        """Verify KPI cards render live empty-state zeros and real computed session metrics."""
        from src.agent.session_manager import CallStatus, MessageRole, SessionManager

        empty_dir = tmp_path / "empty_kpis"
        empty_dir.mkdir(parents=True, exist_ok=True)

        at_empty = AppTest.from_file(APP_FILE)
        at_empty.session_state["calls_storage_dir"] = str(empty_dir)
        at_empty.run()
        assert not at_empty.exception

        empty_md = " ".join(m.value for m in at_empty.markdown)
        assert "0 ms" in empty_md
        assert "0.0%" in empty_md
        assert "680 ms" not in empty_md
        assert "142" not in empty_md
        assert "2.8%" not in empty_md

        populated_dir = tmp_path / "populated_kpis"
        mgr = SessionManager(storage_dir=populated_dir)
        s1 = mgr.create_session(session_id="kpi-sess-1", language="ar")
        s1.add_turn(role=MessageRole.ASSISTANT, content="أهلاً", latency_ms=420.0)
        s1.status = CallStatus.ENDED
        mgr.save_session(s1.session_id)

        s2 = mgr.create_session(session_id="kpi-sess-2", language="ar")
        s2.add_turn(role=MessageRole.ASSISTANT, content="جاري التحويل", latency_ms=580.0)
        s2.context.escalated = True
        s2.status = CallStatus.ESCALATED
        mgr.save_session(s2.session_id)

        at_pop = AppTest.from_file(APP_FILE)
        at_pop.session_state["calls_storage_dir"] = str(populated_dir)
        at_pop.run()
        assert not at_pop.exception

        pop_md = " ".join(m.value for m in at_pop.markdown)
        assert "500 ms" in pop_md
        assert "50.0%" in pop_md

    def test_dashboard_language_toggle_integration(self, tmp_path: Path):
        """Verify that switching language updates the rendered text to Arabic."""
        at = AppTest.from_file(APP_FILE)
        at.session_state["calls_storage_dir"] = str(tmp_path)
        at.run()

        # Verify initial English title
        initial_markdown = " ".join([m.value for m in at.markdown])
        assert "Voice AI Agent Operations" in initial_markdown

        # Select Arabic option from radio using set_value
        at.radio(key="lang_radio").set_value("العربية 🇸🇦").run()

        # Verify Arabic title is rendered
        arabic_markdown = " ".join([m.value for m in at.markdown])
        assert "مركز عمليات المساعد الصوتي الذكي" in arabic_markdown

    def test_service_status_badges_rendered(self, tmp_path: Path):
        """Verify that service health cards appear in rendered output."""
        at = AppTest.from_file(APP_FILE)
        at.session_state["calls_storage_dir"] = str(tmp_path)
        at.run()

        markdown_text = " ".join([m.value for m in at.markdown])
        assert "LiveKit Cloud" in markdown_text
        assert "Qdrant Vector DB" in markdown_text
        assert "Groq Cloud" in markdown_text


# ==============================================================================
# Tier 3: Edge Cases & Error Resilience
# ==============================================================================

class TestDashboardTier3EdgeCases:
    """Defensive resilience tests for unconfigured settings and network failure simulations."""

    def test_health_checker_with_missing_credentials(self):
        """Verify health checker handles completely blank credentials without crashing."""
        with patch.object(Settings, "is_livekit_configured", return_value=False), \
             patch.object(Settings, "is_llm_configured", return_value=False), \
             patch.object(Settings, "is_tts_configured", return_value=False), \
             patch.object(Settings, "is_stt_configured", return_value=False), \
             patch.object(Settings, "is_qdrant_cloud", return_value=False):

            health = check_services_health()
            assert health["livekit"]["status"] == "unconfigured"
            assert health["groq"]["status"] == "unconfigured"
            assert health["elevenlabs"]["status"] == "unconfigured"
            assert health["deepgram"]["status"] == "unconfigured"
            assert health["qdrant"]["status"] == "degraded"  # Defaults to in-memory

    def test_health_checker_exception_defensiveness(self):
        """Verify health checker catches unexpected internal exceptions and marks status offline."""
        with patch.object(Settings, "is_livekit_configured", side_effect=RuntimeError("Connection refused")):
            health = check_services_health()
            assert health["livekit"]["status"] == "offline"
            assert "Connection refused" in health["livekit"]["details"]

    def test_app_resilience_when_css_missing(self, tmp_path: Path):
        """Verify the dashboard still renders cleanly even if the CSS file is absent."""
        fake_css_path = Path(__file__).parent / "non_existent_file.css"
        with patch("src.dashboard.app.CSS_PATH", fake_css_path):
            at = AppTest.from_file(APP_FILE)
            at.session_state["calls_storage_dir"] = str(tmp_path)
            at.run()
            assert not at.exception

