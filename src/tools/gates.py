"""
Deterministic Write Safety Gates, Idempotency Store & Session Caller Identity (Feature 4.5).

Implements:
1. CallerSessionContext & caller_session_scope (contextvars): Server-side caller phone
   injection and confused-deputy spoofing prevention (R1 / R10).
2. Deterministic SHA-256 Idempotency Keys & 24-hour IdempotencyStore with live database
   confirmation cross-check and automatic cancellation invalidation (R3 / R9).
3. DeterministicWriteGate: Hard Python code preconditions verifying active doctor status,
   shift schedule existence, Cairo date/time bounds, strict shift capacity
   (booked_count < max_capacity), 14-day consultation eligibility, and caller ownership
   before any database write (R2 / R8).
"""

from __future__ import annotations

import contextvars
import datetime as dt
import hashlib
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.config import Settings, get_settings
from src.db.models import Appointment, Doctor
from src.db.repository import (
    ClinicRepository,
)
from src.db.schemas import (
    AppointmentStatus,
    DayOfWeek,
    DoctorAvailabilityRead,
    VisitType,
    clean_egyptian_phone,
)
from src.db.session import get_async_session
from src.tools.doctor_availability import CAIRO_TZ, get_cairo_today, match_doctors
from src.tools.schemas import (
    AppointmentBookingInput,
    AppointmentBookingOutput,
    ToolResult,
    parse_colloquial_date,
    parse_visit_type,
)

logger = logging.getLogger(__name__)

# Constants aligned with Phase 3 clinic rules
MAX_BOOKING_DAYS_AHEAD = 30
NEXT_AVAILABLE_LOOKAHEAD_DAYS = 7
CONSULTATION_ELIGIBILITY_DAYS = 14


# ==============================================================================
# 1. Session-Injected Caller Identity (contextvars)
# ==============================================================================


class CallerSessionContext(BaseModel):
    """
    Verified caller identity bound to the current async execution context.
    Derived exclusively from the authenticated session / LiveKit room metadata,
    never from untrusted LLM tool arguments.
    """

    model_config = ConfigDict(extra="forbid")

    caller_phone: str = Field(
        ...,
        description="Normalized Egyptian mobile number of the verified caller.",
    )
    session_id: str | None = Field(
        default=None,
        description="LiveKit room / call session identifier.",
    )
    caller_name: str | None = Field(
        default=None,
        description="Optional caller name from session metadata.",
    )
    tenant_id: str = Field(
        default="default",
        description="Clinic tenant identifier.",
    )
    branch_id: str = Field(
        default="main",
        description="Clinic branch identifier.",
    )


_current_caller_session: contextvars.ContextVar[CallerSessionContext | None] = (
    contextvars.ContextVar("caller_session_context", default=None)
)


def get_current_caller_session() -> CallerSessionContext | None:
    """Return the active CallerSessionContext for the current async task, or None."""
    return _current_caller_session.get()


@contextmanager
def caller_session_scope(
    caller_phone: str,
    *,
    session_id: str | None = None,
    caller_name: str | None = None,
    tenant_id: str = "default",
    branch_id: str = "main",
) -> Iterator[CallerSessionContext]:
    """
    Bind a verified caller phone and session metadata to the current contextvars scope.
    Automatically normalizes the Egyptian phone number and restores prior context on exit.
    """
    cleaned_phone = clean_egyptian_phone(caller_phone)
    ctx = CallerSessionContext(
        caller_phone=cleaned_phone,
        session_id=session_id,
        caller_name=caller_name.strip() if caller_name else None,
        tenant_id=tenant_id,
        branch_id=branch_id,
    )
    token = _current_caller_session.set(ctx)
    try:
        yield ctx
    finally:
        _current_caller_session.reset(token)


def resolve_effective_caller_phone(
    explicit_phone: str | None = None,
    settings: Settings | None = None,
) -> tuple[str | None, bool]:
    """
    Resolve the effective caller phone number in dual-mode:
    1. When a CallerSessionContext is active in contextvars (and enforce_session_caller_identity
       is enabled), forcibly inject the verified session phone. If explicit_phone was also
       passed and differs from the session phone, flag spoof_attempt_blocked=True.
    2. When no CallerSessionContext is active (standalone CLI or Phase 3 unit tests),
       fall back to the explicit_phone parameter.

    Returns:
        (effective_phone, spoof_attempt_blocked)
    """
    cfg = settings or get_settings()
    session_ctx = get_current_caller_session()

    if session_ctx is not None and cfg.enforce_session_caller_identity:
        spoof_blocked = False
        if explicit_phone is not None and str(explicit_phone).strip() != "":
            raw_explicit = str(explicit_phone).strip()
            try:
                norm_explicit = clean_egyptian_phone(raw_explicit)
            except ValueError:
                norm_explicit = raw_explicit

            if norm_explicit != session_ctx.caller_phone:
                spoof_blocked = True
                # Privacy invariant (NFR3): never log raw phone numbers
                logger.warning(
                    "Blocked caller phone spoofing override in session [session_id=%s]",
                    session_ctx.session_id or "active_session",
                )
        return session_ctx.caller_phone, spoof_blocked

    if explicit_phone is None or not str(explicit_phone).strip():
        return None, False

    raw = str(explicit_phone).strip()
    try:
        return clean_egyptian_phone(raw), False
    except ValueError:
        return raw, False


# ==============================================================================
# 2. Deterministic Idempotency Key & 24h IdempotencyStore
# ==============================================================================


def compute_booking_idempotency_key(
    patient_phone: str,
    doctor_id: int,
    schedule_id: int,
    appointment_date: dt.date | str,
) -> str:
    """
    Compute a deterministic SHA-256 idempotency key for a booking request:
    SHA-256("book:{clean_phone}:{doctor_id}:{schedule_id}:{YYYY-MM-DD}").
    """
    try:
        clean_phone = clean_egyptian_phone(str(patient_phone))
    except ValueError:
        clean_phone = re.sub(r"\s+", "", str(patient_phone))

    date_iso = (
        appointment_date.isoformat()
        if isinstance(appointment_date, dt.date)
        else str(appointment_date).strip()
    )
    canonical = f"book:{clean_phone}:{int(doctor_id)}:{int(schedule_id)}:{date_iso}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_reschedule_idempotency_key(
    booking_code: str,
    new_date: dt.date | str,
) -> str:
    """
    Compute a deterministic SHA-256 idempotency key for a reschedule request:
    SHA-256("reschedule:{BOOKING_CODE}:{YYYY-MM-DD}").
    """
    clean_code = re.sub(r"\s+", "", str(booking_code)).upper()
    date_iso = new_date.isoformat() if isinstance(new_date, dt.date) else str(new_date).strip()
    canonical = f"reschedule:{clean_code}:{date_iso}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyRecord(BaseModel):
    """Cached record of a confirmed idempotent booking operation."""

    model_config = ConfigDict(extra="ignore")

    idempotency_key: str
    booking_code: str
    doctor_id: int
    schedule_id: int
    appointment_date: str
    queue_number: int
    response_payload: dict[str, Any]
    message_ar: str
    created_at_monotonic: float
    expires_at_monotonic: float


class IdempotencyStore:
    """
    Thread-safe and async-safe 24-hour TTL Idempotency Registry with LRU eviction
    and automatic invalidation by key or booking_code.
    """

    def __init__(
        self,
        ttl_s: float | None = None,
        max_entries: int | None = None,
    ) -> None:
        cfg = get_settings()
        self.ttl_s: float = float(ttl_s if ttl_s is not None else cfg.idempotency_ttl_s)
        self.max_entries: int = int(
            max_entries if max_entries is not None else cfg.idempotency_max_entries
        )
        self._records: OrderedDict[str, IdempotencyRecord] = OrderedDict()
        self._code_to_key: dict[str, str] = {}
        self._lock = threading.RLock()

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        """Retrieve a non-expired IdempotencyRecord by key, or None."""
        now = time.monotonic()
        with self._lock:
            record = self._records.get(idempotency_key)
            if record is None:
                return None
            if now >= record.expires_at_monotonic:
                self._remove_unlocked(idempotency_key)
                return None
            self._records.move_to_end(idempotency_key)
            return record

    def get_by_booking_code(self, booking_code: str) -> IdempotencyRecord | None:
        """Retrieve a non-expired IdempotencyRecord by booking_code, or None."""
        clean_code = re.sub(r"\s+", "", str(booking_code)).upper()
        with self._lock:
            key = self._code_to_key.get(clean_code)
            if not key:
                return None
            return self.get(key)

    def put(
        self,
        *,
        idempotency_key: str,
        booking_code: str,
        doctor_id: int,
        schedule_id: int,
        appointment_date: str,
        queue_number: int,
        response_payload: dict[str, Any],
        message_ar: str,
        ttl_s: float | None = None,
    ) -> IdempotencyRecord:
        """Store or refresh an IdempotencyRecord with TTL and LRU capacity enforcement."""
        now = time.monotonic()
        effective_ttl = float(ttl_s if ttl_s is not None else self.ttl_s)
        clean_code = re.sub(r"\s+", "", str(booking_code)).upper()

        record = IdempotencyRecord(
            idempotency_key=idempotency_key,
            booking_code=clean_code,
            doctor_id=doctor_id,
            schedule_id=schedule_id,
            appointment_date=appointment_date,
            queue_number=queue_number,
            response_payload=dict(response_payload),
            message_ar=message_ar,
            created_at_monotonic=now,
            expires_at_monotonic=now + effective_ttl,
        )

        with self._lock:
            if idempotency_key in self._records:
                self._remove_unlocked(idempotency_key)

            self._records[idempotency_key] = record
            self._code_to_key[clean_code] = idempotency_key
            self._records.move_to_end(idempotency_key)

            while len(self._records) > self.max_entries:
                oldest_key, _ = next(iter(self._records.items()))
                self._remove_unlocked(oldest_key)

        return record

    def invalidate_key(self, idempotency_key: str) -> bool:
        """Remove an idempotency record by its SHA-256 key."""
        with self._lock:
            return self._remove_unlocked(idempotency_key)

    def invalidate_booking_code(self, booking_code: str) -> bool:
        """Invalidate any idempotency record associated with a booking code (e.g. on cancel)."""
        clean_code = re.sub(r"\s+", "", str(booking_code)).upper()
        with self._lock:
            key = self._code_to_key.get(clean_code)
            if not key:
                return False
            return self._remove_unlocked(key)

    def clear(self) -> None:
        """Clear all stored idempotency records."""
        with self._lock:
            self._records.clear()
            self._code_to_key.clear()

    def size(self) -> int:
        """Return current number of entries in store."""
        with self._lock:
            return len(self._records)

    def _remove_unlocked(self, idempotency_key: str) -> bool:
        record = self._records.pop(idempotency_key, None)
        if record is None:
            return False
        if self._code_to_key.get(record.booking_code) == idempotency_key:
            self._code_to_key.pop(record.booking_code, None)
        return True


_global_idempotency_store: IdempotencyStore | None = None


def get_idempotency_store() -> IdempotencyStore:
    """Return global singleton IdempotencyStore instance."""
    global _global_idempotency_store
    if _global_idempotency_store is None:
        _global_idempotency_store = IdempotencyStore()
    return _global_idempotency_store


# ==============================================================================
# 3. Deterministic Write Safety Gates (DeterministicWriteGate)
# ==============================================================================


class GateVerdict(BaseModel):
    """Structured outcome of a deterministic pre-write safety gate check."""

    model_config = ConfigDict(extra="ignore")

    allowed: bool = Field(description="True if all business and safety preconditions passed.")
    action: str = Field(
        description="Evaluated operation: 'book', 'cancel', 'reschedule', 'lookup'."
    )
    error_code: str | None = Field(
        default=None,
        description="Machine-readable rejection reason when allowed=False.",
    )
    message_ar: str | None = Field(
        default=None,
        description="Polite Egyptian Arabic explanation when rejected or downgraded.",
    )
    doctor_id: int | None = Field(default=None, description="Resolved active doctor ID.")
    doctor_name_ar: str | None = Field(default=None, description="Resolved doctor Arabic name.")
    specialty_name_ar: str | None = Field(
        default=None, description="Resolved specialty Arabic name."
    )
    schedule_id: int | None = Field(default=None, description="Resolved doctor shift schedule ID.")
    target_date: str | None = Field(default=None, description="Target ISO date YYYY-MM-DD.")
    day_name_ar: str | None = Field(default=None, description="Arabic weekday label.")
    shift_window: str | None = Field(default=None, description="Formatted shift window.")
    remaining_capacity: int = Field(default=0, ge=0, description="Remaining free slots in shift.")
    max_capacity: int = Field(default=0, ge=0, description="Maximum patient capacity of shift.")
    effective_visit_type: str | None = Field(
        default=None,
        description="Validated visit type ('examination' or 'consultation').",
    )
    visit_type_downgraded: bool = Field(
        default=False,
        description="True if consultation was downgraded to examination (outside 14-day window).",
    )
    effective_caller_phone: str | None = Field(
        default=None,
        description="Verified session caller phone or normalized explicit phone.",
    )
    spoof_attempt_blocked: bool = Field(
        default=False,
        description="True if an explicit phone conflicted with the active CallerSessionContext.",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Computed SHA-256 Idempotency-Key for the operation.",
    )
    existing_booking_code: str | None = Field(
        default=None,
        description="Resolved booking code for cancel/reschedule/duplicate checks.",
    )
    next_available: dict[str, Any] | None = Field(
        default=None,
        description="Nearest available doctor shift within 7 days when unavailable/full.",
    )
    candidates: list[dict[str, Any]] | None = Field(
        default=None,
        description="Candidate doctors when doctor name is ambiguous.",
    )
    latency_ms: float = Field(default=0.0, description="Gate check execution latency in ms.")


def _get_cairo_now() -> dt.datetime:
    return dt.datetime.now(tz=CAIRO_TZ)


def _format_fee_spoken(fee: float) -> str:
    return str(int(fee)) if float(fee).is_integer() else f"{fee:.2f}"


def _build_next_available_dict(slot: DoctorAvailabilityRead) -> dict[str, Any]:
    return {
        "target_date": slot.target_date.isoformat(),
        "day_name_ar": slot.day_name_ar,
        "shift_hours": slot.formatted_shift,
        "remaining_capacity": slot.remaining_capacity,
    }


def _check_appointment_cancellable(
    appt: Appointment,
    cairo_today: dt.date,
    cairo_now: dt.datetime,
) -> tuple[bool, str | None, str | None]:
    """Verify if an appointment can be cancelled or rescheduled."""
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


class DeterministicWriteGate:
    """
    Hard Python code safety gate enforcing clinic business and security invariants
    before any state-mutating database transaction (`book`, `cancel`, `reschedule`).
    """

    def __init__(
        self,
        session_factory: Any = None,
        idempotency_store: IdempotencyStore | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.idempotency_store = idempotency_store or get_idempotency_store()
        self.settings = settings or get_settings()

    async def _find_next_available_slot(
        self,
        repo: ClinicRepository,
        doctor_id: int,
        start_date: dt.date,
    ) -> DoctorAvailabilityRead | None:
        """Scan up to 7 days ahead for an active shift with remaining capacity."""
        for offset in range(1, NEXT_AVAILABLE_LOOKAHEAD_DAYS + 1):
            slot = await repo.get_doctor_availability(
                doctor_id, start_date + dt.timedelta(days=offset)
            )
            if slot.has_shift and slot.is_available:
                return slot
        return None

    async def _resolve_active_doctor(
        self,
        repo: ClinicRepository,
        doctor_id: int | None,
        doctor_name: str | None,
    ) -> tuple[Doctor | None, str | None, str | None, list[dict[str, Any]] | None]:
        """
        Resolve active doctor by ID or Arabic/English name.
        Returns: (doctor, error_code, error_message_ar, ambiguous_candidates)
        """
        if doctor_id is not None:
            doctor = await repo.get_doctor_by_id(doctor_id)
            if not doctor or not doctor.is_active:
                return (
                    None,
                    "doctor_not_found",
                    f"عذراً، مش لاقيين دكتور مسجل بالرقم {doctor_id}. ممكن تقولي اسم الدكتور؟",
                    None,
                )
            return doctor, None, None, None

        if not doctor_name or not str(doctor_name).strip():
            return (
                None,
                "invalid_input",
                "ممكن تقولي اسم الدكتور اللي حضرتك عايز تحجز معاه؟",
                None,
            )

        candidates = match_doctors(str(doctor_name), await repo.get_doctors(active_only=True))
        if not candidates:
            return (
                None,
                "doctor_not_found",
                f"عذراً، مش لاقيين دكتور باسم '{doctor_name}'. ممكن تتأكد من الاسم أو تقولي التخصص؟",
                None,
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
            return (
                None,
                "ambiguous_doctor",
                f"فيه أكتر من دكتور بالاسم ده: {names}. حضرتك تقصد مين فيهم؟",
                cand_data,
            )
        return candidates[0], None, None, None

    async def verify_booking(
        self,
        repo: ClinicRepository,
        *,
        patient_name: str | None = None,
        patient_phone: str | None = None,
        doctor_id: int | None = None,
        doctor_name: str | None = None,
        date: dt.date | dt.datetime | str | None = None,
        visit_type: VisitType | str | None = VisitType.EXAMINATION,
        notes: str | None = None,
        cairo_today: dt.date | None = None,
        cairo_now: dt.datetime | None = None,
    ) -> GateVerdict:
        """
        Verify all 6 pre-write booking invariants in deterministic Python code:
        1. Session caller identity injection & phone validation.
        2. Cairo date parsing & 30-day window validation.
        3. Active doctor resolution.
        4. Active shift existence & shift not ended today.
        5. Strict shift capacity gate (booked_count < max_capacity).
        6. Consultation 14-day eligibility check (auto-downgrade to examination if ineligible).
        """
        start_t = time.perf_counter()
        today = cairo_today or get_cairo_today()
        now_dt = cairo_now or _get_cairo_now()

        # 1. Resolve effective caller phone (session context overrides explicit phone)
        effective_phone, spoof_blocked = resolve_effective_caller_phone(
            patient_phone, settings=self.settings
        )

        # If caller name is missing, check if session context carries caller_name
        effective_name = patient_name
        if not effective_name or not str(effective_name).strip():
            session_ctx = get_current_caller_session()
            if session_ctx and session_ctx.caller_name:
                effective_name = session_ctx.caller_name

        # 2. Parse target date in Cairo timezone
        if date is None or (isinstance(date, str) and not date.strip()):
            return GateVerdict(
                allowed=False,
                action="book",
                error_code="invalid_date",
                message_ar="ممكن تقولي حضرتك عايز تحجز يوم إيه؟ مثلاً بكرة أو يوم السبت.",
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        try:
            if isinstance(date, dt.datetime):
                target_date = date.date()
            elif isinstance(date, dt.date):
                target_date = date
            else:
                target_date = parse_colloquial_date(str(date), today=today)
        except (ValueError, TypeError):
            return GateVerdict(
                allowed=False,
                action="book",
                error_code="invalid_date",
                message_ar="ممكن تقولي حضرتك عايز تحجز يوم إيه؟ مثلاً بكرة أو يوم السبت.",
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        # Validate remaining input fields via AppointmentBookingInput
        try:
            booking_input = AppointmentBookingInput(
                patient_name=effective_name,
                patient_phone=effective_phone,
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
            return GateVerdict(
                allowed=False,
                action="book",
                error_code="invalid_input",
                message_ar=msg,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        # 3. Check Cairo date window (not past, <= 30 days ahead)
        if target_date < today:
            return GateVerdict(
                allowed=False,
                action="book",
                error_code="past_date",
                message_ar=f"التاريخ {target_date.isoformat()} عدى خلاص. تحب تحجز النهارده أو يوم تاني قريب؟",
                target_date=target_date.isoformat(),
                effective_caller_phone=booking_input.patient_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )
        if target_date > today + dt.timedelta(days=MAX_BOOKING_DAYS_AHEAD):
            return GateVerdict(
                allowed=False,
                action="book",
                error_code="too_far_ahead",
                message_ar=f"الحجز متاح لحد {MAX_BOOKING_DAYS_AHEAD} يوم قدام بس. ممكن تختار يوم أقرب؟",
                target_date=target_date.isoformat(),
                effective_caller_phone=booking_input.patient_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        # 4. Resolve active doctor
        doc, doc_err, doc_msg, cand_list = await self._resolve_active_doctor(
            repo, booking_input.doctor_id, booking_input.doctor_name
        )
        if doc is None:
            return GateVerdict(
                allowed=False,
                action="book",
                error_code=doc_err or "doctor_not_found",
                message_ar=doc_msg,
                target_date=target_date.isoformat(),
                effective_caller_phone=booking_input.patient_phone,
                spoof_attempt_blocked=spoof_blocked,
                candidates=cand_list,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        doc_id = doc.id
        doc_name_ar = doc.name_ar
        spec_name_ar = doc.specialty.name_ar if doc.specialty else ""

        # 5. Verify shift schedule & strict capacity (booked_count < max_capacity)
        avail = await repo.get_doctor_availability(doc_id, target_date)
        date_label = f"يوم {avail.day_name_ar} الموافق {target_date.isoformat()}"
        now_time = now_dt.time().replace(tzinfo=None)

        rejection_reason: str | None = None
        rejection_code: str | None = None

        if not avail.has_shift or not avail.schedule_id:
            rejection_reason = f"{doc_name_ar} مش موجود {date_label}"
            rejection_code = "no_shift"
        elif target_date == today and avail.shift_end is not None and now_time >= avail.shift_end:
            rejection_reason = f"شفت {doc_name_ar} النهارده خلص"
            rejection_code = "shift_ended"
        elif not avail.is_available or avail.booked_count >= avail.max_capacity:
            rejection_reason = f"شفت {doc_name_ar} {date_label} مكتمل"
            rejection_code = "shift_full"

        if rejection_code is not None:
            next_slot = await self._find_next_available_slot(repo, doc_id, target_date)
            next_payload = _build_next_available_dict(next_slot) if next_slot else None
            if next_slot:
                msg = (
                    f"عذراً، {rejection_reason}. أقرب يوم متاح مع {doc_name_ar} هو {next_slot.day_name_ar} "
                    f"الموافق {next_slot.target_date.isoformat()} من الساعة {next_slot.formatted_shift}. "
                    "تحب أحجزلك فيه؟"
                )
            else:
                msg = (
                    f"عذراً، {rejection_reason}، ومفيش مواعيد متاحة مع {doc_name_ar} خلال الـ "
                    f"{NEXT_AVAILABLE_LOOKAHEAD_DAYS} أيام الجاية. ممكن أحولك لموظف الاستقبال يرتبلك ميعاد."
                )
            return GateVerdict(
                allowed=False,
                action="book",
                error_code=rejection_code,
                message_ar=msg,
                doctor_id=doc_id,
                doctor_name_ar=doc_name_ar,
                specialty_name_ar=spec_name_ar,
                schedule_id=avail.schedule_id,
                target_date=target_date.isoformat(),
                day_name_ar=avail.day_name_ar,
                shift_window=avail.formatted_shift,
                remaining_capacity=avail.remaining_capacity,
                max_capacity=avail.max_capacity,
                effective_caller_phone=booking_input.patient_phone,
                spoof_attempt_blocked=spoof_blocked,
                next_available=next_payload,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        # 6. Check 14-day consultation eligibility
        history = await repo.get_patient_appointments(booking_input.patient_phone)
        existing_same_day = next(
            (
                a
                for a in history
                if a.doctor_id == doc_id
                and a.appointment_date == target_date
                and a.status == AppointmentStatus.CONFIRMED.value
            ),
            None,
        )

        final_visit_type = booking_input.visit_type
        downgraded = False
        if booking_input.visit_type == VisitType.CONSULTATION:
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

        idem_key = compute_booking_idempotency_key(
            patient_phone=booking_input.patient_phone,
            doctor_id=doc_id,
            schedule_id=avail.schedule_id,
            appointment_date=target_date,
        )

        return GateVerdict(
            allowed=True,
            action="book",
            doctor_id=doc_id,
            doctor_name_ar=doc_name_ar,
            specialty_name_ar=spec_name_ar,
            schedule_id=avail.schedule_id,
            target_date=target_date.isoformat(),
            day_name_ar=avail.day_name_ar,
            shift_window=avail.formatted_shift,
            remaining_capacity=avail.remaining_capacity,
            max_capacity=avail.max_capacity,
            effective_visit_type=final_visit_type.value,
            visit_type_downgraded=downgraded,
            effective_caller_phone=booking_input.patient_phone,
            spoof_attempt_blocked=spoof_blocked,
            idempotency_key=idem_key,
            existing_booking_code=existing_same_day.booking_code if existing_same_day else None,
            latency_ms=(time.perf_counter() - start_t) * 1000.0,
        )

    async def verify_cancellation(
        self,
        repo: ClinicRepository,
        *,
        booking_code: str | None = None,
        phone: str | None = None,
        cairo_today: dt.date | None = None,
        cairo_now: dt.datetime | None = None,
    ) -> GateVerdict:
        """
        Verify cancellation preconditions in Python code:
        1. Session caller identity injection & ownership verification.
        2. Target appointment existence & CONFIRMED status.
        3. Appointment date not in past & doctor shift not started today.
        """
        start_t = time.perf_counter()
        today = cairo_today or get_cairo_today()
        now_dt = cairo_now or _get_cairo_now()

        effective_phone, spoof_blocked = resolve_effective_caller_phone(
            phone, settings=self.settings
        )
        clean_code = re.sub(r"\s+", "", str(booking_code)).upper() if booking_code else None

        if not clean_code and not effective_phone:
            return GateVerdict(
                allowed=False,
                action="cancel",
                error_code="invalid_input",
                message_ar="يرجى التأكد من تزويدنا بكود الحجز أو رقم الموبايل لتنفيذ طلبك.",
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        target_appt: Appointment | None = None
        if clean_code:
            appt = await repo.get_appointment_by_code(clean_code)
            if not appt:
                return GateVerdict(
                    allowed=False,
                    action="cancel",
                    error_code="not_found",
                    message_ar=f"عذراً، مش لاقيين أي حجز بكود '{clean_code}' للإلغاء.",
                    effective_caller_phone=effective_phone,
                    spoof_attempt_blocked=spoof_blocked,
                    latency_ms=(time.perf_counter() - start_t) * 1000.0,
                )
            if effective_phone:
                try:
                    appt_phone = clean_egyptian_phone(appt.patient.phone)
                    given_phone = clean_egyptian_phone(effective_phone)
                except ValueError:
                    appt_phone = appt.patient.phone
                    given_phone = effective_phone
                if appt_phone != given_phone:
                    return GateVerdict(
                        allowed=False,
                        action="cancel",
                        error_code="phone_mismatch",
                        message_ar="عذراً، كود الحجز ده مش متسجل بنفس رقم الموبايل المطلوب.",
                        effective_caller_phone=effective_phone,
                        spoof_attempt_blocked=spoof_blocked,
                        existing_booking_code=appt.booking_code,
                        latency_ms=(time.perf_counter() - start_t) * 1000.0,
                    )
            target_appt = appt
        else:
            # Cancel by phone alone
            try:
                all_appts = await repo.get_patient_appointments(effective_phone, active_only=False)
            except ValueError:
                return GateVerdict(
                    allowed=False,
                    action="cancel",
                    error_code="invalid_input",
                    message_ar="يرجى التأكد من تزويدنا بكود الحجز أو رقم موبايل مصري صحيح.",
                    effective_caller_phone=effective_phone,
                    spoof_attempt_blocked=spoof_blocked,
                    latency_ms=(time.perf_counter() - start_t) * 1000.0,
                )

            cancellable = [
                a for a in all_appts if _check_appointment_cancellable(a, today, now_dt)[0]
            ]
            if len(cancellable) == 0:
                return GateVerdict(
                    allowed=False,
                    action="cancel",
                    error_code="not_found",
                    message_ar="مش لاقيين أي حجز قادم متاح لإلغاؤه مسجل برقم الموبايل ده.",
                    effective_caller_phone=effective_phone,
                    spoof_attempt_blocked=spoof_blocked,
                    latency_ms=(time.perf_counter() - start_t) * 1000.0,
                )
            if len(cancellable) > 1:
                return GateVerdict(
                    allowed=False,
                    action="cancel",
                    error_code="multiple_appointments",
                    message_ar="حضرتك عندك أكتر من حجز قادم. ممكن توضح كود الحجز اللي تحب تلغيه؟",
                    effective_caller_phone=effective_phone,
                    spoof_attempt_blocked=spoof_blocked,
                    latency_ms=(time.perf_counter() - start_t) * 1000.0,
                )
            target_appt = cancellable[0]

        ok, err_code, err_msg = _check_appointment_cancellable(target_appt, today, now_dt)
        if not ok:
            return GateVerdict(
                allowed=False,
                action="cancel",
                error_code=err_code or "cannot_cancel",
                message_ar=err_msg or "الحجز غير متاح للإلغاء.",
                doctor_id=target_appt.doctor_id,
                schedule_id=target_appt.schedule_id,
                target_date=target_appt.appointment_date.isoformat(),
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                existing_booking_code=target_appt.booking_code,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        return GateVerdict(
            allowed=True,
            action="cancel",
            doctor_id=target_appt.doctor_id,
            doctor_name_ar=target_appt.doctor.name_ar if target_appt.doctor else None,
            schedule_id=target_appt.schedule_id,
            target_date=target_appt.appointment_date.isoformat(),
            effective_caller_phone=effective_phone,
            spoof_attempt_blocked=spoof_blocked,
            existing_booking_code=target_appt.booking_code,
            latency_ms=(time.perf_counter() - start_t) * 1000.0,
        )

    async def verify_reschedule(
        self,
        repo: ClinicRepository,
        *,
        booking_code: str | None = None,
        phone: str | None = None,
        new_date: dt.date | dt.datetime | str | None = None,
        cairo_today: dt.date | None = None,
        cairo_now: dt.datetime | None = None,
    ) -> GateVerdict:
        """
        Verify reschedule preconditions in Python code:
        1. Session caller identity injection & ownership verification.
        2. Old appointment exists and is cancellable/reschedulable.
        3. New target date is valid, within 30 days, and differs from old date.
        4. Same doctor has an active shift on new_date with strict capacity (booked_count < max_capacity).
        """
        start_t = time.perf_counter()
        today = cairo_today or get_cairo_today()
        now_dt = cairo_now or _get_cairo_now()

        effective_phone, spoof_blocked = resolve_effective_caller_phone(
            phone, settings=self.settings
        )
        clean_code = re.sub(r"\s+", "", str(booking_code)).upper() if booking_code else None

        if not clean_code:
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="missing_booking_code",
                message_ar="لتأجيل الميعاد، يرجى تزويدنا بكود الحجز والتاريخ الجديد المطلوب.",
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        old_appt = await repo.get_appointment_by_code(clean_code)
        if not old_appt:
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="not_found",
                message_ar=f"عذراً، مش لاقيين أي حجز مسجل بكود '{clean_code}' لتأجيله.",
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        if effective_phone:
            try:
                appt_phone = clean_egyptian_phone(old_appt.patient.phone)
                given_phone = clean_egyptian_phone(effective_phone)
            except ValueError:
                appt_phone = old_appt.patient.phone
                given_phone = effective_phone
            if appt_phone != given_phone:
                return GateVerdict(
                    allowed=False,
                    action="reschedule",
                    error_code="phone_mismatch",
                    message_ar="عذراً، كود الحجز ده مش متسجل بنفس رقم الموبايل المطلوب.",
                    effective_caller_phone=effective_phone,
                    spoof_attempt_blocked=spoof_blocked,
                    existing_booking_code=old_appt.booking_code,
                    latency_ms=(time.perf_counter() - start_t) * 1000.0,
                )

        ok, err_code, err_msg = _check_appointment_cancellable(old_appt, today, now_dt)
        if not ok:
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code=err_code or "cannot_reschedule",
                message_ar=err_msg or "الحجز غير متاح لتأجيله.",
                existing_booking_code=old_appt.booking_code,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        if new_date is None or (isinstance(new_date, str) and not new_date.strip()):
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="invalid_date",
                message_ar="ممكن توضح التاريخ الجديد اللي تحب تنقل الحجز ليه؟ مثلاً بكرة أو يوم السبت.",
                existing_booking_code=old_appt.booking_code,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        try:
            if isinstance(new_date, dt.datetime):
                target_new_date = new_date.date()
            elif isinstance(new_date, dt.date):
                target_new_date = new_date
            else:
                target_new_date = parse_colloquial_date(str(new_date), today=today)
        except (ValueError, TypeError):
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="invalid_date",
                message_ar="ممكن توضح التاريخ الجديد اللي تحب تنقل الحجز ليه؟ مثلاً بكرة أو يوم السبت.",
                existing_booking_code=old_appt.booking_code,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        if target_new_date < today:
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="past_date",
                message_ar=f"التاريخ الجديد {target_new_date.isoformat()} عدى خلاص. ممكن تختار ميعاد قادم؟",
                target_date=target_new_date.isoformat(),
                existing_booking_code=old_appt.booking_code,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        if target_new_date > today + dt.timedelta(days=MAX_BOOKING_DAYS_AHEAD):
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="too_far_ahead",
                message_ar=f"التأجيل متاح لحد {MAX_BOOKING_DAYS_AHEAD} يوم قدام بس. ممكن تختار يوم أقرب؟",
                target_date=target_new_date.isoformat(),
                existing_booking_code=old_appt.booking_code,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        if target_new_date == old_appt.appointment_date:
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="same_date",
                message_ar=f"الميعاد الجديد هو نفس ميعاد الحجز الحالي ({target_new_date.isoformat()}). يرجى اختيار تاريخ مختلف.",
                target_date=target_new_date.isoformat(),
                existing_booking_code=old_appt.booking_code,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        doc_id = old_appt.doctor_id
        doc_name_ar = old_appt.doctor.name_ar if old_appt.doctor else ""
        avail = await repo.get_doctor_availability(doc_id, target_new_date)
        date_label = f"يوم {avail.day_name_ar} الموافق {target_new_date.isoformat()}"
        now_time = now_dt.time().replace(tzinfo=None)

        rejection_code: str | None = None
        rejection_msg: str | None = None

        if not avail.has_shift or not avail.schedule_id:
            rejection_code = "no_shift"
            rejection_msg = f"عذراً، {doc_name_ar} مش موجود {date_label}. "
        elif (
            target_new_date == today and avail.shift_end is not None and now_time >= avail.shift_end
        ):
            rejection_code = "shift_ended"
            rejection_msg = f"عذراً، شفت {doc_name_ar} النهارده خلص. "
        elif not avail.is_available or avail.booked_count >= avail.max_capacity:
            rejection_code = "shift_full"
            rejection_msg = f"عذراً، شفت {doc_name_ar} {date_label} مكتمل العدد بالكامل. "

        if rejection_code is not None:
            next_slot = await self._find_next_available_slot(repo, doc_id, target_new_date)
            next_payload = _build_next_available_dict(next_slot) if next_slot else None
            if next_slot:
                rejection_msg = (rejection_msg or "") + (
                    f"أقرب يوم متاح مع الطبيب هو {next_slot.day_name_ar} الموافق {next_slot.target_date.isoformat()} "
                    f"من الساعة {next_slot.formatted_shift}. تحب نأجل ليه؟"
                )
            elif rejection_code == "no_shift":
                rejection_msg = (
                    (rejection_msg or "")
                    + f"ومفيش مواعيد متاحة مع الطبيب خلال الـ {NEXT_AVAILABLE_LOOKAHEAD_DAYS} أيام الجاية."
                )
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code=rejection_code,
                message_ar=rejection_msg,
                doctor_id=doc_id,
                doctor_name_ar=doc_name_ar,
                schedule_id=avail.schedule_id,
                target_date=target_new_date.isoformat(),
                day_name_ar=avail.day_name_ar,
                shift_window=avail.formatted_shift,
                remaining_capacity=avail.remaining_capacity,
                max_capacity=avail.max_capacity,
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                existing_booking_code=old_appt.booking_code,
                next_available=next_payload,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        # Duplicate check on target new date
        patient_history = await repo.get_patient_appointments(old_appt.patient.phone)
        if any(
            a.doctor_id == doc_id
            and a.appointment_date == target_new_date
            and a.status == AppointmentStatus.CONFIRMED.value
            for a in patient_history
        ):
            return GateVerdict(
                allowed=False,
                action="reschedule",
                error_code="duplicate_booking",
                message_ar=f"حضرتك عندك حجز مؤكد بالفعل مع {doc_name_ar} {date_label}.",
                doctor_id=doc_id,
                doctor_name_ar=doc_name_ar,
                schedule_id=avail.schedule_id,
                target_date=target_new_date.isoformat(),
                effective_caller_phone=effective_phone,
                spoof_attempt_blocked=spoof_blocked,
                existing_booking_code=old_appt.booking_code,
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        idem_key = compute_reschedule_idempotency_key(old_appt.booking_code, target_new_date)
        return GateVerdict(
            allowed=True,
            action="reschedule",
            doctor_id=doc_id,
            doctor_name_ar=doc_name_ar,
            schedule_id=avail.schedule_id,
            target_date=target_new_date.isoformat(),
            day_name_ar=avail.day_name_ar,
            shift_window=avail.formatted_shift,
            remaining_capacity=avail.remaining_capacity,
            max_capacity=avail.max_capacity,
            effective_caller_phone=effective_phone or old_appt.patient.phone,
            spoof_attempt_blocked=spoof_blocked,
            idempotency_key=idem_key,
            existing_booking_code=old_appt.booking_code,
            latency_ms=(time.perf_counter() - start_t) * 1000.0,
        )

    async def check_idempotent_booking_replay(
        self,
        repo: ClinicRepository,
        *,
        idempotency_key: str,
        effective_phone: str,
        doctor_id: int,
        target_date: dt.date,
        patient_name: str,
        spoof_blocked: bool = False,
    ) -> ToolResult | None:
        """
        Check whether a booking request with `idempotency_key` already has an active
        CONFIRMED appointment (via IdempotencyStore or live DB row).
        If the appointment was cancelled, invalidates the stale key and returns None.
        """
        cached = self.idempotency_store.get(idempotency_key)
        if cached is not None:
            live_appt = await repo.get_appointment_by_code(cached.booking_code)
            if live_appt and live_appt.status == AppointmentStatus.CONFIRMED.value:
                payload = dict(cached.response_payload)
                payload["idempotency_key"] = idempotency_key
                payload["idempotent_replay"] = True
                payload["spoof_attempt_blocked"] = spoof_blocked
                return ToolResult(
                    success=True,
                    message=cached.message_ar,
                    data=payload,
                )
            # Appointment was cancelled or removed in DB -> invalidate cache
            self.idempotency_store.invalidate_key(idempotency_key)

        # Cross-check live DB in case store was restarted within the same day
        history = await repo.get_patient_appointments(effective_phone)
        existing = next(
            (
                a
                for a in history
                if a.doctor_id == doctor_id
                and a.appointment_date == target_date
                and a.status == AppointmentStatus.CONFIRMED.value
            ),
            None,
        )
        if existing is not None:
            doc_name = existing.doctor.name_ar if existing.doctor else ""
            spec_name = (
                existing.doctor.specialty.name_ar
                if existing.doctor and existing.doctor.specialty
                else ""
            )
            day_ar = DayOfWeek.from_date(existing.appointment_date).label_ar()
            shift_str = existing.schedule.formatted_shift if existing.schedule else ""
            visit_enum = VisitType(existing.visit_type)
            msg = (
                f"تمام، حجزك مؤكد بالفعل ({visit_enum.label_ar()}) مع {doc_name} ({spec_name}) "
                f"يوم {day_ar} الموافق {existing.appointment_date.isoformat()} من الساعة {shift_str}. "
                f"نمرة حجزك {existing.queue_number}، وكود الحجز {existing.booking_code}، "
                f"والسعر {_format_fee_spoken(existing.fee)} جنيه."
            )
            output = AppointmentBookingOutput(
                booking_code=existing.booking_code,
                patient_name=existing.patient.name if existing.patient else patient_name,
                doctor_name_ar=doc_name,
                specialty_name_ar=spec_name,
                appointment_date=existing.appointment_date.isoformat(),
                queue_number=existing.queue_number,
                shift_window=shift_str,
                visit_type_ar=visit_enum.label_ar(),
                fee=float(existing.fee),
                message=msg,
            )
            payload = output.model_dump()
            payload["visit_type"] = visit_enum.value
            payload["visit_type_downgraded"] = False
            payload["idempotency_key"] = idempotency_key
            payload["idempotent_replay"] = True
            payload["spoof_attempt_blocked"] = spoof_blocked

            self.idempotency_store.put(
                idempotency_key=idempotency_key,
                booking_code=existing.booking_code,
                doctor_id=doctor_id,
                schedule_id=existing.schedule_id,
                appointment_date=existing.appointment_date.isoformat(),
                queue_number=existing.queue_number,
                response_payload=payload,
                message_ar=msg,
            )
            return ToolResult(success=True, message=msg, data=payload)

        return None

    async def execute_booking(
        self,
        *,
        patient_name: str | None = None,
        patient_phone: str | None = None,
        doctor_id: int | None = None,
        doctor_name: str | None = None,
        date: dt.date | dt.datetime | str | None = None,
        visit_type: VisitType | str | None = VisitType.EXAMINATION,
        notes: str | None = None,
    ) -> ToolResult:
        """
        Execute a booking governed by DeterministicWriteGate and 24h IdempotencyStore.
        On idempotent retry within 24h (while appointment is still CONFIRMED), returns
        the confirmed booking with idempotent_replay=True without incrementing queue_number.
        """
        async with get_async_session(self.session_factory) as session:
            repo = ClinicRepository(session)
            verdict = await self.verify_booking(
                repo,
                patient_name=patient_name,
                patient_phone=patient_phone,
                doctor_id=doctor_id,
                doctor_name=doctor_name,
                date=date,
                visit_type=visit_type,
                notes=notes,
            )
            if not verdict.allowed:
                extra: dict[str, Any] = {
                    "gate_verdict": verdict.model_dump(),
                    "spoof_attempt_blocked": verdict.spoof_attempt_blocked,
                }
                if verdict.next_available is not None or verdict.error_code in (
                    "no_shift",
                    "shift_ended",
                    "shift_full",
                ):
                    extra["next_available"] = verdict.next_available
                if verdict.candidates:
                    extra["candidates"] = verdict.candidates
                return ToolResult(
                    success=False,
                    message=verdict.message_ar or "تعذر إتمام الحجز.",
                    error=verdict.error_code or "gate_rejected",
                    data=extra,
                )

            assert verdict.idempotency_key is not None
            assert verdict.effective_caller_phone is not None
            assert verdict.doctor_id is not None
            assert verdict.target_date is not None

            target_date_obj = dt.date.fromisoformat(verdict.target_date)
            effective_name = (
                patient_name.strip()
                if patient_name and patient_name.strip()
                else (
                    get_current_caller_session().caller_name
                    if get_current_caller_session() and get_current_caller_session().caller_name
                    else ""
                )
            )

            # Check idempotent replay before touching DB writes
            replay_result = await self.check_idempotent_booking_replay(
                repo,
                idempotency_key=verdict.idempotency_key,
                effective_phone=verdict.effective_caller_phone,
                doctor_id=verdict.doctor_id,
                target_date=target_date_obj,
                patient_name=effective_name,
                spoof_blocked=verdict.spoof_attempt_blocked,
            )
            if replay_result is not None:
                return replay_result

        # Perform atomic booking via AppointmentBookingTool
        from src.tools.appointment_booking import AppointmentBookingTool

        booking_tool = AppointmentBookingTool(session_factory=self.session_factory)
        result = await booking_tool.aexecute(
            patient_name=effective_name,
            patient_phone=verdict.effective_caller_phone,
            doctor_id=verdict.doctor_id,
            date=target_date_obj,
            visit_type=parse_visit_type(verdict.effective_visit_type),
            notes=notes,
        )
        if result.success and result.data:
            result.data["idempotency_key"] = verdict.idempotency_key
            result.data["idempotent_replay"] = False
            result.data["spoof_attempt_blocked"] = verdict.spoof_attempt_blocked
            self.idempotency_store.put(
                idempotency_key=verdict.idempotency_key,
                booking_code=result.data["booking_code"],
                doctor_id=verdict.doctor_id,
                schedule_id=verdict.schedule_id or 0,
                appointment_date=verdict.target_date,
                queue_number=result.data["queue_number"],
                response_payload=result.data,
                message_ar=result.message,
            )
        return result


__all__ = [
    "CallerSessionContext",
    "DeterministicWriteGate",
    "GateVerdict",
    "IdempotencyRecord",
    "IdempotencyStore",
    "caller_session_scope",
    "compute_booking_idempotency_key",
    "compute_reschedule_idempotency_key",
    "get_current_caller_session",
    "get_idempotency_store",
    "resolve_effective_caller_phone",
]
