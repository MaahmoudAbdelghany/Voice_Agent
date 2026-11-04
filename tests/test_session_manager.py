"""
Unit, Integration, and Edge-Case Test Suite for Feature 5.2:
Medical Call Session State, Turn Memory, and Metric Tracking (`src/agent/session_manager.py`).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from src.agent.session_manager import (
    BookingRef,
    CallActivity,
    CallLifecycle,
    CallSession,
    CallStatus,
    EscalationInfo,
    MessageRole,
    SessionManager,
    compute_nearest_rank_percentiles,
)
from src.ai_core.finops import FinOpsController
from src.ai_core.tracing import trace_scope
from src.config import get_settings
from src.tools.gates import caller_session_scope

# ==============================================================================
# Tier 1: Unit Verification (U1–U12)
# ==============================================================================


def test_u1_check_doctor_availability_extracts_context():
    """U1 (R2.1): availability tool result sets specialty, doctor id/name, and requested date."""
    session = CallSession(room_name="clinic-room-1", participant_identity="caller-01")
    session.record_tool_call(
        tool_name="check_doctor_availability",
        arguments={"specialty": "عظام", "date": "2026-11-10"},
        result={
            "success": True,
            "data": {
                "doctor_id": 3,
                "doctor_name_ar": "د. طارق علام",
                "specialty_name_ar": "جراحة العظام والمفاصل",
                "target_date": "2026-11-10",
                "has_shift": True,
                "is_available": True,
                "remaining_capacity": 8,
            },
        },
        latency_ms=85.0,
    )

    assert session.context.requested_specialty == "جراحة العظام والمفاصل"
    assert session.context.requested_doctor_id == 3
    assert session.context.requested_doctor_name == "د. طارق علام"
    assert session.context.requested_date == "2026-11-10"
    assert session.context.current_intent == "check_availability"


def test_u2_book_appointment_success_appends_booking_ref():
    """U2 (R2.2): successful book_appointment appends BookingRef(action='booked') and sets patient_name & visit_type."""
    session = CallSession()
    session.record_tool_call(
        tool_name="book_appointment",
        arguments={
            "patient_name": "أحمد محمود",
            "patient_phone": "01099999999",
            "doctor_id": 3,
            "date": "2026-11-10",
            "visit_type": "examination",
        },
        result={
            "success": True,
            "data": {
                "booking_code": "APT-20261110-03004",
                "patient_name": "أحمد محمود",
                "doctor_name_ar": "د. طارق علام",
                "specialty_name_ar": "جراحة العظام والمفاصل",
                "appointment_date": "2026-11-10",
                "queue_number": 4,
                "shift_window": "06:00 PM - 09:00 PM",
                "visit_type": "examination",
                "fee": 350.0,
            },
        },
        latency_ms=120.0,
    )

    assert session.context.patient_name == "أحمد محمود"
    assert session.context.customer_name == "أحمد محمود"
    assert session.context.visit_type == "examination"
    assert len(session.context.bookings) == 1
    ref = session.context.bookings[0]
    assert isinstance(ref, BookingRef)
    assert ref.action == "booked"
    assert ref.booking_code == "APT-20261110-03004"
    assert ref.queue_number == 4
    assert session.context.booking_codes == ["APT-20261110-03004"]


def test_u3_manage_appointment_cancel_and_reschedule_refs():
    """U3 (R2.3): cancel and reschedule results append cancelled / rescheduled BookingRefs."""
    session = CallSession()

    # Reschedule
    session.record_tool_call(
        tool_name="manage_appointment",
        arguments={
            "action": "reschedule",
            "booking_code": "APT-20261110-03004",
            "new_date": "2026-11-12",
        },
        result={
            "success": True,
            "data": {
                "action": "reschedule",
                "status": "rescheduled",
                "appointments": [
                    {
                        "booking_code": "APT-20261110-03004",
                        "appointment_date": "2026-11-12",
                        "queue_number": 2,
                        "doctor_name_ar": "د. طارق علام",
                    }
                ],
            },
        },
    )

    # Cancel
    session.record_tool_call(
        tool_name="manage_appointment",
        arguments={
            "action": "cancel",
            "booking_code": "APT-20261110-03004",
        },
        result={
            "success": True,
            "data": {
                "action": "cancel",
                "status": "cancelled",
                "appointments": [
                    {
                        "booking_code": "APT-20261110-03004",
                        "appointment_date": "2026-11-12",
                        "queue_number": 2,
                    }
                ],
            },
        },
    )

    assert len(session.context.bookings) == 2
    assert session.context.bookings[0].action == "rescheduled"
    assert session.context.bookings[0].appointment_date == "2026-11-12"
    assert session.context.bookings[1].action == "cancelled"
    assert session.context.bookings[1].booking_code == "APT-20261110-03004"


def test_u4_transfer_to_receptionist_emergency_sets_escalation_and_emergency_flag():
    """U4 (R2.4, R2.5): transfer_to_receptionist with urgency=emergency sets escalation, ESCALATED, and emergency_flag."""
    session = CallSession()
    session.add_user_message("عندي ألم شديد في الصدر ومش قادر أتنفس")
    assert session.lifecycle == CallLifecycle.ACTIVE

    session.record_tool_call(
        tool_name="transfer_to_receptionist",
        arguments={
            "reason": "ألم حاد في الصدر وضيق تنفس",
            "department": "emergency",
            "urgency": "emergency",
        },
        result={
            "success": True,
            "data": {
                "handoff_id": "HND-901",
                "queue_position": 1,
                "department": "emergency",
                "urgency": "emergency",
            },
        },
    )

    assert session.lifecycle == CallLifecycle.ESCALATED
    assert session.status == CallStatus.ESCALATED
    assert session.context.emergency_flag is True
    assert session.context.escalated is True
    assert isinstance(session.context.escalation, EscalationInfo)
    assert session.context.escalation.urgency == "emergency"
    assert session.context.escalation.department == "emergency"
    assert session.context.escalation.handoff_id == "HND-901"


def test_u5_failed_tool_result_does_not_mutate_bookings():
    """U5 (R2.6): success=False booking never appends a BookingRef."""
    session = CallSession()
    session.record_tool_call(
        tool_name="book_appointment",
        arguments={
            "patient_name": "سارة علي",
            "doctor_id": 1,
            "date": "2026-11-10",
        },
        result={
            "success": False,
            "error": "SHIFT_CAPACITY_FULL",
            "message": "للأسف العدد مكتمل في هذا الشيفت.",
        },
    )

    assert len(session.context.bookings) == 0
    assert session.metrics.tool_calls_failed == 1
    assert session.metrics.tool_calls_succeeded == 0


def test_u6_patient_phone_populated_only_from_verified_caller_scope():
    """U6 (R1.2): patient_phone in LLM tool arguments is ignored; verified caller_session_scope is used."""
    session = CallSession()

    # Without caller_session_scope, LLM-supplied patient_phone in book_appointment must NOT set context.patient_phone
    session.record_tool_call(
        tool_name="book_appointment",
        arguments={
            "patient_name": "محمود حسن",
            "patient_phone": "01000000001",  # Untrusted LLM argument
            "doctor_id": 2,
            "date": "2026-11-11",
        },
        result={
            "success": True,
            "booking_code": "APT-20261111-02001",
            "queue_number": 1,
        },
    )
    assert session.context.patient_phone is None

    # Inside verified caller_session_scope, the verified phone is bound and spoofed LLM arg is ignored
    with caller_session_scope("01234567890", session_id=session.session_id):
        session.record_tool_call(
            tool_name="book_appointment",
            arguments={
                "patient_name": "محمود حسن",
                "patient_phone": "01555555555",  # Spoofed LLM argument
                "doctor_id": 2,
                "date": "2026-11-12",
            },
            result={
                "success": True,
                "booking_code": "APT-20261112-02002",
                "queue_number": 2,
            },
        )
        assert session.context.patient_phone == "01234567890"
        assert session.context.customer_phone == "01234567890"


def test_u7_lifecycle_transitions_and_terminal_rejection():
    """U7 (R3.1, R3.2): INITIATED -> ACTIVE -> ENDED works; ENDED -> ACTIVE is rejected without exception."""
    session = CallSession()
    assert session.lifecycle == CallLifecycle.INITIATED

    assert session.transition_to(CallLifecycle.ACTIVE) is True
    assert session.lifecycle == CallLifecycle.ACTIVE
    assert session.status == CallStatus.ACTIVE

    session.end_call()
    assert session.lifecycle == CallLifecycle.ENDED
    assert session.status == CallStatus.ENDED

    # Attempting to transition out of ENDED must be rejected gracefully
    assert session.transition_to(CallLifecycle.ACTIVE) is False
    assert session.lifecycle == CallLifecycle.ENDED
    session.status = CallStatus.ACTIVE  # Direct attribute assignment also guarded
    assert session.status == CallStatus.ENDED


def test_u8_activity_updates_do_not_change_lifecycle():
    """U8 (R3.3): CallActivity changes leave CallLifecycle untouched."""
    session = CallSession()
    session.transition_to(CallLifecycle.ACTIVE)

    for act in (
        CallActivity.LISTENING,
        CallActivity.SPEAKING,
        CallActivity.TOOL_CALLING,
        CallActivity.IDLE,
    ):
        session.set_activity(act)
        assert session.activity == act
        assert session.lifecycle == CallLifecycle.ACTIVE
        assert session.status == CallStatus.ACTIVE


def test_u9_nearest_rank_percentiles_and_slo_breaches():
    """U9 (R4.2): samples [100..1000] yield exact nearest-rank P50/P95/max and slo_breach_turns == 2 (>800ms)."""
    session = CallSession()
    samples = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    for s in samples:
        session.add_assistant_message(
            "رد تجريبي",
            latency_ms=s,
            llm_latency_ms=s * 0.4,
            tts_latency_ms=s * 0.3,
        )

    assert session.metrics.measured_latency_turns == 10
    assert session.metrics.p50_latency_ms == 500.0
    assert session.metrics.p95_latency_ms == 1000.0
    assert session.metrics.max_latency_ms == 1000.0
    # Strictly > 800ms: 900.0 and 1000.0 -> 2 breaches
    assert session.metrics.slo_breach_turns == 2
    assert session.metrics.stage_percentiles["e2e"].p50_ms == 500.0
    assert session.metrics.stage_percentiles["llm_ttft"].p50_ms == 200.0


def test_u10_tool_timeout_and_failure_counters():
    """U10 (R4.3): tool with 450ms (>400ms) increments tool_timeouts; failed tool increments tool_calls_failed."""
    session = CallSession()
    session.record_tool_call(
        tool_name="check_doctor_availability",
        arguments={"specialty": "باطنة"},
        result={"success": True, "data": {"is_available": True}},
        latency_ms=450.0,
    )
    session.record_tool_call(
        tool_name="book_appointment",
        arguments={},
        result={"success": False, "error": "VALIDATION_ERROR"},
        latency_ms=50.0,
    )

    assert session.metrics.total_tool_calls == 2
    assert session.metrics.tool_timeouts == 1
    assert session.metrics.tool_calls_succeeded == 1
    assert session.metrics.tool_calls_failed == 1


def test_u11_sliding_window_respects_limit_and_never_starts_with_orphan_tool():
    """U11 (R5.1, R5.2): 30 messages -> <= 12 non-system returned; never starts with a TOOL message."""
    session = CallSession()
    session.add_turn(role=MessageRole.SYSTEM, content="Static clinic system prompt")

    # Build 30 non-system messages including tool turns so that naive slicing (-12) would land on a TOOL message
    for i in range(10):
        session.add_user_message(f"سؤال رقم {i}")
        session.add_assistant_message(f"جاري البحث {i}")
        session.record_tool_call(
            tool_name="search_clinic_knowledge",
            arguments={"query": f"q{i}"},
            result={"success": True, "found": True},
        )

    assert len([m for m in session.messages if m.role != MessageRole.SYSTEM]) == 30

    history = session.get_conversation_history(
        include_system=True, include_context_summary=False
    )
    non_sys = [m for m in history if m["role"] != "system"]
    assert len(non_sys) <= get_settings().session_history_window
    assert non_sys[0]["role"] != "tool"

    # Also verify explicit max_turns where raw cut lands directly on a TOOL turn
    # 30 non-sys messages: indices 0..29 where index % 3 == 2 is TOOL.
    # If max_turns = 10 -> start_idx = 20 (which is index 20: 20 % 3 == 2 -> TOOL!)
    history_cut_on_tool = session.get_conversation_history(
        max_turns=10, include_system=False, include_context_summary=False
    )
    assert history_cut_on_tool[0]["role"] != "tool"


def test_u12_build_context_summary_deterministic_and_empty_when_blank():
    """U12 (R5.3): summary contains patient name + booking code when populated, and is empty when context is blank."""
    session = CallSession()
    assert session.build_context_summary() == ""

    # Empty context adds no extra system summary message
    session.add_user_message("أهلاً")
    hist_empty = session.get_conversation_history(include_system=True)
    assert all(m["role"] != "system" for m in hist_empty)

    # Populate context via booking
    session.record_tool_call(
        tool_name="book_appointment",
        arguments={"patient_name": "ندى سمير", "visit_type": "examination"},
        result={
            "success": True,
            "booking_code": "APT-20261115-01007",
            "queue_number": 7,
            "appointment_date": "2026-11-15",
            "doctor_name_ar": "د. ليلى حسن",
            "specialty_name_ar": "الأطفال",
        },
    )

    summary = session.build_context_summary()
    assert "ندى سمير" in summary
    assert "APT-20261115-01007" in summary
    assert "نمرة 7" in summary

    hist_with_ctx = session.get_conversation_history(include_system=True)
    assert hist_with_ctx[0]["role"] == "system"
    assert "APT-20261115-01007" in hist_with_ctx[0]["content"]


# ==============================================================================
# Tier 2: Integration Verification (I1–I4)
# ==============================================================================


def test_i1_finops_snapshot_captured_on_end_call(monkeypatch):
    """I1 (R4.4): usage recorded in FinOpsController for session_id is copied into metrics.finops_snapshot on end_call()."""
    import src.ai_core.finops as finops_mod

    fresh_finops = FinOpsController()
    monkeypatch.setattr(finops_mod, "_finops_instance", fresh_finops)

    session = CallSession(session_id="sess-finops-001")
    fresh_finops.record_usage(
        model="groq/llama-3.3-70b-versatile",
        prompt_tokens=600,
        completion_tokens=90,
        session_id=session.session_id,
    )

    session.add_user_message("عايز أحجز كشف")
    session.end_call()

    assert session.metrics.finops_snapshot is not None
    assert session.metrics.finops_snapshot["session_id"] == "sess-finops-001"
    assert session.metrics.finops_snapshot["total_tokens"] == 690
    assert session.metrics.finops_snapshot["total_cost_usd"] > 0.0

    summary = session.to_summary_dict()
    assert summary["total_tokens"] == 690
    assert summary["total_cost_usd"] > 0.0


def test_i2_trace_id_captured_inside_trace_scope():
    """I2 (R4.5): inside trace_scope(...), recorded turn captures the active trace_id."""
    session = CallSession(session_id="sess-trace-001")

    with trace_scope(name="voice_turn", session_id=session.session_id) as trace:
        turn = session.add_user_message("مواعيد دكتور الأطفال إيه؟", stt_latency_ms=110.0)
        expected_tid = trace.trace_id

    assert turn.trace_id == expected_tid
    assert expected_tid in session.metrics.trace_ids


def test_i3_persisted_json_redacts_egyptian_phone_and_national_id(tmp_path):
    """I3 (R6.1): saved JSON masks phone 01012345678 and 14-digit national ID while keeping raw values in memory."""
    mgr = SessionManager(storage_dir=tmp_path)
    raw_phone = "01012345678"
    raw_nid = "29501011234567"

    with caller_session_scope(raw_phone, session_id="sess-pii-001"):
        session = mgr.create_session(session_id="sess-pii-001", room_name="room-pii")
        session.add_user_message(
            f"اسمي كريم ورقم موبايلي {raw_phone} والرقم القومي {raw_nid}"
        )
        session.record_tool_call(
            tool_name="book_appointment",
            arguments={"patient_name": "كريم عادل", "patient_phone": raw_phone},
            result={"success": True, "booking_code": "APT-20261110-01001"},
        )

    # In-memory session retains the raw phone during the active call
    assert session.context.patient_phone == raw_phone

    saved_path = mgr.save_session(session.session_id)
    assert saved_path is not None and saved_path.exists()

    disk_text = saved_path.read_text(encoding="utf-8")
    assert raw_phone not in disk_text
    assert raw_nid not in disk_text
    # In-memory session is still unredacted
    assert session.context.patient_phone == raw_phone


def test_i4_end_and_persist_writes_file_evicts_memory_and_reloads(tmp_path):
    """I4 (R6.4, R6.5): end_and_persist writes file, evicts session from memory, and load_session restores it."""
    mgr = SessionManager(storage_dir=tmp_path)
    session = mgr.create_session(session_id="sess-evict-001", room_name="room-evict")
    session.add_user_message("شكراً لحضرتك")
    session.add_assistant_message("العفو يا فندم", latency_ms=220.0)

    saved_path = mgr.end_and_persist(session.session_id, evict=True)
    assert saved_path is not None and saved_path.exists()
    assert mgr.get_session("sess-evict-001") is None
    assert len(mgr.list_all_sessions()) == 0

    reloaded = mgr.load_session("sess-evict-001")
    assert reloaded is not None
    assert reloaded.lifecycle == CallLifecycle.ENDED
    assert len(reloaded.messages) == 2


# ==============================================================================
# Tier 3: Error & Edge-Case Verification (E1–E7)
# ==============================================================================


def test_e1_existing_data_calls_json_files_load_and_legacy_status_maps(tmp_path):
    """E1 (R3.4, R6.6): all existing files in data/calls/*.json load cleanly; legacy 'speaking' -> ACTIVE + speaking."""
    real_calls_dir = Path("data/calls")
    if real_calls_dir.exists():
        mgr = SessionManager(storage_dir=real_calls_dir)
        loaded = mgr.load_all_persisted_sessions()
        assert len(loaded) >= 1

    # Also explicitly test legacy status='speaking' mapping
    legacy_file = tmp_path / "legacy-speaking.json"
    legacy_file.write_text(
        json.dumps(
            {
                "session_id": "legacy-speaking",
                "room_name": "legacy-room",
                "participant_identity": "caller-legacy",
                "status": "speaking",
                "context": {
                    "customer_name": "عميل قديم",
                    "customer_phone": "+201112223333",
                    "order_id": "ORD-123",
                },
                "messages": [],
            }
        ),
        encoding="utf-8",
    )
    tmp_mgr = SessionManager(storage_dir=tmp_path)
    legacy_sess = tmp_mgr.load_session("legacy-speaking")
    assert legacy_sess is not None
    assert legacy_sess.lifecycle == CallLifecycle.ACTIVE
    assert legacy_sess.status == CallStatus.ACTIVE
    assert legacy_sess.activity == CallActivity.SPEAKING
    assert legacy_sess.context.patient_name == "عميل قديم"
    assert legacy_sess.context.order_id == "ORD-123"


def test_e2_malformed_tool_result_never_raises():
    """E2 (NFR-5): malformed tool result (None / non-dict / missing keys) does not raise and leaves bookings clean."""
    session = CallSession()
    session.record_tool_call("book_appointment", None, None)  # type: ignore[arg-type]
    session.record_tool_call("book_appointment", "bad-args", ["not-a-dict"])  # type: ignore[arg-type]
    session.record_tool_call("manage_appointment", {}, {"unexpected": 123})

    assert len(session.context.bookings) == 0
    assert session.metrics.total_tool_calls == 3


def test_e3_zero_latency_samples_no_zero_division(tmp_path):
    """E3: metrics with zero latency samples return 0.0 percentiles and no ZeroDivisionError."""
    stats = compute_nearest_rank_percentiles([])
    assert stats.p50_ms == 0.0
    assert stats.p95_ms == 0.0
    assert stats.max_ms == 0.0
    assert stats.samples == 0

    mgr = SessionManager(storage_dir=tmp_path)
    s = mgr.create_session(session_id="no-lat")
    s.add_user_message("ألو")  # No latency provided
    s.end_call()

    agg = mgr.get_aggregated_metrics()
    assert agg["p50_e2e_ms"] == 0.0
    assert agg["p95_e2e_ms"] == 0.0
    assert agg["slo_breach_ratio"] == 0.0


def test_e4_simulated_atomic_write_failure_leaves_no_partial_file_and_keeps_session(
    tmp_path, monkeypatch
):
    """E4 (R6.2): if os.replace raises during save_session, returns None, cleans up tmp file, and does not evict."""
    mgr = SessionManager(storage_dir=tmp_path)
    s = mgr.create_session(session_id="fail-write")
    s.add_user_message("اختبار")
    s.end_call()

    def _boom(src: str, dst: str) -> None:
        raise OSError("Simulated disk full / replace error")

    monkeypatch.setattr(os, "replace", _boom)

    res = mgr.save_session("fail-write", evict_if_ended=True)
    assert res is None
    assert not (tmp_path / "fail-write.json").exists()
    assert list(tmp_path.glob("*.tmp")) == []
    # Session remains in memory because persistence failed
    assert mgr.get_session("fail-write") is not None


@pytest.mark.asyncio
async def test_e5_async_save_session_uses_asyncio_to_thread(tmp_path, monkeypatch):
    """E5 (R6.3, NFR-2): async_save_session delegates disk I/O to asyncio.to_thread."""
    mgr = SessionManager(storage_dir=tmp_path)
    s = mgr.create_session(session_id="async-save-01")
    s.add_user_message("تجربة حفظ غير متزامن")

    called_to_thread = {"count": 0}
    orig_to_thread = asyncio.to_thread

    async def _spy_to_thread(func, /, *args, **kwargs):
        called_to_thread["count"] += 1
        return await orig_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy_to_thread)

    path = await mgr.async_end_and_persist("async-save-01", evict=True)
    assert called_to_thread["count"] == 1
    assert path is not None and path.exists()
    assert mgr.get_session("async-save-01") is None


@pytest.mark.asyncio
async def test_e6_fifty_concurrent_sessions_stress(tmp_path):
    """E6 (NFR-3): 50 concurrent asyncio tasks creating, updating, and ending sessions -> 50 files, 0 left in memory."""
    mgr = SessionManager(storage_dir=tmp_path)

    async def _run_one_call(idx: int) -> None:
        sid = f"concurrent-call-{idx:03d}"
        sess = mgr.create_session(session_id=sid, room_name=f"room-{idx}")
        sess.add_user_message(f"رسالة المستخدم {idx}", stt_latency_ms=100.0 + idx)
        sess.record_tool_call(
            tool_name="check_doctor_availability",
            arguments={"specialty": "باطنة"},
            result={"success": True, "data": {"specialty_name_ar": "الباطنة العامة"}},
            latency_ms=90.0,
        )
        sess.add_assistant_message(
            f"رد المساعد {idx}",
            latency_ms=350.0 + idx,
            llm_latency_ms=150.0,
            tts_latency_ms=120.0,
        )
        saved = await mgr.async_end_and_persist(sid, evict=True)
        assert saved is not None and saved.exists()

    await asyncio.gather(*(_run_one_call(i) for i in range(50)))

    assert len(list(tmp_path.glob("concurrent-call-*.json"))) == 50
    assert len(mgr.list_all_sessions()) == 0


def test_e7_in_memory_performance_under_one_ms():
    """E7 (NFR-1): adding 200 turns and computing percentiles averages well under 1ms per operation."""
    session = CallSession(session_id="perf-session")
    t0 = time.perf_counter()
    for i in range(200):
        if i % 2 == 0:
            session.add_user_message(f"سؤال {i}", stt_latency_ms=110.0)
        else:
            session.add_assistant_message(
                f"إجابة {i}",
                latency_ms=420.0 + (i % 50),
                llm_latency_ms=180.0,
                tts_latency_ms=140.0,
            )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    avg_op_ms = elapsed_ms / 200.0
    assert avg_op_ms < 1.0, f"Expected < 1.0ms per turn op, got {avg_op_ms:.3f}ms"
