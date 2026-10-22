"""
Test Suite for Appointment Management Tool (Feature 3.4).

Covers:
- Tier 1: Unit verification for cancellable rules, spoken list limitation, and serialization privacy.
- Tier 2: Integration verification on file-based SQLite database for:
  - Lookup by booking code
  - Lookup by phone (upcoming confirmed only, sorted nearest first)
  - Cancel by booking code (with capacity freeing)
  - Cancel by phone alone (single cancellable booking)
  - Reschedule atomic swap (new appointment created, old cancelled, same visit type & doctor)
  - Reschedule transaction failure rollback (old remains confirmed if new fails)
  - Sync and async execution equivalence
  - Centralized TOOL_REGISTRY registration
- Tier 3: Error and edge-case verification for:
  - Lookup unknown code and empty phone
  - Phone mismatch rejection (security / privacy)
  - Cancel by phone with multiple upcoming bookings (disambiguation)
  - Cancel already cancelled / past appointment / shift already started
  - Reschedule same date rejection
  - Reschedule no shift / full shift with 7-day lookahead suggestions
  - Reschedule duplicate on new date
  - Reschedule date window rules (past, > 30 days, shift ended)
  - Graceful handling of unexpected database errors and invalid parameters
"""

import datetime as dt
from datetime import date, time
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Appointment, Doctor, DoctorSchedule, Patient, Specialty
from src.db.repository import ClinicRepository, ShiftCapacityExceededError
from src.db.schemas import AppointmentStatus
from src.tools import (
    TOOL_REGISTRY,
    ManageAppointmentAction,
    ManageAppointmentInput,
    ManageAppointmentOutput,
)
from src.tools.doctor_availability import CAIRO_TZ
from src.tools.manage_appointment import (
    ManageAppointmentTool,
    _format_spoken_list,
    is_cancellable,
    serialize_appointment,
)

# Reference dates based on Saturday 2026-10-24 in Cairo
TODAY = date(2026, 10, 24)  # Saturday
SUN = date(2026, 10, 25)
MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)
WED = date(2026, 10, 28)
NEXT_SAT = date(2026, 10, 31)

NOW_MORNING = dt.datetime(2026, 10, 24, 10, 0, tzinfo=CAIRO_TZ)  # Before 18:00 shift
NOW_DURING_SHIFT = dt.datetime(2026, 10, 24, 19, 0, tzinfo=CAIRO_TZ)  # During 18:00-22:00
NOW_LATE = dt.datetime(2026, 10, 24, 23, 0, tzinfo=CAIRO_TZ)  # After 22:00 shift

PHONE_A = "01012345678"
PHONE_B = "01198765432"


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def frozen_cairo_clock():
    """Freeze Cairo 'today' and 'now' inside manage_appointment and appointment_booking."""
    with (
        patch("src.tools.manage_appointment.get_cairo_today", return_value=TODAY),
        patch("src.tools.manage_appointment.get_cairo_now", return_value=NOW_MORNING) as now,
        patch("src.tools.appointment_booking.get_cairo_today", return_value=TODAY),
        patch("src.tools.appointment_booking.get_cairo_now", return_value=NOW_MORNING),
    ):
        yield now


@pytest.fixture
async def session_factory(tmp_path):
    """Provides isolated file-based SQLite database with seeded specialties, doctors, and schedules."""
    db_file = tmp_path / "manage_appt_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        internal = Specialty(
            code="internal_medicine", name_ar="الباطنة والجهاز الهضمي", name_en="Internal Medicine"
        )
        peds = Specialty(code="pediatrics", name_ar="الأطفال", name_en="Pediatrics")
        session.add_all([internal, peds])
        await session.flush()

        sherif = Doctor(
            specialty_id=internal.id,
            name_ar="د. أحمد محمود الشريف",
            name_en="Dr. Ahmed El-Sherif",
            examination_fee=350.0,
            consultation_fee=150.0,
        )
        marwa = Doctor(
            specialty_id=internal.id,
            name_ar="د. مروة كمال الدين",
            name_en="Dr. Marwa Kamal",
            examination_fee=250.0,
            consultation_fee=100.0,
        )
        session.add_all([sherif, marwa])
        await session.flush()

        # Doctor schedules:
        # Sherif: Saturday (day 0, 18:00-22:00, cap 2), Monday (day 2, 18:00-22:00, cap 5)
        # Marwa: Wednesday (day 4, 17:00-20:00, cap 5)
        sched_sat = DoctorSchedule(
            doctor_id=sherif.id,
            day_of_week=0,
            start_time=time(18, 0),
            end_time=time(22, 0),
            max_capacity=2,
        )
        sched_mon = DoctorSchedule(
            doctor_id=sherif.id,
            day_of_week=2,
            start_time=time(18, 0),
            end_time=time(22, 0),
            max_capacity=5,
        )
        sched_wed = DoctorSchedule(
            doctor_id=marwa.id,
            day_of_week=4,
            start_time=time(17, 0),
            end_time=time(20, 0),
            max_capacity=5,
        )
        session.add_all([sched_sat, sched_mon, sched_wed])
        await session.flush()

        # Seed Patient A & B
        patient_a = Patient(name="محمد علي", phone=PHONE_A)
        patient_b = Patient(name="سارة أحمد", phone=PHONE_B)
        session.add_all([patient_a, patient_b])
        await session.flush()

        # Seed initial appointments:
        # 1. Confirmed upcoming booking for Patient A on Saturday (TODAY)
        appt_a1 = Appointment(
            booking_code="APT-20261024-01001",
            patient_id=patient_a.id,
            doctor_id=sherif.id,
            schedule_id=sched_sat.id,
            appointment_date=TODAY,
            queue_number=1,
            visit_type="examination",
            status=AppointmentStatus.CONFIRMED.value,
            fee=350.0,
        )
        # 2. Confirmed upcoming booking for Patient A on Monday
        appt_a2 = Appointment(
            booking_code="APT-20261026-01001",
            patient_id=patient_a.id,
            doctor_id=sherif.id,
            schedule_id=sched_mon.id,
            appointment_date=MON,
            queue_number=1,
            visit_type="consultation",
            fee=150.0,
        )
        # 3. Past appointment for Patient A (2026-10-10)
        appt_a_past = Appointment(
            booking_code="APT-20261010-01001",
            patient_id=patient_a.id,
            doctor_id=sherif.id,
            schedule_id=sched_sat.id,
            appointment_date=date(2026, 10, 10),
            queue_number=1,
            visit_type="examination",
            status=AppointmentStatus.COMPLETED.value,
            fee=350.0,
        )
        # 4. Confirmed booking for Patient B on Wednesday
        appt_b = Appointment(
            booking_code="APT-20261028-02001",
            patient_id=patient_b.id,
            doctor_id=marwa.id,
            schedule_id=sched_wed.id,
            appointment_date=WED,
            queue_number=1,
            visit_type="examination",
            status=AppointmentStatus.CONFIRMED.value,
            fee=250.0,
        )
        session.add_all([appt_a1, appt_a2, appt_a_past, appt_b])
        await session.commit()

    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def tool(session_factory) -> ManageAppointmentTool:
    return ManageAppointmentTool(session_factory=session_factory)


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_is_cancellable_rule():
    sched = DoctorSchedule(day_of_week=0, start_time=time(18, 0), end_time=time(22, 0))

    # Future date: allowed
    appt_future = Appointment(
        booking_code="APT-F",
        appointment_date=MON,
        status="confirmed",
        schedule=sched,
    )
    ok, err_code, _ = is_cancellable(appt_future, TODAY, NOW_MORNING)
    assert ok is True
    assert err_code is None

    # Today before shift start: allowed
    appt_today = Appointment(
        booking_code="APT-T",
        appointment_date=TODAY,
        status="confirmed",
        schedule=sched,
    )
    ok, err_code, _ = is_cancellable(appt_today, TODAY, NOW_MORNING)  # 10:00 < 18:00
    assert ok is True

    # Today during / after shift start: rejected
    ok, err_code, _ = is_cancellable(appt_today, TODAY, NOW_DURING_SHIFT)  # 19:00 >= 18:00
    assert ok is False
    assert err_code == "shift_started"

    # Past date: rejected
    appt_past = Appointment(
        booking_code="APT-P",
        appointment_date=date(2026, 10, 10),
        status="confirmed",
        schedule=sched,
    )
    ok, err_code, _ = is_cancellable(appt_past, TODAY, NOW_MORNING)
    assert ok is False
    assert err_code == "past_appointment"

    # Already cancelled: rejected
    appt_canc = Appointment(
        booking_code="APT-C",
        appointment_date=MON,
        status="cancelled",
        schedule=sched,
    )
    ok, err_code, _ = is_cancellable(appt_canc, TODAY, NOW_MORNING)
    assert ok is False
    assert err_code == "already_cancelled"

    # Completed: rejected
    appt_comp = Appointment(
        booking_code="APT-DONE",
        appointment_date=MON,
        status="completed",
        schedule=sched,
    )
    ok, err_code, _ = is_cancellable(appt_comp, TODAY, NOW_MORNING)
    assert ok is False
    assert err_code == "not_confirmed"


def test_spoken_list_limited_to_three():
    appts = [
        {
            "doctor_name_ar": f"دكتور {i}",
            "day_name_ar": "السبت",
            "appointment_date": f"2026-10-{20 + i}",
            "queue_number": i,
            "booking_code": f"APT-{i}",
        }
        for i in range(1, 6)
    ]
    spoken = _format_spoken_list(appts, max_items=3)
    assert "دكتور 1" in spoken
    assert "دكتور 2" in spoken
    assert "دكتور 3" in spoken
    assert "دكتور 4" not in spoken
    assert "دكتور 5" not in spoken


def test_serialize_appointment_excludes_phone():
    patient = Patient(name="أحمد", phone="01012345678")
    doctor = Doctor(
        name_ar="د. الشريف",
        specialty=Specialty(name_ar="الباطنة", code="internal", name_en="Internal"),
    )
    sched = DoctorSchedule(day_of_week=0, start_time=time(18, 0), end_time=time(22, 0))
    appt = Appointment(
        booking_code="APT-999",
        appointment_date=TODAY,
        queue_number=1,
        visit_type="examination",
        fee=350.0,
        status="confirmed",
        patient=patient,
        doctor=doctor,
        schedule=sched,
    )
    serialized = serialize_appointment(appt)
    assert "phone" not in serialized
    assert "patient_phone" not in serialized
    assert serialized["booking_code"] == "APT-999"
    assert serialized["patient_name"] == "أحمد"
    assert serialized["doctor_name_ar"] == "د. الشريف"
    assert serialized["status_ar"] == "مؤكد"


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


async def test_lookup_by_code(tool):
    res = await tool.aexecute(
        action=ManageAppointmentAction.LOOKUP, booking_code="APT-20261024-01001"
    )
    assert res.success is True
    assert "مؤكد" in res.message
    assert "د. أحمد محمود الشريف" in res.message
    assert res.data["status"] == "confirmed"
    assert len(res.data["appointments"]) == 1
    assert res.data["appointments"][0]["booking_code"] == "APT-20261024-01001"


async def test_lookup_by_phone_upcoming_only(tool):
    # Patient A has 2 upcoming confirmed (TODAY and MON) and 1 past completed (2026-10-10)
    res = await tool.aexecute(action=ManageAppointmentAction.LOOKUP, phone=PHONE_A)
    assert res.success is True
    assert res.data["status"] == "found"
    # Past appointment must NOT be returned in upcoming lookup
    assert len(res.data["appointments"]) == 2
    dates = [a["appointment_date"] for a in res.data["appointments"]]
    assert dates == ["2026-10-24", "2026-10-26"]  # sorted ascending


async def test_cancel_by_code_success(tool, session_factory):
    # Check initial availability on Saturday: cap 2, booked 1 -> remaining 1
    async with session_factory() as session:
        avail_before = await ClinicRepository(session).get_doctor_availability(1, TODAY)
        assert avail_before.remaining_capacity == 1

    res = await tool.aexecute(
        action=ManageAppointmentAction.CANCEL,
        booking_code="APT-20261024-01001",
        reason="ظروف سفر",
    )
    assert res.success is True
    assert "تم إلغاء حجز حضرتك" in res.message
    assert res.data["status"] == "cancelled"

    # Verify status in database and slot freed
    async with session_factory() as session:
        repo = ClinicRepository(session)
        cancelled = await repo.get_appointment_by_code("APT-20261024-01001")
        assert cancelled.status == AppointmentStatus.CANCELLED.value
        assert "سبب الإلغاء: ظروف سفر" in cancelled.notes

        avail_after = await repo.get_doctor_availability(1, TODAY)
        assert avail_after.remaining_capacity == 2  # slot freed!


async def test_cancel_by_phone_single_booking(tool):
    # Patient B has exactly 1 upcoming confirmed booking (on Wednesday)
    res = await tool.aexecute(action=ManageAppointmentAction.CANCEL, phone=PHONE_B)
    assert res.success is True
    assert "سارة أحمد" in res.message
    assert "د. مروة كمال الدين" in res.message
    assert res.data["status"] == "cancelled"
    assert res.data["appointments"][0]["booking_code"] == "APT-20261028-02001"


async def test_reschedule_success_atomic_swap(tool, session_factory):
    # Reschedule Patient A's Saturday booking to NEXT Saturday 2026-10-31
    res = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261024-01001",
        new_date=NEXT_SAT,
    )
    assert res.success is True
    assert "تم تأجيل حجز حضرتك" in res.message
    assert res.data["status"] == "rescheduled"
    assert len(res.data["appointments"]) == 2

    new_item = res.data["appointments"][0]
    old_item = res.data["appointments"][1]

    assert new_item["appointment_date"] == "2026-10-31"
    assert new_item["queue_number"] == 1
    assert new_item["status"] == "confirmed"
    assert new_item["visit_type"] == "examination"

    assert old_item["booking_code"] == "APT-20261024-01001"
    assert old_item["status"] == "cancelled"

    # Verify in DB
    async with session_factory() as session:
        repo = ClinicRepository(session)
        old_db = await repo.get_appointment_by_code("APT-20261024-01001")
        assert old_db.status == AppointmentStatus.CANCELLED.value

        new_db = await repo.get_appointment_by_code(new_item["booking_code"])
        assert new_db.status == AppointmentStatus.CONFIRMED.value


async def test_reschedule_rollback_keeps_old(tool, session_factory):
    # Simulate create_appointment failing during reschedule
    with patch.object(
        ClinicRepository,
        "create_appointment",
        side_effect=ShiftCapacityExceededError("Shift full"),
    ):
        res = await tool.aexecute(
            action=ManageAppointmentAction.RESCHEDULE,
            booking_code="APT-20261024-01001",
            new_date=NEXT_SAT,
        )
    assert res.success is False
    assert res.error == "shift_full"

    # Old appointment MUST still be confirmed
    async with session_factory() as session:
        old_db = await ClinicRepository(session).get_appointment_by_code("APT-20261024-01001")
        assert old_db.status == AppointmentStatus.CONFIRMED.value


async def test_sync_and_async_execution(tool):
    # Sync lookup
    sync_res = tool.execute(action="lookup", booking_code="APT-20261026-01001")
    assert sync_res.success is True
    assert sync_res.data["appointments"][0]["booking_code"] == "APT-20261026-01001"

    # Async lookup
    from src.tools.manage_appointment import async_manage_appointment

    with patch(
        "src.tools.manage_appointment.manage_appointment_tool",
        tool,
    ):
        async_res = await async_manage_appointment(
            action="lookup", booking_code="APT-20261026-01001"
        )
    assert async_res.success is True
    assert async_res.data["appointments"][0]["booking_code"] == "APT-20261026-01001"


def test_tool_registered_in_registry():
    assert "manage_appointment" in TOOL_REGISTRY
    tool_def = TOOL_REGISTRY["manage_appointment"]
    assert tool_def.input_schema is ManageAppointmentInput
    assert tool_def.output_schema is ManageAppointmentOutput
    assert tool_def.to_openai_dict()["function"]["name"] == "manage_appointment"


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


async def test_lookup_unknown_code(tool):
    res = await tool.aexecute(action=ManageAppointmentAction.LOOKUP, booking_code="APT-UNKNOWN")
    assert res.success is False
    assert res.error == "not_found"
    assert "مش لاقيين أي حجز" in res.message


async def test_lookup_phone_none(tool):
    res = await tool.aexecute(action=ManageAppointmentAction.LOOKUP, phone="01511112222")
    assert res.success is True
    assert res.data["status"] == "none"
    assert "معندكش أي حجوزات قادمة" in res.message


async def test_phone_mismatch_rejected(tool):
    # Appointment belongs to PHONE_A; trying to lookup/cancel with PHONE_B
    res = await tool.aexecute(
        action=ManageAppointmentAction.LOOKUP,
        booking_code="APT-20261024-01001",
        phone=PHONE_B,
    )
    assert res.success is False
    assert res.error == "phone_mismatch"
    assert "مش متسجل بنفس رقم الموبايل" in res.message


async def test_cancel_by_phone_multiple_asks_for_code(tool):
    # Patient A has 2 upcoming bookings (TODAY and MON) -> cannot cancel by phone alone
    res = await tool.aexecute(action=ManageAppointmentAction.CANCEL, phone=PHONE_A)
    assert res.success is False
    assert res.error == "multiple_appointments"
    assert "أكتر من حجز قادم" in res.message
    assert len(res.data["appointments"]) == 2


async def test_cancel_already_cancelled(tool):
    # Cancel once
    await tool.aexecute(action=ManageAppointmentAction.CANCEL, booking_code="APT-20261024-01001")
    # Cancel again
    res = await tool.aexecute(
        action=ManageAppointmentAction.CANCEL, booking_code="APT-20261024-01001"
    )
    assert res.success is False
    assert res.error == "already_cancelled"
    assert "ملغي بالفعل" in res.message


async def test_cancel_past_appointment(tool):
    res = await tool.aexecute(
        action=ManageAppointmentAction.CANCEL, booking_code="APT-20261010-01001"
    )
    assert res.success is False
    assert res.error == "not_confirmed"  # status is completed
    assert "مش متاح" in res.message


async def test_cancel_after_shift_started(tool, frozen_cairo_clock):
    # Move clock to 19:00 (during Saturday 18:00-22:00 shift)
    frozen_cairo_clock.return_value = NOW_DURING_SHIFT
    res = await tool.aexecute(
        action=ManageAppointmentAction.CANCEL, booking_code="APT-20261024-01001"
    )
    assert res.success is False
    assert res.error == "shift_started"
    assert "بدأ بالفعل" in res.message


async def test_reschedule_same_date_rejected(tool):
    res = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261024-01001",
        new_date=TODAY,
    )
    assert res.success is False
    assert res.error == "same_date"
    assert "نفس ميعاد الحجز الحالي" in res.message


async def test_reschedule_no_shift_suggests_next_available(tool):
    # Tuesday 2026-10-27: Dr. El-Sherif has no shift (shifts are Sat and Mon)
    res = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261024-01001",
        new_date=TUE,
    )
    assert res.success is False
    assert res.error == "no_shift"
    assert "مش موجود" in res.message
    assert "next_available" in res.data
    assert res.data["next_available"]["target_date"] == "2026-10-31"


async def test_reschedule_full_shift_suggests_next_available(tool, session_factory):
    # Saturay 2026-10-24 capacity is 2; let's fill it with another patient
    async with session_factory() as session:
        p_extra = Patient(name="زياد", phone="01200000000")
        session.add(p_extra)
        await session.flush()
        session.add(
            Appointment(
                booking_code="APT-20261024-01002",
                patient_id=p_extra.id,
                doctor_id=1,
                schedule_id=1,
                appointment_date=TODAY,
                queue_number=2,
            )
        )
        await session.commit()

    # Now reschedule Patient A's Monday booking to Saturday (which is now full)
    res = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261026-01001",
        new_date=TODAY,
    )
    assert res.success is False
    assert res.error == "shift_full"
    assert "مكتمل العدد بالكامل" in res.message


async def test_reschedule_duplicate_on_new_date(tool):
    # Patient A already has an appointment on Monday!
    # Trying to reschedule Saturday's appointment to Monday
    res = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261024-01001",
        new_date=MON,
    )
    assert res.success is False
    assert res.error == "duplicate_booking"
    assert "حجز مؤكد بالفعل" in res.message


async def test_reschedule_date_rules(tool, frozen_cairo_clock):
    # Past date
    res_past = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261024-01001",
        new_date=date(2026, 10, 20),
    )
    assert res_past.success is False
    assert res_past.error == "past_date"

    # > 30 days
    res_far = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261024-01001",
        new_date=TODAY + dt.timedelta(days=35),
    )
    assert res_far.success is False
    assert res_far.error == "too_far_ahead"

    # Today after shift end
    frozen_cairo_clock.return_value = NOW_LATE
    res_late = await tool.aexecute(
        action=ManageAppointmentAction.RESCHEDULE,
        booking_code="APT-20261026-01001",
        new_date=TODAY,
    )
    assert res_late.success is False
    assert res_late.error == "shift_ended"


async def test_unexpected_db_error_graceful(tool):
    with patch.object(
        ClinicRepository,
        "get_appointment_by_code",
        side_effect=RuntimeError("db connection failed"),
    ):
        res = await tool.aexecute(action=ManageAppointmentAction.LOOKUP, booking_code="APT-1")
    assert res.success is False
    assert "unexpected_error" in res.error
    assert "حدث خطأ" in res.message


async def test_invalid_input_parameters(tool):
    # Action lookup missing both code and phone
    res = await tool.aexecute(action=ManageAppointmentAction.LOOKUP)
    assert res.success is False
    assert res.error == "invalid_input"
