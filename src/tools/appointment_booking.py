"""
Appointment Booking Tool for Egyptian Polyclinics (Feature 3.3).

Reserves a confirmed queue slot (نمرة الحجز) for a patient with a doctor on a
given date. Responsibilities layered on top of ``ClinicRepository``:

1. Doctor resolution by ID or fuzzy Arabic/English name (reuses Feature 3.2 matching).
2. Booking date rules in Africa/Cairo time (no past dates, no shift that already
   ended today, max 30 days ahead).
3. Availability check with a 7-day "nearest available day" suggestion (never auto-books).
4. Duplicate guard (same phone + doctor + date).
5. Consultation eligibility (examination with same doctor in the last 14 days),
   otherwise downgrade to examination.
6. Atomic booking via ``ClinicRepository.create_appointment`` (per-shift lock,
   capacity check, sequential queue number) with one retry on a uniqueness conflict.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from src.db.models import Doctor
from src.db.repository import (
    ClinicRepository,
    ShiftCapacityExceededError,
    ShiftNotFoundError,
)
from src.db.schemas import AppointmentStatus, DoctorAvailabilityRead, VisitType
from src.db.session import get_async_session
from src.tools.doctor_availability import CAIRO_TZ, get_cairo_today, match_doctors
from src.tools.schemas import (
    AppointmentBookingInput,
    AppointmentBookingOutput,
    ToolResult,
    parse_colloquial_date,
)

logger = logging.getLogger(__name__)

# Business rules (approved decisions D2-D4)
MAX_BOOKING_DAYS_AHEAD = 30
NEXT_AVAILABLE_LOOKAHEAD_DAYS = 7
CONSULTATION_ELIGIBILITY_DAYS = 14
MAX_BOOKING_ATTEMPTS = 2  # first attempt + one retry on uniqueness conflict


# ==============================================================================
# Pure helpers (unit-testable, no DB)
# ==============================================================================


def get_cairo_now() -> dt.datetime:
    """Return the current wall-clock time in Egyptian local time (Africa/Cairo)."""
    return dt.datetime.now(tz=CAIRO_TZ)


def resolve_booking_date(value: dt.date | dt.datetime | str | None, today: dt.date) -> dt.date:
    """
    Resolve the requested booking date using Cairo ``today`` as the base.

    Raises:
        ValueError: when the date is missing or cannot be understood.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("Booking date is required.")
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return parse_colloquial_date(str(value), today=today)


def check_date_window(target_date: dt.date, today: dt.date) -> str | None:
    """Return an error code if the date is outside the bookable window, else ``None``."""
    if target_date < today:
        return "past_date"
    if target_date > today + dt.timedelta(days=MAX_BOOKING_DAYS_AHEAD):
        return "too_far_ahead"
    return None


def shift_already_ended(
    target_date: dt.date,
    today: dt.date,
    shift_end: dt.time | None,
    now_time: dt.time,
) -> bool:
    """True when booking is for today and the shift end time has already passed."""
    return target_date == today and shift_end is not None and now_time >= shift_end


def format_fee(fee: float) -> str:
    """Render a fee as plain digits suitable for TTS (e.g. 350.0 -> '350')."""
    return str(int(fee)) if float(fee).is_integer() else f"{fee:.2f}"


def build_confirmation_message(
    *,
    doctor_name_ar: str,
    specialty_name_ar: str,
    day_name_ar: str,
    appointment_date: dt.date,
    shift_window: str,
    queue_number: int,
    booking_code: str,
    visit_type_ar: str,
    fee: float,
    downgraded: bool = False,
) -> str:
    """Build the spoken Egyptian Arabic booking confirmation."""
    prefix = ""
    if downgraded:
        prefix = (
            f"ملحوظة: الاستشارة بتكون خلال {CONSULTATION_ELIGIBILITY_DAYS} يوم من آخر كشف "
            "مع نفس الدكتور، فسجلتلك الزيارة كشف جديد. "
        )
    return (
        f"{prefix}تمام، اتحجزلك {visit_type_ar} مع {doctor_name_ar} ({specialty_name_ar}) "
        f"يوم {day_name_ar} الموافق {appointment_date.isoformat()} من الساعة {shift_window}. "
        f"نمرة حجزك {queue_number}، وكود الحجز {booking_code}، "
        f"والسعر {format_fee(fee)} جنيه. نورتنا!"
    )


def _failure(message: str, error: str, data: dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(success=False, message=message, error=error, data=data)


def _next_available_payload(slot: DoctorAvailabilityRead) -> dict[str, Any]:
    return {
        "target_date": slot.target_date.isoformat(),
        "day_name_ar": slot.day_name_ar,
        "shift_hours": slot.formatted_shift,
        "remaining_capacity": slot.remaining_capacity,
    }


# ==============================================================================
# Tool
# ==============================================================================


class AppointmentBookingTool:
    """Execution tool that books a patient appointment with an atomic queue number."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    # --------------------------------------------------------------------------
    # Internal async steps
    # --------------------------------------------------------------------------

    async def _resolve_doctor(
        self,
        repo: ClinicRepository,
        doctor_id: int | None,
        doctor_name: str | None,
    ) -> Doctor | ToolResult:
        """Return the matched active doctor, or a failure ``ToolResult``."""
        if doctor_id is not None:
            doctor = await repo.get_doctor_by_id(doctor_id)
            if not doctor or not doctor.is_active:
                return _failure(
                    f"عذراً، مش لاقيين دكتور مسجل بالرقم {doctor_id}. ممكن تقولي اسم الدكتور؟",
                    "doctor_not_found",
                )
            return doctor

        candidates = match_doctors(doctor_name or "", await repo.get_doctors(active_only=True))
        if not candidates:
            return _failure(
                f"عذراً، مش لاقيين دكتور باسم '{doctor_name}'. ممكن تتأكد من الاسم أو تقولي التخصص؟",
                "doctor_not_found",
            )
        if len(candidates) > 1:
            cand_data = [
                {
                    "doctor_id": d.id,
                    "name_ar": d.name_ar,
                    "specialty_name_ar": d.specialty.name_ar if d.specialty else "",
                }
                for d in candidates
            ]
            names = "، و".join(f"{c['name_ar']} ({c['specialty_name_ar']})" for c in cand_data)
            return _failure(
                f"فيه أكتر من دكتور بالاسم ده: {names}. حضرتك تقصد مين فيهم؟",
                "ambiguous_doctor",
                {"candidates": cand_data},
            )
        return candidates[0]

    async def _find_next_available(
        self,
        repo: ClinicRepository,
        doctor_id: int,
        start_date: dt.date,
    ) -> DoctorAvailabilityRead | None:
        """Scan the next 7 days after ``start_date`` for a shift with free slots."""
        for offset in range(1, NEXT_AVAILABLE_LOOKAHEAD_DAYS + 1):
            slot = await repo.get_doctor_availability(
                doctor_id, start_date + dt.timedelta(days=offset)
            )
            if slot.has_shift and slot.is_available:
                return slot
        return None

    async def _unavailable_result(
        self,
        repo: ClinicRepository,
        doctor_id: int,
        doctor_name_ar: str,
        target_date: dt.date,
        reason: str,
        error: str,
    ) -> ToolResult:
        """Build a no-booking failure that suggests the nearest available day."""
        next_slot = await self._find_next_available(repo, doctor_id, target_date)
        if next_slot:
            msg = (
                f"عذراً، {reason}. أقرب يوم متاح مع {doctor_name_ar} هو {next_slot.day_name_ar} "
                f"الموافق {next_slot.target_date.isoformat()} من الساعة {next_slot.formatted_shift}. "
                "تحب أحجزلك فيه؟"
            )
            return _failure(msg, error, {"next_available": _next_available_payload(next_slot)})
        msg = (
            f"عذراً، {reason}، ومفيش مواعيد متاحة مع {doctor_name_ar} خلال الـ "
            f"{NEXT_AVAILABLE_LOOKAHEAD_DAYS} أيام الجاية. ممكن أحولك لموظف الاستقبال يرتبلك ميعاد."
        )
        return _failure(msg, error, {"next_available": None})

    async def _attempt_booking(
        self,
        patient_name: str,
        patient_phone: str,
        doctor_id: int,
        target_date: dt.date,
        visit_type: VisitType,
        notes: str | None,
    ):
        """One atomic booking attempt in a fresh session (patient + appointment)."""
        async with get_async_session(self.session_factory) as session:
            repo = ClinicRepository(session)
            patient = await repo.get_or_create_patient(patient_name, patient_phone)
            # Persist the patient before entering the per-shift lock so the
            # appointment transaction stays as short as possible.
            await session.commit()
            return await repo.create_appointment(
                patient_id=patient.id,
                doctor_id=doctor_id,
                appointment_date=target_date,
                visit_type=visit_type,
                notes=notes,
            )

    # --------------------------------------------------------------------------
    # Public entrypoints
    # --------------------------------------------------------------------------

    async def aexecute(
        self,
        patient_name: str | None = None,
        patient_phone: str | None = None,
        doctor_id: int | None = None,
        doctor_name: str | None = None,
        date: dt.date | str | None = None,
        visit_type: VisitType | str | None = VisitType.EXAMINATION,
        notes: str | None = None,
    ) -> ToolResult:
        """Asynchronously validate and book an appointment."""
        # 1. Resolve date in Cairo time before schema validation (avoids UTC base)
        cairo_today = get_cairo_today()
        try:
            target_date = resolve_booking_date(date, cairo_today)
        except (ValueError, TypeError):
            return _failure(
                "ممكن تقولي حضرتك عايز تحجز يوم إيه؟ مثلاً بكرة أو يوم السبت.",
                "invalid_date",
            )

        # 2. Validate remaining fields against the Feature 3.1 contract
        try:
            booking = AppointmentBookingInput(
                patient_name=patient_name,
                patient_phone=patient_phone,
                doctor_id=doctor_id,
                doctor_name=doctor_name,
                date=target_date,
                visit_type=visit_type if visit_type is not None else VisitType.EXAMINATION,
                notes=notes,
            )
        except ValidationError as exc:
            fields = {str(err["loc"][0]) for err in exc.errors() if err.get("loc")}
            if "patient_phone" in fields:
                msg = "رقم الموبايل مش واضح. ممكن تقولي رقم موبايل مصري يبدأ بـ 010 أو 011 أو 012 أو 015؟"
            elif "patient_name" in fields:
                msg = "ممكن تقولي اسم المريض بالكامل؟"
            elif "visit_type" in fields:
                msg = "حضرتك عايز كشف جديد ولا استشارة؟"
            else:
                msg = "ممكن تقولي اسم الدكتور اللي حضرتك عايز تحجز معاه؟"
            return _failure(msg, "invalid_input")

        # 3. Date window rules
        window_error = check_date_window(target_date, cairo_today)
        if window_error == "past_date":
            return _failure(
                f"التاريخ {target_date.isoformat()} عدى خلاص. تحب تحجز النهارده أو يوم تاني قريب؟",
                "past_date",
            )
        if window_error == "too_far_ahead":
            return _failure(
                f"الحجز متاح لحد {MAX_BOOKING_DAYS_AHEAD} يوم قدام بس. ممكن تختار يوم أقرب؟",
                "too_far_ahead",
            )

        try:
            # 4. Pre-checks: doctor, availability, duplicate, eligibility
            async with get_async_session(self.session_factory) as session:
                repo = ClinicRepository(session)

                resolved = await self._resolve_doctor(repo, booking.doctor_id, booking.doctor_name)
                if isinstance(resolved, ToolResult):
                    return resolved
                doc_id = resolved.id
                doc_name = resolved.name_ar
                spec_name = resolved.specialty.name_ar if resolved.specialty else ""

                avail = await repo.get_doctor_availability(doc_id, target_date)
                date_label = f"يوم {avail.day_name_ar} الموافق {target_date.isoformat()}"
                if not avail.has_shift:
                    return await self._unavailable_result(
                        repo,
                        doc_id,
                        doc_name,
                        target_date,
                        f"{doc_name} مش موجود {date_label}",
                        "no_shift",
                    )
                now_time = get_cairo_now().time().replace(tzinfo=None)
                if shift_already_ended(target_date, cairo_today, avail.shift_end, now_time):
                    return await self._unavailable_result(
                        repo,
                        doc_id,
                        doc_name,
                        target_date,
                        f"شفت {doc_name} النهارده خلص",
                        "shift_ended",
                    )
                if not avail.is_available:
                    return await self._unavailable_result(
                        repo,
                        doc_id,
                        doc_name,
                        target_date,
                        f"شفت {doc_name} {date_label} مكتمل",
                        "shift_full",
                    )

                history = await repo.get_patient_appointments(booking.patient_phone)
                existing = next(
                    (
                        a
                        for a in history
                        if a.doctor_id == doc_id
                        and a.appointment_date == target_date
                        and a.status == AppointmentStatus.CONFIRMED.value
                    ),
                    None,
                )
                if existing:
                    return _failure(
                        f"حضرتك حاجز بالفعل مع {doc_name} {date_label}، "
                        f"نمرة حجزك {existing.queue_number} وكود الحجز {existing.booking_code}.",
                        "duplicate_booking",
                        {
                            "existing_appointment": {
                                "booking_code": existing.booking_code,
                                "queue_number": existing.queue_number,
                                "appointment_date": existing.appointment_date.isoformat(),
                                "doctor_name_ar": doc_name,
                            }
                        },
                    )

                final_visit_type = booking.visit_type
                downgraded = False
                if booking.visit_type == VisitType.CONSULTATION:
                    window_start = target_date - dt.timedelta(days=CONSULTATION_ELIGIBILITY_DAYS)
                    eligible = any(
                        a.doctor_id == doc_id
                        and a.visit_type == VisitType.EXAMINATION.value
                        and a.status != AppointmentStatus.CANCELLED.value
                        and window_start <= a.appointment_date < target_date
                        for a in history
                    )
                    if not eligible:
                        final_visit_type = VisitType.EXAMINATION
                        downgraded = True

            # 5. Atomic booking with one retry on uniqueness conflict
            appointment = None
            for attempt in range(1, MAX_BOOKING_ATTEMPTS + 1):
                try:
                    appointment = await self._attempt_booking(
                        booking.patient_name,
                        booking.patient_phone,
                        doc_id,
                        target_date,
                        final_visit_type,
                        booking.notes,
                    )
                    break
                except IntegrityError:
                    logger.warning(
                        "Booking uniqueness conflict (doctor_id=%s, date=%s, attempt=%s)",
                        doc_id,
                        target_date,
                        attempt,
                    )
                except (ShiftNotFoundError, ShiftCapacityExceededError) as exc:
                    error = "no_shift" if isinstance(exc, ShiftNotFoundError) else "shift_full"
                    async with get_async_session(self.session_factory) as session:
                        return await self._unavailable_result(
                            ClinicRepository(session),
                            doc_id,
                            doc_name,
                            target_date,
                            f"شفت {doc_name} {date_label} اتملى دلوقتي",
                            error,
                        )

            if appointment is None:
                return _failure(
                    "عذراً، حصل ضغط على الحجز في نفس اللحظة. ممكن نحاول تاني بعد ثواني؟",
                    "booking_conflict",
                )

            # 6. Build confirmation
            visit_enum = VisitType(appointment.visit_type)
            shift_window = (
                appointment.schedule.formatted_shift
                if appointment.schedule
                else (avail.formatted_shift or "")
            )
            message = build_confirmation_message(
                doctor_name_ar=doc_name,
                specialty_name_ar=spec_name,
                day_name_ar=avail.day_name_ar,
                appointment_date=target_date,
                shift_window=shift_window,
                queue_number=appointment.queue_number,
                booking_code=appointment.booking_code,
                visit_type_ar=visit_enum.label_ar(),
                fee=appointment.fee,
                downgraded=downgraded,
            )
            output = AppointmentBookingOutput(
                booking_code=appointment.booking_code,
                patient_name=booking.patient_name,
                doctor_name_ar=doc_name,
                specialty_name_ar=spec_name,
                appointment_date=target_date.isoformat(),
                queue_number=appointment.queue_number,
                shift_window=shift_window,
                visit_type_ar=visit_enum.label_ar(),
                fee=appointment.fee,
                message=message,
            )
            payload = output.model_dump()
            payload["visit_type"] = visit_enum.value
            payload["visit_type_downgraded"] = downgraded
            return ToolResult(success=True, message=message, data=payload)

        except Exception as exc:
            # No patient identifiers in logs (NFR-4)
            logger.exception("Unexpected error in appointment booking")
            return _failure(
                "عذراً، حصلت مشكلة أثناء الحجز. ممكن نحاول تاني؟",
                f"unexpected_error: {type(exc).__name__}",
            )

    def execute(self, **kwargs: Any) -> ToolResult:
        """Synchronous entrypoint; safe to call from inside a running event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(self.aexecute(**kwargs))).result()
        return asyncio.run(self.aexecute(**kwargs))


# Global singleton instance
appointment_booking_tool = AppointmentBookingTool()


async def async_book_appointment(
    patient_name: str | None = None,
    patient_phone: str | None = None,
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    date: dt.date | str | None = None,
    visit_type: VisitType | str | None = VisitType.EXAMINATION,
    notes: str | None = None,
) -> ToolResult:
    """Async wrapper for LiveKit Voice Agent and LLM tool calling."""
    return await appointment_booking_tool.aexecute(
        patient_name=patient_name,
        patient_phone=patient_phone,
        doctor_id=doctor_id,
        doctor_name=doctor_name,
        date=date,
        visit_type=visit_type,
        notes=notes,
    )


def book_appointment(
    patient_name: str | None = None,
    patient_phone: str | None = None,
    doctor_id: int | None = None,
    doctor_name: str | None = None,
    date: dt.date | str | None = None,
    visit_type: VisitType | str | None = VisitType.EXAMINATION,
    notes: str | None = None,
) -> ToolResult:
    """Sync wrapper for testing and synchronous dispatchers."""
    return appointment_booking_tool.execute(
        patient_name=patient_name,
        patient_phone=patient_phone,
        doctor_id=doctor_id,
        doctor_name=doctor_name,
        date=date,
        visit_type=visit_type,
        notes=notes,
    )
