"""
Pydantic Schemas and Enums for Clinic Domain.

Provides typed Enums, request/response DTOs, and input validation
for Specialties, Doctors, Schedules, Patients, and Appointments.
"""

import re
from datetime import date, datetime, time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ==============================================================================
# Domain Enums
# ==============================================================================


class DayOfWeek(int, Enum):
    """Egyptian clinic week: Saturday (0) through Friday (6)."""

    SATURDAY = 0
    SUNDAY = 1
    MONDAY = 2
    TUESDAY = 3
    WEDNESDAY = 4
    THURSDAY = 5
    FRIDAY = 6

    def label_ar(self) -> str:
        names = {
            0: "السبت",
            1: "الأحد",
            2: "الاثنين",
            3: "الثلاثاء",
            4: "الأربعاء",
            5: "الخميس",
            6: "الجمعة",
        }
        return names.get(self.value, "")

    def label_en(self) -> str:
        names = {
            0: "Saturday",
            1: "Sunday",
            2: "Monday",
            3: "Tuesday",
            4: "Wednesday",
            5: "Thursday",
            6: "Friday",
        }
        return names.get(self.value, "")

    @classmethod
    def from_date(cls, d: date) -> "DayOfWeek":
        """Convert a standard Python date to Egyptian DayOfWeek (0=Saturday..6=Friday)."""
        # Python weekday: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        # Egyptian DayOfWeek: Sat=0, Sun=1, Mon=2, Tue=3, Wed=4, Thu=5, Fri=6
        val = (d.weekday() + 2) % 7
        return cls(val)


class DoctorTitle(str, Enum):
    """Medical professional hierarchy."""

    SPECIALIST = "specialist"      # أخصائي
    CONSULTANT = "consultant"      # استشاري
    PROFESSOR = "professor"        # أستاذ دكتور

    def label_ar(self) -> str:
        labels = {
            "specialist": "أخصائي",
            "consultant": "استشاري",
            "professor": "أستاذ دكتور",
        }
        return labels.get(self.value, self.value)


class VisitType(str, Enum):
    """Clinic visit categorization."""

    EXAMINATION = "examination"    # كشف جديد
    CONSULTATION = "consultation"  # استشارة / إعادة

    def label_ar(self) -> str:
        labels = {
            "examination": "كشف جديد",
            "consultation": "استشارة",
        }
        return labels.get(self.value, self.value)


class AppointmentStatus(str, Enum):
    """Lifecycle status of a patient appointment."""

    CONFIRMED = "confirmed"        # مؤكد
    COMPLETED = "completed"        # تم الكشف
    CANCELLED = "cancelled"        # ملغي
    NO_SHOW = "no_show"            # لم يحضر

    def label_ar(self) -> str:
        labels = {
            "confirmed": "مؤكد",
            "completed": "تم الكشف",
            "cancelled": "ملغي",
            "no_show": "لم يحضر",
        }
        return labels.get(self.value, self.value)


# ==============================================================================
# Helper Validators
# ==============================================================================


def clean_egyptian_phone(phone: str) -> str:
    """Normalize and validate Egyptian mobile numbers (010, 011, 012, 015)."""
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone.strip())
    pattern = r"^(?:\+?20|0)?(1[0125]\d{8})$"
    match = re.match(pattern, cleaned)
    if not match:
        raise ValueError(
            f"Invalid Egyptian mobile number: '{phone}'. Must be a valid 11-digit mobile (010, 011, 012, 015)."
        )
    return f"0{match.group(1)}"


# ==============================================================================
# Specialty Schemas
# ==============================================================================


class SpecialtyBase(BaseModel):
    code: str = Field(..., description="Unique slug/code (e.g. cardiology)")
    name_ar: str = Field(..., description="Arabic name (e.g. أمراض القلب)")
    name_en: str = Field(..., description="English name (e.g. Cardiology)")
    description: str | None = Field(None, description="Clinical scope or treated symptoms")


class SpecialtyCreate(SpecialtyBase):
    pass


class SpecialtyRead(SpecialtyBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Doctor Schemas
# ==============================================================================


class DoctorBase(BaseModel):
    specialty_id: int = Field(..., description="Foreign key to Specialty")
    name_ar: str = Field(..., description="Doctor Arabic full name with honorific")
    name_en: str = Field(..., description="Doctor English name")
    title: DoctorTitle = Field(default=DoctorTitle.SPECIALIST, description="Medical title")
    examination_fee: float = Field(..., ge=0, description="Examination fee in EGP")
    consultation_fee: float = Field(default=0.0, ge=0, description="Consultation fee in EGP")
    is_active: bool = Field(default=True, description="Active status")


class DoctorCreate(DoctorBase):
    pass


class DoctorRead(DoctorBase):
    id: int
    specialty: SpecialtyRead | None = None
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Doctor Schedule Schemas
# ==============================================================================


class DoctorScheduleBase(BaseModel):
    doctor_id: int = Field(..., description="Foreign key to Doctor")
    day_of_week: DayOfWeek = Field(..., description="Day of week (0=Saturday..6=Friday)")
    start_time: time = Field(..., description="Shift start time")
    end_time: time = Field(..., description="Shift end time")
    max_capacity: int = Field(default=20, gt=0, description="Max patient cap per shift")
    is_active: bool = Field(default=True, description="Schedule active status")


class DoctorScheduleCreate(DoctorScheduleBase):
    pass


class DoctorScheduleRead(DoctorScheduleBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Patient Schemas
# ==============================================================================


class PatientBase(BaseModel):
    name: str = Field(..., min_length=2, description="Patient full name")
    phone: str = Field(..., description="Egyptian contact mobile number")
    gender: str | None = Field(None, description="Gender (male/female)")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return clean_egyptian_phone(v)


class PatientCreate(PatientBase):
    pass


class PatientRead(PatientBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Appointment Schemas
# ==============================================================================


class AppointmentBase(BaseModel):
    patient_id: int = Field(..., description="Foreign key to Patient")
    doctor_id: int = Field(..., description="Foreign key to Doctor")
    schedule_id: int = Field(..., description="Foreign key to DoctorSchedule")
    appointment_date: date = Field(..., description="Date of appointment")
    queue_number: int = Field(..., gt=0, description="Queue number within shift")
    visit_type: VisitType = Field(default=VisitType.EXAMINATION, description="Visit type")
    status: AppointmentStatus = Field(default=AppointmentStatus.CONFIRMED, description="Booking status")
    fee: float = Field(default=0.0, ge=0, description="Total fee charged in EGP")
    notes: str | None = Field(None, description="Optional symptoms or caller notes")


class AppointmentCreate(BaseModel):
    booking_code: str | None = Field(None, description="Unique booking code (auto-generated if omitted)")
    patient_id: int
    doctor_id: int
    schedule_id: int
    appointment_date: date
    queue_number: int = Field(..., gt=0)
    visit_type: VisitType = VisitType.EXAMINATION
    status: AppointmentStatus = AppointmentStatus.CONFIRMED
    fee: float = Field(default=0.0, ge=0)
    notes: str | None = None


class AppointmentRead(AppointmentBase):
    id: int
    booking_code: str
    created_at: datetime
    patient: PatientRead | None = None
    doctor: DoctorRead | None = None
    schedule: DoctorScheduleRead | None = None
    model_config = ConfigDict(from_attributes=True)


# ==============================================================================
# Availability Schemas
# ==============================================================================


class DoctorAvailabilityRead(BaseModel):
    """Calculated shift availability and remaining capacity for a doctor on a specific date."""

    doctor_id: int
    doctor_name_ar: str
    specialty_name_ar: str
    target_date: date
    day_of_week: DayOfWeek
    day_name_ar: str
    has_shift: bool
    schedule_id: int | None = None
    shift_start: time | None = None
    shift_end: time | None = None
    formatted_shift: str | None = None
    max_capacity: int = 0
    booked_count: int = 0
    remaining_capacity: int = 0
    is_available: bool = False
    examination_fee: float = 0.0
    consultation_fee: float = 0.0

