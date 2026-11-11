"""
3-Tier Validation Suite for Call Logs, Audio Playback & Clinic Transcript Viewer.

Covers:
- Tier 1: Unit Verification (Clinic session filtering, audio resolution, clinic i18n keys)
- Tier 2: Integration Verification (load_call_sessions on clinic fixtures, Streamlit AppTest empty & populated rendering)
- Tier 3: Error & Edge-Case Verification (Empty storage returns [], corrupted JSON tolerance, zero-message sessions, null tool result handling)
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.agent.session_manager import (
    BookingRef,
    CallSession,
    CallStatus,
    EscalationInfo,
    MessageRole,
    SessionManager,
    TurnMessage,
)
from src.dashboard.calls_data import (
    filter_call_sessions,
    generate_demo_tone_wav,
    load_all_call_sessions,
    load_call_sessions,
    resolve_call_audio,
)
from src.dashboard.i18n import TRANSLATIONS, t


def _persist_clinic_fixture_sessions(storage_dir: Path) -> list[CallSession]:
    """Create and persist 3 deterministic clinic CallSession fixtures in storage_dir."""
    mgr = SessionManager(storage_dir=storage_dir)
    now = datetime.now(timezone.utc)

    # 1. Arabic appointment booking session
    s1 = mgr.create_session(
        session_id="call-ar-book-8801",
        room_name="clinic-room-ar-01",
        participant_identity="patient-nadia",
        language="ar",
        customer_phone="+201012345678",
    )
    s1.start_time = now - timedelta(minutes=30)
    s1.context.patient_name = "نادية محمود"
    s1.context.customer_name = "نادية محمود"
    s1.context.requested_specialty = "الباطنة"
    s1.context.requested_doctor_name = "د. طارق حسن"
    s1.context.sentiment = "positive"
    s1.context.bookings.append(
        BookingRef(
            booking_code="APP-8801",
            action="book",
            doctor_name="د. طارق حسن",
            specialty_name="الباطنة",
            appointment_date="2026-11-15",
            queue_number=4,
        )
    )
    s1.add_turn(
        role=MessageRole.USER,
        content="عايزة أحجز كشف باطنة مع دكتور طارق حسن يوم الأحد",
        stt_latency_ms=165.0,
    )
    s1.add_turn(
        role=MessageRole.TOOL,
        content="Confirmed appointment APP-8801",
        tool_name="book_appointment",
        tool_arguments={"doctor_id": 1, "appointment_date": "2026-11-15"},
        tool_result={"booking_code": "APP-8801", "queue_number": 4, "status": "confirmed"},
    )
    s1.add_turn(
        role=MessageRole.ASSISTANT,
        content="تم تأكيد حجزك مع دكتور طارق حسن برقم كود APP-8801 ورقم الدور 4.",
        latency_ms=580.0,
        llm_latency_ms=220.0,
        tts_latency_ms=195.0,
    )
    s1.end_time = s1.start_time + timedelta(seconds=72)
    s1.status = CallStatus.ENDED
    s1.metrics.duration_seconds = 72.0
    mgr.save_session(s1.session_id)

    # 2. English lab knowledge search session
    s2 = mgr.create_session(
        session_id="call-en-kb-3020",
        room_name="clinic-room-en-02",
        participant_identity="patient-omar",
        language="en",
        customer_phone="+201198765432",
    )
    s2.start_time = now - timedelta(hours=2)
    s2.context.patient_name = "Omar Farouk"
    s2.context.customer_name = "Omar Farouk"
    s2.context.requested_specialty = "Lab & Radiology"
    s2.context.sentiment = "neutral"
    s2.add_turn(
        role=MessageRole.USER,
        content="Do I need to fast before a lipid profile blood test?",
        stt_latency_ms=155.0,
    )
    s2.add_turn(
        role=MessageRole.TOOL,
        content="Fasting 9 to 12 hours required.",
        tool_name="search_clinic_knowledge",
        tool_arguments={"query": "lipid profile fasting instructions", "category": "lab_radiology"},
        tool_result={"found": True, "category": "lab_radiology"},
    )
    s2.add_turn(
        role=MessageRole.ASSISTANT,
        content="Yes, a lipid profile requires 9 to 12 hours of fasting with water permitted.",
        latency_ms=610.0,
        llm_latency_ms=240.0,
        tts_latency_ms=215.0,
    )
    s2.end_time = s2.start_time + timedelta(seconds=64)
    s2.status = CallStatus.ENDED
    s2.metrics.duration_seconds = 64.0
    mgr.save_session(s2.session_id)

    # 3. Escalated emergency/receptionist transfer session
    s3 = mgr.create_session(
        session_id="call-ar-esc-9910",
        room_name="clinic-room-ar-03",
        participant_identity="patient-kamel",
        language="ar",
        customer_phone="+201234567890",
    )
    s3.start_time = now - timedelta(hours=4)
    s3.context.patient_name = "كامل عبد الرحمن"
    s3.context.customer_name = "كامل عبد الرحمن"
    s3.context.sentiment = "negative"
    s3.context.escalated = True
    s3.context.emergency_flag = True
    s3.context.escalation_reason = "ألم شديد في الصدر وضيق تنفس"
    s3.context.escalation_department = "emergency"
    s3.context.escalation = EscalationInfo(
        ticket_id="ESC-9910",
        department="emergency",
        urgency="critical",
        reason="ألم شديد في الصدر وضيق تنفس",
    )
    s3.add_turn(
        role=MessageRole.USER,
        content="عندي ألم شديد في الصدر ومحتاج دكتور طوارئ فوراً",
        stt_latency_ms=190.0,
    )
    s3.add_turn(
        role=MessageRole.TOOL,
        content="Transferred to emergency receptionist",
        tool_name="transfer_to_receptionist",
        tool_arguments={"department": "emergency", "urgency": "critical"},
        tool_result={"ticket_id": "ESC-9910", "department": "emergency", "status": "queued"},
    )
    s3.add_turn(
        role=MessageRole.ASSISTANT,
        content="يرجى التوجه فوراً لأقرب طوارئ أو الاتصال بالإسعاف 123، وجاري تحويلك للاستقبال فوراً.",
        latency_ms=540.0,
        llm_latency_ms=190.0,
        tts_latency_ms=160.0,
        interrupted=True,
    )
    s3.end_time = s3.start_time + timedelta(seconds=50)
    s3.status = CallStatus.ESCALATED
    s3.metrics.duration_seconds = 50.0
    mgr.save_session(s3.session_id)

    return [s1, s2, s3]


# ==============================================================================
# Tier 1: Unit Verification Tests
# ==============================================================================

class TestCallsPageTier1Unit:
    """Isolated unit tests for clinic calls data layer, filters, and audio resolver."""

    def test_load_persisted_clinic_sessions(self, tmp_path: Path):
        """T2.2: Verify load_call_sessions loads persisted clinic fixtures with bookings and escalations."""
        _persist_clinic_fixture_sessions(tmp_path)
        sessions = load_call_sessions(storage_dir=tmp_path)
        assert len(sessions) == 3

        ar_booking = next(s for s in sessions if s.session_id == "call-ar-book-8801")
        assert ar_booking.context.language == "ar"
        assert len(ar_booking.context.bookings) == 1
        assert ar_booking.context.bookings[0].booking_code == "APP-8801"
        assert any(
            m.role == MessageRole.TOOL and m.tool_name == "book_appointment"
            for m in ar_booking.messages
        )

        esc_sess = next(s for s in sessions if s.session_id == "call-ar-esc-9910")
        assert esc_sess.context.escalated is True
        assert esc_sess.status == CallStatus.ESCALATED
        assert esc_sess.context.escalation is not None
        assert esc_sess.context.escalation.department == "emergency"

    def test_session_filtering_logic(self, tmp_path: Path):
        """Verify multi-criteria filtering by status, language, booking code, doctor, and specialty."""
        _persist_clinic_fixture_sessions(tmp_path)
        sessions = load_all_call_sessions(storage_dir=tmp_path)

        # Filter by status: escalated
        esc_filtered = filter_call_sessions(sessions, status="escalated")
        assert len(esc_filtered) == 1
        assert esc_filtered[0].session_id == "call-ar-esc-9910"

        # Filter by language: en
        en_filtered = filter_call_sessions(sessions, language="en")
        assert len(en_filtered) == 1
        assert en_filtered[0].session_id == "call-en-kb-3020"

        # Filter by booking code
        booking_filtered = filter_call_sessions(sessions, search_query="APP-8801")
        assert len(booking_filtered) == 1
        assert booking_filtered[0].session_id == "call-ar-book-8801"

        # Filter by doctor name
        doc_filtered = filter_call_sessions(sessions, search_query="طارق حسن")
        assert len(doc_filtered) == 1
        assert doc_filtered[0].session_id == "call-ar-book-8801"

        # Non-matching term
        none_filtered = filter_call_sessions(sessions, search_query="XYZ-NONEXISTENT")
        assert len(none_filtered) == 0

    def test_audio_resolver_synthetic_fallback(self, tmp_path: Path):
        """Verify resolve_call_audio() produces valid WAV bytes when file is absent."""
        audio_src, is_demo = resolve_call_audio("nonexistent-session", storage_dir=tmp_path)
        assert is_demo is True
        assert isinstance(audio_src, (bytes, bytearray))
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
        """Verify clinic translation keys are present in both EN and AR without restaurant keys."""
        required_keys = [
            "calls_page_title",
            "calls_page_subtitle",
            "sidebar_clinic_name",
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
            "detail_specialty",
            "detail_doctor",
            "detail_bookings",
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
    """Streamlit simulation tests verifying empty-state and clinic fixture rendering."""

    def test_calls_page_renders_empty_state_cleanly(self, tmp_path: Path):
        """Verify 01_calls.py renders an empty state without auto-seeding or exceptions."""
        empty_dir = tmp_path / "empty_calls"
        empty_dir.mkdir(parents=True, exist_ok=True)

        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.session_state["calls_storage_dir"] = str(empty_dir)
        app.run(timeout=10)
        assert len(app.exception) == 0, f"AppTest raised exceptions: {[e.value for e in app.exception]}"
        assert len(app.info) >= 1
        assert list(empty_dir.glob("*.json")) == []

    def test_calls_page_displays_clinic_table_and_inspector(self, tmp_path: Path):
        """T2.2: Verify KPI cards, clinic call table, and booking/escalation inspector render."""
        clinic_dir = tmp_path / "clinic_calls"
        clinic_dir.mkdir(parents=True, exist_ok=True)
        _persist_clinic_fixture_sessions(clinic_dir)

        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.session_state["calls_storage_dir"] = str(clinic_dir)
        app.run(timeout=10)
        assert len(app.exception) == 0

        assert len(app.markdown) >= 4
        assert len(app.dataframe) == 1

        session_boxes = [sb for sb in app.selectbox if sb.key == "selected_call_session"]
        assert len(session_boxes) == 1
        box = session_boxes[0]
        assert len(box.options) == 3

        # Inspect escalated session as well
        box.select("call-ar-esc-9910").run(timeout=10)
        assert len(app.exception) == 0

    def test_calls_page_language_toggle(self, tmp_path: Path):
        """Verify switching session language to Arabic renders clinic fixtures cleanly."""
        clinic_dir = tmp_path / "clinic_calls_ar"
        clinic_dir.mkdir(parents=True, exist_ok=True)
        _persist_clinic_fixture_sessions(clinic_dir)

        app = AppTest.from_file(CALLS_PAGE_FILE)
        app.session_state["calls_storage_dir"] = str(clinic_dir)
        app.session_state["lang"] = "ar"
        app.run(timeout=10)
        assert len(app.exception) == 0


# ==============================================================================
# Tier 3: Error & Edge-Case Verification Tests
# ==============================================================================

class TestCallsPageTier3EdgeCases:
    """Resilience tests under empty storage, corrupt data, and null fields."""

    def test_empty_storage_returns_empty_list_without_seeding(self, tmp_path: Path):
        """T3.3: Verify empty directory returns [] and generates zero synthetic demo seed files."""
        empty_dir = tmp_path / "empty_calls"
        empty_dir.mkdir(parents=True, exist_ok=True)
        sessions = load_call_sessions(storage_dir=empty_dir)
        assert sessions == []
        assert list(empty_dir.glob("*.json")) == []

    def test_corrupted_json_file_handled_gracefully(self, tmp_path: Path):
        """Verify corrupted JSON files are skipped without raising exceptions."""
        calls_dir = tmp_path / "calls_with_corrupt"
        calls_dir.mkdir(parents=True, exist_ok=True)

        valid_sess = _persist_clinic_fixture_sessions(calls_dir)[0]

        broken_file = calls_dir / "broken_session.json"
        broken_file.write_text("{this is corrupted invalid json content!!!", encoding="utf-8")

        mgr = SessionManager(storage_dir=calls_dir)
        loaded = mgr.load_all_persisted_sessions()

        assert len(loaded) == 3
        assert any(s.session_id == valid_sess.session_id for s in loaded)

    def test_call_with_no_messages_renders_placeholder(self):
        """Verify a session with zero messages filters gracefully without index error."""
        sess = CallSession(session_id="call-empty-zero-msg")
        assert len(sess.messages) == 0

        filtered = filter_call_sessions([sess], search_query="empty")
        assert len(filtered) == 1

    def test_tool_turn_without_result(self):
        """Verify turn with role == TOOL but null tool_result does not fail."""
        turn = TurnMessage(
            role=MessageRole.TOOL,
            content="Tool executed with empty result",
            tool_name="check_doctor_availability",
            tool_result=None,
        )
        assert turn.tool_result is None
        assert turn.role == MessageRole.TOOL
