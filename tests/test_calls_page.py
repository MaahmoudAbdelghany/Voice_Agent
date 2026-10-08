"""
3-Tier Validation Suite for Feature 5.2 — Call Logs, Audio Playback & Transcript Viewer.

Covers:
- Tier 1: Unit Verification (Seed creation, filtering logic, audio resolution, i18n keys)
- Tier 2: Integration Verification (Streamlit AppTest simulation, table rendering, session inspection, language toggle)
- Tier 3: Error & Edge-Case Verification (Empty storage auto-seed, corrupted JSON tolerance, zero-message sessions, null tool result handling)
"""

from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest

from src.agent.session_manager import (
    CallSession,
    CallStatus,
    MessageRole,
    SessionManager,
    TurnMessage,
)
from src.dashboard.calls_data import (
    filter_call_sessions,
    generate_demo_tone_wav,
    load_all_call_sessions,
    resolve_call_audio,
    seed_demo_calls,
)
from src.dashboard.i18n import TRANSLATIONS, t


# ==============================================================================
# Tier 1: Unit Verification Tests
# ==============================================================================

class TestCallsPageTier1Unit:
    """Isolated unit tests for calls data layer, filters, and audio resolver."""

    def test_seed_sessions_creation(self, tmp_path: Path):
        """Verify seed_demo_calls() produces valid sessions conforming to schema."""
        sessions = seed_demo_calls(storage_dir=tmp_path)
        assert len(sessions) == 4
        
        # Verify Arabic order inquiry
        ar_order = next(s for s in sessions if s.session_id == "call-ar-ord-7821")
        assert ar_order.context.language == "ar"
        assert ar_order.context.order_id == "ORD-7821"
        assert len(ar_order.messages) >= 4
        assert any(m.role == MessageRole.TOOL and m.tool_name == "check_order_status" for m in ar_order.messages)
        
        # Verify English reservation
        en_res = next(s for s in sessions if s.session_id == "call-en-res-4092")
        assert en_res.context.language == "en"
        assert en_res.context.reservation_draft.get("guests") == 4
        
        # Verify Escalation session
        esc_sess = next(s for s in sessions if s.session_id == "call-ar-esc-9930")
        assert esc_sess.context.escalated is True
        assert esc_sess.status == CallStatus.ESCALATED
        assert esc_sess.context.escalation_department == "إدارة خدمة العملاء والجودة"

    def test_session_filtering_logic(self, tmp_path: Path):
        """Verify multi-criteria filtering by status, language, and search query."""
        sessions = seed_demo_calls(storage_dir=tmp_path)
        
        # Filter by status: escalated
        esc_filtered = filter_call_sessions(sessions, status="escalated")
        assert len(esc_filtered) == 1
        assert esc_filtered[0].session_id == "call-ar-esc-9930"
        
        # Filter by language: en
        en_filtered = filter_call_sessions(sessions, language="en")
        assert len(en_filtered) == 1
        assert en_filtered[0].session_id == "call-en-res-4092"
        
        # Filter by search query: phone number
        phone_filtered = filter_call_sessions(sessions, search_query="+966501234567")
        assert len(phone_filtered) == 1
        assert phone_filtered[0].session_id == "call-ar-ord-7821"
        
        # Filter by search query: order ID
        ord_filtered = filter_call_sessions(sessions, search_query="ORD-7821")
        assert len(ord_filtered) == 1
        
        # Search non-matching term
        none_filtered = filter_call_sessions(sessions, search_query="XYZ-NONEXISTENT")
        assert len(none_filtered) == 0

    def test_audio_resolver_synthetic_fallback(self, tmp_path: Path):
        """Verify resolve_call_audio() produces valid WAV bytes when file is absent."""
        audio_src, is_demo = resolve_call_audio("nonexistent-session", storage_dir=tmp_path)
        assert is_demo is True
        assert isinstance(audio_src, (bytes, bytearray))
        # Check standard RIFF WAV header (first 4 bytes should be b'RIFF')
        assert audio_src[:4] == b"RIFF"

    def test_audio_resolver_with_existing_file(self, tmp_path: Path):
        """Verify resolve_call_audio() returns path when physical audio exists."""
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        fake_audio_file = audio_dir / "test-call-123.wav"
        fake_audio_file.write_bytes(generate_demo_tone_wav())
        
        audio_src, is_demo = resolve_call_audio("test-call-123", storage_dir=tmp_path)
        assert is_demo is False
        assert isinstance(audio_src, Path)
        assert audio_src.exists()

    def test_i18n_calls_page_keys(self):
        """Verify all Feature 5.2 translation keys are present in both EN and AR."""
        required_keys = [
            "calls_page_title",
            "calls_page_subtitle",
            "filter_status_label",
            "filter_status_all",
            "filter_status_active",
            "filter_status_ended",
            "filter_status_escalated",
            "filter_lang_label",
            "filter_search_label",
            "col_session_id",
            "col_customer",
            "col_status",
            "detail_select_prompt",
            "detail_header_title",
            "audio_player_title",
            "transcript_section_title",
            "role_caller",
            "role_assistant",
            "role_tool",
            "interrupted_badge",
        ]
        for k in required_keys:
            assert k in TRANSLATIONS["en"], f"Missing EN key: {k}"
            assert k in TRANSLATIONS["ar"], f"Missing AR key: {k}"
            assert t(k, "en") != k
            assert t(k, "ar") != k


CALLS_PAGE_FILE = str(Path(__file__).parent.parent / "src" / "dashboard" / "pages" / "01_calls.py")


# ==============================================================================
# Tier 2: Integration Verification Tests (Streamlit AppTest)
# ==============================================================================

class TestCallsPageTier2Integration:
    """Streamlit simulation tests verifying page rendering and state interactions."""

    def test_calls_page_renders_cleanly(self):
        """Verify 01_calls.py runs and renders without any unhandled exceptions."""
        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.run(timeout=10)
        assert len(app.exception) == 0, f"AppTest raised exceptions: {[e.value for e in app.exception]}"

    def test_calls_page_displays_table_and_metrics(self):
        """Verify that KPI cards and call list render elements."""
        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.run(timeout=10)
        assert len(app.exception) == 0
        
        # Verify markdown elements exist (header banner, KPI cards, inspector)
        assert len(app.markdown) >= 4
        # Verify selectbox for session selection exists
        assert len(app.selectbox) >= 2

    def test_calls_page_session_selection(self):
        """Simulate selecting a specific call session ID and verify inspector renders."""
        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.run(timeout=10)
        assert len(app.exception) == 0
        
        # Verify the session selectbox is present
        session_boxes = [sb for sb in app.selectbox if sb.key == "selected_call_session"]
        if session_boxes:
            box = session_boxes[0]
            assert len(box.options) > 0
            # Select first option and rerun
            box.select(box.options[0]).run(timeout=10)
            assert len(app.exception) == 0

    def test_calls_page_language_toggle(self):
        """Verify switching session language to Arabic renders cleanly."""
        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.session_state["lang"] = "ar"
        app.run(timeout=10)
        assert len(app.exception) == 0


# ==============================================================================
# Tier 3: Error & Edge-Case Verification Tests
# ==============================================================================

class TestCallsPageTier3EdgeCases:
    """Resilience tests under corrupt data, empty inputs, and null fields."""

    def test_empty_storage_triggers_auto_seed(self, tmp_path: Path):
        """Verify empty directory automatically seeds and returns sessions."""
        empty_dir = tmp_path / "empty_calls"
        empty_dir.mkdir(parents=True, exist_ok=True)
        sessions = load_all_call_sessions(storage_dir=empty_dir, auto_seed=True)
        assert len(sessions) >= 4

    def test_corrupted_json_file_handled_gracefully(self, tmp_path: Path):
        """Verify corrupted JSON files are skipped without raising exceptions."""
        calls_dir = tmp_path / "calls_with_corrupt"
        calls_dir.mkdir(parents=True, exist_ok=True)
        
        # Write valid session
        valid_sess = seed_demo_calls(storage_dir=calls_dir)[0]
        
        # Write completely corrupted JSON file
        broken_file = calls_dir / "broken_session.json"
        broken_file.write_text("{this is corrupted invalid json content!!!", encoding="utf-8")
        
        mgr = SessionManager(storage_dir=calls_dir)
        loaded = mgr.load_all_persisted_sessions()
        
        # Must load the valid one and skip the broken one
        assert len(loaded) >= 1
        assert any(s.session_id == valid_sess.session_id for s in loaded)

    def test_call_with_no_messages_renders_placeholder(self, tmp_path: Path):
        """Verify a session with zero messages renders gracefully without index error."""
        sess = CallSession(session_id="call-empty-zero-msg")
        assert len(sess.messages) == 0
        
        # Filtering should handle it without error
        filtered = filter_call_sessions([sess], search_query="empty")
        assert len(filtered) == 1

    def test_tool_turn_without_result(self):
        """Verify turn with role == TOOL but null tool_result does not fail."""
        turn = TurnMessage(
            role=MessageRole.TOOL,
            content="Tool executed with empty result",
            tool_name="test_tool",
            tool_result=None,
        )
        assert turn.tool_result is None
        assert turn.role == MessageRole.TOOL
