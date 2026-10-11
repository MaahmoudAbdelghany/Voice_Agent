"""
Database package for Voice Agent.

Provides DeclarativeBase, Async SQLAlchemy engine, session factories,
database lifecycle management, ORM models, and domain schemas.
"""

from src.db.base import Base
from src.db.models import (
    Appointment,
    Doctor,
    DoctorSchedule,
    Patient,
    Specialty,
)
from src.db.schemas import (
    AppointmentCreate,
    AppointmentRead,
    AppointmentStatus,
    DayOfWeek,
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
    "AppointmentRead",
    "AppointmentStatus",
    "Base",
    "DayOfWeek",
    "Doctor",
    "DoctorCreate",
    "DoctorRead",
    "DoctorSchedule",
    "DoctorScheduleCreate",
    "DoctorScheduleRead",
    "DoctorTitle",
    "Patient",
    "PatientCreate",
    "PatientRead",
    "Specialty",
    "SpecialtyCreate",
    "SpecialtyRead",
    "VisitType",
    "close_db",
    "get_async_session",
    "get_engine",
    "get_session_factory",
    "init_db",
]
