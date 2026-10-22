"""
Automated Unit and Contract Tests for Clinic Domain Tool Schemas.

Covers Feature 3.1:
- Tier 1: Unit tests for ToolResult, normalizers, and all clinic domain models
- Tier 2: Integration / Function Calling JSON Schema generation
- Tier 3: Edge cases, invalid inputs, and defensive tolerances
"""

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from src.db.schemas import VisitType, clean_egyptian_phone
from src.tools.schemas import (
    AppointmentBookingInput,
    AppointmentBookingOutput,
    AppointmentCancelInput,
    AppointmentLookupInput,
    AppointmentRescheduleInput,
    ClinicKnowledgeSearchInput,
    ClinicKnowledgeSearchOutput,
    DoctorAvailabilityInput,
    DoctorAvailabilityOutput,
    HandoffDepartmentEnum,
    HandoffUrgencyEnum,
    KnowledgeChunk,
    ManageAppointmentAction,
    ManageAppointmentInput,
    ManageAppointmentOutput,
    ReceptionistHandoffInput,
    ReceptionistHandoffOutput,
    ToolResult,
    parse_colloquial_date,
    parse_visit_type,
)

# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================

def test_tool_result_envelope():
    """Verify ToolResult envelope serialization with payload."""
    res = ToolResult(
        success=True,
        message="تم العثور على المواعيد المتاحة بنجاح.",
        data={"slots": 3},
    )
    assert res.success is True
    assert "بنجاح" in res.message
    assert res.data == {"slots": 3}
    assert res.error is None

    err_res = ToolResult(
        success=False,
        message="حدث خطأ أثناء البحث.",
        error="Doctor not found",
    )
    assert err_res.success is False
    assert err_res.error == "Doctor not found"


def test_egyptian_phone_normalizer():
    """Verify normalization of Egyptian mobile formats (010, 011, 012, 015)."""
    assert clean_egyptian_phone("01012345678") == "01012345678"
    assert clean_egyptian_phone("+201123456789") == "01123456789"
    assert clean_egyptian_phone("00201234567890") == "01234567890"
    assert clean_egyptian_phone("201501234567") == "01501234567"
    assert clean_egyptian_phone(" 010-1234-5678 ") == "01012345678"


def test_colloquial_date_parser():
    """Verify colloquial Egyptian expressions relative to a fixed base date."""
    base = dt.date(2026, 10, 20)  # Tuesday (weekday() == 1)

    # Relative tokens
    assert parse_colloquial_date("النهاردة", today=base) == base
    assert parse_colloquial_date("اليوم", today=base) == base
    assert parse_colloquial_date("بكرة", today=base) == dt.date(2026, 10, 21)
    assert parse_colloquial_date("غداً", today=base) == dt.date(2026, 10, 21)
    assert parse_colloquial_date("بعد بكرة", today=base) == dt.date(2026, 10, 22)
    assert parse_colloquial_date("بعد غد", today=base) == dt.date(2026, 10, 22)

    # Colloquial Egyptian weekdays
    assert parse_colloquial_date("السبت", today=base) == dt.date(2026, 10, 24)
    assert parse_colloquial_date("التلات", today=base) == dt.date(2026, 10, 20)  # Same day
    assert parse_colloquial_date("يوم الأربع", today=base) == dt.date(2026, 10, 21)
    assert parse_colloquial_date("الخميس الجاي", today=base) == dt.date(2026, 10, 22)

    # ISO format string
    assert parse_colloquial_date("2026-11-15", today=base) == dt.date(2026, 11, 15)

    # Python date and datetime objects
    assert parse_colloquial_date(base) == base
    assert (
        parse_colloquial_date(dt.datetime(2026, 10, 25, 14, 30, tzinfo=dt.timezone.utc))
        == dt.date(2026, 10, 25)
    )


def test_parse_visit_type():
    """Verify mapping of Arabic and English aliases to VisitType enum."""
    assert parse_visit_type("كشف") == VisitType.EXAMINATION
    assert parse_visit_type("كشف جديد") == VisitType.EXAMINATION
    assert parse_visit_type("examination") == VisitType.EXAMINATION
    assert parse_visit_type("استشارة") == VisitType.CONSULTATION
    assert parse_visit_type("إعادة") == VisitType.CONSULTATION
    assert parse_visit_type("consultation") == VisitType.CONSULTATION
    assert parse_visit_type(None) == VisitType.EXAMINATION


def test_doctor_availability_schemas():
    """Verify input parsing and output structure for availability queries."""
    inp = DoctorAvailabilityInput(
        doctor_name_or_id="د. أحمد الشريف",
        date="بكرة",
    )
    assert inp.doctor_name_or_id == "د. أحمد الشريف"
    assert isinstance(inp.date, dt.date)

    inp_spec = DoctorAvailabilityInput(
        specialty="cardiology",
        date="2026-11-01",
    )
    assert inp_spec.specialty == "cardiology"
    assert inp_spec.date == dt.date(2026, 11, 1)

    out = DoctorAvailabilityOutput(
        doctor_id=1,
        doctor_name_ar="د. أحمد محمود الشريف",
        specialty_name_ar="الباطنة والجهاز الهضمي",
        target_date="2026-10-21",
        day_name_ar="الأربعاء",
        has_shift=True,
        shift_hours="06:00 PM - 10:00 PM",
        remaining_capacity=5,
        is_available=True,
        examination_fee=350.0,
        consultation_fee=150.0,
        message="د. أحمد متاح غداً الأربعاء من 6 إلى 10 مساءً ومتبقي 5 أماكن.",
    )
    assert out.doctor_id == 1
    assert out.is_available is True
    assert out.remaining_capacity == 5


def test_appointment_booking_schemas():
    """Verify booking input normalization and output confirmation."""
    inp = AppointmentBookingInput(
        patient_name="  محمد علي أحمد  ",
        patient_phone="+20 100 555 4433",
        doctor_id=1,
        date="السبت",
        visit_type="استشارة",
        notes="متابعة تحاليل السكر",
    )
    assert inp.patient_name == "محمد علي أحمد"
    assert inp.patient_phone == "01005554433"
    assert isinstance(inp.date, dt.date)
    assert inp.visit_type == VisitType.CONSULTATION

    out = AppointmentBookingOutput(
        booking_code="APT-20261024-01004",
        patient_name=inp.patient_name,
        doctor_name_ar="د. أحمد الشريف",
        specialty_name_ar="باطنة",
        appointment_date="2026-10-24",
        queue_number=4,
        shift_window="06:00 PM - 10:00 PM",
        visit_type_ar="استشارة",
        fee=150.0,
        message="تم تأكيد حجزك مع د. أحمد الشريف بنمرة 4.",
    )
    assert out.booking_code == "APT-20261024-01004"
    assert out.queue_number == 4


def test_appointment_management_schemas():
    """Verify individual and unified appointment management models."""
    # Lookup by phone
    lookup_p = AppointmentLookupInput(phone="01122334455")
    assert lookup_p.phone == "01122334455"
    assert lookup_p.booking_code is None

    # Lookup by booking code
    lookup_c = AppointmentLookupInput(booking_code=" apt-20261020-01 ")
    assert lookup_c.booking_code == "APT-20261020-01"

    # Cancel
    cancel = AppointmentCancelInput(
        booking_code="APT-100",
        reason="سفر طارئ",
    )
    assert cancel.booking_code == "APT-100"
    assert cancel.reason == "سفر طارئ"

    # Reschedule
    resched = AppointmentRescheduleInput(
        booking_code="APT-100",
        new_date="بعد بكرة",
    )
    assert resched.booking_code == "APT-100"
    assert isinstance(resched.new_date, dt.date)

    # Unified ManageAppointmentInput
    mgmt_lookup = ManageAppointmentInput(
        action=ManageAppointmentAction.LOOKUP,
        phone="01234567890",
    )
    assert mgmt_lookup.action == ManageAppointmentAction.LOOKUP

    mgmt_cancel = ManageAppointmentInput(
        action="cancel",
        booking_code="APT-999",
    )
    assert mgmt_cancel.action == ManageAppointmentAction.CANCEL

    mgmt_resched = ManageAppointmentInput(
        action="reschedule",
        booking_code="APT-999",
        new_date="2026-11-05",
    )
    assert mgmt_resched.action == ManageAppointmentAction.RESCHEDULE
    assert mgmt_resched.new_date == dt.date(2026, 11, 5)

    out = ManageAppointmentOutput(
        action="reschedule",
        status="rescheduled",
        appointments=[{"booking_code": "APT-999", "new_queue": 2}],
        message="تم تعديل موعدك بنجاح.",
    )
    assert out.status == "rescheduled"


def test_clinic_knowledge_search_schemas():
    """Verify clinic RAG search input and output with chunks."""
    inp = ClinicKnowledgeSearchInput(
        query="ما هي شروط تحليل السكر الصائم؟",
        limit=2,
        category="lab_radiology",
    )
    assert inp.query == "ما هي شروط تحليل السكر الصائم؟"
    assert inp.limit == 2
    assert inp.category == "lab_radiology"

    chunk = KnowledgeChunk(
        id="chunk-1",
        content="الصيام من 8 إلى 10 ساعات قبل سحب العينة.",
        score=0.88,
        section="تعليمات التحاليل",
    )
    out = ClinicKnowledgeSearchOutput(
        query=inp.query,
        found=True,
        total_results=1,
        chunks=[chunk],
        context_text=chunk.content,
        message="تحليل السكر الصائم يتطلب صيام 8 إلى 10 ساعات.",
    )
    assert out.found is True
    assert len(out.chunks) == 1
    assert out.chunks[0].score == 0.88


def test_receptionist_handoff_schemas():
    """Verify human receptionist escalation input and ticket output."""
    inp = ReceptionistHandoffInput(
        caller_name="سارة محمود",
        caller_phone="01512345678",
        reason="المريض يشتكي من دوار شديد مفاجئ",
        department=HandoffDepartmentEnum.EMERGENCY,
        urgency=HandoffUrgencyEnum.EMERGENCY,
        summary="طلب تحويل فوري للطوارئ الطبية",
    )
    assert inp.caller_name == "سارة محمود"
    assert inp.department == HandoffDepartmentEnum.EMERGENCY
    assert inp.urgency == HandoffUrgencyEnum.EMERGENCY

    out = ReceptionistHandoffOutput(
        ticket_id="TICKET-2026-008",
        status="queued",
        urgency="emergency",
        department="emergency",
        estimated_wait_seconds=0,
        message="جاري تحويل حضرتك لمسؤول الاستقبال فوراً، خليك معايا لحظة.",
    )
    assert out.ticket_id == "TICKET-2026-008"
    assert out.estimated_wait_seconds == 0


# ==============================================================================
# Tier 2: Integration Verification (Function Calling Schemas & Tolerance)
# ==============================================================================

def test_tool_json_schema_generation():
    """Verify that all tool inputs generate valid OpenAPI / JSON Schema without error."""
    tool_inputs = [
        DoctorAvailabilityInput,
        AppointmentBookingInput,
        AppointmentLookupInput,
        AppointmentCancelInput,
        AppointmentRescheduleInput,
        ManageAppointmentInput,
        ClinicKnowledgeSearchInput,
        ReceptionistHandoffInput,
    ]

    for model_cls in tool_inputs:
        schema = model_cls.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema
        # Validate that json.dumps serializes cleanly
        json_str = json.dumps(schema)
        assert len(json_str) > 50


def test_extra_arguments_tolerance():
    """Verify extra LLM hallucinated arguments are ignored without error."""
    inp = DoctorAvailabilityInput(
        specialty="orthopedics",
        date="2026-10-25",
        hallucinated_param="extra_value",
        confidence_score=0.99,
    )
    assert inp.specialty == "orthopedics"
    assert not hasattr(inp, "hallucinated_param")


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================

def test_invalid_phone_rejection():
    """Reject invalid Egyptian mobile numbers."""
    with pytest.raises(ValueError, match="Invalid Egyptian mobile"):
        clean_egyptian_phone("022345678")  # Landline Cairo prefix

    with pytest.raises(ValueError, match="Invalid Egyptian mobile"):
        clean_egyptian_phone("01312345678")  # Invalid network prefix (013 is Benha landline)

    with pytest.raises(ValidationError):
        AppointmentBookingInput(
            patient_name="علي مصطفى",
            patient_phone="12345",  # Too short
            doctor_id=1,
            date="بكرة",
        )


def test_invalid_colloquial_date_rejection():
    """Reject nonsensical or unsupported date expressions."""
    with pytest.raises(ValueError, match="Could not understand date"):
        parse_colloquial_date("في الصيف القادم")

    with pytest.raises(ValueError, match="Could not understand date"):
        parse_colloquial_date("مشمش")


def test_doctor_availability_requires_target():
    """Assert DoctorAvailabilityInput requires either doctor or specialty."""
    with pytest.raises(ValidationError, match="Provide at least one"):
        DoctorAvailabilityInput(date="بكرة")


def test_booking_validation_missing_patient():
    """Assert booking requires patient name with min length 2."""
    with pytest.raises(ValidationError):
        AppointmentBookingInput(
            patient_name="A",  # Too short
            patient_phone="01012345678",
            doctor_id=1,
            date="بكرة",
        )


def test_manage_appointment_requires_identifier():
    """Assert lookup requires booking_code or phone."""
    with pytest.raises(ValidationError, match="requires 'booking_code' or 'phone'"):
        ManageAppointmentInput(action=ManageAppointmentAction.LOOKUP)

    with pytest.raises(ValidationError, match="'cancel' requires 'booking_code' or 'phone'"):
        ManageAppointmentInput(action=ManageAppointmentAction.CANCEL)

    valid_cancel_phone = ManageAppointmentInput(
        action=ManageAppointmentAction.CANCEL,
        phone="01012345678",
    )
    assert valid_cancel_phone.phone == "01012345678"

    with pytest.raises(ValidationError, match="'reschedule' requires 'booking_code' and 'new_date'"):
        ManageAppointmentInput(
            action=ManageAppointmentAction.RESCHEDULE,
            booking_code="APT-1",
        )

