"""
Automated Test Suite for Feature 4.5 — Deterministic State Machine, Idempotency Keys & Write Safety Gates.

Covers:
- Tier 1 (Unit):
  * Deterministic SHA-256 idempotency key hashing & Egyptian phone normalization
  * IdempotencyStore TTL expiry, LRU eviction, and explicit invalidation by key / booking_code
  * CallerSessionContext & caller_session_scope (contextvars async isolation & spoofing override)
  * LLMAppointmentBookingInput & LLMManageAppointmentInput (extra="forbid", zero phone/ID fields)
- Tier 2 (Integration):
  * AppointmentWorkflowStateMachine idempotent booking replay (same queue_number & booking_code)
  * Automatic idempotency key invalidation upon appointment cancellation or rescheduling
  * Anti-spoofing ownership verification preventing Caller B from cancelling/rescheduling Caller A's booking
  * Atomic reschedule swap governed by DeterministicWriteGate & AppointmentWorkflowStateMachine
- Tier 3 (Error & Edge-Case):
  * Full shift rejection (shift_full) in Python code with 7-day nearest available slot suggestion
  * Concurrency test (5 simultaneous bookings on a shift with max_capacity=2 -> exactly 2 succeed)
  * Step-budget exhaustion (max_steps=2 -> transitions to ESCALATED with step_budget_exhausted)
  * Missing slot halting at SLOT_COLLECTION without database writes
"""

from __future__ import annotations

import asyncio
import datetime as dt
from datetime import date, time
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.ai_core.workflow import (
    AppointmentWorkflowStateMachine,
    WorkflowAction,
    WorkflowState,
)
from src.db.base import Base
from src.db.models import Appointment, Doctor, DoctorSchedule, Specialty
from src.db.repository import ClinicRepository
from src.tools import (
    LLMAppointmentBookingInput,
    LLMManageAppointmentInput,
    caller_session_scope,
    compute_booking_idempotency_key,
    compute_reschedule_idempotency_key,
    get_current_caller_session,
    get_idempotency_store,
    get_session_scoped_tool_definitions,
    resolve_effective_caller_phone,
)
from src.tools.doctor_availability import CAIRO_TZ
from src.tools.gates import DeterministicWriteGate, IdempotencyStore

# Frozen Cairo calendar: Saturday 2026-10-24 10:00 AM
TODAY = date(2026, 10, 24)  # Saturday (DayOfWeek.SATURDAY = 0)
MON = date(2026, 10, 26)  # Monday (DayOfWeek.MONDAY = 2)
WED = date(2026, 10, 28)  # Wednesday (DayOfWeek.WEDNESDAY = 4)
NOW_MORNING = dt.datetime(2026, 10, 24, 10, 0, tzinfo=CAIRO_TZ)

PHONE_A = "01011112222"
PHONE_B = "01199998888"


@pytest.fixture(autouse=True)
def frozen_cairo_time():
    """Freeze Cairo clock across gates, workflow, and tools."""
    get_idempotency_store().clear()
    with (
        patch("src.tools.gates.get_cairo_today", return_value=TODAY),
        patch("src.tools.gates._get_cairo_now", return_value=NOW_MORNING),
        patch("src.ai_core.workflow.get_cairo_today", return_value=TODAY),
        patch("src.tools.appointment_booking.get_cairo_today", return_value=TODAY),
        patch("src.tools.appointment_booking.get_cairo_now", return_value=NOW_MORNING),
        patch("src.tools.manage_appointment.get_cairo_today", return_value=TODAY),
        patch("src.tools.manage_appointment.get_cairo_now", return_value=NOW_MORNING),
    ):
        yield
    get_idempotency_store().clear()


@pytest.fixture
async def session_factory(tmp_path):
    """Isolated file-backed SQLite database for transactional and concurrency testing."""
    db_path = (tmp_path / "workflow_gates_test.db").as_posix()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        cardio = Specialty(
            code="cardiology", name_ar="القلب والأوعية الدموية", name_en="Cardiology"
        )
        ortho = Specialty(code="orthopedics", name_ar="العظام", name_en="Orthopedics")
        session.add_all([cardio, ortho])
        await session.flush()

        # Doctor 1: Dr. Tarek (Cardiology) — shifts on Saturday (max_capacity=2) and Monday (max_capacity=5)
        dr_tarek = Doctor(
            specialty_id=cardio.id,
            name_ar="د. طارق عزت",
            name_en="Dr. Tarek Ezzat",
            examination_fee=400.0,
            consultation_fee=150.0,
            is_active=True,
        )
        # Doctor 2: Dr. Noha (Orthopedics) — shift on Wednesday (max_capacity=1)
        dr_noha = Doctor(
            specialty_id=ortho.id,
            name_ar="د. نهى عبد الرحمن",
            name_en="Dr. Noha Abdelrahman",
            examination_fee=350.0,
            consultation_fee=100.0,
            is_active=True,
        )
        session.add_all([dr_tarek, dr_noha])
        await session.flush()

        # Egyptian DayOfWeek: 0=Saturday, 2=Monday, 4=Wednesday
        sched_sat = DoctorSchedule(
            doctor_id=dr_tarek.id,
            day_of_week=0,
            start_time=time(18, 0),
            end_time=time(21, 0),
            max_capacity=2,
            is_active=True,
        )
        sched_mon = DoctorSchedule(
            doctor_id=dr_tarek.id,
            day_of_week=2,
            start_time=time(17, 0),
            end_time=time(20, 0),
            max_capacity=5,
            is_active=True,
        )
        sched_wed = DoctorSchedule(
            doctor_id=dr_noha.id,
            day_of_week=4,
            start_time=time(16, 0),
            end_time=time(19, 0),
            max_capacity=1,
            is_active=True,
        )
        session.add_all([sched_sat, sched_mon, sched_wed])
        await session.commit()

    yield factory
    await engine.dispose()


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_compute_booking_idempotency_key_deterministic_and_normalized():
    """Equivalent Egyptian phone representations produce identical 64-char SHA-256 keys."""
    k1 = compute_booking_idempotency_key("01012345678", 1, 10, date(2026, 10, 26))
    k2 = compute_booking_idempotency_key("+20 10 1234-5678", 1, 10, "2026-10-26")
    k3 = compute_booking_idempotency_key("00201012345678", 1, 10, date(2026, 10, 26))

    assert len(k1) == 64
    assert k1 == k2 == k3

    # Changing doctor, schedule, or date changes the hash
    assert compute_booking_idempotency_key("01012345678", 2, 10, date(2026, 10, 26)) != k1
    assert compute_booking_idempotency_key("01012345678", 1, 11, date(2026, 10, 26)) != k1
    assert compute_booking_idempotency_key("01012345678", 1, 10, date(2026, 10, 27)) != k1

    # Reschedule key is deterministic and case/space insensitive for booking_code
    rk1 = compute_reschedule_idempotency_key("apt-20261024-01001", date(2026, 10, 26))
    rk2 = compute_reschedule_idempotency_key(" APT-20261024-01001 ", "2026-10-26")
    assert len(rk1) == 64
    assert rk1 == rk2


def test_idempotency_store_ttl_expiry_lru_and_invalidation():
    """Verify IdempotencyStore TTL expiration, LRU eviction, and invalidation."""
    store = IdempotencyStore(ttl_s=10.0, max_entries=2)

    store.put(
        idempotency_key="key_1",
        booking_code="APT-20261024-01001",
        doctor_id=1,
        schedule_id=1,
        appointment_date="2026-10-24",
        queue_number=1,
        response_payload={"booking_code": "APT-20261024-01001"},
        message_ar="تم الحجز 1",
    )
    store.put(
        idempotency_key="key_2",
        booking_code="APT-20261024-01002",
        doctor_id=1,
        schedule_id=1,
        appointment_date="2026-10-24",
        queue_number=2,
        response_payload={"booking_code": "APT-20261024-01002"},
        message_ar="تم الحجز 2",
    )
    assert store.size() == 2

    # Access key_1 so key_2 becomes the oldest, then insert key_3 -> key_2 is evicted
    assert store.get("key_1") is not None
    store.put(
        idempotency_key="key_3",
        booking_code="APT-20261024-01003",
        doctor_id=1,
        schedule_id=1,
        appointment_date="2026-10-24",
        queue_number=3,
        response_payload={"booking_code": "APT-20261024-01003"},
        message_ar="تم الحجز 3",
    )
    assert store.size() == 2
    assert store.get("key_2") is None
    assert store.get("key_1") is not None
    assert store.get_by_booking_code("APT-20261024-01003") is not None

    # Invalidate by booking code
    assert store.invalidate_booking_code("apt-20261024-01003") is True
    assert store.get("key_3") is None

    # TTL expiration check
    store.put(
        idempotency_key="key_short",
        booking_code="APT-20261024-01099",
        doctor_id=1,
        schedule_id=1,
        appointment_date="2026-10-24",
        queue_number=99,
        response_payload={},
        message_ar="قصير",
        ttl_s=-1.0,  # Already expired
    )
    assert store.get("key_short") is None


@pytest.mark.asyncio
async def test_caller_session_scope_isolation_and_spoof_override():
    """Verify contextvars isolation across concurrent tasks and spoofing override."""
    assert get_current_caller_session() is None

    # Outside session scope: falls back to explicit phone
    phone, spoofed = resolve_effective_caller_phone("+20 10 1111 2222")
    assert phone == "01011112222"
    assert spoofed is False

    # Inside session scope: overrides conflicting phone and sets spoof_attempt_blocked=True
    with caller_session_scope(PHONE_A, session_id="room_101", caller_name="أحمد علي"):
        ctx = get_current_caller_session()
        assert ctx is not None
        assert ctx.caller_phone == PHONE_A
        assert ctx.caller_name == "أحمد علي"

        eff_phone, spoof_flag = resolve_effective_caller_phone(PHONE_B)
        assert eff_phone == PHONE_A
        assert spoof_flag is True

        # Matching phone does not trigger spoof flag
        eff_same, spoof_same = resolve_effective_caller_phone("+201011112222")
        assert eff_same == PHONE_A
        assert spoof_same is False

    assert get_current_caller_session() is None

    # Concurrent async tasks have strictly isolated CallerSessionContext
    async def _worker(caller_phone: str, delay: float) -> str | None:
        with caller_session_scope(caller_phone):
            await asyncio.sleep(delay)
            eff, _ = resolve_effective_caller_phone("01500000000")
            return eff

    res_a, res_b = await asyncio.gather(
        _worker(PHONE_A, 0.02),
        _worker(PHONE_B, 0.01),
    )
    assert res_a == PHONE_A
    assert res_b == PHONE_B


def test_llm_session_scoped_schemas_forbid_phone_and_patient_id():
    """Verify LLMAppointmentBookingInput and LLMManageAppointmentInput reject phone/ID fields."""
    # Valid LLM booking payload without phone
    valid_book = LLMAppointmentBookingInput(
        patient_name="محمود سعيد",
        doctor_name="د. طارق عزت",
        date="2026-10-26",
        visit_type="examination",
    )
    assert valid_book.patient_name == "محمود سعيد"

    # Attempt to inject patient_phone or patient_id fails with extra="forbid"
    with pytest.raises(ValidationError):
        LLMAppointmentBookingInput(
            patient_name="محمود سعيد",
            patient_phone="01012345678",
            doctor_id=1,
            date="2026-10-26",
        )
    with pytest.raises(ValidationError):
        LLMAppointmentBookingInput(
            patient_name="محمود سعيد",
            patient_id=99,
            doctor_id=1,
            date="2026-10-26",
        )

    # Attempt to inject phone in LLMManageAppointmentInput fails
    with pytest.raises(ValidationError):
        LLMManageAppointmentInput(
            action="cancel",
            booking_code="APT-20261026-01001",
            phone="01012345678",
        )

    # Verify OpenAI/Groq tool definitions omit phone fields in session-scoped definitions
    defs = get_session_scoped_tool_definitions()
    book_def = next(d for d in defs if d["function"]["name"] == "book_appointment")
    manage_def = next(d for d in defs if d["function"]["name"] == "manage_appointment")

    book_props = book_def["function"]["parameters"]["properties"]
    manage_props = manage_def["function"]["parameters"]["properties"]

    assert "patient_phone" not in book_props
    assert "patient_id" not in book_props
    assert "phone" not in manage_props
    assert "patient_id" not in manage_props


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_workflow_book_idempotent_replay_returns_same_queue_number(session_factory):
    """Duplicate booking request within 24h returns idempotent_replay=True without incrementing queue_number."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    with caller_session_scope(PHONE_A, session_id="call_1"):
        # 1st booking call
        res1 = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="سارة محمد",
            doctor_name="د. طارق عزت",
            date=MON,
            visit_type="examination",
        )
        assert res1.success is True
        assert res1.terminal_state == WorkflowState.COMPLETED
        assert res1.idempotent_replay is False
        assert res1.idempotency_key is not None
        assert res1.tool_result.data["queue_number"] == 1
        code_1 = res1.tool_result.data["booking_code"]

        # 2nd identical booking call (network retry / duplicate tool emission)
        res2 = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="سارة محمد",
            doctor_name="د. طارق عزت",
            date=MON,
            visit_type="examination",
        )
        assert res2.success is True
        assert res2.terminal_state == WorkflowState.COMPLETED
        assert res2.idempotent_replay is True
        assert res2.idempotency_key == res1.idempotency_key
        assert res2.tool_result.data["booking_code"] == code_1
        assert res2.tool_result.data["queue_number"] == 1
        assert any(t.to_state == WorkflowState.IDEMPOTENCY_CHECK for t in res2.step_traces)

    # Verify only 1 appointment row exists in the database
    async with session_factory() as session:
        count = (await session.execute(select(func.count(Appointment.id)))).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_workflow_cancel_invalidates_idempotency_allowing_rebook(session_factory):
    """Cancelling an appointment invalidates its idempotency key so the patient can re-book."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    with caller_session_scope(PHONE_A, session_id="call_rebook"):
        res1 = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="كريم عادل",
            doctor_id=1,
            date=MON,
        )
        assert res1.success is True
        first_code = res1.tool_result.data["booking_code"]
        assert get_idempotency_store().get(res1.idempotency_key) is not None

        # Cancel appointment
        cancel_res = await workflow.execute(
            WorkflowAction.CANCEL,
            booking_code=first_code,
            reason="ظرف طارئ",
        )
        assert cancel_res.success is True
        assert cancel_res.terminal_state == WorkflowState.COMPLETED
        # Key was invalidated upon cancellation
        assert get_idempotency_store().get(res1.idempotency_key) is None

        # Re-book same doctor & date -> creates a fresh confirmed booking (not a replay of cancelled)
        res2 = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="كريم عادل",
            doctor_id=1,
            date=MON,
        )
        assert res2.success is True
        assert res2.idempotent_replay is False
        assert res2.tool_result.data["booking_code"] != first_code
        assert res2.tool_result.data["queue_number"] == 2


@pytest.mark.asyncio
async def test_workflow_session_phone_prevents_cross_patient_cancel_and_lookup(session_factory):
    """Caller B cannot cancel, reschedule, or look up Caller A's appointment even by spoofing phone."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    # Caller A books an appointment
    with caller_session_scope(PHONE_A, session_id="session_patient_a"):
        book_a = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="أحمد صاحب الحجز",
            doctor_id=1,
            date=MON,
        )
        assert book_a.success is True
        code_a = book_a.tool_result.data["booking_code"]

    # Caller B attempts to cancel Caller A's booking_code while passing Caller A's phone in args
    with caller_session_scope(PHONE_B, session_id="session_attacker_b"):
        spoof_cancel = await workflow.execute(
            WorkflowAction.CANCEL,
            booking_code=code_a,
            phone=PHONE_A,  # Spoof attempt! Overridden by PHONE_B from session context
        )
        assert spoof_cancel.success is False
        assert spoof_cancel.terminal_state == WorkflowState.REJECTED_BY_GATE
        assert spoof_cancel.spoof_attempt_blocked is True
        assert spoof_cancel.error_class == "phone_mismatch"

        # Caller B also cannot look up Caller A's booking code
        spoof_lookup = await workflow.execute(
            WorkflowAction.LOOKUP,
            booking_code=code_a,
            phone=PHONE_A,
        )
        assert spoof_lookup.success is False
        assert spoof_lookup.terminal_state == WorkflowState.REJECTED_BY_GATE
        assert spoof_lookup.spoof_attempt_blocked is True
        assert spoof_lookup.error_class == "phone_mismatch"

    # Verify Caller A's appointment is still CONFIRMED in DB
    async with session_factory() as session:
        repo = ClinicRepository(session)
        appt = await repo.get_appointment_by_code(code_a)
        assert appt is not None
        assert appt.status == "confirmed"


@pytest.mark.asyncio
async def test_workflow_reschedule_atomic_swap_and_gate_validation(session_factory):
    """Rescheduling moves booking from Saturday to Monday atomically and invalidates old key."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    with caller_session_scope(PHONE_A, session_id="session_resched"):
        book_res = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="منى حسن",
            doctor_id=1,
            date=TODAY,  # Saturday 2026-10-24
        )
        assert book_res.success is True
        old_code = book_res.tool_result.data["booking_code"]
        old_idem_key = book_res.idempotency_key

        resched = await workflow.execute(
            WorkflowAction.RESCHEDULE,
            booking_code=old_code,
            new_date=MON,  # Monday 2026-10-26
            reason="سفر",
        )
        assert resched.success is True
        assert resched.terminal_state == WorkflowState.COMPLETED
        assert get_idempotency_store().get(old_idem_key) is None
        appts = resched.tool_result.data["appointments"]
        assert appts[0]["appointment_date"] == MON.isoformat()
        assert appts[0]["status"] == "confirmed"
        assert appts[1]["booking_code"] == old_code
        assert appts[1]["status"] == "cancelled"


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_deterministic_gate_rejects_full_shift_with_next_available(session_factory):
    """When shift reaches max_capacity, gate rejects write and suggests next available shift within 7 days."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    # Dr. Noha (doctor_id=2) works Wednesday 2026-10-28 with max_capacity=1
    with caller_session_scope(PHONE_A):
        first = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="مريض أول",
            doctor_id=2,
            date=WED,
        )
        assert first.success is True

    # Second patient tries to book Dr. Noha on Wednesday -> rejected by gate (shift_full)
    with caller_session_scope(PHONE_B):
        second = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="مريض ثاني",
            doctor_id=2,
            date=WED,
        )
        assert second.success is False
        assert second.terminal_state == WorkflowState.REJECTED_BY_GATE
        assert second.error_class == "shift_full"
        assert second.gate_verdict is not None
        assert second.gate_verdict.remaining_capacity == 0

    # Also test Dr. Tarek (doctor_id=1) on Saturday (max_capacity=2) -> 3rd caller gets Monday suggestion
    p1 = await workflow.execute(
        WorkflowAction.BOOK,
        patient_name="مريض 1",
        patient_phone="01010000001",
        doctor_id=1,
        date=TODAY,
    )
    p2 = await workflow.execute(
        WorkflowAction.BOOK,
        patient_name="مريض 2",
        patient_phone="01010000002",
        doctor_id=1,
        date=TODAY,
    )
    assert p1.success and p2.success

    p3 = await workflow.execute(
        WorkflowAction.BOOK,
        patient_name="مريض 3",
        patient_phone="01010000003",
        doctor_id=1,
        date=TODAY,
    )
    assert p3.success is False
    assert p3.terminal_state == WorkflowState.REJECTED_BY_GATE
    assert p3.error_class == "shift_full"
    next_avail = p3.tool_result.data.get("next_available")
    assert next_avail is not None
    assert next_avail["target_date"] == MON.isoformat()


@pytest.mark.asyncio
async def test_concurrent_workflow_bookings_never_exceed_shift_capacity(session_factory):
    """5 concurrent workflow bookings on a shift with max_capacity=2 result in exactly 2 confirmations."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    async def _attempt(idx: int):
        phone = f"0120000000{idx}"
        with caller_session_scope(phone, session_id=f"conc_{idx}"):
            return await workflow.execute(
                WorkflowAction.BOOK,
                patient_name=f"مريض متزامن {idx}",
                doctor_id=1,
                date=TODAY,  # Saturday shift has max_capacity=2
            )

    results = await asyncio.gather(*[_attempt(i) for i in range(1, 6)])
    successes = [r for r in results if r.success]
    rejections = [r for r in results if not r.success]

    assert len(successes) == 2
    assert len(rejections) == 3
    queues = sorted(r.tool_result.data["queue_number"] for r in successes)
    assert queues == [1, 2]
    assert all(r.terminal_state == WorkflowState.REJECTED_BY_GATE for r in rejections)
    assert all(r.error_class == "shift_full" for r in rejections)


@pytest.mark.asyncio
async def test_workflow_step_budget_exhaustion_escalates_safely(session_factory):
    """Exceeding workflow_max_steps aborts execution and transitions to ESCALATED."""
    # Normal BOOK takes 5 transitions (INIT -> SLOT -> GATE -> IDEMPOTENCY -> ATOMIC -> COMPLETED).
    # Setting max_steps=2 forces step budget exhaustion before DB write.
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory, max_steps=2)

    with caller_session_scope(PHONE_A):
        res = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="عمرو دياب",
            doctor_id=1,
            date=MON,
        )
        assert res.success is False
        assert res.terminal_state == WorkflowState.ESCALATED
        assert res.escalate is True
        assert res.error_class == "step_budget_exhausted"
        assert res.steps_taken == 2

    # Ensure zero DB rows were written
    async with session_factory() as session:
        count = (await session.execute(select(func.count(Appointment.id)))).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_workflow_missing_slots_halts_at_slot_collection(session_factory):
    """Missing required booking slots halts at SLOT_COLLECTION without touching the database."""
    workflow = AppointmentWorkflowStateMachine(session_factory=session_factory)

    with caller_session_scope(PHONE_A):
        res_no_date = await workflow.execute(
            WorkflowAction.BOOK,
            patient_name="تامر حسني",
            doctor_id=1,
            date=None,
        )
        assert res_no_date.success is False
        assert res_no_date.terminal_state == WorkflowState.SLOT_COLLECTION
        assert res_no_date.error_class == "missing_or_invalid_slot"
        assert res_no_date.steps_taken == 1

    # Also test DeterministicWriteGate.execute_booking directly
    gate = DeterministicWriteGate(session_factory=session_factory)
    with caller_session_scope(PHONE_A):
        g_res = await gate.execute_booking(
            patient_name="تامر حسني",
            doctor_id=1,
            date=MON,
        )
        assert g_res.success is True
        assert g_res.data["idempotent_replay"] is False

        g_replay = await gate.execute_booking(
            patient_name="تامر حسني",
            doctor_id=1,
            date=MON,
        )
        assert g_replay.success is True
        assert g_replay.data["idempotent_replay"] is True
        assert g_replay.data["queue_number"] == g_res.data["queue_number"]
