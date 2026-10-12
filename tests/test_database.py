"""
Automated Database & Concurrency Test Suite (Feature 1.5).

Verifies:
- Tier 1: Unit verification for queue numbering and booking code formatting.
- Tier 2: Integration verification for multi-session concurrent bookings (asyncio.gather),
  multi-doctor queue isolation, and operational appointment rescheduling.
- Tier 3: Error & edge-case verification for race-condition capacity cap enforcement
  (ShiftCapacityExceededError) and atomic rollback resilience on transaction failure.
- Tier 4: Regression prevention across relational integrity and capacity management.
"""

import asyncio
from datetime import date, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Appointment, Doctor, DoctorSchedule, Patient, Specialty
from src.db.repository import (
    ClinicRepository,
    ShiftCapacityExceededError,
)
from src.db.schemas import AppointmentStatus, VisitType


@pytest.fixture
async def db_session_factory():
    """
    Creates an isolated in-memory SQLite database engine with StaticPool
    and yields an async_sessionmaker factory for multi-session concurrency testing.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield session_factory
    finally:
        await engine.dispose()


@pytest.fixture
async def clinic_seed_data(db_session_factory: async_sessionmaker[AsyncSession]):
    """
    Seeds baseline specialties, two distinct doctors with shifts,
    and returns their identifiers for concurrency and isolation testing.
    """
    async with db_session_factory() as session:
        # 1. Specialties
        spec_cardio = Specialty(
            code="cardio",
            name_ar="أمراض القلب والأوعية الدموية",
            name_en="Cardiology",
        )
        spec_ortho = Specialty(
            code="ortho",
            name_ar="جراحة العظام والمفاصل",
            name_en="Orthopedics",
        )
        session.add_all([spec_cardio, spec_ortho])
        await session.flush()

        # 2. Doctors
        doc_a = Doctor(
            specialty_id=spec_cardio.id,
            name_ar="د. طارق الحصري",
            name_en="Dr. Tarek El-Hosary",
            title="consultant",
            examination_fee=400.0,
            consultation_fee=200.0,
        )
        doc_b = Doctor(
            specialty_id=spec_ortho.id,
            name_ar="د. سمير الشاذلي",
            name_en="Dr. Samir El-Shazly",
            title="specialist",
            examination_fee=350.0,
            consultation_fee=175.0,
        )
        session.add_all([doc_a, doc_b])
        await session.flush()

        # 3. Schedules (Saturday: day_of_week = 0, Monday: day_of_week = 2)
        sched_a_sat = DoctorSchedule(
            doctor_id=doc_a.id,
            day_of_week=0,  # Saturday
            start_time=time(18, 0),
            end_time=time(22, 0),
            max_capacity=10,
        )
        sched_b_sat = DoctorSchedule(
            doctor_id=doc_b.id,
            day_of_week=0,  # Saturday
            start_time=time(17, 0),
            end_time=time(21, 0),
            max_capacity=10,
        )
        sched_a_mon = DoctorSchedule(
            doctor_id=doc_a.id,
            day_of_week=2,  # Monday
            start_time=time(18, 0),
            end_time=time(22, 0),
            max_capacity=5,
        )
        session.add_all([sched_a_sat, sched_b_sat, sched_a_mon])

        # 4. Patients (Pool of 15 realistic Egyptian callers)
        patients = [
            Patient(name=f"مريض {i + 1}", phone=f"010123456{i:02d}")
            for i in range(15)
        ]
        session.add_all(patients)
        await session.commit()

        return {
            "doctor_a_id": doc_a.id,
            "doctor_b_id": doc_b.id,
            "patient_ids": [p.id for p in patients],
            "sched_a_sat_id": sched_a_sat.id,
            "sched_b_sat_id": sched_b_sat.id,
            "sched_a_mon_id": sched_a_mon.id,
        }


# ==============================================================================
# Tier 1: Unit Verification (Queue Number Generator & Code Formatting)
# ==============================================================================


@pytest.mark.asyncio
async def test_queue_number_sequential_increment_and_code_format(
    db_session_factory: async_sessionmaker[AsyncSession],
    clinic_seed_data: dict,
):
    """
    Tier 1 Unit Verification:
    Asserts sequential queue numbers start at 1 and strictly increment per booking,
    and verifies booking code formatting matches APT-YYYYMMDD-{doctor_id:02d}{queue:03d}.
    """
    doc_id = clinic_seed_data["doctor_a_id"]
    p_ids = clinic_seed_data["patient_ids"]
    target_date = date(2026, 10, 17)  # Saturday

    async with db_session_factory() as session:
        repo = ClinicRepository(session)

        # 1st booking
        apt1 = await repo.create_appointment(
            patient_id=p_ids[0],
            doctor_id=doc_id,
            appointment_date=target_date,
            visit_type=VisitType.EXAMINATION,
        )
        assert apt1.queue_number == 1
        assert apt1.booking_code == f"APT-20261017-{doc_id:02d}001"
        assert apt1.status == AppointmentStatus.CONFIRMED.value

        # 2nd booking
        apt2 = await repo.create_appointment(
            patient_id=p_ids[1],
            doctor_id=doc_id,
            appointment_date=target_date,
            visit_type=VisitType.CONSULTATION,
        )
        assert apt2.queue_number == 2
        assert apt2.booking_code == f"APT-20261017-{doc_id:02d}002"

        # 3rd booking
        apt3 = await repo.create_appointment(
            patient_id=p_ids[2],
            doctor_id=doc_id,
            appointment_date=target_date,
            visit_type=VisitType.EXAMINATION,
        )
        assert apt3.queue_number == 3
        assert apt3.booking_code == f"APT-20261017-{doc_id:02d}003"


# ==============================================================================
# Tier 2: Integration Verification (Concurrency, Isolation, Rescheduling)
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrent_bookings_multi_session_integrity(
    db_session_factory: async_sessionmaker[AsyncSession],
    clinic_seed_data: dict,
):
    """
    Tier 2 Integration Verification (FR-1):
    Simulates 6 simultaneous callers via asyncio.gather on independent sessions.
    Asserts:
    - All 6 bookings succeed without IntegrityError.
    - Queue numbers strictly form the set {1, 2, 3, 4, 5, 6} with zero duplicates.
    - All booking codes are distinct.
    - Doctor availability remaining capacity is decremented accurately by 6.
    """
    doc_id = clinic_seed_data["doctor_a_id"]
    patient_ids = clinic_seed_data["patient_ids"][:6]
    target_date = date(2026, 10, 17)  # Saturday

    async def simulate_caller_booking(patient_id: int):
        async with db_session_factory() as session:
            repo = ClinicRepository(session)
            return await repo.create_appointment(
                patient_id=patient_id,
                doctor_id=doc_id,
                appointment_date=target_date,
                visit_type=VisitType.EXAMINATION,
            )

    # Launch 6 concurrent caller tasks simultaneously
    results = await asyncio.gather(
        *[simulate_caller_booking(pid) for pid in patient_ids],
        return_exceptions=False,
    )

    assert len(results) == 6

    # Extract queue numbers and booking codes
    queue_numbers = [apt.queue_number for apt in results]
    booking_codes = [apt.booking_code for apt in results]

    # Verify zero duplicate queue numbers and strict set match {1, 2, 3, 4, 5, 6}
    assert sorted(queue_numbers) == [1, 2, 3, 4, 5, 6]
    assert len(set(booking_codes)) == 6

    # Verify database state from a separate session
    async with db_session_factory() as session:
        repo = ClinicRepository(session)
        avail = await repo.get_doctor_availability(doc_id, target_date)
        assert avail.booked_count == 6
        assert avail.remaining_capacity == 4  # max_capacity=10 - 6


@pytest.mark.asyncio
async def test_multi_doctor_independent_queue_isolation(
    db_session_factory: async_sessionmaker[AsyncSession],
    clinic_seed_data: dict,
):
    """
    Tier 2 Integration Verification (FR-3):
    Simulates concurrent callers booking appointments across two distinct doctors
    (Doctor A and Doctor B) on the same date.
    Asserts:
    - Doctor A patients receive queue numbers {1, 2, 3}.
    - Doctor B patients receive independent queue numbers {1, 2, 3}.
    - Doctor A bookings do not decrement Doctor B's shift capacity.
    """
    doc_a_id = clinic_seed_data["doctor_a_id"]
    doc_b_id = clinic_seed_data["doctor_b_id"]
    p_ids = clinic_seed_data["patient_ids"]
    target_date = date(2026, 10, 17)  # Saturday

    patients_doc_a = p_ids[0:3]
    patients_doc_b = p_ids[3:6]

    async def book_caller(doc_id: int, patient_id: int):
        async with db_session_factory() as session:
            repo = ClinicRepository(session)
            return await repo.create_appointment(
                patient_id=patient_id,
                doctor_id=doc_id,
                appointment_date=target_date,
            )

    tasks = [
        book_caller(doc_a_id, pid) for pid in patients_doc_a
    ] + [
        book_caller(doc_b_id, pid) for pid in patients_doc_b
    ]

    results = await asyncio.gather(*tasks, return_exceptions=False)
    assert len(results) == 6

    # Filter results by doctor
    apts_a = [apt for apt in results if apt.doctor_id == doc_a_id]
    apts_b = [apt for apt in results if apt.doctor_id == doc_b_id]

    assert sorted([apt.queue_number for apt in apts_a]) == [1, 2, 3]
    assert sorted([apt.queue_number for apt in apts_b]) == [1, 2, 3]

    # Verify both doctors have independent capacities in database
    async with db_session_factory() as session:
        repo = ClinicRepository(session)
        avail_a = await repo.get_doctor_availability(doc_a_id, target_date)
        avail_b = await repo.get_doctor_availability(doc_b_id, target_date)

        assert avail_a.booked_count == 3
        assert avail_a.remaining_capacity == 7  # 10 - 3
        assert avail_b.booked_count == 3
        assert avail_b.remaining_capacity == 7  # 10 - 3


@pytest.mark.asyncio
async def test_operational_rescheduling_and_capacity_recovery(
    db_session_factory: async_sessionmaker[AsyncSession],
    clinic_seed_data: dict,
):
    """
    Tier 2 Integration Verification (FR-5):
    Verifies operational flow of booking, cancelling, and rescheduling into another shift.
    Asserts:
    - Cancelling an appointment restores 1 slot in the old shift.
    - Booking in the new shift consumes 1 slot in the new shift.
    - Patient appointment history reflects both cancelled and active records.
    """
    doc_id = clinic_seed_data["doctor_a_id"]
    patient_id = clinic_seed_data["patient_ids"][0]

    date_sat = date(2026, 10, 17)  # Saturday
    date_mon = date(2026, 10, 19)  # Monday

    async with db_session_factory() as session:
        repo = ClinicRepository(session)

        # 1. Book in Saturday shift
        apt_sat = await repo.create_appointment(
            patient_id=patient_id,
            doctor_id=doc_id,
            appointment_date=date_sat,
            notes="حجز مبدئي يوم السبت",
        )
        assert apt_sat.status == AppointmentStatus.CONFIRMED.value

        avail_sat_before = await repo.get_doctor_availability(doc_id, date_sat)
        assert avail_sat_before.booked_count == 1
        assert avail_sat_before.remaining_capacity == 9

        # 2. Cancel Saturday appointment (Rescheduling intention)
        cancelled = await repo.cancel_appointment(
            booking_code=apt_sat.booking_code,
            reason="طلب المريض تغيير الموعد ليوم الإثنين",
        )
        assert cancelled is not None
        assert cancelled.status == AppointmentStatus.CANCELLED.value

        # Capacity in Saturday shift restored!
        avail_sat_after = await repo.get_doctor_availability(doc_id, date_sat)
        assert avail_sat_after.booked_count == 0
        assert avail_sat_after.remaining_capacity == 10

        # 3. Book in Monday shift
        apt_mon = await repo.create_appointment(
            patient_id=patient_id,
            doctor_id=doc_id,
            appointment_date=date_mon,
            notes="الموعد البديل بعد إعادة الجدولة",
        )
        assert apt_mon.queue_number == 1
        assert apt_mon.appointment_date == date_mon

        # Monday shift capacity consumed
        avail_mon = await repo.get_doctor_availability(doc_id, date_mon)
        assert avail_mon.booked_count == 1
        assert avail_mon.remaining_capacity == 4  # max_capacity=5 - 1


# ==============================================================================
# Tier 3: Error & Edge-Case Verification (Overbooking, Atomic Rollback)
# ==============================================================================


@pytest.mark.asyncio
async def test_race_condition_overbooking_rejection(
    db_session_factory: async_sessionmaker[AsyncSession],
    clinic_seed_data: dict,
):
    """
    Tier 3 Error & Edge-Case Verification (FR-2):
    Tests race condition overbooking rejection.
    Sets Monday shift with max_capacity = 3.
    Launches 7 concurrent booking tasks simultaneously via asyncio.gather.
    Asserts:
    - Exactly 3 bookings succeed.
    - Exactly 4 requests fail gracefully with ShiftCapacityExceededError.
    - Zero orphaned / ghost rows exist in the database (total count == 3).
    """
    doc_id = clinic_seed_data["doctor_a_id"]
    patient_ids = clinic_seed_data["patient_ids"][:7]
    target_date = date(2026, 10, 19)  # Monday (max_capacity = 5 in fixture, we override to 3)

    # Adjust Monday shift capacity to 3 for tight race testing
    async with db_session_factory() as session:
        sched_stmt = select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doc_id,
            DoctorSchedule.day_of_week == 2,  # Monday
        )
        sched_res = await session.execute(sched_stmt)
        sched = sched_res.scalars().one()
        sched.max_capacity = 3
        await session.commit()

    async def attempt_booking(patient_id: int):
        async with db_session_factory() as session:
            repo = ClinicRepository(session)
            return await repo.create_appointment(
                patient_id=patient_id,
                doctor_id=doc_id,
                appointment_date=target_date,
            )

    # Fire 7 simultaneous booking requests
    raw_results = await asyncio.gather(
        *[attempt_booking(pid) for pid in patient_ids],
        return_exceptions=True,
    )

    successes = [r for r in raw_results if not isinstance(r, Exception)]
    failures = [r for r in raw_results if isinstance(r, Exception)]

    # Exactly 3 must succeed, exactly 4 must fail
    assert len(successes) == 3
    assert len(failures) == 4

    # Every failure must be a clean ShiftCapacityExceededError
    for fail in failures:
        assert isinstance(fail, ShiftCapacityExceededError)
        assert "مكتمل بالكامل" in str(fail)

    # The 3 successes must have strictly sequential queues
    success_queues = sorted([s.queue_number for s in successes])
    assert success_queues == [1, 2, 3]

    # Verify database has exactly 3 records and zero ghost records
    async with db_session_factory() as session:
        count_stmt = select(func.count(Appointment.id)).where(
            Appointment.doctor_id == doc_id,
            Appointment.appointment_date == target_date,
        )
        count_res = await session.execute(count_stmt)
        total_db_records = count_res.scalar_one()
        assert total_db_records == 3


@pytest.mark.asyncio
async def test_atomic_rollback_on_transaction_failure(
    db_session_factory: async_sessionmaker[AsyncSession],
    clinic_seed_data: dict,
):
    """
    Tier 3 Error & Edge-Case Verification (FR-4):
    Verifies that uncommitted or aborted operations rollback completely.
    If a transaction fails before commit, no partial patient or appointment
    rows persist in the database.
    """
    doc_id = clinic_seed_data["doctor_a_id"]
    target_date = date(2026, 10, 17)

    # Simulate an operation where a new patient and appointment are drafted,
    # but an unhandled exception triggers a rollback before completion.
    with pytest.raises(RuntimeError, match="Simulated crash during booking flow"):
        async with db_session_factory() as session:
            # Add patient without commit
            p_fail = Patient(name="مريض ملغي", phone="01099999999")
            session.add(p_fail)
            await session.flush()

            # Draft appointment without commit
            apt_fail = Appointment(
                booking_code="APT-FAIL-TEST",
                patient_id=p_fail.id,
                doctor_id=doc_id,
                schedule_id=clinic_seed_data["sched_a_sat_id"],
                appointment_date=target_date,
                queue_number=99,
                visit_type="examination",
                status="confirmed",
            )
            session.add(apt_fail)
            await session.flush()

            # Simulate unexpected crash mid-transaction
            raise RuntimeError("Simulated crash during booking flow")

    # Verify that neither the patient nor the appointment exists in the DB
    async with db_session_factory() as session:
        p_check = await session.execute(
            select(Patient).where(Patient.phone == "01099999999")
        )
        assert p_check.scalars().first() is None

        apt_check = await session.execute(
            select(Appointment).where(Appointment.booking_code == "APT-FAIL-TEST")
        )
        assert apt_check.scalars().first() is None
