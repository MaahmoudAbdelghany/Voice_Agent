"""
Tests for ClinicRepository and Database Seeding Pipeline (Feature 1.4).

Verifies:
- Specialty and doctor lookups
- Doctor availability and remaining capacity calculation
- Patient get-or-create with Egyptian phone normalization
- Atomic appointment booking with sequential queue numbering
- Shift capacity cap enforcement (ShiftCapacityExceededError)
- Booking on non-shift days rejection (ShiftNotFoundError)
- Appointment cancellation and capacity recovery
- Database seeder execution and idempotency
"""

from datetime import date, time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from scripts.seed_clinic_db import seed_clinic_database
from src.db.base import Base
from src.db.models import Doctor, DoctorSchedule, Patient, Specialty
from src.db.repository import (
    ClinicRepository,
    ShiftCapacityExceededError,
    ShiftNotFoundError,
)
from src.db.schemas import DayOfWeek, VisitType


@pytest.fixture
async def async_test_session():
    """Provides an isolated in-memory SQLite database session for repository testing."""
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

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_specialty_and_doctor_queries(async_test_session: AsyncSession):
    """Test retrieving specialties and doctors with filters."""
    repo = ClinicRepository(async_test_session)

    # Insert specialty
    spec = Specialty(
        code="cardiology",
        name_ar="أمراض القلب",
        name_en="Cardiology",
        description="فحص ورعاية القلب والشرايين",
    )
    async_test_session.add(spec)
    await async_test_session.flush()

    # Insert doctor
    doc = Doctor(
        specialty_id=spec.id,
        name_ar="د. مجدي يعقوب",
        name_en="Dr. Magdi Yacoub",
        title="professor",
        examination_fee=500.0,
        consultation_fee=250.0,
    )
    async_test_session.add(doc)
    await async_test_session.commit()

    # 1. Query specialties
    specs = await repo.get_specialties()
    assert len(specs) == 1
    assert specs[0].code == "cardiology"

    spec_by_code = await repo.get_specialty_by_code("cardiology")
    assert spec_by_code is not None
    assert spec_by_code.name_ar == "أمراض القلب"

    none_spec = await repo.get_specialty_by_code("non_existent")
    assert none_spec is None

    # 2. Query doctors
    docs = await repo.get_doctors(specialty_code="cardiology")
    assert len(docs) == 1
    assert docs[0].name_ar == "د. مجدي يعقوب"
    assert docs[0].specialty.code == "cardiology"

    doc_by_id = await repo.get_doctor_by_id(doc.id)
    assert doc_by_id is not None
    assert doc_by_id.name_ar == "د. مجدي يعقوب"


@pytest.mark.asyncio
async def test_doctor_availability_calculation(async_test_session: AsyncSession):
    """Test shift availability calculation and capacity remaining."""
    repo = ClinicRepository(async_test_session)

    spec = Specialty(code="internal", name_ar="باطنة", name_en="Internal")
    async_test_session.add(spec)
    await async_test_session.flush()

    doc = Doctor(
        specialty_id=spec.id,
        name_ar="د. أحمد محمود",
        name_en="Dr. Ahmed",
        examination_fee=300.0,
        consultation_fee=150.0,
    )
    async_test_session.add(doc)
    await async_test_session.flush()

    # Schedule: Saturday (0), 18:00 - 22:00, capacity 2
    sched = DoctorSchedule(
        doctor_id=doc.id,
        day_of_week=0,  # Saturday
        start_time=time(18, 0),
        end_time=time(22, 0),
        max_capacity=2,
    )
    async_test_session.add(sched)
    await async_test_session.commit()

    # 2026-10-17 is a Saturday (DayOfWeek.SATURDAY = 0)
    target_saturday = date(2026, 10, 17)
    assert DayOfWeek.from_date(target_saturday) == DayOfWeek.SATURDAY

    avail = await repo.get_doctor_availability(doc.id, target_saturday)
    assert avail.has_shift is True
    assert avail.is_available is True
    assert avail.max_capacity == 2
    assert avail.booked_count == 0
    assert avail.remaining_capacity == 2
    assert avail.examination_fee == 300.0

    # 2026-10-18 is Sunday (no schedule for this doctor)
    target_sunday = date(2026, 10, 18)
    avail_sun = await repo.get_doctor_availability(doc.id, target_sunday)
    assert avail_sun.has_shift is False
    assert avail_sun.is_available is False


@pytest.mark.asyncio
async def test_patient_get_or_create(async_test_session: AsyncSession):
    """Test patient registration with phone cleaning and deduplication."""
    repo = ClinicRepository(async_test_session)

    # 1. Create new patient with uncleaned phone
    p1 = await repo.get_or_create_patient(
        name="محمود عبد الغني",
        phone_number="+201012345678",
        gender="male",
    )
    assert p1.id is not None
    assert p1.phone == "01012345678"

    # 2. Get existing patient using different formatting
    p2 = await repo.get_or_create_patient(
        name="محمود عبد الغني المعدل",
        phone_number="010 1234 5678",
    )
    assert p2.id == p1.id
    assert p2.name == "محمود عبد الغني المعدل"

    # 3. Lookup by phone
    found = await repo.get_patient_by_phone("01012345678")
    assert found is not None
    assert found.id == p1.id


@pytest.mark.asyncio
async def test_atomic_appointment_booking_and_queue(async_test_session: AsyncSession):
    """Test atomic appointment creation with queue number incrementation."""
    repo = ClinicRepository(async_test_session)

    spec = Specialty(code="peds", name_ar="أطفال", name_en="Pediatrics")
    async_test_session.add(spec)
    await async_test_session.flush()

    doc = Doctor(
        specialty_id=spec.id,
        name_ar="د. نهى علي",
        name_en="Dr. Noha",
        examination_fee=250.0,
        consultation_fee=120.0,
    )
    async_test_session.add(doc)
    await async_test_session.flush()

    sched = DoctorSchedule(
        doctor_id=doc.id,
        day_of_week=0,  # Saturday
        start_time=time(10, 0),
        end_time=time(14, 0),
        max_capacity=5,
    )
    async_test_session.add(sched)

    patient_1 = Patient(name="أحمد حسن", phone="01111111111")
    patient_2 = Patient(name="سارة سامي", phone="01222222222")
    async_test_session.add_all([patient_1, patient_2])
    await async_test_session.commit()

    target_date = date(2026, 10, 17)  # Saturday

    # Book 1st appointment
    apt1 = await repo.create_appointment(
        patient_id=patient_1.id,
        doctor_id=doc.id,
        appointment_date=target_date,
        visit_type=VisitType.EXAMINATION,
        notes="فحص حرارة وسعال",
    )
    assert apt1.queue_number == 1
    assert apt1.booking_code.startswith("APT-20261017-")
    assert apt1.fee == 250.0
    assert apt1.status == "confirmed"

    # Book 2nd appointment
    apt2 = await repo.create_appointment(
        patient_id=patient_2.id,
        doctor_id=doc.id,
        appointment_date=target_date,
        visit_type=VisitType.CONSULTATION,
        notes="استشارة متابعة تحاليل",
    )
    assert apt2.queue_number == 2
    assert apt2.fee == 120.0

    # Verify remaining capacity
    avail = await repo.get_doctor_availability(doc.id, target_date)
    assert avail.booked_count == 2
    assert avail.remaining_capacity == 3


@pytest.mark.asyncio
async def test_shift_capacity_cap_enforcement(async_test_session: AsyncSession):
    """Test that booking beyond max_capacity raises ShiftCapacityExceededError."""
    repo = ClinicRepository(async_test_session)

    spec = Specialty(code="ortho", name_ar="عظام", name_en="Orthopedics")
    async_test_session.add(spec)
    await async_test_session.flush()

    doc = Doctor(specialty_id=spec.id, name_ar="د. حسام", name_en="Dr. Hossam", examination_fee=300.0)
    async_test_session.add(doc)
    await async_test_session.flush()

    # Cap = 1 patient
    sched = DoctorSchedule(
        doctor_id=doc.id,
        day_of_week=0,
        start_time=time(18, 0),
        end_time=time(20, 0),
        max_capacity=1,
    )
    p1 = Patient(name="مريض 1", phone="01011111111")
    p2 = Patient(name="مريض 2", phone="01022222222")
    async_test_session.add_all([sched, p1, p2])
    await async_test_session.commit()

    target_date = date(2026, 10, 17)

    # 1st booking succeeds
    await repo.create_appointment(patient_id=p1.id, doctor_id=doc.id, appointment_date=target_date)

    # 2nd booking should fail with ShiftCapacityExceededError
    with pytest.raises(ShiftCapacityExceededError) as exc_info:
        await repo.create_appointment(patient_id=p2.id, doctor_id=doc.id, appointment_date=target_date)

    assert "مكتمل بالكامل" in str(exc_info.value)


@pytest.mark.asyncio
async def test_booking_on_day_without_shift_fails(async_test_session: AsyncSession):
    """Test that booking on a day when doctor has no shift raises ShiftNotFoundError."""
    repo = ClinicRepository(async_test_session)

    spec = Specialty(code="dental", name_ar="أسنان", name_en="Dentistry")
    async_test_session.add(spec)
    await async_test_session.flush()

    doc = Doctor(specialty_id=spec.id, name_ar="د. طارق", name_en="Dr. Tarek", examination_fee=200.0)
    p1 = Patient(name="مريض", phone="01033333333")
    async_test_session.add_all([doc, p1])
    await async_test_session.commit()

    # Target date has no shift for doctor
    target_date = date(2026, 10, 17)

    with pytest.raises(ShiftNotFoundError) as exc_info:
        await repo.create_appointment(patient_id=p1.id, doctor_id=doc.id, appointment_date=target_date)

    assert "ليس لديه شفت عمل مجدول" in str(exc_info.value)


@pytest.mark.asyncio
async def test_appointment_cancellation_and_capacity_recovery(async_test_session: AsyncSession):
    """Test appointment cancellation restores available shift capacity."""
    repo = ClinicRepository(async_test_session)

    spec = Specialty(code="dental", name_ar="أسنان", name_en="Dentistry")
    async_test_session.add(spec)
    await async_test_session.flush()

    doc = Doctor(specialty_id=spec.id, name_ar="د. عمرو", name_en="Dr. Amr", examination_fee=250.0)
    async_test_session.add(doc)
    await async_test_session.flush()

    sched = DoctorSchedule(
        doctor_id=doc.id,
        day_of_week=0,
        start_time=time(16, 0),
        end_time=time(20, 0),
        max_capacity=1,
    )
    p1 = Patient(name="مريض", phone="01044444444")
    async_test_session.add_all([sched, p1])
    await async_test_session.commit()

    target_date = date(2026, 10, 17)
    apt = await repo.create_appointment(patient_id=p1.id, doctor_id=doc.id, appointment_date=target_date)

    # Initial availability: 0 remaining
    avail_before = await repo.get_doctor_availability(doc.id, target_date)
    assert avail_before.remaining_capacity == 0

    # Cancel appointment
    cancelled = await repo.cancel_appointment(apt.booking_code, reason="سفر مفاجئ للمريض")
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert "سفر مفاجئ" in (cancelled.notes or "")

    # Availability after cancellation: 1 remaining restored!
    avail_after = await repo.get_doctor_availability(doc.id, target_date)
    assert avail_after.remaining_capacity == 1
    assert avail_after.is_available is True


@pytest.mark.asyncio
async def test_clinic_database_seeder_execution():
    """Test running database seeder pipeline in both reset and idempotent modes."""
    # 1. Reset mode
    counts = await seed_clinic_database(reset=True)
    assert counts["specialties"] == 5
    assert counts["doctors"] == 10
    assert counts["schedules"] == 30

    # 2. Idempotent re-run mode (must not crash or violate constraints)
    counts_rerun = await seed_clinic_database(reset=False)
    assert counts_rerun["specialties"] == 5
    assert counts_rerun["doctors"] == 10
    assert counts_rerun["schedules"] == 30
