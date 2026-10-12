"""
Clinic Database Repository Layer for Egyptian Polyclinics.

Provides an asynchronous, transactional data access abstraction for:
- Medical specialties and doctor profiles
- Doctor shift schedules and real-time availability calculation
- Patient registration with Egyptian phone normalization
- Atomic appointment booking with sequential queue numbering
- Booking lookups and cancellations
"""

import asyncio
from collections.abc import Sequence
from datetime import date
from typing import ClassVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Appointment, Doctor, DoctorSchedule, Patient, Specialty
from src.db.schemas import (
    AppointmentStatus,
    DayOfWeek,
    DoctorAvailabilityRead,
    VisitType,
    clean_egyptian_phone,
)

# ==============================================================================
# Domain Exceptions
# ==============================================================================


class ClinicRepositoryError(Exception):
    """Base exception for clinic repository errors."""


class DoctorNotFoundError(ClinicRepositoryError):
    """Raised when the requested doctor does not exist."""


class PatientNotFoundError(ClinicRepositoryError):
    """Raised when the requested patient does not exist."""


class ShiftNotFoundError(ClinicRepositoryError):
    """Raised when a doctor has no scheduled shift on the requested date."""


class ShiftCapacityExceededError(ClinicRepositoryError):
    """Raised when a doctor shift has reached maximum patient capacity."""


class AppointmentNotFoundError(ClinicRepositoryError):
    """Raised when the requested appointment booking code is not found."""


# ==============================================================================
# Clinic Repository
# ==============================================================================


class ClinicRepository:
    """Async repository managing clinic entities, transactions, and bookings."""

    _shift_locks: ClassVar[dict[tuple[asyncio.AbstractEventLoop, int, date], asyncio.Lock]] = {}

    @classmethod
    async def _get_shift_lock(cls, doctor_id: int, appointment_date: date) -> asyncio.Lock:
        """Retrieve or create an asyncio.Lock per doctor shift date bound to the running event loop."""
        loop = asyncio.get_running_loop()
        key = (loop, doctor_id, appointment_date)
        if key not in cls._shift_locks:
            cls._shift_locks[key] = asyncio.Lock()
        return cls._shift_locks[key]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------------------------------------------------------
    # Specialties
    # --------------------------------------------------------------------------

    async def get_specialties(self, active_only: bool = True) -> Sequence[Specialty]:
        """Retrieve all medical specialties ordered by Arabic name."""
        stmt = (
            select(Specialty)
            .options(selectinload(Specialty.doctors))
            .order_by(Specialty.name_ar)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_specialty_by_code(self, code: str) -> Specialty | None:
        """Retrieve a single specialty by its unique code slug."""
        stmt = (
            select(Specialty)
            .options(selectinload(Specialty.doctors))
            .where(Specialty.code == code.strip().lower())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    # --------------------------------------------------------------------------
    # Doctors
    # --------------------------------------------------------------------------

    async def get_doctors(
        self,
        specialty_code: str | None = None,
        active_only: bool = True,
    ) -> Sequence[Doctor]:
        """Retrieve doctors, optionally filtered by specialty code and active status."""
        stmt = (
            select(Doctor)
            .options(
                selectinload(Doctor.specialty),
                selectinload(Doctor.schedules),
            )
            .order_by(Doctor.name_ar)
        )
        if active_only:
            stmt = stmt.where(Doctor.is_active.is_(True))

        if specialty_code:
            stmt = stmt.join(Doctor.specialty).where(
                Specialty.code == specialty_code.strip().lower()
            )

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_doctor_by_id(self, doctor_id: int) -> Doctor | None:
        """Retrieve a doctor by primary key with loaded specialty and schedules."""
        stmt = (
            select(Doctor)
            .options(
                selectinload(Doctor.specialty),
                selectinload(Doctor.schedules),
            )
            .where(Doctor.id == doctor_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_doctor_schedules(
        self,
        doctor_id: int,
        active_only: bool = True,
    ) -> Sequence[DoctorSchedule]:
        """Retrieve recurring shift schedules for a specific doctor."""
        stmt = (
            select(DoctorSchedule)
            .where(DoctorSchedule.doctor_id == doctor_id)
            .order_by(DoctorSchedule.day_of_week, DoctorSchedule.start_time)
        )
        if active_only:
            stmt = stmt.where(DoctorSchedule.is_active.is_(True))

        result = await self.session.execute(stmt)
        return result.scalars().all()

    # --------------------------------------------------------------------------
    # Doctor Availability & Shift Capacity
    # --------------------------------------------------------------------------

    async def get_doctor_availability(
        self,
        doctor_id: int,
        target_date: date,
    ) -> DoctorAvailabilityRead:
        """
        Calculate shift schedule and remaining patient capacity on target_date.

        Maps target_date to Egyptian DayOfWeek (0=Saturday..6=Friday),
        queries the active DoctorSchedule, and counts confirmed bookings.
        """
        doctor = await self.get_doctor_by_id(doctor_id)
        if not doctor:
            raise DoctorNotFoundError(f"Doctor with ID {doctor_id} not found.")

        day_of_week = DayOfWeek.from_date(target_date)
        day_name_ar = day_of_week.label_ar()

        # Find active schedule for doctor on that day
        stmt = select(DoctorSchedule).where(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.day_of_week == day_of_week.value,
            DoctorSchedule.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        schedule = result.scalars().first()

        specialty_name = doctor.specialty.name_ar if doctor.specialty else ""

        if not schedule:
            return DoctorAvailabilityRead(
                doctor_id=doctor.id,
                doctor_name_ar=doctor.name_ar,
                specialty_name_ar=specialty_name,
                target_date=target_date,
                day_of_week=day_of_week,
                day_name_ar=day_name_ar,
                has_shift=False,
                schedule_id=None,
                shift_start=None,
                shift_end=None,
                formatted_shift=None,
                max_capacity=0,
                booked_count=0,
                remaining_capacity=0,
                is_available=False,
                examination_fee=doctor.examination_fee,
                consultation_fee=doctor.consultation_fee,
            )

        # Count confirmed (active) appointments on this target_date
        count_stmt = select(func.count(Appointment.id)).where(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == target_date,
            Appointment.status != AppointmentStatus.CANCELLED.value,
        )
        count_res = await self.session.execute(count_stmt)
        booked_count = count_res.scalar_one() or 0

        remaining = max(0, schedule.max_capacity - booked_count)
        is_available = remaining > 0

        return DoctorAvailabilityRead(
            doctor_id=doctor.id,
            doctor_name_ar=doctor.name_ar,
            specialty_name_ar=specialty_name,
            target_date=target_date,
            day_of_week=day_of_week,
            day_name_ar=day_name_ar,
            has_shift=True,
            schedule_id=schedule.id,
            shift_start=schedule.start_time,
            shift_end=schedule.end_time,
            formatted_shift=schedule.formatted_shift,
            max_capacity=schedule.max_capacity,
            booked_count=booked_count,
            remaining_capacity=remaining,
            is_available=is_available,
            examination_fee=doctor.examination_fee,
            consultation_fee=doctor.consultation_fee,
        )

    # --------------------------------------------------------------------------
    # Patients
    # --------------------------------------------------------------------------

    async def get_patient_by_phone(self, phone_number: str) -> Patient | None:
        """Find patient using normalized Egyptian mobile number."""
        cleaned_phone = clean_egyptian_phone(phone_number)
        stmt = select(Patient).where(Patient.phone == cleaned_phone)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_or_create_patient(
        self,
        name: str,
        phone_number: str,
        gender: str | None = None,
    ) -> Patient:
        """Find existing patient by normalized phone or create a new one."""
        cleaned_phone = clean_egyptian_phone(phone_number)
        patient = await self.get_patient_by_phone(cleaned_phone)
        if patient:
            if name and patient.name != name.strip():
                patient.name = name.strip()
            if gender and patient.gender != gender:
                patient.gender = gender
            await self.session.flush()
            return patient

        patient = Patient(
            name=name.strip(),
            phone=cleaned_phone,
            gender=gender,
        )
        self.session.add(patient)
        await self.session.flush()
        return patient

    # --------------------------------------------------------------------------
    # Appointments (Atomic Booking & Queueing)
    # --------------------------------------------------------------------------

    async def create_appointment(
        self,
        patient_id: int,
        doctor_id: int,
        appointment_date: date,
        visit_type: VisitType | str = VisitType.EXAMINATION,
        notes: str | None = None,
        auto_commit: bool = True,
    ) -> Appointment:
        """
        Atomically reserve a patient appointment inside a database transaction.

        - Uses per-shift asyncio lock to prevent race conditions across concurrent callers
        - Verifies patient and doctor exist
        - Verifies doctor shift exists on target appointment_date
        - Enforces shift maximum capacity
        - Assigns next sequential queue number starting at 1
        - Generates unique booking code: APT-YYYYMMDD-D{doctor_id}Q{queue_number}
        - Commits transaction by default (auto_commit=True) for immediate multi-session consistency
        """
        lock = await self._get_shift_lock(doctor_id, appointment_date)
        async with lock:
            # 1. Verify Patient
            stmt_p = select(Patient).where(Patient.id == patient_id)
            res_p = await self.session.execute(stmt_p)
            patient = res_p.scalars().first()
            if not patient:
                raise PatientNotFoundError(f"Patient with ID {patient_id} does not exist.")

            # 2. Check Doctor Availability & Shift Capacity
            avail = await self.get_doctor_availability(doctor_id, appointment_date)
            if not avail.has_shift or not avail.schedule_id:
                raise ShiftNotFoundError(
                    f"الطبيب ليس لديه شفت عمل مجدول في يوم {avail.day_name_ar} ({appointment_date})."
                )

            if not avail.is_available:
                raise ShiftCapacityExceededError(
                    f"شفت الطبيب {avail.doctor_name_ar} مكتمل بالكامل في تاريخ {appointment_date} "
                    f"(السعة القصوى {avail.max_capacity} مريض)."
                )

            # 3. Determine Visit Type and Fee
            if isinstance(visit_type, VisitType):
                v_type_str = visit_type.value
            else:
                v_type_str = str(visit_type).lower()

            fee = (
                avail.consultation_fee
                if v_type_str == VisitType.CONSULTATION.value
                else avail.examination_fee
            )

            # 4. Atomically Calculate Next Queue Number
            stmt_max = select(func.coalesce(func.max(Appointment.queue_number), 0)).where(
                Appointment.doctor_id == doctor_id,
                Appointment.appointment_date == appointment_date,
            )
            max_res = await self.session.execute(stmt_max)
            current_max = max_res.scalar_one() or 0
            next_queue = current_max + 1

            # 5. Generate Human-Readable Booking Code
            # Format: APT-YYYYMMDD-XXX (e.g. APT-20261015-001)
            date_str = appointment_date.strftime("%Y%m%d")
            booking_code = f"APT-{date_str}-{doctor_id:02d}{next_queue:03d}"

            # 6. Instantiate Appointment
            appointment = Appointment(
                booking_code=booking_code,
                patient_id=patient_id,
                doctor_id=doctor_id,
                schedule_id=avail.schedule_id,
                appointment_date=appointment_date,
                queue_number=next_queue,
                visit_type=v_type_str,
                status=AppointmentStatus.CONFIRMED.value,
                fee=fee,
                notes=notes,
            )

            self.session.add(appointment)
            if auto_commit:
                await self.session.commit()
            else:
                await self.session.flush()

            # Eagerly refresh to populate relationships
            return await self.get_appointment_by_code(booking_code) or appointment

    async def get_appointment_by_code(self, booking_code: str) -> Appointment | None:
        """Retrieve an appointment by its unique booking code."""
        stmt = (
            select(Appointment)
            .options(
                selectinload(Appointment.patient),
                selectinload(Appointment.doctor).selectinload(Doctor.specialty),
                selectinload(Appointment.schedule),
            )
            .where(Appointment.booking_code == booking_code.strip())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_patient_appointments(
        self,
        phone_number: str,
        active_only: bool = False,
    ) -> Sequence[Appointment]:
        """Retrieve appointments for a patient by normalized phone number."""
        cleaned_phone = clean_egyptian_phone(phone_number)
        stmt = (
            select(Appointment)
            .join(Appointment.patient)
            .options(
                selectinload(Appointment.patient),
                selectinload(Appointment.doctor).selectinload(Doctor.specialty),
                selectinload(Appointment.schedule),
            )
            .where(Patient.phone == cleaned_phone)
            .order_by(Appointment.appointment_date.desc(), Appointment.queue_number.desc())
        )
        if active_only:
            stmt = stmt.where(Appointment.status == AppointmentStatus.CONFIRMED.value)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def cancel_appointment(
        self,
        booking_code: str,
        reason: str | None = None,
        auto_commit: bool = True,
    ) -> Appointment | None:
        """Cancel an appointment and record cancellation reason."""
        appointment = await self.get_appointment_by_code(booking_code)
        if not appointment:
            return None

        appointment.status = AppointmentStatus.CANCELLED.value
        if reason:
            existing_notes = appointment.notes
            appointment.notes = (
                f"{existing_notes} | سبب الإلغاء: {reason}"
                if existing_notes
                else f"سبب الإلغاء: {reason}"
            )

        if auto_commit:
            await self.session.commit()
        else:
            await self.session.flush()
        return appointment
