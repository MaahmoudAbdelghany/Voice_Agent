"""
Human Supervisor Escalation and Handoff Tool for Voice Agent.

Handles call escalation to live human representatives, department routing
(Customer Support, Kitchen Manager, Delivery Dispatch, Billing), urgency triage,
and queue wait-time estimation with voice-friendly Arabic confirmation messages.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.tools.schemas import (
    HandoffDepartmentEnum,
    HandoffUrgencyEnum,
    HumanHandoffInput,
    HumanHandoffOutput,
    ToolResult,
)

logger = logging.getLogger(__name__)

# Arabic display names for departments
DEPARTMENT_NAMES_ARABIC: Dict[HandoffDepartmentEnum, str] = {
    HandoffDepartmentEnum.CUSTOMER_SUPPORT: "خدمة العملاء والدعم المباشر",
    HandoffDepartmentEnum.KITCHEN_MANAGER: "إدارة المطبخ وجودة الأغذية",
    HandoffDepartmentEnum.DELIVERY_DISPATCH: "مشرف عمليات ومتابعة التوصيل",
    HandoffDepartmentEnum.BILLING: "قسم الحسابات والمدفوعات",
}

# Arabic display names for urgency levels
URGENCY_NAMES_ARABIC: Dict[HandoffUrgencyEnum, str] = {
    HandoffUrgencyEnum.LOW: "عادي",
    HandoffUrgencyEnum.MEDIUM: "متوسط",
    HandoffUrgencyEnum.HIGH: "عالي",
    HandoffUrgencyEnum.CRITICAL: "طارئ جداً",
}

# Department specialized agents roster
DEPARTMENT_AGENTS: Dict[HandoffDepartmentEnum, List[str]] = {
    HandoffDepartmentEnum.CUSTOMER_SUPPORT: [
        "أحمد ممدوح (كبير مسؤولي خدمة العملاء)",
        "رنا يوسف (أخصائي تجربة العملاء)",
        "كريم سامي (مشرف الدعم)",
    ],
    HandoffDepartmentEnum.KITCHEN_MANAGER: [
        "الشيف محمود عبد الغني (مدير الجودة)",
        "الشيف سمير إبراهيم (مسؤول قسم الطهي)",
    ],
    HandoffDepartmentEnum.DELIVERY_DISPATCH: [
        "خالد النجار (مشرف حركة التوصيل)",
        "طارق مصطفى (مسؤول التوزيع السريع)",
    ],
    HandoffDepartmentEnum.BILLING: [
        "وليد الشافعي (أخصائي التسويات والمدفوعات)",
        "سارة كمال (مشرفة الفواتير)",
    ],
}

# In-memory handoff queue and history store
MOCK_HANDOFF_QUEUE: Dict[str, Dict[str, Any]] = {
    "ESC-1001": {
        "handoff_id": "ESC-1001",
        "reason": "عميل يطلب التحدث مع الإدارة بخصوص تأخر الطلب 50 دقيقة",
        "customer_phone": "+966501112233",
        "customer_name": "سامح فوزي",
        "urgency": HandoffUrgencyEnum.HIGH,
        "department": HandoffDepartmentEnum.DELIVERY_DISPATCH,
        "department_arabic": "مشرف عمليات ومتابعة التوصيل",
        "status": "transferred",
        "assigned_agent": "خالد النجار (مشرف حركة التوصيل)",
        "estimated_wait_seconds": 20,
        "conversation_summary": "العميل طلب أوردر ORD-1001 ولم يصل في الموعد المحدد ومندوب التوصيل لا يجيب.",
        "created_at": "2026-09-12T11:15:00",
    },
    "ESC-1002": {
        "handoff_id": "ESC-1002",
        "reason": "استفسار دقيق عن مكونات مسببة لحساسية السمسم في الصوص الخاص",
        "customer_phone": "+966509998877",
        "customer_name": "هدى كمال",
        "urgency": HandoffUrgencyEnum.CRITICAL,
        "department": HandoffDepartmentEnum.KITCHEN_MANAGER,
        "department_arabic": "إدارة المطبخ وجودة الأغذية",
        "status": "transferred",
        "assigned_agent": "الشيف محمود عبد الغني (مدير الجودة)",
        "estimated_wait_seconds": 10,
        "conversation_summary": "العميلة تعاني من حساسية شديدة وتريد تأكيداً مباشراً من الشيف قبل بدء التحضير.",
        "created_at": "2026-09-12T11:45:00",
    },
}


class HumanHandoffTool:
    """
    Tool for escalating live voice calls to human supervisors or specialist departments.
    """

    def __init__(self, queue_store: Optional[Dict[str, Dict[str, Any]]] = None):
        """Initialize with existing or new escalation queue store."""
        self._queue = queue_store if queue_store is not None else MOCK_HANDOFF_QUEUE
        self._counter = 2000

    def _generate_handoff_id(self) -> str:
        """Generate sequential escalation reference ID."""
        self._counter += 1
        return f"ESC-{self._counter}"

    def infer_department_and_urgency(
        self, reason: str, conversation_summary: Optional[str] = None
    ) -> tuple[HandoffDepartmentEnum, HandoffUrgencyEnum]:
        """
        Analyze reason and conversation text to infer the most appropriate department and urgency.

        Args:
            reason: Caller's reason for escalation.
            conversation_summary: Optional previous dialog summary.

        Returns:
            Tuple of (HandoffDepartmentEnum, HandoffUrgencyEnum).
        """
        combined = f"{reason} {conversation_summary or ''}".lower()

        # Urgency detection
        critical_keywords = [
            "تسمم", "حساسية مفرطة", "مستشفى", "طوارئ", "حادث", "إغماء",
            "poison", "emergency", "severe allergy", "hospital", "choking"
        ]
        high_keywords = [
            "متأخر جداً", "بارد", "بايظ", "تالف", "أكل فاسد", "طلب خطأ",
            "مندوب وقح", "سرقة", "لم يصل", "ساعة ونص", "غضبان", "angry", "complaint",
            "شديد", "مرتين", "استرداد"
        ]

        if any(kw in combined for kw in critical_keywords):
            urgency = HandoffUrgencyEnum.CRITICAL
        elif any(kw in combined for kw in high_keywords):
            urgency = HandoffUrgencyEnum.HIGH
        else:
            urgency = HandoffUrgencyEnum.MEDIUM

        # Department detection with token-aware matching & scoring
        kitchen_keywords = [
            "مطبخ", "شيف", "طعام", "أكل", "محروق", "طعم", "مكونات",
            "صلصة", "صوص", "حساسية", "جلوتين", "نباتي", "لحم", "دجاج",
            "غير ناضج", "طازج", "taste", "kitchen", "chef", "cook", "allergen", "raw"
        ]
        delivery_keywords = [
            "توصيل", "سائق", "سواق", "دليفري", "مندوب", "لوكيشن", "عنوان", "تأخر", "متأخر",
            "طريق", "خريطة", "فين الأوردر", "لم يصل", "delivery", "driver", "courier", "delayed"
        ]
        billing_keywords = [
            "حساب", "فاتورة", "فلوس", "فيزا", "بطاقة", "خصم", "استرداد", "دفع",
            "بنك", "مرتجع", "كاش", "مبلغ", "محفظة", "bill", "invoice", "payment", "card", "refund", "charge"
        ]

        def _count_matches(text: str, keywords: List[str]) -> int:
            count = 0
            for kw in keywords:
                if " " in kw:
                    if kw in text:
                        count += 2
                else:
                    pattern = rf"(?:^|[^\w])(?:ال|و|ب|ف|لل|وال|بال)?{re.escape(kw)}(?:[^\w]|$)"
                    if re.search(pattern, text):
                        count += 1
            return count

        scores = {
            HandoffDepartmentEnum.KITCHEN_MANAGER: _count_matches(combined, kitchen_keywords),
            HandoffDepartmentEnum.DELIVERY_DISPATCH: _count_matches(combined, delivery_keywords),
            HandoffDepartmentEnum.BILLING: _count_matches(combined, billing_keywords),
        }

        best_dept = max(scores, key=scores.get)
        if scores[best_dept] > 0:
            department = best_dept
        else:
            department = HandoffDepartmentEnum.CUSTOMER_SUPPORT

        return department, urgency

    def _estimate_wait_time(self, urgency: HandoffUrgencyEnum) -> int:
        """Calculate estimated wait time in seconds based on urgency priority."""
        if urgency == HandoffUrgencyEnum.CRITICAL:
            return random.randint(10, 15)
        elif urgency == HandoffUrgencyEnum.HIGH:
            return random.randint(20, 35)
        elif urgency == HandoffUrgencyEnum.MEDIUM:
            return random.randint(40, 60)
        else:
            return random.randint(60, 90)

    def _pick_agent(self, department: HandoffDepartmentEnum) -> str:
        """Select an active representative from the department roster."""
        roster = DEPARTMENT_AGENTS.get(
            department,
            DEPARTMENT_AGENTS[HandoffDepartmentEnum.CUSTOMER_SUPPORT],
        )
        return random.choice(roster)

    def execute(
        self,
        reason: str,
        customer_phone: Optional[str] = None,
        customer_name: Optional[str] = None,
        urgency: Optional[HandoffUrgencyEnum] = None,
        department: Optional[HandoffDepartmentEnum] = None,
        conversation_summary: Optional[str] = None,
    ) -> HumanHandoffOutput:
        """
        Synchronously process a human escalation request and prepare caller transfer.

        Args:
            reason: Explicit reason for transferring to human.
            customer_phone: Caller contact number.
            customer_name: Name of customer if known.
            urgency: Priority level (auto-inferred if omitted).
            department: Target department (auto-inferred if omitted).
            conversation_summary: Context notes for the receiving human agent.

        Returns:
            HumanHandoffOutput with transfer status, wait time, and voice script.
        """
        clean_reason = reason.strip()
        clean_phone = customer_phone.strip() if customer_phone else None
        clean_name = customer_name.strip() if customer_name else None

        # Auto-infer department or urgency if not provided
        inferred_dept, inferred_urg = self.infer_department_and_urgency(
            clean_reason, conversation_summary
        )
        final_department = department or inferred_dept
        final_urgency = urgency or inferred_urg

        # Select agent and calculate wait
        assigned_agent = self._pick_agent(final_department)
        wait_seconds = self._estimate_wait_time(final_urgency)
        handoff_id = self._generate_handoff_id()
        dept_name_ar = DEPARTMENT_NAMES_ARABIC.get(
            final_department, "خدمة العملاء والدعم المباشر"
        )

        status = "transferred" if final_urgency == HandoffUrgencyEnum.CRITICAL else "queued"

        # Record handoff ticket in queue store
        record = {
            "handoff_id": handoff_id,
            "reason": clean_reason,
            "customer_phone": clean_phone,
            "customer_name": clean_name,
            "urgency": final_urgency,
            "department": final_department,
            "department_arabic": dept_name_ar,
            "status": status,
            "assigned_agent": assigned_agent,
            "estimated_wait_seconds": wait_seconds,
            "conversation_summary": conversation_summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._queue[handoff_id] = record

        logger.info(
            f"Escalation ticket created: id={handoff_id}, dept={final_department.value}, "
            f"urgency={final_urgency.value}, wait={wait_seconds}s, agent='{assigned_agent}'"
        )

        # Build natural voice-friendly response
        greeting = f"أهلاً بك يا {clean_name}. " if clean_name else "تحت أمرك تماماً. "

        if final_urgency == HandoffUrgencyEnum.CRITICAL:
            spoken_message = (
                f"{greeting}نظراً لأهمية الأمر وحرصنا الكامل على سلامتكم، أقوم الآن فوراً "
                f"بتحويل مكالمتك بشكل مباشر إلى {dept_name_ar} مع {assigned_agent}. "
                f"رقم بطاقة المتابعة هو {handoff_id}. يرجى البقاء على الخط، جاري التوصيل الآن."
            )
        elif final_urgency == HandoffUrgencyEnum.HIGH:
            spoken_message = (
                f"{greeting}أتفهم انزعاجك تماماً ونعتذر عن أي تقصير. أقوم حالياً بتحويلك إلى "
                f"{dept_name_ar} لمراجعة طلبك وحل المشكلة على الفور مع {assigned_agent}. "
                f"رقم تذكرتك هو {handoff_id}، ومتوسط الانتظار المتوقع حوالي {wait_seconds} ثانية. "
                f"يرجى التفضل بالبقاء على الخط."
            )
        else:
            spoken_message = (
                f"{greeting}بكل سرور، أقوم بتحويل مكالمتك الآن إلى {dept_name_ar}. "
                f"رقم طلب التحويل هو {handoff_id}، والوقت المتوقع للتوصيل حوالي {wait_seconds} ثانية. "
                f"يرجى الانتظار لحظات وسيكون معك أحد مسؤولينا."
            )

        return HumanHandoffOutput(
            handoff_id=handoff_id,
            status=status,
            department=dept_name_ar,
            urgency=final_urgency,
            assigned_agent=assigned_agent,
            estimated_wait_seconds=wait_seconds,
            message=spoken_message,
        )

    async def aexecute(
        self,
        reason: str,
        customer_phone: Optional[str] = None,
        customer_name: Optional[str] = None,
        urgency: Optional[HandoffUrgencyEnum] = None,
        department: Optional[HandoffDepartmentEnum] = None,
        conversation_summary: Optional[str] = None,
    ) -> HumanHandoffOutput:
        """
        Asynchronously process human escalation (non-blocking for LiveKit voice turns).
        """
        return await asyncio.to_thread(
            self.execute,
            reason=reason,
            customer_phone=customer_phone,
            customer_name=customer_name,
            urgency=urgency,
            department=department,
            conversation_summary=conversation_summary,
        )

    def get_handoff_status(self, handoff_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve existing handoff status and details by ticket ID.
        """
        clean_id = handoff_id.strip().upper()
        return self._queue.get(clean_id)

    def schedule_callback(
        self,
        customer_phone: str,
        customer_name: Optional[str] = None,
        preferred_time: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ToolResult:
        """
        Schedule a callback if all lines are busy or if caller prefers a later callback.
        """
        ticket_id = self._generate_handoff_id()
        time_text = f"خلال {preferred_time}" if preferred_time else "خلال 15 دقيقة"
        name_text = f"يا {customer_name}" if customer_name else "عزيزي العميل"

        callback_record = {
            "handoff_id": ticket_id,
            "status": "callback_scheduled",
            "customer_phone": customer_phone,
            "customer_name": customer_name,
            "preferred_time": preferred_time or "15 minutes",
            "reason": reason or "طلب إعادة اتصال من العميل",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._queue[ticket_id] = callback_record

        return ToolResult(
            success=True,
            message=(
                f"تم جدولة إعادة الاتصال بك بنجاح {name_text} على الرقم {customer_phone} {time_text}. "
                f"رقم التذكرة الخاص بك هو {ticket_id}. نتمنى لك يوماً سعيداً!"
            ),
            data=callback_record,
        )


# Singleton tool instance
human_handoff_tool = HumanHandoffTool()


def escalate_to_human(
    reason: str,
    customer_phone: Optional[str] = None,
    customer_name: Optional[str] = None,
    urgency: Optional[HandoffUrgencyEnum] = None,
    department: Optional[HandoffDepartmentEnum] = None,
    conversation_summary: Optional[str] = None,
) -> HumanHandoffOutput:
    """
    Convenience function to trigger human agent escalation.

    Args:
        reason: Reason for transfer.
        customer_phone: Caller phone.
        customer_name: Caller name.
        urgency: Optional priority level.
        department: Optional destination department.
        conversation_summary: Context notes for receiving human.

    Returns:
        HumanHandoffOutput with ticket ID, wait time, and voice message.
    """
    return human_handoff_tool.execute(
        reason=reason,
        customer_phone=customer_phone,
        customer_name=customer_name,
        urgency=urgency,
        department=department,
        conversation_summary=conversation_summary,
    )


async def async_escalate_to_human(
    reason: str,
    customer_phone: Optional[str] = None,
    customer_name: Optional[str] = None,
    urgency: Optional[HandoffUrgencyEnum] = None,
    department: Optional[HandoffDepartmentEnum] = None,
    conversation_summary: Optional[str] = None,
) -> HumanHandoffOutput:
    """
    Asynchronous convenience function to trigger human agent escalation.
    """
    return await human_handoff_tool.aexecute(
        reason=reason,
        customer_phone=customer_phone,
        customer_name=customer_name,
        urgency=urgency,
        department=department,
        conversation_summary=conversation_summary,
    )
