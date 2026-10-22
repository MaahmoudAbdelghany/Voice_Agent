"""
Pydantic Schemas for Egyptian Polyclinic Voice Agent Tools.

Defines strongly-typed, voice-optimized input and output contracts for:
1. Generic Tool Execution Envelope (``ToolResult``)
2. Egyptian phone normalization & colloquial Arabic date parsing
3. Doctor Availability & Shift Lookup (``check_doctor_availability``)
4. Appointment Booking with Queue Assignment (``book_appointment``)
5. Appointment Management: Lookup / Cancel / Reschedule (``manage_appointment``)
6. Clinic Knowledge Search via RAG (``search_clinic_knowledge``)
7. Human Receptionist Escalation (``transfer_to_receptionist``)

Legacy restaurant schemas were relocated to ``src.tools.legacy_schemas``.
"""

import datetime as dt
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.db.schemas import (
    AppointmentStatus,
    DayOfWeek,
    DoctorTitle,
    VisitType,
    clean_egyptian_phone,
)

# ==============================================================================
# Common & Base Tool Models
# ==============================================================================


class ToolResult(BaseModel):
    """Generic execution envelope for any tool response."""

    model_config = ConfigDict(extra="ignore")

    success: bool = Field(
        default=True,
        description="Whether the tool execution succeeded.",
    )
    message: str = Field(
        ...,
        description="Voice-friendly natural language response message.",
    )
    data: dict[str, Any] | None = Field(
        default=None,
        description="Structured payload data returned by the tool.",
    )
    error: str | None = Field(
        default=None,
        description="Error details if tool execution failed.",
    )


# ==============================================================================
# Colloquial Egyptian Arabic Date Parser
# ==============================================================================

_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")  # tashkeel + tatweel


def _normalize_arabic(text: str) -> str:
    """Normalize Arabic spelling variants for robust token matching."""
    text = _ARABIC_DIACRITICS.sub("", text.strip().lower())
    text = re.sub(r"[أإآ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي")
    text = re.sub(r"[^\w\s-]", " ", text)  # drop punctuation (؟ ، . !)
    return re.sub(r"\s+", " ", text).strip()


# Relative day offsets (keys are already normalized)
_RELATIVE_TOKENS: dict[str, int] = {
    "اليوم": 0,
    "النهارده": 0,
    "انهارده": 0,
    "today": 0,
    "بكره": 1,
    "بكرا": 1,
    "غدا": 1,
    "الغد": 1,
    "tomorrow": 1,
    "بعد بكره": 2,
    "بعد بكرا": 2,
    "بعد غد": 2,
    "بعد الغد": 2,
    "day after tomorrow": 2,
}

# Weekday names -> Python weekday() (Mon=0 .. Sun=6). Keys are normalized.
_WEEKDAY_TOKENS: dict[str, int] = {
    "السبت": 5,
    "سبت": 5,
    "saturday": 5,
    "الاحد": 6,
    "الحد": 6,
    "احد": 6,
    "sunday": 6,
    "الاثنين": 0,
    "الاتنين": 0,
    "التنين": 0,
    "اثنين": 0,
    "اتنين": 0,
    "monday": 0,
    "الثلاثاء": 1,
    "الثلاث": 1,
    "التلات": 1,
    "التلاته": 1,
    "تلات": 1,
    "tuesday": 1,
    "الاربعاء": 2,
    "الاربع": 2,
    "اربع": 2,
    "wednesday": 2,
    "الخميس": 3,
    "خميس": 3,
    "thursday": 3,
    "الجمعه": 4,
    "جمعه": 4,
    "friday": 4,
}

_LEADING_FILLERS = ("يوم ", "في ", "ف ", "on ", "next ", "الجاي ", "الجايه ")


def parse_colloquial_date(
    value: dt.date | dt.datetime | str,
    today: dt.date | None = None,
) -> dt.date:
    """
    Resolve a date from ISO strings, date objects, or colloquial Egyptian expressions.

    Supported:
      - ``datetime.date`` / ``datetime.datetime`` objects
      - ISO strings ``YYYY-MM-DD``
      - ``اليوم`` / ``النهاردة`` -> today
      - ``بكرة`` / ``غدا`` / ``غداً`` -> today + 1
      - ``بعد بكرة`` / ``بعد غد`` -> today + 2
      - Weekday names (``السبت`` .. ``الجمعة``, incl. ``التلات``) -> next occurrence
        within 7 days, where *today counts* (offset 0..6).

    Raises:
        ValueError: when the expression cannot be resolved (message guides the agent).
    """
    base = today or dt.datetime.now(tz=dt.timezone.utc).date()

    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "Date is empty or invalid. Provide YYYY-MM-DD or a colloquial day "
            "like 'النهاردة', 'بكرة', 'السبت'."
        )

    raw = value.strip()

    # 1. ISO format
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        pass

    token = _normalize_arabic(raw)
    for filler in _LEADING_FILLERS:
        if token.startswith(filler):
            token = token[len(filler) :].strip()
    for suffix in (" الجاي", " الجايه", " next"):
        if token.endswith(suffix):
            token = token[: -len(suffix)].strip()

    # 2. Relative tokens
    if token in _RELATIVE_TOKENS:
        return base + dt.timedelta(days=_RELATIVE_TOKENS[token])

    # 3. Weekday names
    if token in _WEEKDAY_TOKENS:
        offset = (_WEEKDAY_TOKENS[token] - base.weekday()) % 7
        return base + dt.timedelta(days=offset)

    raise ValueError(
        f"Could not understand date '{value}'. Ask the caller for a specific day "
        "(e.g. 'بكرة', 'يوم السبت') or a date in YYYY-MM-DD format."
    )


# ==============================================================================
# Shared Field Helpers
# ==============================================================================

_VISIT_TYPE_ALIASES: dict[str, VisitType] = {
    "examination": VisitType.EXAMINATION,
    "exam": VisitType.EXAMINATION,
    "new": VisitType.EXAMINATION,
    "كشف": VisitType.EXAMINATION,
    "كشف جديد": VisitType.EXAMINATION,
    "consultation": VisitType.CONSULTATION,
    "follow-up": VisitType.CONSULTATION,
    "followup": VisitType.CONSULTATION,
    "استشاره": VisitType.CONSULTATION,
    "اعاده": VisitType.CONSULTATION,
    "متابعه": VisitType.CONSULTATION,
}


def parse_visit_type(value: Any) -> VisitType:
    """Map English/Arabic visit-type expressions to ``VisitType``."""
    if isinstance(value, VisitType):
        return value
    if value is None:
        return VisitType.EXAMINATION
    key = _normalize_arabic(str(value))
    if key in _VISIT_TYPE_ALIASES:
        return _VISIT_TYPE_ALIASES[key]
    raise ValueError(
        f"Unknown visit type '{value}'. Use 'examination' (كشف) or 'consultation' (استشارة)."
    )


def _normalize_booking_code(value: str | None) -> str | None:
    if value is None:
        return None
    code = re.sub(r"\s+", "", str(value)).upper()
    return code or None


def _optional_phone(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return clean_egyptian_phone(str(value))


def _optional_date(value: Any) -> dt.date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return parse_colloquial_date(value)


_DATE_DESCRIPTION = (
    "Target date as YYYY-MM-DD or a colloquial Egyptian expression "
    "(e.g. 'النهاردة', 'بكرة', 'بعد بكرة', 'السبت', 'التلات')."
)


# ==============================================================================
# Domain Enums
# ==============================================================================


class ManageAppointmentAction(str, Enum):
    """Supported operations on an existing appointment."""

    LOOKUP = "lookup"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"


class HandoffUrgencyEnum(str, Enum):
    """Urgency level for receptionist escalation."""

    LOW = "low"
    MEDIUM = "medium"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class HandoffDepartmentEnum(str, Enum):
    """Clinic department receiving the escalation."""

    RECEPTION = "reception"
    NURSING = "nursing"
    BILLING = "billing"
    EMERGENCY = "emergency"


# ==============================================================================
# 1. Doctor Availability & Shift Lookup Schemas
# ==============================================================================


class DoctorAvailabilityInput(BaseModel):
    """Input for checking doctor shift hours and remaining capacity."""

    model_config = ConfigDict(extra="ignore")

    doctor_name_or_id: str | None = Field(
        default=None,
        description="Doctor name in Arabic/English (e.g. 'د. أحمد') or numeric doctor ID.",
    )
    specialty: str | None = Field(
        default=None,
        description="Specialty code (e.g. 'cardiology') or Arabic name (e.g. 'قلب', 'أطفال').",
    )
    date: dt.date | str | None = Field(
        default=None,
        description=_DATE_DESCRIPTION + " Defaults to today when omitted.",
    )

    @field_validator("doctor_name_or_id", "specialty", mode="before")
    @classmethod
    def _strip_text(cls, v: Any) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> dt.date | None:
        return _optional_date(v)

    @model_validator(mode="after")
    def _require_target(self) -> "DoctorAvailabilityInput":
        if not self.doctor_name_or_id and not self.specialty:
            raise ValueError("Provide at least one of 'doctor_name_or_id' or 'specialty'.")
        return self


class DoctorAvailabilityOutput(BaseModel):
    """Shift availability for one doctor on one date."""

    model_config = ConfigDict(extra="ignore")

    doctor_id: int = Field(description="Doctor primary key.")
    doctor_name_ar: str = Field(description="Doctor Arabic name.")
    specialty_name_ar: str = Field(description="Specialty Arabic name.")
    target_date: str = Field(description="Checked date in ISO format (YYYY-MM-DD).")
    day_name_ar: str = Field(description="Arabic weekday name (e.g. 'السبت').")
    has_shift: bool = Field(description="True if the doctor works on this date.")
    shift_hours: str | None = Field(
        default=None,
        description="Formatted shift window (e.g. '06:00 PM - 09:00 PM').",
    )
    remaining_capacity: int = Field(default=0, ge=0, description="Remaining patient slots.")
    is_available: bool = Field(description="True if the shift exists and has free slots.")
    examination_fee: float = Field(ge=0, description="New examination fee in EGP.")
    consultation_fee: float = Field(ge=0, description="Follow-up consultation fee in EGP.")
    message: str = Field(description="Spoken summary in polite Egyptian Arabic.")


# ==============================================================================
# 2. Appointment Booking Schemas
# ==============================================================================


class AppointmentBookingInput(BaseModel):
    """Input for reserving a queue slot with a doctor."""

    model_config = ConfigDict(extra="ignore")

    patient_name: str = Field(..., min_length=2, description="Patient full name.")
    patient_phone: str = Field(
        ...,
        description="Egyptian mobile number (010/011/012/015), e.g. '01012345678'.",
    )
    doctor_id: int | None = Field(default=None, ge=1, description="Doctor numeric ID.")
    doctor_name: str | None = Field(default=None, description="Doctor name if ID unknown.")
    date: dt.date | str = Field(..., description=_DATE_DESCRIPTION)
    visit_type: VisitType = Field(
        default=VisitType.EXAMINATION,
        description="'examination' (كشف جديد) or 'consultation' (استشارة / إعادة).",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Optional caller notes (administrative only, no diagnosis).",
    )

    @field_validator("patient_name", mode="before")
    @classmethod
    def _strip_name(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v

    @field_validator("patient_phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> str:
        return clean_egyptian_phone(str(v))

    @field_validator("doctor_name", mode="before")
    @classmethod
    def _strip_doctor(cls, v: Any) -> str | None:
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> dt.date:
        return parse_colloquial_date(v)

    @field_validator("visit_type", mode="before")
    @classmethod
    def _visit_type(cls, v: Any) -> VisitType:
        return parse_visit_type(v)

    @model_validator(mode="after")
    def _require_doctor(self) -> "AppointmentBookingInput":
        if self.doctor_id is None and not self.doctor_name:
            raise ValueError("Provide either 'doctor_id' or 'doctor_name'.")
        return self


class AppointmentBookingOutput(BaseModel):
    """Confirmation details of a booked appointment."""

    model_config = ConfigDict(extra="ignore")

    booking_code: str = Field(description="Unique booking code (e.g. 'APT-20261015-01003').")
    patient_name: str = Field(description="Patient name.")
    doctor_name_ar: str = Field(description="Doctor Arabic name.")
    specialty_name_ar: str = Field(description="Specialty Arabic name.")
    appointment_date: str = Field(description="Appointment date in ISO format.")
    queue_number: int = Field(ge=1, description="Queue number (نمرة الحجز).")
    shift_window: str = Field(description="Shift window (e.g. '06:00 PM - 09:00 PM').")
    visit_type_ar: str = Field(description="Arabic visit type label (كشف جديد / استشارة).")
    fee: float = Field(ge=0, description="Fee in EGP.")
    message: str = Field(description="Polite spoken confirmation including queue number.")


# ==============================================================================
# 3. Appointment Management Schemas
# ==============================================================================


class AppointmentLookupInput(BaseModel):
    """Find appointments by booking code or phone."""

    model_config = ConfigDict(extra="ignore")

    booking_code: str | None = Field(default=None, description="Booking code.")
    phone: str | None = Field(default=None, description="Patient Egyptian mobile number.")

    @field_validator("booking_code", mode="before")
    @classmethod
    def _code(cls, v: Any) -> str | None:
        return _normalize_booking_code(v)

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> str | None:
        return _optional_phone(v)

    @model_validator(mode="after")
    def _require_identifier(self) -> "AppointmentLookupInput":
        if not self.booking_code and not self.phone:
            raise ValueError("Provide either 'booking_code' or 'phone'.")
        return self


class AppointmentCancelInput(BaseModel):
    """Cancel an appointment by booking code."""

    model_config = ConfigDict(extra="ignore")

    booking_code: str = Field(..., min_length=3, description="Booking code to cancel.")
    phone: str | None = Field(default=None, description="Phone for ownership verification.")
    reason: str | None = Field(default=None, max_length=300, description="Cancellation reason.")

    @field_validator("booking_code", mode="before")
    @classmethod
    def _code(cls, v: Any) -> str:
        return _normalize_booking_code(v) or ""

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> str | None:
        return _optional_phone(v)


class AppointmentRescheduleInput(BaseModel):
    """Move an appointment to a new date."""

    model_config = ConfigDict(extra="ignore")

    booking_code: str = Field(..., min_length=3, description="Booking code to reschedule.")
    new_date: dt.date | str = Field(..., description=_DATE_DESCRIPTION)
    phone: str | None = Field(default=None, description="Phone for ownership verification.")
    reason: str | None = Field(default=None, max_length=300, description="Reschedule reason.")

    @field_validator("booking_code", mode="before")
    @classmethod
    def _code(cls, v: Any) -> str:
        return _normalize_booking_code(v) or ""

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> str | None:
        return _optional_phone(v)

    @field_validator("new_date", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> dt.date:
        return parse_colloquial_date(v)


class ManageAppointmentInput(BaseModel):
    """Unified input for lookup / cancel / reschedule of appointments."""

    model_config = ConfigDict(extra="ignore")

    action: ManageAppointmentAction = Field(
        ..., description="Operation: 'lookup', 'cancel', or 'reschedule'."
    )
    booking_code: str | None = Field(default=None, description="Booking code.")
    phone: str | None = Field(default=None, description="Patient Egyptian mobile number.")
    new_date: dt.date | str | None = Field(
        default=None, description="Required for 'reschedule'. " + _DATE_DESCRIPTION
    )
    reason: str | None = Field(default=None, max_length=300, description="Optional reason.")

    @field_validator("booking_code", mode="before")
    @classmethod
    def _code(cls, v: Any) -> str | None:
        return _normalize_booking_code(v)

    @field_validator("phone", mode="before")
    @classmethod
    def _phone(cls, v: Any) -> str | None:
        return _optional_phone(v)

    @field_validator("action", mode="before")
    @classmethod
    def _action(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("new_date", mode="before")
    @classmethod
    def _parse_date(cls, v: Any) -> dt.date | None:
        return _optional_date(v)

    @model_validator(mode="after")
    def _check_action_fields(self) -> "ManageAppointmentInput":
        if self.action == ManageAppointmentAction.LOOKUP:
            if not self.booking_code and not self.phone:
                raise ValueError("'lookup' requires 'booking_code' or 'phone'.")
        elif self.action == ManageAppointmentAction.CANCEL:
            if not self.booking_code and not self.phone:
                raise ValueError("'cancel' requires 'booking_code' or 'phone'.")
        elif (
            self.action == ManageAppointmentAction.RESCHEDULE
            and (not self.booking_code or self.new_date is None)
        ):
            raise ValueError("'reschedule' requires 'booking_code' and 'new_date'.")
        return self


class ManageAppointmentOutput(BaseModel):
    """Consolidated result for appointment management actions."""

    model_config = ConfigDict(extra="ignore")

    action: str = Field(description="Executed action.")
    status: str = Field(description="Outcome status (e.g. 'found', 'cancelled', 'not_found').")
    appointments: list[dict[str, Any]] = Field(
        default_factory=list, description="Affected or matching appointments."
    )
    message: str = Field(description="Spoken summary in polite Egyptian Arabic.")


# ==============================================================================
# 4. Clinic Knowledge Search Schemas (RAG)
# ==============================================================================


class ClinicKnowledgeSearchInput(BaseModel):
    """Input for semantic search over the clinic knowledge base."""

    model_config = ConfigDict(extra="ignore")

    query: str = Field(
        ...,
        min_length=2,
        max_length=500,
        description="Question about specialties, fees, insurance, lab preparation, address, policies.",
    )
    limit: int = Field(default=3, ge=1, le=10, description="Max snippets to retrieve.")
    score_threshold: float = Field(
        default=0.35, ge=0.0, le=1.0, description="Minimum similarity score."
    )
    category: str | None = Field(
        default=None,
        description="Optional filter (e.g. 'lab_radiology', 'insurance', 'pricing', 'specialties').",
    )


class KnowledgeChunk(BaseModel):
    """Individual chunk retrieved from the vector store."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique chunk identifier.")
    content: str = Field(description="Text content of the knowledge chunk.")
    score: float = Field(description="Similarity score of the match.")
    section: str | None = Field(default=None, description="Header section name.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra chunk metadata.")


class ClinicKnowledgeSearchOutput(BaseModel):
    """Output payload from clinic knowledge retrieval."""

    model_config = ConfigDict(extra="ignore")

    query: str = Field(description="Original search query.")
    found: bool = Field(description="True if matching snippets were found.")
    total_results: int = Field(default=0, ge=0, description="Number of results.")
    chunks: list[KnowledgeChunk] = Field(default_factory=list, description="Matching chunks.")
    context_text: str = Field(default="", description="Formatted context for LLM synthesis.")
    message: str = Field(description="Spoken summary for voice playback.")


# ==============================================================================
# 5. Human Receptionist Escalation Schemas
# ==============================================================================


class ReceptionistHandoffInput(BaseModel):
    """Input for escalating the call to front-desk staff."""

    model_config = ConfigDict(extra="ignore")

    caller_name: str | None = Field(default=None, description="Caller name if known.")
    caller_phone: str | None = Field(
        default=None,
        description="Caller phone. Normalized if valid Egyptian mobile; otherwise kept as-is.",
    )
    reason: str = Field(..., min_length=3, description="Reason for escalation.")
    department: HandoffDepartmentEnum = Field(
        default=HandoffDepartmentEnum.RECEPTION, description="Target department."
    )
    urgency: HandoffUrgencyEnum = Field(
        default=HandoffUrgencyEnum.MEDIUM, description="Urgency level."
    )
    summary: str | None = Field(
        default=None, max_length=1000, description="Brief context for the receptionist."
    )

    @field_validator("caller_phone", mode="before")
    @classmethod
    def _lenient_phone(cls, v: Any) -> str | None:
        # Escalation must never fail because of a malformed phone number.
        if v is None or str(v).strip() == "":
            return None
        try:
            return clean_egyptian_phone(str(v))
        except ValueError:
            return str(v).strip()

    @field_validator("department", "urgency", mode="before")
    @classmethod
    def _lower_enum(cls, v: Any) -> Any:
        return v.strip().lower() if isinstance(v, str) else v


class ReceptionistHandoffOutput(BaseModel):
    """Confirmation of a receptionist escalation ticket."""

    model_config = ConfigDict(extra="ignore")

    ticket_id: str = Field(description="Unique escalation ticket ID.")
    status: str = Field(default="queued", description="'queued', 'transferred', or 'callback'.")
    urgency: str = Field(description="Urgency level.")
    department: str = Field(description="Assigned department.")
    estimated_wait_seconds: int = Field(default=30, ge=0, description="Estimated wait in seconds.")
    message: str = Field(description="Comforting, polite reassurance in Egyptian Arabic.")


__all__ = [
    "AppointmentBookingInput",
    "AppointmentBookingOutput",
    "AppointmentCancelInput",
    "AppointmentLookupInput",
    "AppointmentRescheduleInput",
    "AppointmentStatus",
    "ClinicKnowledgeSearchInput",
    "ClinicKnowledgeSearchOutput",
    "DayOfWeek",
    "DoctorAvailabilityInput",
    "DoctorAvailabilityOutput",
    "DoctorTitle",
    "HandoffDepartmentEnum",
    "HandoffUrgencyEnum",
    "KnowledgeChunk",
    "ManageAppointmentAction",
    "ManageAppointmentInput",
    "ManageAppointmentOutput",
    "ReceptionistHandoffInput",
    "ReceptionistHandoffOutput",
    "ToolResult",
    "VisitType",
    "clean_egyptian_phone",
    "parse_colloquial_date",
    "parse_visit_type",
]
