"""
Appointment Management Tool for Egyptian Polyclinics (Feature 3.4).

Provides unified management for patient appointments:
1. Lookup: By booking code or by phone (upcoming confirmed only, sorted nearest first).
2. Cancel: By booking code (ownership verified if phone given) or by phone alone
   when the caller has exactly one cancellable upcoming booking.
3. Reschedule: Same doctor, atomic swap (new appointment created + old cancelled in
   one transaction), enforcing 3.3 Cairo date rules, capacity check, and 7-day fallback suggestions.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from src.db.models import Appointment
from src.db.repository import (
    ClinicRepository,
    ShiftCapacityExceededError,
    ShiftNotFoundError,
)
from src.db.schemas import AppointmentStatus, DayOfWeek, VisitType
from src.db.session import get_async_session
from src.tools.appointment_booking import (
    MAX_BOOKING_DAYS_AHEAD,
    NEXT_AVAILABLE_LOOKAHEAD_DAYS,
    check_date_window,
    get_cairo_now,
    resolve_booking_date,
    shift_already_ended,
)
from src.tools.doctor_availability import get_cairo_today
from src.tools.schemas import (
    ManageAppointmentAction,
    ManageAppointmentInput,
    ManageAppointmentOutput,
    ToolResult,
    clean_egyptian_phone,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Pure Helpers (unit-testable, no DB side-effects)
# ==============================================================================


def serialize_appointment(appt: Appointment) -> dict[str, Any]:
    """
    Format an Appointment model into the standardized dictionary required by FR-6.2.
    Phone number is intentionally excluded for privacy (NFR-4).
    """
    day_enum = DayOfWeek.from_date(appt.appointment_date)
    shift_str = appt.schedule.formatted_shift if appt.schedule else ""
    doc_name = appt.doctor.name_ar if appt.doctor else ""
    spec_name = appt.doctor.specialty.name_ar if appt.doctor and appt.doctor.specialty else ""
    patient_name = appt.patient.name if appt.patient else ""

    try:
        status_enum = AppointmentStatus(appt.status)
        status_ar = status_enum.label_ar()
    except ValueError:
        status_ar = appt.status

    try:
        visit_enum = VisitType(appt.visit_type)
        visit_ar = visit_enum.label_ar()
    except ValueError:
        visit_ar = appt.visit_type

    return {
        "booking_code": appt.booking_code,
        "patient_name": patient_name,
        "doctor_name_ar": doc_name,
        "specialty_name_ar": spec_name,
        "appointment_date": appt.appointment_date.isoformat(),
        "day_name_ar": day_enum.label_ar(),
        "shift_window": shift_str,
        "queue_number": appt.queue_number,
        "visit_type": appt.visit_type,
        "visit_type_ar": visit_ar,
        "fee": float(appt.fee),
        "status": appt.status,
        "status_ar": status_ar,
    }


def is_cancellable(
    appt: Appointment,
    cairo_today: dt.date,
    cairo_now: dt.datetime,
) -> tuple[bool, str | None, str | None]:
    """
    Evaluate if an appointment is eligible for cancellation or rescheduling (FR-3.2).

    Returns:
        (is_allowed, error_code, error_message)
    """
    if appt.status != AppointmentStatus.CONFIRMED.value:
        if appt.status == AppointmentStatus.CANCELLED.value:
            return (
                False,
                "already_cancelled",
                f"الحجز بكود {appt.booking_code} ملغي بالفعل.",
            )
        return (
            False,
            "not_confirmed",
            f"الحجز بكود {appt.booking_code} حالته '{appt.status}' ومش متاح تعديله أو إلغاؤه.",
        )

    if appt.appointment_date < cairo_today:
        return (
            False,
            "past_appointment",
            f"ميعاد الحجز ده كان يوم {appt.appointment_date.isoformat()} وفات خلاص، ومش متاح إلغاؤه أو تغييره.",
        )

    if appt.appointment_date == cairo_today and appt.schedule and appt.schedule.start_time:
        now_time = cairo_now.time().replace(tzinfo=None)
        if now_time >= appt.schedule.start_time:
            return (
                False,
                "shift_started",
                "شفت عمل الطبيب بدأ بالفعل النهارده، وللأسف مش متاح إلغاء أو تأجيل الحجز دلوقتي. ممكن تتواصل مع الاستقبال لو فيه أي استفسار.",
            )

    return True, None, None


def _format_spoken_list(appts: list[dict[str, Any]], max_items: int = 3) -> str:
    """Format up to max_items appointment summaries into spoken Egyptian Arabic."""
    spoken_parts = []
    for a in appts[:max_items]:
        part = f"{a['doctor_name_ar']} يوم {a['day_name_ar']} الموافق {a['appointment_date']} (نمرة {a['queue_number']}، كود {a['booking_code']})"
        spoken_parts.append(part)
    return "، و".join(spoken_parts)


def _failure(
    action: str,
    message: str,
    error: str,
    status: str = "failed",
    appointments: list[dict[str, Any]] | None = None,
    extra_data: dict[str, Any] | None = None,
) -> ToolResult:
    """Standardized failure response builder."""
    payload = ManageAppointmentOutput(
        action=action,
        status=status,
        appointments=appointments or [],
        message=message,
    ).model_dump()
    if extra_data:
        payload.update(extra_data)
    return ToolResult(success=False, message=message, error=error, data=payload)


def _success(
    action: str,
    message: str,
    status: str,
    appointments: list[dict[str, Any]],
    extra_data: dict[str, Any] | None = None,
) -> ToolResult:
    """Standardized success response builder."""
    payload = ManageAppointmentOutput(
        action=action,
        status=status,
        appointments=appointments,
        message=message,
    ).model_dump()
    if extra_data:
        payload.update(extra_data)
    return ToolResult(success=True, message=message, data=payload)


# ==============================================================================
# ManageAppointmentTool Implementation
# ==============================================================================


class ManageAppointmentTool:
    """Execution tool for query, cancellation, and rescheduling of appointments."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    async def _find_next_available(
        self,
        repo: ClinicRepository,
        doctor_id: int,
        start_date: dt.date,
    ):
        """Scan up to 7 days for a doctor's shift with free capacity."""
        for offset in range(1, NEXT_AVAILABLE_LOOKAHEAD_DAYS + 1):
            check_date = start_date + dt.timedelta(days=offset)
            slot = await repo.get_doctor_availability(doctor_id, check_date)
            if slot.has_shift and slot.is_available:
                return slot
        return None

    # --------------------------------------------------------------------------
    # Sub-action: Lookup
    # --------------------------------------------------------------------------

    async def _handle_lookup(
        self,
        repo: ClinicRepository,
        booking_code: str | None,
        phone: str | None,
        cairo_today: dt.date,
    ) -> ToolResult:
        if booking_code:
            appt = await repo.get_appointment_by_code(booking_code)
            if not appt:
                return _failure(
                    "lookup",
                    f"عذراً، مش لاقيين أي حجز مسجل بكود '{booking_code}'. ممكن تتأكد من الكود أو تقولي رقم الموبايل؟",
                    "not_found",
                    status="not_found",
                )
            if phone:
                appt_phone = clean_egyptian_phone(appt.patient.phone)
                given_phone = clean_egyptian_phone(phone)
                if appt_phone != given_phone:
                    return _failure(
                        "lookup",
                        "عذراً، كود الحجز ده مش متسجل بنفس رقم الموبايل المطلوب.",
                        "phone_mismatch",
                        status="mismatch",
                    )

            data_item = serialize_appointment(appt)
            if appt.status == AppointmentStatus.CONFIRMED.value:
                msg = (
                    f"حجز حضرتك مع {data_item['doctor_name_ar']} ({data_item['specialty_name_ar']}) "
                    f"مؤكد يوم {data_item['day_name_ar']} الموافق {data_item['appointment_date']} "
                    f"من الساعة {data_item['shift_window']}. نمرة حجزك {data_item['queue_number']}، "
                    f"وكود الحجز {data_item['booking_code']}."
                )
            elif appt.status == AppointmentStatus.CANCELLED.value:
                msg = (
                    f"حجز حضرتك مع {data_item['doctor_name_ar']} يوم {data_item['appointment_date']} "
                    f"بكود {data_item['booking_code']} ملغي."
                )
            elif appt.status == AppointmentStatus.COMPLETED.value:
                msg = (
                    f"حجز حضرتك مع {data_item['doctor_name_ar']} يوم {data_item['appointment_date']} "
                    f"بكود {data_item['booking_code']} تم الكشف فيه بالفعل."
                )
            else:
                msg = (
                    f"حجز حضرتك مع {data_item['doctor_name_ar']} يوم {data_item['appointment_date']} "
                    f"مسجل بحالة '{data_item['status_ar']}'."
                )

            return _success("lookup", msg, appt.status, [data_item])

        # Lookup by phone only
        all_appts = await repo.get_patient_appointments(phone, active_only=False)
        upcoming = [
            a
            for a in all_appts
            if a.status == AppointmentStatus.CONFIRMED.value and a.appointment_date >= cairo_today
        ]
        upcoming.sort(key=lambda a: (a.appointment_date, a.queue_number))

        if not upcoming:
            msg = (
                "حضرتك معندكش أي حجوزات قادمة مسجلة برقم الموبايل ده. تحب أحجزلك ميعاد مع أي دكتور؟"
            )
            return _success("lookup", msg, "none", [])

        serialized = [serialize_appointment(a) for a in upcoming]
        spoken = _format_spoken_list(serialized, max_items=3)
        if len(upcoming) == 1:
            msg = f"حضرتك عندك حجز قادم مع {spoken}."
        else:
            msg = f"حضرتك عندك {len(upcoming)} حجوزات قادمة: {spoken}."

        return _success("lookup", msg, "found", serialized)

    # --------------------------------------------------------------------------
    # Sub-action: Cancel
    # --------------------------------------------------------------------------

    async def _handle_cancel(
        self,
        repo: ClinicRepository,
        booking_code: str | None,
        phone: str | None,
        reason: str | None,
        cairo_today: dt.date,
        cairo_now: dt.datetime,
    ) -> ToolResult:
        target_appt: Appointment | None = None

        if booking_code:
            appt = await repo.get_appointment_by_code(booking_code)
            if not appt:
                return _failure(
                    "cancel",
                    f"عذراً، مش لاقيين أي حجز بكود '{booking_code}' للإلغاء.",
                    "not_found",
                    status="not_found",
                )
            if phone:
                appt_phone = clean_egyptian_phone(appt.patient.phone)
                given_phone = clean_egyptian_phone(phone)
                if appt_phone != given_phone:
                    return _failure(
                        "cancel",
                        "عذراً، كود الحجز ده مش متسجل بنفس رقم الموبايل المطلوب.",
                        "phone_mismatch",
                        status="mismatch",
                    )
            target_appt = appt
        else:
            # Cancel by phone alone (D1)
            all_appts = await repo.get_patient_appointments(phone, active_only=False)
            cancellable = []
            for a in all_appts:
                ok, _, _ = is_cancellable(a, cairo_today, cairo_now)
                if ok:
                    cancellable.append(a)

            if len(cancellable) == 0:
                return _failure(
                    "cancel",
                    "مش لاقيين أي حجز قادم متاح لإلغاؤه مسجل برقم الموبايل ده.",
                    "not_found",
                    status="not_found",
                )
            if len(cancellable) > 1:
                serialized_list = [serialize_appointment(a) for a in cancellable]
                spoken = _format_spoken_list(serialized_list, max_items=3)
                msg = f"حضرتك عندك أكتر من حجز قادم: {spoken}. ممكن توضح كود الحجز اللي تحب تلغيه؟"
                return _failure(
                    "cancel",
                    msg,
                    "multiple_appointments",
                    status="multiple",
                    appointments=serialized_list,
                )
            target_appt = cancellable[0]

        # Verify cancellable eligibility
        ok, err_code, err_msg = is_cancellable(target_appt, cairo_today, cairo_now)
        if not ok:
            return _failure(
                "cancel",
                err_msg or "الحجز غير متاح للإلغاء.",
                err_code or "cannot_cancel",
                status="cannot_cancel",
                appointments=[serialize_appointment(target_appt)],
            )

        # Execute cancellation
        cancelled = await repo.cancel_appointment(
            target_appt.booking_code,
            reason=reason,
            auto_commit=True,
        )
        data_item = serialize_appointment(cancelled or target_appt)
        patient_clause = f" الخاص بـ {data_item['patient_name']}" if not booking_code else ""
        msg = (
            f"تم إلغاء حجز حضرتك{patient_clause} مع {data_item['doctor_name_ar']} "
            f"يوم {data_item['day_name_ar']} الموافق {data_item['appointment_date']} "
            f"(كود الحجز {data_item['booking_code']}) بنجاح. لو حبيت تحجز في أي وقت تاني إحنا في الخدمة!"
        )
        return _success("cancel", msg, "cancelled", [data_item])

    # --------------------------------------------------------------------------
    # Sub-action: Reschedule
    # --------------------------------------------------------------------------

    async def _handle_reschedule(
        self,
        repo: ClinicRepository,
        booking_code: str | None,
        phone: str | None,
        new_date: dt.date | str | None,
        reason: str | None,
        cairo_today: dt.date,
        cairo_now: dt.datetime,
    ) -> ToolResult:
        if not booking_code:
            return _failure(
                "reschedule",
                "لتأجيل الميعاد، يرجى تزويدنا بكود الحجز والتاريخ الجديد المطلوب.",
                "missing_booking_code",
            )

        old_appt = await repo.get_appointment_by_code(booking_code)
        if not old_appt:
            return _failure(
                "reschedule",
                f"عذراً، مش لاقيين أي حجز مسجل بكود '{booking_code}' لتأجيله.",
                "not_found",
                status="not_found",
            )

        if phone:
            appt_phone = clean_egyptian_phone(old_appt.patient.phone)
            given_phone = clean_egyptian_phone(phone)
            if appt_phone != given_phone:
                return _failure(
                    "reschedule",
                    "عذراً، كود الحجز ده مش متسجل بنفس رقم الموبايل المطلوب.",
                    "phone_mismatch",
                    status="mismatch",
                )

        # Check cancellable/reschedulable status of old appointment
        ok, err_code, err_msg = is_cancellable(old_appt, cairo_today, cairo_now)
        if not ok:
            return _failure(
                "reschedule",
                err_msg or "الحجز غير متاح لتأجيله.",
                err_code or "cannot_reschedule",
                status="cannot_reschedule",
                appointments=[serialize_appointment(old_appt)],
            )

        # Parse new date
        try:
            target_new_date = resolve_booking_date(new_date, cairo_today)
        except (ValueError, TypeError):
            return _failure(
                "reschedule",
                "ممكن توضح التاريخ الجديد اللي تحب تنقل الحجز ليه؟ مثلاً بكرة أو يوم السبت.",
                "invalid_date",
            )

        # Date window checks
        window_err = check_date_window(target_new_date, cairo_today)
        if window_err == "past_date":
            return _failure(
                "reschedule",
                f"التاريخ الجديد {target_new_date.isoformat()} عدى خلاص. ممكن تختار ميعاد قادم؟",
                "past_date",
            )
        if window_err == "too_far_ahead":
            return _failure(
                "reschedule",
                f"التأجيل متاح لحد {MAX_BOOKING_DAYS_AHEAD} يوم قدام بس. ممكن تختار يوم أقرب؟",
                "too_far_ahead",
            )

        if target_new_date == old_appt.appointment_date:
            return _failure(
                "reschedule",
                f"الميعاد الجديد هو نفس ميعاد الحجز الحالي ({target_new_date.isoformat()}). يرجى اختيار تاريخ مختلف.",
                "same_date",
            )

        doc_id = old_appt.doctor_id
        doc_name = old_appt.doctor.name_ar if old_appt.doctor else ""

        # Doctor availability checks on new date
        avail = await repo.get_doctor_availability(doc_id, target_new_date)
        date_label = f"يوم {avail.day_name_ar} الموافق {target_new_date.isoformat()}"

        if not avail.has_shift:
            next_slot = await self._find_next_available(repo, doc_id, target_new_date)
            extra = (
                {
                    "next_available": {
                        "target_date": next_slot.target_date.isoformat(),
                        "day_name_ar": next_slot.day_name_ar,
                        "shift_hours": next_slot.formatted_shift,
                        "remaining_capacity": next_slot.remaining_capacity,
                    }
                }
                if next_slot
                else None
            )
            msg = f"عذراً، {doc_name} مش موجود {date_label}. " + (
                f"أقرب يوم متاح مع الطبيب هو {next_slot.day_name_ar} الموافق {next_slot.target_date.isoformat()} "
                f"من الساعة {next_slot.formatted_shift}. تحب نأجل ليه؟"
                if next_slot
                else f"ومفيش مواعيد متاحة مع الطبيب خلال الـ {NEXT_AVAILABLE_LOOKAHEAD_DAYS} أيام الجاية."
            )
            return _failure("reschedule", msg, "no_shift", extra_data=extra)

        now_time = cairo_now.time().replace(tzinfo=None)
        if shift_already_ended(target_new_date, cairo_today, avail.shift_end, now_time):
            next_slot = await self._find_next_available(repo, doc_id, target_new_date)
            extra = (
                {
                    "next_available": {
                        "target_date": next_slot.target_date.isoformat(),
                        "day_name_ar": next_slot.day_name_ar,
                        "shift_hours": next_slot.formatted_shift,
                        "remaining_capacity": next_slot.remaining_capacity,
                    }
                }
                if next_slot
                else None
            )
            msg = f"عذراً، شفت {doc_name} النهارده خلص. " + (
                f"أقرب يوم متاح مع الطبيب هو {next_slot.day_name_ar} الموافق {next_slot.target_date.isoformat()}. تحب نأجل ليه؟"
                if next_slot
                else ""
            )
            return _failure("reschedule", msg, "shift_ended", extra_data=extra)

        if not avail.is_available:
            next_slot = await self._find_next_available(repo, doc_id, target_new_date)
            extra = (
                {
                    "next_available": {
                        "target_date": next_slot.target_date.isoformat(),
                        "day_name_ar": next_slot.day_name_ar,
                        "shift_hours": next_slot.formatted_shift,
                        "remaining_capacity": next_slot.remaining_capacity,
                    }
                }
                if next_slot
                else None
            )
            msg = f"عذراً، شفت {doc_name} {date_label} مكتمل العدد بالكامل. " + (
                f"أقرب يوم متاح مع الطبيب هو {next_slot.day_name_ar} الموافق {next_slot.target_date.isoformat()}. تحب نأجل ليه؟"
                if next_slot
                else ""
            )
            return _failure("reschedule", msg, "shift_full", extra_data=extra)

        # Check duplicate on target new date for the same patient phone
        patient_phone = old_appt.patient.phone
        patient_history = await repo.get_patient_appointments(patient_phone)
        duplicate = any(
            a.doctor_id == doc_id
            and a.appointment_date == target_new_date
            and a.status == AppointmentStatus.CONFIRMED.value
            for a in patient_history
        )
        if duplicate:
            return _failure(
                "reschedule",
                f"حضرتك عندك حجز مؤكد بالفعل مع {doc_name} {date_label}.",
                "duplicate_booking",
            )

        # Perform atomic swap in one transaction
        # Cancel old appointment with flush, then create new appointment with commit
        old_code = old_appt.booking_code
        old_day_label = DayOfWeek.from_date(old_appt.appointment_date).label_ar()
        old_date_iso = old_appt.appointment_date.isoformat()

        try:
            old_appt.status = AppointmentStatus.CANCELLED.value
            resched_note = f"تم التأجيل إلى {target_new_date.isoformat()}"
            old_appt.notes = (
                f"{old_appt.notes} | {resched_note}" if old_appt.notes else resched_note
            )
            await repo.session.flush()

            new_notes = f"تأجيل من الحجز {old_code}" + (f" | {reason}" if reason else "")
            new_appt = await repo.create_appointment(
                patient_id=old_appt.patient_id,
                doctor_id=old_appt.doctor_id,
                appointment_date=target_new_date,
                visit_type=old_appt.visit_type,
                notes=new_notes,
                auto_commit=True,
            )
        except (ShiftCapacityExceededError, ShiftNotFoundError) as exc:
            logger.warning(f"Reschedule capacity race condition: {exc}")
            return _failure(
                "reschedule",
                f"عذراً، شفت {doc_name} {date_label} اتملى في نفس اللحظة. تحب نختار ميعاد تاني؟",
                "shift_full",
            )
        except IntegrityError:
            logger.warning(
                "Reschedule uniqueness conflict on doctor %s, date %s",
                doc_id,
                target_new_date,
            )
            return _failure(
                "reschedule",
                "عذراً، حصل ضغط لحظي أثناء تأجيل الميعاد. ممكن نحاول تاني بعد لحظات؟",
                "booking_conflict",
            )

        serialized_new = serialize_appointment(new_appt)
        serialized_old = serialize_appointment(old_appt)

        msg = (
            f"تمام، تم تأجيل حجز حضرتك مع {doc_name} من يوم {old_day_label} {old_date_iso} "
            f"إلى يوم {avail.day_name_ar} الموافق {target_new_date.isoformat()} "
            f"من الساعة {avail.formatted_shift}. نمرة حجزك الجديدة {new_appt.queue_number}، "
            f"وكود الحجز الجديد {new_appt.booking_code}."
        )
        return _success(
            "reschedule",
            msg,
            "rescheduled",
            [serialized_new, serialized_old],
        )

    # --------------------------------------------------------------------------
    # Public aexecute / execute Entrypoints
    # --------------------------------------------------------------------------

    async def aexecute(
        self,
        action: ManageAppointmentAction | str,
        booking_code: str | None = None,
        phone: str | None = None,
        new_date: dt.date | str | None = None,
        reason: str | None = None,
    ) -> ToolResult:
        """
        Asynchronous execution entrypoint for appointment management.
        """
        # Validate input schema
        try:
            validated = ManageAppointmentInput(
                action=action,
                booking_code=booking_code,
                phone=phone,
                new_date=new_date,
                reason=reason,
            )
        except ValidationError as exc:
            first_err = exc.errors()[0] if exc.errors() else {}
            err_msg = first_err.get("msg", "Invalid input parameters")
            logger.info("Validation error in ManageAppointmentInput: %s", err_msg)
            return _failure(
                str(action),
                "يرجى التأكد من تزويدنا بكود الحجز أو رقم الموبايل لتنفيذ طلبك.",
                "invalid_input",
            )

        cairo_today = get_cairo_today()
        cairo_now = get_cairo_now()

        try:
            async with get_async_session(self.session_factory) as session:
                repo = ClinicRepository(session)

                if validated.action == ManageAppointmentAction.LOOKUP:
                    return await self._handle_lookup(
                        repo=repo,
                        booking_code=validated.booking_code,
                        phone=validated.phone,
                        cairo_today=cairo_today,
                    )
                elif validated.action == ManageAppointmentAction.CANCEL:
                    return await self._handle_cancel(
                        repo=repo,
                        booking_code=validated.booking_code,
                        phone=validated.phone,
                        reason=validated.reason,
                        cairo_today=cairo_today,
                        cairo_now=cairo_now,
                    )
                elif validated.action == ManageAppointmentAction.RESCHEDULE:
                    return await self._handle_reschedule(
                        repo=repo,
                        booking_code=validated.booking_code,
                        phone=validated.phone,
                        new_date=validated.new_date,
                        reason=validated.reason,
                        cairo_today=cairo_today,
                        cairo_now=cairo_now,
                    )
                else:
                    return _failure(
                        str(validated.action),
                        "إجراء غير مدعوم لإدارة المواعيد.",
                        "unsupported_action",
                    )

        except Exception as exc:
            # Privacy: no patient phone or name logged (NFR-4)
            logger.exception("Unexpected error in manage_appointment execution")
            return _failure(
                str(action),
                "عذراً، حدث خطأ أثناء تنفيذ هذا الإجراء. هل يمكنك إعادة المحاولة؟",
                f"unexpected_error: {type(exc).__name__}",
            )

    def execute(
        self,
        action: ManageAppointmentAction | str,
        booking_code: str | None = None,
        phone: str | None = None,
        new_date: dt.date | str | None = None,
        reason: str | None = None,
    ) -> ToolResult:
        """
        Synchronous execution entrypoint safe for existing running event loops.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(
                    lambda: asyncio.run(
                        self.aexecute(
                            action=action,
                            booking_code=booking_code,
                            phone=phone,
                            new_date=new_date,
                            reason=reason,
                        )
                    )
                ).result()
        return asyncio.run(
            self.aexecute(
                action=action,
                booking_code=booking_code,
                phone=phone,
                new_date=new_date,
                reason=reason,
            )
        )


# Global singleton instance
manage_appointment_tool = ManageAppointmentTool()


async def async_manage_appointment(
    action: ManageAppointmentAction | str,
    booking_code: str | None = None,
    phone: str | None = None,
    new_date: dt.date | str | None = None,
    reason: str | None = None,
) -> ToolResult:
    """Async convenience wrapper for LiveKit Voice Agent and LLM tool calling."""
    return await manage_appointment_tool.aexecute(
        action=action,
        booking_code=booking_code,
        phone=phone,
        new_date=new_date,
        reason=reason,
    )


def manage_appointment(
    action: ManageAppointmentAction | str,
    booking_code: str | None = None,
    phone: str | None = None,
    new_date: dt.date | str | None = None,
    reason: str | None = None,
) -> ToolResult:
    """Sync convenience wrapper for synchronous dispatchers and testing."""
    return manage_appointment_tool.execute(
        action=action,
        booking_code=booking_code,
        phone=phone,
        new_date=new_date,
        reason=reason,
    )
