"""
Test Suite for Appointment Booking Tool (Feature 3.3).

Tier 1: pure helpers (date window, shift-ended rule, Cairo date parsing, message).
Tier 2: integration with ClinicRepository on in-memory SQLite (booking, queue numbers,
        concurrency, consultation eligibility, patient reuse, sync/async, registry).
Tier 3: edge cases (no shift, full shift, no alternative, duplicates, cancellations,
        unknown/ambiguous doctors, integrity retry, unexpected errors, invalid input).

Calendar used by fixtures (Cairo "today" is frozen to Saturday 2026-10-24, 10:00):
    Sat 10-24 | Sun 10-25 | Mon 10-26 | Tue 10-27 | Wed 10-28 | ... | Sat 10-31
"""

import asyncio
import datetime as dt
from datetime import date, time
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Appointment, Doctor, DoctorSchedule, Patient, Specialty
from src.db.repository import ClinicRepository
from src.tools import TOOL_REGISTRY, AppointmentBookingInput, AppointmentBookingOutput
from src.tools.appointment_booking import (
    AppointmentBookingTool,
    build_confirmation_message,
    check_date_window,
    resolve_booking_date,
    shift_already_ended,
)
from src.tools.doctor_availability import CAIRO_TZ

TODAY = date(2026, 10, 24)  # Saturday
SAT, MON, TUE, WED = date(2026, 10, 24), date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)
NOW_MORNING = dt.datetime(2026, 10, 24, 10, 0, tzinfo=CAIRO_TZ)
NOW_LATE = dt.datetime(2026, 10, 24, 23, 0, tzinfo=CAIRO_TZ)

PHONE_A = "01012345678"
PHONE_B = "01198765432"


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(autouse=True)
def frozen_cairo_clock():
    """Freeze Cairo 'today' and 'now' inside the booking tool."""
    with (
        patch("src.tools.appointment_booking.get_cairo_today", return_value=TODAY),
        patch("src.tools.appointment_booking.get_cairo_now", return_value=NOW_MORNING) as now,
    ):
        yield now


@pytest.fixture
async def session_factory(tmp_path):
    # File-based SQLite (one connection per session) gives real transaction isolation,
    # which the concurrency test needs; StaticPool would share a single connection.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'booking_test.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        internal = Specialty(code="internal_medicine", name_ar="الباطنة", name_en="Internal")
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
        samy = Doctor(
            specialty_id=peds.id,
            name_ar="د. أحمد سامي عثمان",
            name_en="Dr. Ahmed Samy",
            examination_fee=200.0,
            consultation_fee=100.0,
        )
        farouk = Doctor(
            specialty_id=peds.id,
            name_ar="د. فاروق الألفي",
            name_en="Dr. Farouk El-Alfy",
            examination_fee=400.0,
            consultation_fee=200.0,
        )
        session.add_all([sherif, marwa, samy, farouk])
        await session.flush()

        session.add_all(
            [
                # Sherif: Saturday (cap 2) and Monday (cap 5)
                DoctorSchedule(
                    doctor_id=sherif.id,
                    day_of_week=0,
                    start_time=time(18, 0),
                    end_time=time(22, 0),
                    max_capacity=2,
                ),
                DoctorSchedule(
                    doctor_id=sherif.id,
                    day_of_week=2,
                    start_time=time(18, 0),
                    end_time=time(22, 0),
                    max_capacity=5,
                ),
                # Marwa: Wednesday
                DoctorSchedule(
                    doctor_id=marwa.id,
                    day_of_week=4,
                    start_time=time(17, 0),
                    end_time=time(20, 0),
                    max_capacity=5,
                ),
                # Samy: Sunday
                DoctorSchedule(
                    doctor_id=samy.id,
                    day_of_week=1,
                    start_time=time(12, 0),
                    end_time=time(15, 0),
                    max_capacity=5,
                ),
                # Farouk: no schedules at all
            ]
        )
        await session.commit()

    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def tool(session_factory) -> AppointmentBookingTool:
    return AppointmentBookingTool(session_factory=session_factory)


async def _count_appointments(factory, doctor_id: int | None = None) -> int:
    async with factory() as session:
        stmt = select(func.count(Appointment.id))
        if doctor_id is not None:
            stmt = stmt.where(Appointment.doctor_id == doctor_id)
        return (await session.execute(stmt)).scalar_one()


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_date_rules_reject_past_and_far_future():
    assert check_date_window(TODAY - dt.timedelta(days=1), TODAY) == "past_date"
    assert check_date_window(TODAY + dt.timedelta(days=31), TODAY) == "too_far_ahead"
    assert check_date_window(TODAY, TODAY) is None
    assert check_date_window(TODAY + dt.timedelta(days=30), TODAY) is None


def test_today_after_shift_end_rejected():
    end = time(22, 0)
    assert shift_already_ended(TODAY, TODAY, end, time(22, 30)) is True
    assert shift_already_ended(TODAY, TODAY, end, time(22, 0)) is True
    assert shift_already_ended(TODAY, TODAY, end, time(21, 59)) is False
    # Future dates are never "ended"
    assert shift_already_ended(MON, TODAY, end, time(23, 0)) is False


def test_raw_colloquial_date_uses_cairo_today():
    # 23:30 UTC on Oct 23 is already Oct 24 in Cairo -> "بكرة" must be Oct 25
    cairo_today = (
        dt.datetime(2026, 10, 23, 23, 30, tzinfo=dt.timezone.utc).astimezone(CAIRO_TZ).date()
    )
    assert cairo_today == date(2026, 10, 24)
    assert resolve_booking_date("بكرة", cairo_today) == date(2026, 10, 25)
    assert resolve_booking_date("2026-11-01", cairo_today) == date(2026, 11, 1)
    with pytest.raises(ValueError):
        resolve_booking_date("", cairo_today)


def test_confirmation_message_contents():
    msg = build_confirmation_message(
        doctor_name_ar="د. أحمد محمود الشريف",
        specialty_name_ar="الباطنة",
        day_name_ar="الاثنين",
        appointment_date=MON,
        shift_window="06:00 PM - 10:00 PM",
        queue_number=3,
        booking_code="APT-20261026-01003",
        visit_type_ar="كشف جديد",
        fee=350.0,
    )
    for part in (
        "د. أحمد محمود الشريف",
        "2026-10-26",
        "06:00 PM - 10:00 PM",
        "نمرة حجزك 3",
        "APT-20261026-01003",
        "350 جنيه",
    ):
        assert part in msg
    assert msg.count("APT-20261026-01003") == 1


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


async def test_book_by_doctor_id_success(tool, session_factory):
    res = await tool.aexecute(patient_name="محمد علي", patient_phone=PHONE_A, doctor_id=1, date=MON)
    assert res.success is True, res.message
    assert res.data["queue_number"] == 1
    assert res.data["fee"] == 350.0
    assert res.data["visit_type_downgraded"] is False
    assert res.data["booking_code"] in res.message
    assert await _count_appointments(session_factory, 1) == 1


async def test_book_by_doctor_name_success(tool):
    res = await tool.aexecute(
        patient_name="محمد علي", patient_phone=PHONE_A, doctor_name="الشريف", date="2026-10-26"
    )
    assert res.success is True, res.message
    assert res.data["doctor_name_ar"] == "د. أحمد محمود الشريف"
    assert res.data["shift_window"] == "06:00 PM - 10:00 PM"


async def test_sequential_queue_numbers(tool):
    r1 = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    r2 = await tool.aexecute(patient_name="سارة", patient_phone=PHONE_B, doctor_id=1, date=MON)
    assert (r1.data["queue_number"], r2.data["queue_number"]) == (1, 2)


async def test_concurrent_bookings_respect_capacity(tool, session_factory):
    phones = [f"010{i:08d}" for i in range(1, 9)]  # 8 callers, Monday capacity = 5
    results = await asyncio.gather(
        *[
            tool.aexecute(patient_name=f"مريض {i}", patient_phone=p, doctor_id=1, date=MON)
            for i, p in enumerate(phones)
        ]
    )
    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 5
    assert len(failures) == 3
    assert sorted(r.data["queue_number"] for r in successes) == [1, 2, 3, 4, 5]
    assert all(r.error == "shift_full" for r in failures)
    assert await _count_appointments(session_factory, 1) == 5


async def _seed_past_examination(factory, phone: str, appt_date: date, visit_type: str):
    async with factory() as session:
        patient = Patient(name="محمد علي", phone=phone)
        session.add(patient)
        await session.flush()
        sched = (
            (
                await session.execute(
                    select(DoctorSchedule).where(
                        DoctorSchedule.doctor_id == 1, DoctorSchedule.day_of_week == 2
                    )
                )
            )
            .scalars()
            .first()
        )
        session.add(
            Appointment(
                booking_code=f"OLD-{appt_date:%Y%m%d}",
                patient_id=patient.id,
                doctor_id=1,
                schedule_id=sched.id,
                appointment_date=appt_date,
                queue_number=1,
                visit_type=visit_type,
                fee=350.0,
            )
        )
        await session.commit()


async def test_consultation_eligible_uses_consultation_fee(tool, session_factory):
    await _seed_past_examination(session_factory, PHONE_A, date(2026, 10, 19), "examination")
    res = await tool.aexecute(
        patient_name="محمد علي",
        patient_phone=PHONE_A,
        doctor_id=1,
        date=MON,
        visit_type="consultation",
    )
    assert res.success is True, res.message
    assert res.data["visit_type"] == "consultation"
    assert res.data["fee"] == 150.0
    assert res.data["visit_type_downgraded"] is False


async def test_consultation_not_eligible_downgraded(tool, session_factory):
    # Examination 21 days earlier -> outside the 14-day window
    await _seed_past_examination(session_factory, PHONE_A, date(2026, 10, 5), "examination")
    res = await tool.aexecute(
        patient_name="محمد علي",
        patient_phone=PHONE_A,
        doctor_id=1,
        date=MON,
        visit_type="استشارة",
    )
    assert res.success is True, res.message
    assert res.data["visit_type"] == "examination"
    assert res.data["fee"] == 350.0
    assert res.data["visit_type_downgraded"] is True
    assert "كشف جديد" in res.message and "14 يوم" in res.message


async def test_existing_patient_reused(tool, session_factory):
    await tool.aexecute(patient_name="محمد علي", patient_phone=PHONE_A, doctor_id=1, date=MON)
    await tool.aexecute(
        patient_name="محمد علي", patient_phone="+20 10 1234 5678", doctor_id=2, date=WED
    )
    async with session_factory() as session:
        count = (await session.execute(select(func.count(Patient.id)))).scalar_one()
    assert count == 1


async def test_async_execution(session_factory):
    with patch(
        "src.tools.appointment_booking.appointment_booking_tool",
        AppointmentBookingTool(session_factory=session_factory),
    ):
        from src.tools.appointment_booking import async_book_appointment

        res = await async_book_appointment(
            patient_name="محمد علي", patient_phone=PHONE_A, doctor_id=2, date=WED
        )
    assert res.success is True, res.message
    assert res.data["doctor_name_ar"] == "د. مروة كمال الدين"


def test_sync_execution(tool):
    res = tool.execute(patient_name="محمد علي", patient_phone=PHONE_A, doctor_id=2, date=WED)
    assert res.success is True, res.message
    assert res.data["queue_number"] == 1


def test_tool_registered_in_registry():
    assert "book_appointment" in TOOL_REGISTRY
    tool_def = TOOL_REGISTRY["book_appointment"]
    assert tool_def.input_schema is AppointmentBookingInput
    assert tool_def.output_schema is AppointmentBookingOutput
    assert tool_def.to_openai_dict()["function"]["name"] == "book_appointment"


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


async def test_no_shift_suggests_next_available_without_booking(tool, session_factory):
    res = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=TUE)
    assert res.success is False
    assert res.error == "no_shift"
    assert res.data["next_available"]["target_date"] == "2026-10-31"
    assert "تحب أحجزلك فيه" in res.message
    assert await _count_appointments(session_factory) == 0


async def test_full_shift_suggests_next_available(tool, session_factory):
    for phone in (PHONE_A, PHONE_B):
        assert (
            await tool.aexecute(patient_name="مريض", patient_phone=phone, doctor_id=1, date=SAT)
        ).success
    res = await tool.aexecute(
        patient_name="مريض", patient_phone="01500000001", doctor_id=1, date=SAT
    )
    assert res.success is False
    assert res.error == "shift_full"
    assert res.data["next_available"]["target_date"] == "2026-10-26"
    assert await _count_appointments(session_factory, 1) == 2


async def test_today_after_shift_end_rejected_by_tool(tool, frozen_cairo_clock):
    frozen_cairo_clock.return_value = NOW_LATE
    res = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=SAT)
    assert res.success is False
    assert res.error == "shift_ended"
    assert res.data["next_available"]["target_date"] == "2026-10-26"


async def test_no_alternative_within_seven_days(tool):
    res = await tool.aexecute(
        patient_name="محمد", patient_phone=PHONE_A, doctor_name="فاروق", date=MON
    )
    assert res.success is False
    assert res.data["next_available"] is None
    assert "موظف الاستقبال" in res.message


async def test_duplicate_booking_returns_existing(tool, session_factory):
    first = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    second = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    assert second.success is False
    assert second.error == "duplicate_booking"
    existing = second.data["existing_appointment"]
    assert existing["booking_code"] == first.data["booking_code"]
    assert existing["queue_number"] == 1
    assert first.data["booking_code"] in second.message
    assert await _count_appointments(session_factory, 1) == 1


async def test_cancelled_booking_not_counted_as_duplicate(tool, session_factory):
    first = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    async with session_factory() as session:
        await ClinicRepository(session).cancel_appointment(first.data["booking_code"])
    again = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    assert again.success is True, again.message
    assert again.data["queue_number"] == 2


async def test_unknown_doctor_id_and_name(tool):
    by_id = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=99, date=MON)
    by_name = await tool.aexecute(
        patient_name="محمد", patient_phone=PHONE_A, doctor_name="د. فلان الفلاني", date=MON
    )
    assert by_id.success is False and by_id.error == "doctor_not_found"
    assert by_name.success is False and by_name.error == "doctor_not_found"


async def test_ambiguous_doctor_name_returns_candidates(tool, session_factory):
    res = await tool.aexecute(
        patient_name="محمد", patient_phone=PHONE_A, doctor_name="أحمد", date=MON
    )
    assert res.success is False
    assert res.error == "ambiguous_doctor"
    assert len(res.data["candidates"]) == 2
    assert await _count_appointments(session_factory) == 0


async def test_integrity_conflict_retry(tool):
    original = AppointmentBookingTool._attempt_booking
    calls = {"n": 0}

    async def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        return await original(self, *args, **kwargs)

    with patch.object(AppointmentBookingTool, "_attempt_booking", flaky):
        res = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    assert res.success is True, res.message
    assert calls["n"] == 2


async def test_integrity_conflict_twice_fails_politely(tool, session_factory):
    async def always_conflict(self, *args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))

    with patch.object(AppointmentBookingTool, "_attempt_booking", always_conflict):
        res = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    assert res.success is False
    assert res.error == "booking_conflict"
    assert await _count_appointments(session_factory) == 0


async def test_unexpected_db_error_graceful(tool):
    with patch.object(
        ClinicRepository, "get_doctor_availability", side_effect=RuntimeError("db down")
    ):
        res = await tool.aexecute(patient_name="محمد", patient_phone=PHONE_A, doctor_id=1, date=MON)
    assert res.success is False
    assert res.error.startswith("unexpected_error")
    assert "مشكلة" in res.message


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"date": date(2026, 10, 20)}, "past_date"),
        ({"date": date(2026, 12, 31)}, "too_far_ahead"),
        ({"date": "يوم المشمش"}, "invalid_date"),
        ({"patient_phone": "12345"}, "invalid_input"),
        ({"patient_name": "م"}, "invalid_input"),
    ],
)
async def test_invalid_inputs_graceful(tool, session_factory, kwargs, error):
    base = {"patient_name": "محمد", "patient_phone": PHONE_A, "doctor_id": 1, "date": MON}
    base.update(kwargs)
    res = await tool.aexecute(**base)
    assert res.success is False
    assert res.error == error
    assert await _count_appointments(session_factory) == 0
