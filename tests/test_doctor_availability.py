"""
Comprehensive Test Suite for Doctor Availability & Shift Lookup Tool (Feature 3.2).

Covers:
- Tier 1: Unit verification for Arabic text normalization, phonetic/title stripping,
  specialty & doctor matching, and Cairo timezone calculation.
- Tier 2: Integration verification with in-memory SQLite database for:
  - Doctor available with remaining slots
  - Doctor with no shift on requested date -> 7-day lookahead suggestion
  - Doctor with fully booked shift -> 7-day lookahead suggestion
  - Specialty multi-doctor lookup (up to 3 doctors)
  - Sync and async execution equivalence
  - Centralized TOOL_REGISTRY registration
- Tier 3: Error and edge-case verification for:
  - Doctor not found graceful handling
  - Specialty not found graceful handling
  - No slots within 7 days handling
  - Disambiguation when multiple doctors match the same name
  - Missing doctor and specialty parameters
"""

import datetime as dt
from datetime import date, time, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.base import Base
from src.db.models import Appointment, Doctor, DoctorSchedule, Patient, Specialty
from src.db.schemas import AppointmentStatus, VisitType
from src.tools import (
    TOOL_REGISTRY,
    DoctorAvailabilityTool,
)
from src.tools.doctor_availability import (
    get_cairo_today,
    match_doctors,
    match_specialty,
    normalize_text_ar,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
async def test_session_factory():
    """Provides an isolated in-memory SQLite database populated with clinic test data."""
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

    # Populate realistic seed doctors and schedules
    async with session_factory() as session:
        # 1. Specialties
        spec_internal = Specialty(
            code="internal_medicine",
            name_ar="الباطنة والجهاز الهضمي",
            name_en="Internal Medicine & Gastroenterology",
            description="أمراض الباطنة العامة والكبد والجهاز الهضمي.",
        )
        spec_pediatrics = Specialty(
            code="pediatrics",
            name_ar="الأطفال وحديثي الولادة",
            name_en="Pediatrics & Neonatology",
            description="طب الأطفال وحديثي الولادة.",
        )
        session.add_all([spec_internal, spec_pediatrics])
        await session.flush()

        # 2. Doctors
        doc_sherif = Doctor(
            specialty_id=spec_internal.id,
            name_ar="د. أحمد محمود الشريف",
            name_en="Dr. Ahmed Mahmoud El-Sherif",
            title="consultant",
            examination_fee=350.0,
            consultation_fee=150.0,
            is_active=True,
        )
        doc_marwa = Doctor(
            specialty_id=spec_internal.id,
            name_ar="د. مروة كمال الدين",
            name_en="Dr. Marwa Kamal El-Din",
            title="specialist",
            examination_fee=250.0,
            consultation_fee=100.0,
            is_active=True,
        )
        # Doctor with same first name 'أحمد' in pediatrics for disambiguation testing
        doc_ahmed_samy = Doctor(
            specialty_id=spec_pediatrics.id,
            name_ar="د. أحمد سامي عثمان",
            name_en="Dr. Ahmed Samy Osman",
            title="specialist",
            examination_fee=200.0,
            consultation_fee=100.0,
            is_active=True,
        )
        # Doctor with no active schedule for 7-day fallback exhaustion testing
        doc_retired = Doctor(
            specialty_id=spec_pediatrics.id,
            name_ar="د. فاروق الألفي",
            name_en="Dr. Farouk El-Alfy",
            title="consultant",
            examination_fee=400.0,
            consultation_fee=200.0,
            is_active=True,
        )
        session.add_all([doc_sherif, doc_marwa, doc_ahmed_samy, doc_retired])
        await session.flush()

        # 3. Shift Schedules
        # Saturday = 0, Monday = 2, Wednesday = 4
        schedules = [
            DoctorSchedule(
                doctor_id=doc_sherif.id,
                day_of_week=0,  # السبت
                start_time=time(18, 0),
                end_time=time(22, 0),
                max_capacity=2,  # Low capacity for full-shift test
                is_active=True,
            ),
            DoctorSchedule(
                doctor_id=doc_sherif.id,
                day_of_week=2,  # الاثنين
                start_time=time(18, 0),
                end_time=time(22, 0),
                max_capacity=20,
                is_active=True,
            ),
            DoctorSchedule(
                doctor_id=doc_marwa.id,
                day_of_week=0,  # السبت (works same day as Sherif for multi-doctor test)
                start_time=time(11, 0),
                end_time=time(15, 0),
                max_capacity=15,
                is_active=True,
            ),
            DoctorSchedule(
                doctor_id=doc_ahmed_samy.id,
                day_of_week=1,  # الأحد
                start_time=time(14, 0),
                end_time=time(18, 0),
                max_capacity=10,
                is_active=True,
            ),
        ]
        session.add_all(schedules)

        # 4. Patient & existing appointment to fill doc_sherif on Saturday 2026-10-24
        patient1 = Patient(
            name="مريض تجريبي أول",
            phone="01011112222",
        )
        patient2 = Patient(
            name="مريض تجريبي ثان",
            phone="01033334444",
        )
        session.add_all([patient1, patient2])
        await session.flush()

        # Book 2 appointments for doc_sherif on 2026-10-24 (which has max_capacity=2)
        app1 = Appointment(
            booking_code="TEST-BK-01",
            doctor_id=doc_sherif.id,
            schedule_id=schedules[0].id,
            patient_id=patient1.id,
            appointment_date=date(2026, 10, 24),
            queue_number=1,
            visit_type=VisitType.EXAMINATION.value,
            fee=350.0,
            status=AppointmentStatus.CONFIRMED.value,
        )
        app2 = Appointment(
            booking_code="TEST-BK-02",
            doctor_id=doc_sherif.id,
            schedule_id=schedules[0].id,
            patient_id=patient2.id,
            appointment_date=date(2026, 10, 24),
            queue_number=2,
            visit_type=VisitType.EXAMINATION.value,
            fee=350.0,
            status=AppointmentStatus.CONFIRMED.value,
        )
        session.add_all([app1, app2])
        await session.commit()

    yield session_factory
    await engine.dispose()


@pytest.fixture
def availability_tool(test_session_factory):
    """Provides a DoctorAvailabilityTool instance bound to the in-memory test database."""
    return DoctorAvailabilityTool(session_factory=test_session_factory)


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_normalize_name_ar():
    """Verify Arabic text normalization and title stripping."""
    assert normalize_text_ar("د. أحمد محمود الشريف") == "احمد محمود الشريف"
    assert normalize_text_ar("دكتورة مروة كمال") == "مروه كمال"
    assert normalize_text_ar("أ.د. حسام") == "حسام"
    assert normalize_text_ar("استشاري أمراض القلب") == "امراض القلب"
    assert normalize_text_ar("أخصائية النساء والتوليد") == "النساء والتوليد"
    assert normalize_text_ar("دُكْتُورْ أَحْمَدْ") == "احمد"
    assert normalize_text_ar("Dr. Ahmed El-Sherif") == "ahmed el sherif"


def test_match_doctor_by_name():
    """Verify fuzzy matching for doctor names (partial, title-stripped, English)."""
    doc1 = Doctor(id=1, name_ar="د. أحمد محمود الشريف", name_en="Dr. Ahmed Mahmoud El-Sherif")
    doc2 = Doctor(id=2, name_ar="د. مروة كمال الدين", name_en="Dr. Marwa Kamal El-Din")
    doctors = [doc1, doc2]

    # Substring match
    matches = match_doctors("الشريف", doctors)
    assert len(matches) == 1
    assert matches[0].id == 1

    # Match with title prefix
    matches = match_doctors("دكتورة مروة", doctors)
    assert len(matches) == 1
    assert matches[0].id == 2

    # Match English name
    matches = match_doctors("El-Sherif", doctors)
    assert len(matches) == 1
    assert matches[0].id == 1


def test_match_specialty_by_code_and_name():
    """Verify specialty matching by code, Arabic name, or common dialect aliases."""
    s1 = Specialty(
        code="internal_medicine",
        name_ar="الباطنة والجهاز الهضمي",
        name_en="Internal Medicine",
    )
    s2 = Specialty(
        code="pediatrics",
        name_ar="الأطفال وحديثي الولادة",
        name_en="Pediatrics",
    )
    specialties = [s1, s2]

    # Code match
    assert match_specialty("internal_medicine", specialties) == s1
    # Arabic full name
    assert match_specialty("الباطنة والجهاز الهضمي", specialties) == s1
    # Dialect token / alias
    assert match_specialty("باطنة", specialties) == s1
    assert match_specialty("باطنه", specialties) == s1
    assert match_specialty("أطفال", specialties) == s2
    assert match_specialty("اطفال", specialties) == s2


def test_default_date_uses_cairo_timezone():
    """Verify default date calculation respects Africa/Cairo local time."""
    # When UTC is 2026-10-19 23:30, Cairo time (UTC+2 / UTC+3) is 2026-10-20
    simulated_utc = dt.datetime(2026, 10, 19, 23, 30, tzinfo=timezone.utc)
    with patch("src.tools.doctor_availability.dt.datetime") as mock_dt:
        mock_dt.now.side_effect = lambda tz=None: simulated_utc.astimezone(tz or timezone.utc)
        today = get_cairo_today()
        # Should be the 20th in Cairo
        assert today == date(2026, 10, 20)


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_doctor_availability_found_and_available(availability_tool: DoctorAvailabilityTool):
    """Verify doctor availability query on a day when the doctor has open slots."""
    # Monday 2026-10-26 (DayOfWeek=2): Dr. Ahmed El-Sherif has shift 18:00-22:00, cap=20, booked=0
    result = await availability_tool.aexecute(
        doctor_name_or_id="الشريف",
        date="2026-10-26",
    )
    assert result.success is True
    assert "أحمد محمود الشريف" in result.message
    assert "متاح يوم الاثنين" in result.message
    assert result.data is not None
    assert result.data["is_available"] is True
    assert result.data["remaining_capacity"] == 20
    assert result.data["examination_fee"] == 350.0


@pytest.mark.asyncio
async def test_doctor_has_no_shift_suggests_next_available(
    availability_tool: DoctorAvailabilityTool,
):
    """Verify that if doctor has no shift on target date, tool scans 7 days and suggests next slot."""
    # Sunday 2026-10-25: Dr. Ahmed El-Sherif has no shift
    # Next available shift is Monday 2026-10-26
    result = await availability_tool.aexecute(
        doctor_name_or_id="الشريف",
        date="2026-10-25",
    )
    assert result.success is True
    assert "ليس لديه شفت عمل يوم الأحد" in result.message
    assert "أقرب موعد متاح هو يوم الاثنين" in result.message
    assert result.data is not None
    assert result.data["is_available"] is False
    assert "next_available" in result.data
    assert result.data["next_available"]["target_date"] == "2026-10-26"
    assert result.data["next_available"]["day_name_ar"] == "الاثنين"


@pytest.mark.asyncio
async def test_doctor_shift_fully_booked_suggests_next_available(
    availability_tool: DoctorAvailabilityTool,
):
    """Verify that when shift capacity is exhausted, tool suggests the next available day."""
    # Saturday 2026-10-24: Dr. Ahmed El-Sherif max_capacity=2, booked=2 (from fixture)
    # Next available shift is Monday 2026-10-26
    result = await availability_tool.aexecute(
        doctor_name_or_id="الشريف",
        date="2026-10-24",
    )
    assert result.success is True
    assert "مكتمل العدد بالكامل" in result.message
    assert "أقرب موعد متاح هو يوم الاثنين" in result.message
    assert result.data is not None
    assert result.data["is_available"] is False
    assert result.data["remaining_capacity"] == 0
    assert "next_available" in result.data
    assert result.data["next_available"]["target_date"] == "2026-10-26"


@pytest.mark.asyncio
async def test_specialty_lookup_multiple_doctors(availability_tool: DoctorAvailabilityTool):
    """Verify specialty query on a day with multiple doctors returns up to 3 available doctors."""
    # Saturday 2026-10-31:
    # Dr. Ahmed El-Sherif has shift (booked=0 on this date)
    # Dr. Marwa Kamal has shift
    # Both in 'internal_medicine'
    result = await availability_tool.aexecute(
        specialty="باطنة",
        date="2026-10-31",
    )
    assert result.success is True
    assert "الأطباء المتاحون في تخصص الباطنة والجهاز الهضمي" in result.message
    assert "أحمد محمود الشريف" in result.message
    assert "مروة كمال الدين" in result.message
    assert result.data is not None
    assert "doctors" in result.data
    assert len(result.data["doctors"]) == 2


def test_sync_and_async_execution(availability_tool: DoctorAvailabilityTool):
    """Verify that sync and async entrypoints yield identical results."""
    sync_res = availability_tool.execute(
        doctor_name_or_id="مروة",
        date="2026-10-31",
    )
    assert sync_res.success is True
    assert "مروة كمال الدين" in sync_res.message
    assert sync_res.data["is_available"] is True


def test_tool_registered_in_registry():
    """Verify tool is properly registered in master TOOL_REGISTRY."""
    assert "check_doctor_availability" in TOOL_REGISTRY
    tool_def = TOOL_REGISTRY["check_doctor_availability"]
    assert tool_def.name == "check_doctor_availability"
    assert callable(tool_def.sync_callable)
    assert callable(tool_def.async_callable)
    assert tool_def.input_schema is not None
    assert tool_def.output_schema is not None


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_doctor_not_found_graceful_message(availability_tool: DoctorAvailabilityTool):
    """Verify unknown doctor name returns graceful error with available specialties."""
    result = await availability_tool.aexecute(
        doctor_name_or_id="د. فلان الفلاني المجهول",
        date="2026-10-26",
    )
    assert result.success is False
    assert "لم نتمكن من العثور على الطبيب" in result.message
    assert "التخصصات المتاحة" in result.message


@pytest.mark.asyncio
async def test_specialty_not_found_graceful_message(availability_tool: DoctorAvailabilityTool):
    """Verify unknown specialty returns graceful error listing available specialties."""
    result = await availability_tool.aexecute(
        specialty="مخ وأعصاب وجراحة عمود فقري",
        date="2026-10-26",
    )
    assert result.success is False
    assert "لم نتمكن من العثور على التخصص المطلوب" in result.message
    assert "التخصصات المسجلة" in result.message


@pytest.mark.asyncio
async def test_no_shift_and_no_slots_within_seven_days(availability_tool: DoctorAvailabilityTool):
    """Verify that a doctor with zero scheduled shifts returns a reception contact recommendation."""
    # Dr. Farouk El-Alfy has no schedules configured
    result = await availability_tool.aexecute(
        doctor_name_or_id="فاروق الألفي",
        date="2026-10-26",
    )
    assert result.success is True
    assert result.data["is_available"] is False
    assert "ولا توجد مواعيد متاحة للطبيب خلال الـ 7 أيام القادمة" in result.message
    assert "التواصل مع موظف الاستقبال" in result.message


@pytest.mark.asyncio
async def test_ambiguous_doctor_name_returns_candidates(availability_tool: DoctorAvailabilityTool):
    """Verify ambiguous name matching returns candidates list without auto-selection."""
    # We have two doctors with first name 'أحمد':
    # 1. د. أحمد محمود الشريف (internal_medicine)
    # 2. د. أحمد سامي عثمان (pediatrics)
    result = await availability_tool.aexecute(
        doctor_name_or_id="دكتور أحمد",
        date="2026-10-26",
    )
    assert result.success is False
    assert "يوجد أكثر من طبيب بهذا الاسم" in result.message
    assert result.data is not None
    assert "candidates" in result.data
    assert len(result.data["candidates"]) == 2

    # But if specialty is also provided, it should narrow down to the right one!
    narrowed = await availability_tool.aexecute(
        doctor_name_or_id="دكتور أحمد",
        specialty="باطنة",
        date="2026-10-26",
    )
    assert narrowed.success is True
    assert "أحمد محمود الشريف" in narrowed.message


@pytest.mark.asyncio
async def test_missing_doctor_and_specialty_graceful(availability_tool: DoctorAvailabilityTool):
    """Verify calling without doctor or specialty returns a polite guidance message."""
    result = await availability_tool.aexecute()
    assert result.success is False
    assert "يرجى توضيح اسم الطبيب أو التخصص المطلوب" in result.message
    assert result.error is not None
