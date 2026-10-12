"""
Database package for Voice Agent.

Provides DeclarativeBase, Async SQLAlchemy engine, session factories,
database lifecycle management, ORM models, domain schemas, and ClinicRepository.
"""

from src.db.base import Base
from src.db.models import (
    Appointment,
    Doctor,
    DoctorSchedule,
    Patient,
    Specialty,
)
from src.db.repository import (
    AppointmentNotFoundError,
    ClinicRepository,
    ClinicRepositoryError,
    DoctorNotFoundError,
    PatientNotFoundError,
    ShiftCapacityExceededError,
    ShiftNotFoundError,
)
from src.db.schemas import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentStatus,
    DayOfWeek,
    DoctorAvailabilityRead,
    DoctorCreate,
    DoctorRead,
    DoctorScheduleCreate,
    DoctorScheduleRead,
    DoctorTitle,
    PatientCreate,
    PatientRead,
    SpecialtyCreate,
    SpecialtyRead,
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

__all__ = [
    "Appointment",
    "AppointmentCreate",
    "AppointmentNotFoundError",
    "AppointmentRead",
    "AppointmentStatus",
    "Base",
    "ClinicRepository",
    "ClinicRepositoryError",
    "DayOfWeek",
    "Doctor",
    "DoctorAvailabilityRead",
    "DoctorCreate",
    "DoctorNotFoundError",
    "DoctorRead",
    "DoctorSchedule",
    "DoctorScheduleCreate",
    "DoctorScheduleRead",
    "DoctorTitle",
    "Patient",
    "PatientCreate",
    "PatientNotFoundError",
    "PatientRead",
    "ShiftCapacityExceededError",
    "ShiftNotFoundError",
    "Specialty",
    "SpecialtyCreate",
    "SpecialtyRead",
    "VisitType",
    "clean_egyptian_phone",
    "close_db",
    "get_async_session",
    "get_engine",
    "get_session_factory",
    "init_db",
]
