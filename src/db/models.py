"""
SQLAlchemy 2.0 ORM Relational Models for Egyptian Polyclinics.

Defines database entities: Specialty, Doctor, DoctorSchedule, Patient, and Appointment.
Fully typed with Mapped[T], async-ready lazy="selectin" relationships,
and Python default initializers.
"""

from datetime import date, datetime, time, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Specialty(Base):
    """Medical specialty department (e.g. Cardiology, Pediatrics)."""

    __tablename__ = "specialties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships (async-safe eager loading with selectin)
    doctors: Mapped[list["Doctor"]] = relationship(
        "Doctor",
        back_populates="specialty",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Specialty(id={self.id}, code='{self.code}', name_ar='{self.name_ar}')>"


class Doctor(Base):
    """Physician / Medical consultant practicing at the clinic."""

    __tablename__ = "doctors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    specialty_id: Mapped[int] = mapped_column(
        ForeignKey("specialties.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name_ar: Mapped[str] = mapped_column(String(100), nullable=False)
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(50), default="specialist", nullable=False)
    examination_fee: Mapped[float] = mapped_column(Float, nullable=False)
    consultation_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    specialty: Mapped["Specialty"] = relationship(
        "Specialty", back_populates="doctors", lazy="selectin"
    )
    schedules: Mapped[list["DoctorSchedule"]] = relationship(
        "DoctorSchedule",
        back_populates="doctor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="doctor",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("title", "specialist")
        kwargs.setdefault("consultation_fee", 0.0)
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Doctor(id={self.id}, name_ar='{self.name_ar}', title='{self.title}')>"


class DoctorSchedule(Base):
    """Recurring weekly shift window for a doctor."""

    __tablename__ = "doctor_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Saturday..6=Friday
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    max_capacity: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    doctor: Mapped["Doctor"] = relationship("Doctor", back_populates="schedules", lazy="selectin")
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="schedule",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("max_capacity", 20)
        kwargs.setdefault("is_active", True)
        super().__init__(**kwargs)

    @property
    def formatted_shift(self) -> str:
        """Human-readable shift time (e.g. 06:00 PM - 09:00 PM)."""
        start_str = self.start_time.strftime("%I:%M %p")
        end_str = self.end_time.strftime("%I:%M %p")
        return f"{start_str} - {end_str}"

    def __repr__(self) -> str:
        return (
            f"<DoctorSchedule(id={self.id}, doctor_id={self.doctor_id}, "
            f"day={self.day_of_week}, shift='{self.formatted_shift}')>"
        )


class Patient(Base):
    """Clinic patient record."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now,
        nullable=False,
    )

    # Relationships
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment",
        back_populates="patient",
        lazy="selectin",
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("created_at", _utc_now())
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<Patient(id={self.id}, name='{self.name}', phone='{self.phone}')>"


class Appointment(Base):
    """Confirmed or historical patient appointment."""

    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint(
            "doctor_id",
            "appointment_date",
            "queue_number",
            name="uq_doctor_date_queue",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_code: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        index=True,
        nullable=False,
    )
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    doctor_id: Mapped[int] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    schedule_id: Mapped[int] = mapped_column(
        ForeignKey("doctor_schedules.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    appointment_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    queue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    visit_type: Mapped[str] = mapped_column(String(20), default="examination", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)
    fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=_utc_now,
        nullable=False,
    )

    # Relationships
    patient: Mapped["Patient"] = relationship(
        "Patient", back_populates="appointments", lazy="selectin"
    )
    doctor: Mapped["Doctor"] = relationship(
        "Doctor", back_populates="appointments", lazy="selectin"
    )
    schedule: Mapped["DoctorSchedule"] = relationship(
        "DoctorSchedule", back_populates="appointments", lazy="selectin"
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("visit_type", "examination")
        kwargs.setdefault("status", "confirmed")
        kwargs.setdefault("fee", 0.0)
        kwargs.setdefault("created_at", _utc_now())
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<Appointment(code='{self.booking_code}', doctor_id={self.doctor_id}, "
            f"date='{self.appointment_date}', queue={self.queue_number}, status='{self.status}')>"
        )


class Escalation(Base):
    """Receptionist escalation / supervisor handoff ticket."""

    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    caller_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    caller_phone: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str] = mapped_column(String(50), default="reception", nullable=False)
    urgency: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    estimated_wait_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __init__(self, **kwargs):
        kwargs.setdefault("department", "reception")
        kwargs.setdefault("urgency", "medium")
        kwargs.setdefault("status", "queued")
        kwargs.setdefault("estimated_wait_seconds", 0)
        kwargs.setdefault("created_at", _utc_now())
        kwargs.setdefault("updated_at", _utc_now())
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return (
            f"<Escalation(id={self.id}, ticket_id='{self.ticket_id}', "
            f"status='{self.status}', urgency='{self.urgency}', dept='{self.department}')>"
        )
