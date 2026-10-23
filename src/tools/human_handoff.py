"""
Receptionist Escalation and Handoff Tool for Egyptian Polyclinics (Feature 3.6).

Handles patient call escalation to clinic front-desk reception, department triage
(Reception, Nursing, Billing, Emergency), emergency keyword safety net,
reception working hours validation, ticket de-duplication, and deterministic
wait estimation with polite Egyptian Arabic voice messages.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import get_settings
from src.db.repository import ClinicRepository
from src.db.schemas import EscalationStatus, clean_egyptian_phone
from src.db.session import get_async_session
from src.tools.appointment_booking import get_cairo_now
from src.tools.doctor_availability import get_cairo_today
from src.tools.schemas import (
    HandoffDepartmentEnum,
    HandoffUrgencyEnum,
    ToolResult,
    _normalize_arabic,
)

logger = logging.getLogger(__name__)

# ==============================================================================
# Arabic Labels & Department Roster
# ==============================================================================

DEPARTMENT_NAMES_ARABIC: dict[str, str] = {
    HandoffDepartmentEnum.RECEPTION.value: "الاستقبال",
    HandoffDepartmentEnum.NURSING.value: "التمريض",
    HandoffDepartmentEnum.BILLING.value: "الحسابات",
    HandoffDepartmentEnum.EMERGENCY.value: "الطوارئ",
    "reception": "الاستقبال",
    "nursing": "التمريض",
    "billing": "الحسابات",
    "emergency": "الطوارئ",
    # Legacy mappings
    "customer_support": "الاستقبال",
    "kitchen_manager": "الاستقبال",
    "delivery_dispatch": "الاستقبال",
}

URGENCY_RANKS: dict[str, int] = {
    HandoffUrgencyEnum.LOW.value: 1,
    HandoffUrgencyEnum.MEDIUM.value: 2,
    HandoffUrgencyEnum.URGENT.value: 3,
    HandoffUrgencyEnum.EMERGENCY.value: 4,
    "low": 1,
    "medium": 2,
    "urgent": 3,
    "emergency": 4,
    # Legacy mappings
    "high": 3,
    "critical": 4,
}

# ==============================================================================
# Pure Helper Functions (Unit-Testable)
# ==============================================================================

# Compiled regex patterns for emergency detection (FR-2.1)
_EMERGENCY_PATTERNS = [
    # Chest pain / Heart attack
    re.compile(r"(?:الم|وجع|تعب|ثقل|وجع جامد|الم شديد).*(?:صدر|قلب)"),
    re.compile(r"(?:صدر|قلب).*(?:الم|وجع|بيوجع|تعب)"),
    re.compile(r"ذبحة|ذبحه|ازمة قلبية|ازمه قلبيه|جلطة|جلطه|chest\s*pain|heart\s*attack"),
    # Breathing difficulties / Choking
    re.compile(r"(?:مش قادر|مش قادره|مش قادرين|صعوبة|صعوبه|ضيق|مش عارف).*(?:تنفس|اتنفس|نفس)"),
    re.compile(
        r"اختناق|بيختنق|بتختنق|شرقان|شرقانه|difficulty\s*breathing|shortness\s*of\s*breath|choking"
    ),
    # Severe bleeding
    re.compile(r"نزيف|بينزف|بتنزف|دم\s*كتير|نزف|severe\s*bleeding|bleeding|hemorrhage"),
    # Fainting / Unconsciousness / Coma
    re.compile(r"اغما|اغم[يى]|مغم[يى]|غيبوب|faint|unconscious|coma"),
    re.compile(r"(?:فقد|فقدان|فاقد|فاقده|فاقدة).*(?:وعي|الوعي)"),
    re.compile(r"مش واعي|مش واعيه|مش واعية"),
    # Seizures / Convulsions
    re.compile(r"تشنج|صرع|seizure|convulsion|بيترعش جامد"),
    # Stroke / Paralysis
    re.compile(r"شلل|جلطة مخية|جلطه مخيه|stroke|paralysis"),
    re.compile(r"اعوجاج.*فم"),
    # Poisoning / Overdose
    re.compile(r"تسمم|جرعة زائدة|جرعه زائده|جرعة زايدة|poison|poisoning|overdose"),
    re.compile(r"شرب.*(?:كلور|دوا|دواء|منظف)"),
    # Serious accident / Severe trauma
    re.compile(r"حادث|حادثة|حادثه|كسر مضاعف|حرق خطير|severe\s*accident|trauma"),
    # Self-harm / Suicide
    re.compile(r"انتحار|هينتحر|هتنتحر|suicide"),
]


def detect_emergency(text: str) -> bool:
    """
    Detect life-threatening medical emergency symptoms in caller text (FR-2.1).
    Evaluates Egyptian colloquial, Modern Standard Arabic, and English.
    """
    if not text or not text.strip():
        return False

    normalized = _normalize_arabic(text)
    lower_raw = text.lower()

    for pattern in _EMERGENCY_PATTERNS:
        if pattern.search(normalized) or pattern.search(lower_raw):
            return True

    return False


def is_reception_open(now_cairo: dt.datetime, settings_obj: Any = None) -> bool:
    """
    Determine if clinic reception desk is currently operating (FR-3.1).
    Friday hours: reception_friday_open_time (14:00) to reception_close_time (22:00).
    Sat-Thu hours: reception_open_time (09:00) to reception_close_time (22:00).
    Boundary: inclusive at open, exclusive at close.
    """
    cfg = settings_obj or get_settings()

    def _parse_time(t_str: str, default_h: int, default_m: int) -> dt.time:
        try:
            parts = t_str.strip().split(":")
            return dt.time(int(parts[0]), int(parts[1]))
        except (ValueError, TypeError, IndexError):
            return dt.time(default_h, default_m)

    open_norm = _parse_time(getattr(cfg, "reception_open_time", "09:00"), 9, 0)
    close_norm = _parse_time(getattr(cfg, "reception_close_time", "22:00"), 22, 0)
    open_friday = _parse_time(getattr(cfg, "reception_friday_open_time", "14:00"), 14, 0)

    current_time = now_cairo.time()

    # Python weekday: Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
    if now_cairo.weekday() == 4:  # Friday
        return open_friday <= current_time < close_norm
    else:  # Sat - Thu
        return open_norm <= current_time < close_norm


def estimate_wait_seconds(urgency: str | HandoffUrgencyEnum, open_ahead: int = 0) -> int:
    """
    Calculate deterministic estimated queue wait in seconds (FR-3.3).
    Formula: base(urgency) + 30s * open_ahead, capped at 600s.
    Emergency urgency is always 0.
    """
    u_str = urgency.value if hasattr(urgency, "value") else str(urgency).lower()

    if u_str in (HandoffUrgencyEnum.EMERGENCY.value, "emergency", "critical"):
        return 0

    base_map = {
        HandoffUrgencyEnum.URGENT.value: 30,
        "urgent": 30,
        "high": 30,
        HandoffUrgencyEnum.MEDIUM.value: 60,
        "medium": 60,
        HandoffUrgencyEnum.LOW.value: 120,
        "low": 120,
    }
    base = base_map.get(u_str, 60)
    total = base + (30 * max(0, open_ahead))
    return min(600, total)


def mask_phone_for_speech(phone: str | None) -> str:
    """
    Mask phone number for safe voice readback, speaking only the last 3 digits (NFR-3).
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) >= 3:
        return digits[-3:]
    return phone


def build_voice_message(
    status: str,
    urgency: str,
    department: str,
    ticket_id: str,
    caller_name: str | None = None,
    caller_phone: str | None = None,
    wait_seconds: int = 0,
    emergency_phone: str = "123",
) -> str:
    """
    Generate reassuring, natural Egyptian Arabic spoken response (FR-6).
    """
    greeting = (
        f"أهلاً بك يا {caller_name.strip()}. "
        if caller_name and caller_name.strip()
        else "تحت أمرك تماماً. "
    )
    dept_ar = DEPARTMENT_NAMES_ARABIC.get(department, "الاستقبال")

    if status == EscalationStatus.TRANSFERRED.value or urgency in ("emergency", "critical"):
        return (
            f"{greeting}نظراً لأهمية الحالة وحرصاً على سلامتكم، يرجى الاتصال فوراً بالإسعاف على رقم "
            f"{emergency_phone} أو التوجه لأقرب طوارئ. جاري تحويل مكالمتك الآن إلى {dept_ar}، "
            f"ورقم التذكرة هو {ticket_id}."
        )

    if status == EscalationStatus.QUEUED.value:
        if wait_seconds <= 45:
            wait_text = f"حوالي {wait_seconds} ثانية"
        elif wait_seconds <= 90:
            wait_text = "حوالي دقيقة"
        elif wait_seconds <= 150:
            wait_text = "حوالي دقيقتين"
        else:
            mins = max(1, round(wait_seconds / 60))
            wait_text = f"حوالي {mins} دقائق"

        return (
            f"{greeting}تم تسجيل طلبك وجاري تحويلك إلى قسم {dept_ar}. متوسط الانتظار {wait_text}، "
            f"ورقم التذكرة {ticket_id}. يرجى البقاء على الخط."
        )

    # status == CALLBACK
    if caller_phone and caller_phone.strip():
        last3 = mask_phone_for_speech(caller_phone)
        return (
            f"{greeting}قسم الاستقبال غير متاح حالياً؛ مواعيد العمل من 9 صباحاً حتى 10 مساءً والجمعة من 2 ظهراً. "
            f"تم تسجيل طلبك برقم {ticket_id} وسنعاود الاتصال بك على الرقم المنتهي بـ {last3} فور فتح العيادة."
        )
    else:
        return (
            f"{greeting}قسم الاستقبال غير متاح حالياً؛ مواعيد العمل من 9 صباحاً حتى 10 مساءً والجمعة من 2 ظهراً. "
            f"تم تسجيل طلبك برقم {ticket_id}، ويرجى تزويدنا برقم الموبايل للتواصل معك فور فتح العيادة."
        )


# ==============================================================================
# Tool Implementation
# ==============================================================================


class ReceptionistHandoffTool:
    """
    Production Receptionist Escalation Tool for Egyptian Polyclinics (Feature 3.6).
    Creates persistent database tickets, applies emergency safety net, handles working hours,
    and supports call de-duplication with 400ms resilient fallback.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        timeout_s: float = 0.4,
    ) -> None:
        self.session_factory = session_factory
        self.timeout_s = timeout_s

    def _normalize_department(self, dept: Any) -> str:
        d = str(dept.value if hasattr(dept, "value") else dept or "").strip().lower()
        if d in ("reception", "customer_support", "kitchen_manager", "delivery_dispatch"):
            return HandoffDepartmentEnum.RECEPTION.value
        if d in ("nursing",):
            return HandoffDepartmentEnum.NURSING.value
        if d in ("billing",):
            return HandoffDepartmentEnum.BILLING.value
        if d in ("emergency",):
            return HandoffDepartmentEnum.EMERGENCY.value
        logger.warning("Unknown department '%s' requested, defaulting to reception", dept)
        return HandoffDepartmentEnum.RECEPTION.value

    def _normalize_urgency(self, urg: Any) -> str:
        u = str(urg.value if hasattr(urg, "value") else urg or "").strip().lower()
        if u in ("emergency", "critical"):
            return HandoffUrgencyEnum.EMERGENCY.value
        if u in ("urgent", "high"):
            return HandoffUrgencyEnum.URGENT.value
        if u in ("medium",):
            return HandoffUrgencyEnum.MEDIUM.value
        if u in ("low",):
            return HandoffUrgencyEnum.LOW.value
        logger.warning("Unknown urgency '%s' requested, defaulting to medium", urg)
        return HandoffUrgencyEnum.MEDIUM.value

    async def aexecute(
        self,
        reason: str | None = None,
        caller_name: str | None = None,
        caller_phone: str | None = None,
        department: str | HandoffDepartmentEnum = HandoffDepartmentEnum.RECEPTION,
        urgency: str | HandoffUrgencyEnum = HandoffUrgencyEnum.MEDIUM,
        summary: str | None = None,
        session_id: str | None = None,
        # Legacy keyword compatibility
        customer_name: str | None = None,
        customer_phone: str | None = None,
        conversation_summary: str | None = None,
    ) -> ToolResult:
        """
        Asynchronously process a human escalation request (non-blocking for LiveKit turns).
        """
        # Resolve parameter aliases
        final_name = (caller_name or customer_name or "").strip() or None
        raw_phone = (caller_phone or customer_phone or "").strip() or None
        final_summary = (summary or conversation_summary or "").strip() or None

        # Clean phone leniently (FR-1.3)
        final_phone = raw_phone
        if raw_phone:
            try:
                final_phone = clean_egyptian_phone(raw_phone)
            except ValueError:
                final_phone = raw_phone

        # Default reason if omitted on direct calls (FR-1.4)
        clean_reason = (reason or "").strip()
        if not clean_reason:
            clean_reason = "طلب التحدث مع موظف الاستقبال"

        # Normalize requested department & urgency
        clean_dept = self._normalize_department(department)
        clean_urgency = self._normalize_urgency(urgency)

        # FR-2: Emergency Safety Net
        combined_text = f"{clean_reason} {final_summary or ''}"
        is_emergency = detect_emergency(combined_text) or (
            clean_urgency == HandoffUrgencyEnum.EMERGENCY.value
        )

        if is_emergency:
            effective_urgency = HandoffUrgencyEnum.EMERGENCY.value
            effective_dept = HandoffDepartmentEnum.EMERGENCY.value
        else:
            effective_urgency = clean_urgency
            effective_dept = clean_dept

        # FR-3: Reception hours & Status determination
        cairo_now = get_cairo_now()
        cairo_today = get_cairo_today()
        reception_open = is_reception_open(cairo_now)

        if is_emergency:
            status = EscalationStatus.TRANSFERRED.value
            wait_seconds = 0
        elif reception_open:
            status = EscalationStatus.QUEUED.value
            wait_seconds = estimate_wait_seconds(effective_urgency, 0)
        else:
            status = EscalationStatus.CALLBACK.value
            wait_seconds = 0

        needs_phone = bool(status == EscalationStatus.CALLBACK.value and not final_phone)

        # Database persistence task with 400ms timeout budget (FR-7)
        async def _persist_escalation() -> tuple[str, str, str, str, int, bool, bool]:
            async with get_async_session(self.session_factory) as session:
                repo = ClinicRepository(session)

                current_wait = wait_seconds
                if status == EscalationStatus.QUEUED.value:
                    ahead = await repo.count_open_escalations(min_urgency=effective_urgency)
                    current_wait = estimate_wait_seconds(effective_urgency, ahead)

                # FR-5: De-duplication check (within last 10 minutes)
                existing = None
                if final_phone:
                    since_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
                    existing = await repo.find_recent_open_escalation(final_phone, since_utc)

                if existing:
                    # Upgrade priority if new request has higher urgency
                    new_rank = URGENCY_RANKS.get(effective_urgency, 2)
                    old_rank = URGENCY_RANKS.get(existing.urgency, 2)

                    upgraded_urgency = existing.urgency
                    upgraded_dept = existing.department
                    upgraded_status = existing.status
                    upgraded_wait = existing.estimated_wait_seconds

                    if new_rank > old_rank:
                        upgraded_urgency = effective_urgency
                        upgraded_dept = effective_dept
                        upgraded_status = status
                        upgraded_wait = current_wait
                        existing.urgency = effective_urgency
                        existing.department = effective_dept
                        existing.status = status
                        existing.estimated_wait_seconds = current_wait

                    if clean_reason and clean_reason != existing.reason:
                        old_s = existing.summary or existing.reason
                        existing.summary = f"{old_s} | [تحديث]: {clean_reason}"[:1000]

                    if final_name and not existing.caller_name:
                        existing.caller_name = final_name
                    if session_id and not existing.session_id:
                        existing.session_id = session_id

                    await repo.save_escalation(existing)

                    return (
                        existing.ticket_id,
                        upgraded_status,
                        upgraded_urgency,
                        upgraded_dept,
                        upgraded_wait,
                        True,  # deduplicated
                        True,  # persisted
                    )

                # Create new persistent escalation ticket
                escalation = await repo.create_escalation(
                    reason=clean_reason,
                    caller_name=final_name,
                    caller_phone=final_phone,
                    department=effective_dept,
                    urgency=effective_urgency,
                    status=status,
                    summary=final_summary,
                    session_id=session_id,
                    estimated_wait_seconds=current_wait,
                    cairo_date=cairo_today,
                )
                return (
                    escalation.ticket_id,
                    escalation.status,
                    escalation.urgency,
                    escalation.department,
                    escalation.estimated_wait_seconds,
                    False,  # deduplicated
                    True,  # persisted
                )

        try:
            (
                final_ticket_id,
                final_status,
                final_urgency_res,
                final_dept_res,
                final_wait_res,
                is_dedup,
                is_persisted,
            ) = await asyncio.wait_for(_persist_escalation(), timeout=self.timeout_s)
        except Exception as exc:  # noqa: BLE001
            # Fallback path (FR-7.2): Resilience over logging, never crash caller turn
            logger.error("Escalation DB execution failed or timed out: %s", type(exc).__name__)
            final_ticket_id = f"ESC-TMP-{uuid.uuid4().hex[:6].upper()}"
            final_status = status
            final_urgency_res = effective_urgency
            final_dept_res = effective_dept
            final_wait_res = wait_seconds
            is_dedup = False
            is_persisted = False

        # Privacy-safe logging (NFR-3)
        logger.info(
            "Escalation processed: ticket_id=%s, urgency=%s, dept=%s, status=%s, persisted=%s, dedup=%s",
            final_ticket_id,
            final_urgency_res,
            final_dept_res,
            final_status,
            is_persisted,
            is_dedup,
        )

        spoken_msg = build_voice_message(
            status=final_status,
            urgency=final_urgency_res,
            department=final_dept_res,
            ticket_id=final_ticket_id,
            caller_name=final_name,
            caller_phone=final_phone,
            wait_seconds=final_wait_res,
            emergency_phone=get_settings().emergency_phone,
        )

        dept_ar = DEPARTMENT_NAMES_ARABIC.get(final_dept_res, "الاستقبال")

        output_payload = {
            "ticket_id": final_ticket_id,
            "status": final_status,
            "urgency": final_urgency_res,
            "department": final_dept_res,
            "department_ar": dept_ar,
            "estimated_wait_seconds": final_wait_res,
            "message": spoken_msg,
            "transfer_requested": bool(
                final_status in (EscalationStatus.TRANSFERRED.value, EscalationStatus.QUEUED.value)
            ),
            "emergency_detected": is_emergency,
            "needs_phone": needs_phone,
            "deduplicated": is_dedup,
            "persisted": is_persisted,
        }

        return ToolResult(
            success=True,
            message=spoken_msg,
            data=output_payload,
        )

    def execute(
        self,
        reason: str | None = None,
        caller_name: str | None = None,
        caller_phone: str | None = None,
        department: str | HandoffDepartmentEnum = HandoffDepartmentEnum.RECEPTION,
        urgency: str | HandoffUrgencyEnum = HandoffUrgencyEnum.MEDIUM,
        summary: str | None = None,
        session_id: str | None = None,
        # Legacy parameter compatibility
        customer_name: str | None = None,
        customer_phone: str | None = None,
        conversation_summary: str | None = None,
    ) -> ToolResult:
        """
        Synchronous execution entrypoint safe for existing running event loops.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        kwargs = {
            "reason": reason,
            "caller_name": caller_name,
            "caller_phone": caller_phone,
            "department": department,
            "urgency": urgency,
            "summary": summary,
            "session_id": session_id,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "conversation_summary": conversation_summary,
        }

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(lambda: asyncio.run(self.aexecute(**kwargs))).result()
        return asyncio.run(self.aexecute(**kwargs))


# Singleton tool instance
receptionist_handoff_tool = ReceptionistHandoffTool()


async def async_transfer_to_receptionist(
    reason: str | None = None,
    caller_name: str | None = None,
    caller_phone: str | None = None,
    department: str | HandoffDepartmentEnum = HandoffDepartmentEnum.RECEPTION,
    urgency: str | HandoffUrgencyEnum = HandoffUrgencyEnum.MEDIUM,
    summary: str | None = None,
    session_id: str | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Async convenience wrapper for LiveKit Voice Agent and LLM tool calling."""
    return await receptionist_handoff_tool.aexecute(
        reason=reason,
        caller_name=caller_name,
        caller_phone=caller_phone,
        department=department,
        urgency=urgency,
        summary=summary,
        session_id=session_id,
        **kwargs,
    )


def transfer_to_receptionist(
    reason: str | None = None,
    caller_name: str | None = None,
    caller_phone: str | None = None,
    department: str | HandoffDepartmentEnum = HandoffDepartmentEnum.RECEPTION,
    urgency: str | HandoffUrgencyEnum = HandoffUrgencyEnum.MEDIUM,
    summary: str | None = None,
    session_id: str | None = None,
    **kwargs: Any,
) -> ToolResult:
    """Sync convenience wrapper for synchronous tool dispatchers and testing."""
    return receptionist_handoff_tool.execute(
        reason=reason,
        caller_name=caller_name,
        caller_phone=caller_phone,
        department=department,
        urgency=urgency,
        summary=summary,
        session_id=session_id,
        **kwargs,
    )


# ==============================================================================
# Backward-Compatibility Aliases (Deprecated; Phase 5 cleans up)
# ==============================================================================

HumanHandoffTool = ReceptionistHandoffTool
human_handoff_tool = receptionist_handoff_tool
escalate_to_human = transfer_to_receptionist
async_escalate_to_human = async_transfer_to_receptionist

__all__ = [  # noqa: RUF022
    "DEPARTMENT_NAMES_ARABIC",
    "HumanHandoffTool",
    "ReceptionistHandoffTool",
    "URGENCY_RANKS",
    "async_escalate_to_human",
    "async_transfer_to_receptionist",
    "build_voice_message",
    "detect_emergency",
    "escalate_to_human",
    "estimate_wait_seconds",
    "human_handoff_tool",
    "is_reception_open",
    "mask_phone_for_speech",
    "receptionist_handoff_tool",
    "transfer_to_receptionist",
]
