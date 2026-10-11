"""
Unit and Integration Tests for Clinic Relational ORM Models and Pydantic Schemas.
"""

from datetime import date, time

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.models import (
    Appointment,
    Doctor,
    DoctorSchedule,
    Patient,
    Specialty,
)
from src.db.schemas import (
    AppointmentStatus,
    DayOfWeek,
    DoctorCreate,
    DoctorTitle,
    PatientCreate,
    VisitType,
    clean_egyptian_phone,
)
from src.db.session import (
    close_db,
    get_async_session,
    get_engine,
    get_session_factory,
    init_db,
)

# ==============================================================================
# Tier 1: Unit Verification (Schemas & Enums)
# ==============================================================================


def test_enums_and_arabic_labels():
    """Verify domain enums and their Arabic / English localization helpers."""
    # DayOfWeek
    assert DayOfWeek.SATURDAY == 0
    assert DayOfWeek.SATURDAY.label_ar() == "السبت"
    assert DayOfWeek.FRIDAY.label_ar() == "الجمعة"
    assert DayOfWeek.SUNDAY.label_en() == "Sunday"

    # DoctorTitle
    assert DoctorTitle.SPECIALIST.label_ar() == "أخصائي"
    assert DoctorTitle.CONSULTANT.label_ar() == "استشاري"
    assert DoctorTitle.PROFESSOR.label_ar() == "أستاذ دكتور"

    # VisitType
    assert VisitType.EXAMINATION.label_ar() == "كشف جديد"
    assert VisitType.CONSULTATION.label_ar() == "استشارة"

    # AppointmentStatus
    assert AppointmentStatus.CONFIRMED.label_ar() == "مؤكد"
    assert AppointmentStatus.CANCELLED.label_ar() == "ملغي"


def test_egyptian_phone_validation():
    """Verify phone cleaner normalizes valid Egyptian mobiles and rejects invalid ones."""
    # Valid formats
    assert clean_egyptian_phone("01012345678") == "01012345678"
    assert clean_egyptian_phone("+201123456789") == "01123456789"
    assert clean_egyptian_phone("201212345678") == "01212345678"
    assert clean_egyptian_phone(" 015 1234 5678 ") == "01512345678"

    # Invalid formats
    with pytest.raises(ValueError):
        clean_egyptian_phone("01812345678")  # 018 is not an Egyptian mobile prefix

    with pytest.raises(ValueError):
        clean_egyptian_phone("01012345")  # Too short

    with pytest.raises(ValueError):
        clean_egyptian_phone("abcdefghijk")  # Non-digit


def test_pydantic_patient_validation():
    """Verify PatientCreate validates Egyptian phone numbers."""
    valid_patient = PatientCreate(
        name="محمود عبد الغني",
        phone="+201012345678",
        gender="male",
    )
    assert valid_patient.phone == "01012345678"

    with pytest.raises(ValidationError):
        PatientCreate(
            name="مريض تجريبي",
            phone="123456",
        )


def test_doctor_fee_validation():
    """Verify DoctorCreate rejects negative fees."""
    valid_doc = DoctorCreate(
        specialty_id=1,
        name_ar="د. سارة المنشاوي",
        name_en="Dr. Sara El-Menshawy",
        title=DoctorTitle.CONSULTANT,
        examination_fee=300.0,
        consultation_fee=150.0,
    )
    assert valid_doc.examination_fee == 300.0

    with pytest.raises(ValidationError):
        DoctorCreate(
            specialty_id=1,
            name_ar="د. أحمد",
            name_en="Dr. Ahmed",
            examination_fee=-50.0,
        )


def test_doctor_schedule_formatted_shift():
    """Verify DoctorSchedule.formatted_shift helper."""
    schedule = DoctorSchedule(
        doctor_id=1,
        day_of_week=0,
        start_time=time(18, 0),
        end_time=time(21, 30),
        max_capacity=20,
    )
    assert schedule.formatted_shift == "06:00 PM - 09:30 PM"
    assert schedule.is_active is True


# ==============================================================================
# Tier 2: Integration Verification (Schema Generation & Relationships)
# ==============================================================================


@pytest.mark.asyncio
async def test_relational_schema_creation_and_traversal():
    """Verify creating all tables, persisting entities, and traversing relationships."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    await init_db(engine=test_engine)
    test_factory = get_session_factory(engine=test_engine)

    async with get_async_session(session_factory=test_factory) as session:
        # 1. Create Specialty
        cardiology = Specialty(
            code="cardiology",
            name_ar="أمراض القلب والأوعية الدموية",
            name_en="Cardiology",
            description="فحص القلب ورسم القلب والموجات الصوتية",
        )
        session.add(cardiology)
        await session.flush()

        # 2. Create Doctor linked to Specialty
        doctor = Doctor(
            specialty_id=cardiology.id,
            name_ar="د. حسام موافي",
            name_en="Dr. Hossam Mowafy",
            title="professor",
            examination_fee=500.0,
            consultation_fee=250.0,
        )
        session.add(doctor)
        await session.flush()

        # 3. Create DoctorSchedule linked to Doctor
        schedule = DoctorSchedule(
            doctor_id=doctor.id,
            day_of_week=DayOfWeek.SATURDAY.value,
            start_time=time(18, 0),
            end_time=time(21, 0),
            max_capacity=15,
        )
        session.add(schedule)
        await session.flush()

        # 4. Create Patient
        patient = Patient(
            name="علي حسن مصطفى",
            phone="01099887766",
            gender="male",
        )
        session.add(patient)
        await session.flush()

        # 5. Create Appointment
        appointment = Appointment(
            booking_code="APT-1001",
            patient_id=patient.id,
            doctor_id=doctor.id,
            schedule_id=schedule.id,
            appointment_date=date(2026, 10, 17),
            queue_number=1,
            visit_type="examination",
            status="confirmed",
            fee=500.0,
            notes="فحص دوري لضغط الدم",
        )
        session.add(appointment)
        await session.commit()

    # Query and verify relationship traversal
    async with get_async_session(session_factory=test_factory) as session:
        result = await session.execute(
            select(Specialty).where(Specialty.code == "cardiology")
        )
        fetched_specialty = result.scalar_one()

        # Specialty -> Doctors
        assert len(fetched_specialty.doctors) == 1
        fetched_doc = fetched_specialty.doctors[0]
        assert fetched_doc.name_ar == "د. حسام موافي"
        assert fetched_doc.title == "professor"

        # Doctor -> Schedules
        assert len(fetched_doc.schedules) == 1
        fetched_sched = fetched_doc.schedules[0]
        assert fetched_sched.max_capacity == 15
        assert fetched_sched.day_of_week == 0

        # Doctor -> Appointments
        assert len(fetched_doc.appointments) == 1
        fetched_apt = fetched_doc.appointments[0]
        assert fetched_apt.booking_code == "APT-1001"
        assert fetched_apt.queue_number == 1
        assert fetched_apt.fee == 500.0

        # Appointment -> Patient
        assert fetched_apt.patient.name == "علي حسن مصطفى"
        assert fetched_apt.patient.phone == "01099887766"

    await close_db(engine=test_engine)


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_duplicate_specialty_code_rejected():
    """Verify unique constraint on Specialty.code."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    await init_db(engine=test_engine)
    test_factory = get_session_factory(engine=test_engine)

    async with get_async_session(session_factory=test_factory) as session:
        s1 = Specialty(code="pediatrics", name_ar="الأطفال", name_en="Pediatrics")
        session.add(s1)
        await session.commit()

    with pytest.raises(IntegrityError):
        async with get_async_session(session_factory=test_factory) as session:
            s2 = Specialty(code="pediatrics", name_ar="طب الأطفال التخصصي", name_en="Pediatrics 2")
            session.add(s2)
            await session.commit()

    await close_db(engine=test_engine)


@pytest.mark.asyncio
async def test_duplicate_booking_code_rejected():
    """Verify unique constraint on Appointment.booking_code."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    await init_db(engine=test_engine)
    test_factory = get_session_factory(engine=test_engine)

    # Setup parent records
    async with get_async_session(session_factory=test_factory) as session:
        spec = Specialty(code="dentistry", name_ar="الأسنان", name_en="Dentistry")
        session.add(spec)
        await session.flush()

        doc = Doctor(
            specialty_id=spec.id,
            name_ar="د. منى زكي",
            name_en="Dr. Mona Zaki",
            examination_fee=200.0,
        )
        session.add(doc)
        await session.flush()

        sched = DoctorSchedule(
            doctor_id=doc.id,
            day_of_week=1,
            start_time=time(10, 0),
            end_time=time(14, 0),
            max_capacity=10,
        )
        session.add(sched)
        await session.flush()

        p1 = Patient(name="أحمد سمير", phone="01112223334")
        p2 = Patient(name="كريم عادل", phone="01223334445")
        session.add_all([p1, p2])
        await session.commit()

        doc_id = doc.id
        sched_id = sched.id
        p1_id = p1.id
        p2_id = p2.id

    # Add first appointment
    async with get_async_session(session_factory=test_factory) as session:
        apt1 = Appointment(
            booking_code="APT-DUPLICATE",
            patient_id=p1_id,
            doctor_id=doc_id,
            schedule_id=sched_id,
            appointment_date=date(2026, 10, 18),
            queue_number=1,
        )
        session.add(apt1)
        await session.commit()

    # Attempt second appointment with same booking_code
    with pytest.raises(IntegrityError):
        async with get_async_session(session_factory=test_factory) as session:
            apt2 = Appointment(
                booking_code="APT-DUPLICATE",
                patient_id=p2_id,
                doctor_id=doc_id,
                schedule_id=sched_id,
                appointment_date=date(2026, 10, 18),
                queue_number=2,
            )
            session.add(apt2)
            await session.commit()

    await close_db(engine=test_engine)


@pytest.mark.asyncio
async def test_duplicate_queue_number_per_doctor_shift_rejected():
    """Verify unique constraint on (doctor_id, appointment_date, queue_number)."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    await init_db(engine=test_engine)
    test_factory = get_session_factory(engine=test_engine)

    async with get_async_session(session_factory=test_factory) as session:
        spec = Specialty(code="ent", name_ar="أنف وأذن", name_en="ENT")
        session.add(spec)
        await session.flush()

        doc = Doctor(
            specialty_id=spec.id,
            name_ar="د. طارق شوقي",
            name_en="Dr. Tarek Shawky",
            examination_fee=250.0,
        )
        session.add(doc)
        await session.flush()

        sched = DoctorSchedule(
            doctor_id=doc.id,
            day_of_week=2,
            start_time=time(17, 0),
            end_time=time(20, 0),
            max_capacity=10,
        )
        session.add(sched)
        await session.flush()

        p1 = Patient(name="محمد يوسف", phone="01511223344")
        p2 = Patient(name="إبراهيم خليل", phone="01055667788")
        session.add_all([p1, p2])
        await session.commit()

        doc_id = doc.id
        sched_id = sched.id
        p1_id = p1.id
        p2_id = p2.id

    # First patient gets queue number 1
    async with get_async_session(session_factory=test_factory) as session:
        apt1 = Appointment(
            booking_code="APT-Q1",
            patient_id=p1_id,
            doctor_id=doc_id,
            schedule_id=sched_id,
            appointment_date=date(2026, 10, 19),
            queue_number=1,
        )
        session.add(apt1)
        await session.commit()

    # Attempt to assign queue number 1 again to second patient for the same doctor and date
    with pytest.raises(IntegrityError):
        async with get_async_session(session_factory=test_factory) as session:
            apt2 = Appointment(
                booking_code="APT-Q2",
                patient_id=p2_id,
                doctor_id=doc_id,
                schedule_id=sched_id,
                appointment_date=date(2026, 10, 19),
                queue_number=1,  # Duplicate queue number!
            )
            session.add(apt2)
            await session.commit()

    await close_db(engine=test_engine)
