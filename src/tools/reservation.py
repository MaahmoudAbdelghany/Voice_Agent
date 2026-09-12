"""
Table Reservation and Availability Management Tool for Voice Agent.

Handles restaurant table reservations, slot availability verification,
reservation status lookups, and cancellations for restaurant branches.
Supports both synchronous and asynchronous execution for LiveKit voice turns.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.tools.schemas import (
    ReservationInput,
    ReservationOutput,
    ReservationStatusEnum,
    ToolResult,
)

logger = logging.getLogger(__name__)

# Standard branches supported by the restaurant
VALID_BRANCHES = [
    "مدينة نصر",
    "التجمع الخامس",
    "الدقي",
    "الشيخ زايد",
    "الفرع الرئيسي",
]

# Initial in-memory mock reservations store
MOCK_RESERVATIONS: Dict[str, Dict[str, Any]] = {
    "RES-1001": {
        "reservation_id": "RES-1001",
        "customer_name": "محمد حسن",
        "phone_number": "+966501112233",
        "party_size": 4,
        "date": "2026-09-12",
        "time": "20:00",
        "branch": "فرع التجمع الخامس",
        "status": ReservationStatusEnum.CONFIRMED,
        "status_arabic": "مؤكد",
        "table_number": 12,
        "confirmation_code": "RES-101",
        "special_requests": "كرسي أطفال وطاولة بجوار النافذة",
        "created_at": "2026-09-12T10:00:00",
    },
    "RES-1002": {
        "reservation_id": "RES-1002",
        "customer_name": "نورة العلي",
        "phone_number": "+966509998877",
        "party_size": 2,
        "date": "2026-09-12",
        "time": "19:30",
        "branch": "فرع مدينة نصر",
        "status": ReservationStatusEnum.CONFIRMED,
        "status_arabic": "مؤكد",
        "table_number": 5,
        "confirmation_code": "RES-102",
        "special_requests": "جلسة هادئة خارجية (Outdoor)",
        "created_at": "2026-09-12T10:30:00",
    },
    "RES-1003": {
        "reservation_id": "RES-1003",
        "customer_name": "كريم عبد العزيز",
        "phone_number": "+966555443322",
        "party_size": 6,
        "date": "2026-09-13",
        "time": "21:00",
        "branch": "فرع الدقي",
        "status": ReservationStatusEnum.WAITLISTED,
        "status_arabic": "قائمة الانتظار",
        "table_number": None,
        "confirmation_code": "RES-103",
        "special_requests": "احتفال بعيد ميلاد",
        "created_at": "2026-09-12T11:00:00",
    },
}


class ReservationTool:
    """
    Tool for managing restaurant table reservations, capacity checks, and inquiries.
    """

    def __init__(self, reservations_store: Optional[Dict[str, Dict[str, Any]]] = None):
        """Initialize with default or custom reservations database."""
        self._reservations = (
            reservations_store if reservations_store is not None else MOCK_RESERVATIONS
        )
        self._counter = 2000

    def _generate_reservation_id(self) -> str:
        """Generate unique sequential reservation ID."""
        self._counter += 1
        return f"RES-{self._counter}"

    def _generate_confirmation_code(self) -> str:
        """Generate short 3-digit confirmation code."""
        code = random.randint(100, 999)
        return f"RES-{code}"

    def _assign_table_number(self, party_size: int) -> int:
        """Assign table number based on party capacity."""
        if party_size <= 2:
            return random.randint(1, 8)
        elif party_size <= 4:
            return random.randint(9, 18)
        elif party_size <= 8:
            return random.randint(19, 25)
        else:
            return random.randint(26, 30)

    def _normalize_phone(self, phone: str) -> str:
        """Standardize phone numbers for flexible lookups."""
        cleaned = re.sub(r"[^\d]", "", phone)
        if cleaned.startswith("05") and len(cleaned) == 10:
            cleaned = "966" + cleaned[1:]
        elif cleaned.startswith("01") and len(cleaned) == 11:
            # Egyptian mobile format (e.g. 01012345678 -> 201012345678)
            cleaned = "20" + cleaned[1:]
        return cleaned

    def _normalize_date(self, raw_date: str) -> str:
        """Convert relative colloquial date terms into ISO date."""
        lowered = raw_date.strip().lower()
        now = datetime.now()
        if lowered in ["today", "اليوم", "النهاردة"]:
            return now.strftime("%Y-%m-%d")
        elif lowered in ["tomorrow", "بكرة", "غداً"]:
            from datetime import timedelta
            return (now + timedelta(days=1)).strftime("%Y-%m-%d")
        return raw_date.strip()

    def check_availability(
        self,
        date: str,
        time: str,
        party_size: int,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check if tables are available for the requested party size and time.

        Args:
            date: Reservation date string.
            time: Requested time slot.
            party_size: Number of guests.
            branch: Optional branch name.

        Returns:
            Dictionary with available status, reason, and suggested slots.
        """
        if party_size > 30:
            return {
                "available": False,
                "reason": "عفواً، الحجوزات المباشرة متاحة حتى 30 فرداً. للعزومات الكبيرة والحفلات يرجى التنسيق مع إدارة الحفلات.",
                "max_capacity": 30,
            }
        if party_size < 1:
            return {
                "available": False,
                "reason": "عدد الأفراد يجب أن يكون شخصاً واحداً على الأقل.",
                "max_capacity": 30,
            }

        # Check existing reservations at same date/time/branch
        norm_date = self._normalize_date(date)
        matching_count = sum(
            1
            for r in self._reservations.values()
            if r.get("date") == norm_date
            and r.get("time") == time
            and r.get("status") == ReservationStatusEnum.CONFIRMED
        )

        # Capacity ceiling per slot
        is_available = matching_count < 10
        return {
            "available": is_available,
            "current_bookings": matching_count,
            "date": norm_date,
            "time": time,
            "party_size": party_size,
            "branch": branch or "الفرع الرئيسي",
        }

    def execute(
        self,
        customer_name: str,
        phone_number: str,
        party_size: int,
        date: str,
        time: str,
        special_requests: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> ReservationOutput:
        """
        Synchronously book a table reservation.

        Args:
            customer_name: Full name of caller.
            phone_number: Contact phone for confirmation.
            party_size: Number of guests (1-30).
            date: Desired date (e.g., '2026-09-12', 'today', 'tomorrow').
            time: Desired time (e.g., '20:00', '8:00 PM').
            special_requests: Optional seating or event requests (e.g. 'Outdoor', 'Baby chair').
            branch: Optional branch name.

        Returns:
            ReservationOutput detailing reservation ID, assigned table, and voice message.
        """
        clean_name = customer_name.strip()
        clean_phone = phone_number.strip()
        normalized_date = self._normalize_date(date)
        clean_time = time.strip()
        selected_branch = branch.strip() if branch else "فرع التجمع الخامس"

        logger.info(
            f"Processing table reservation for {clean_name}, party={party_size}, "
            f"date={normalized_date}, time={clean_time}, branch={selected_branch}"
        )

        # 1. Validation for large groups (> 30 requires catering coordination)
        if party_size > 30:
            return ReservationOutput(
                reservation_id="REQ-EVENT",
                customer_name=clean_name,
                party_size=party_size,
                date=normalized_date,
                time=clean_time,
                status=ReservationStatusEnum.REJECTED,
                status_arabic="يتطلب تنسيق حفلات",
                table_number=None,
                confirmation_code="NONE",
                special_requests=special_requests,
                message=(
                    f"أهلاً بك يا {clean_name}. بالنسبة للحجوزات التي تتعدى 30 فرداً، "
                    f"يتم التنسيق مباشرة مع قسم تنظيم الحفلات والعزومات لتجهيز صالة خاصة وبوفيه مخصص. "
                    f"هل تود أن أقوم بتحويلك إلى ممثل خدمة الحفلات؟"
                ),
            )

        if party_size < 1:
            return ReservationOutput(
                reservation_id="INVALID",
                customer_name=clean_name,
                party_size=party_size,
                date=normalized_date,
                time=clean_time,
                status=ReservationStatusEnum.REJECTED,
                status_arabic="غير صالح",
                table_number=None,
                confirmation_code="NONE",
                special_requests=special_requests,
                message="عذراً، يرجى تحديد عدد أفراد صحيح لإتمام الحجز.",
            )

        # 2. Check capacity
        availability = self.check_availability(
            date=normalized_date,
            time=clean_time,
            party_size=party_size,
            branch=selected_branch,
        )

        reservation_id = self._generate_reservation_id()
        conf_code = self._generate_confirmation_code()

        if not availability["available"]:
            # Place on waitlist
            waitlist_record = {
                "reservation_id": reservation_id,
                "customer_name": clean_name,
                "phone_number": clean_phone,
                "party_size": party_size,
                "date": normalized_date,
                "time": clean_time,
                "branch": selected_branch,
                "status": ReservationStatusEnum.WAITLISTED,
                "status_arabic": "قائمة الانتظار",
                "table_number": None,
                "confirmation_code": conf_code,
                "special_requests": special_requests,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._reservations[reservation_id] = waitlist_record

            return ReservationOutput(
                reservation_id=reservation_id,
                customer_name=clean_name,
                party_size=party_size,
                date=normalized_date,
                time=clean_time,
                status=ReservationStatusEnum.WAITLISTED,
                status_arabic="قائمة الانتظار",
                table_number=None,
                confirmation_code=conf_code,
                special_requests=special_requests,
                message=(
                    f"أهلاً بك يا {clean_name}. نظراً للإقبال الشديد، هذا الموعد مكتمل حالياً، "
                    f"وقد تم تسجيل حجزك في قائمة الانتظار برقم {reservation_id}. "
                    f"سنتواصل معك عبر الهاتف فور توفر طاولة مناسبة."
                ),
            )

        # 3. Confirm reservation
        table_num = self._assign_table_number(party_size)
        reservation_record = {
            "reservation_id": reservation_id,
            "customer_name": clean_name,
            "phone_number": clean_phone,
            "party_size": party_size,
            "date": normalized_date,
            "time": clean_time,
            "branch": selected_branch,
            "status": ReservationStatusEnum.CONFIRMED,
            "status_arabic": "مؤكد",
            "table_number": table_num,
            "confirmation_code": conf_code,
            "special_requests": special_requests,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._reservations[reservation_id] = reservation_record

        # Build natural voice message
        requests_msg = (
            f" مع مراعاة طلبك الخاص ({special_requests})" if special_requests else ""
        )
        spoken_message = (
            f"تم تأكيد حجزك بنجاح يا {clean_name}! طاولة رقم {table_num} لعدد {party_size} أفراد "
            f"في {selected_branch} يوم {normalized_date} الساعة {clean_time}{requests_msg}. "
            f"كود التأكيد الخاص بك هو {conf_code}. "
            f"علماً بأن الطاولة تظل محجوزة لمدة 15 دقيقة بعد الموعد المحدد. نتطلع لزيارتكم الكريمة!"
        )

        return ReservationOutput(
            reservation_id=reservation_id,
            customer_name=clean_name,
            party_size=party_size,
            date=normalized_date,
            time=clean_time,
            status=ReservationStatusEnum.CONFIRMED,
            status_arabic="مؤكد",
            table_number=table_num,
            confirmation_code=conf_code,
            special_requests=special_requests,
            message=spoken_message,
        )

    async def aexecute(
        self,
        customer_name: str,
        phone_number: str,
        party_size: int,
        date: str,
        time: str,
        special_requests: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> ReservationOutput:
        """
        Asynchronously book a table reservation (non-blocking for LiveKit voice turns).
        """
        return await asyncio.to_thread(
            self.execute,
            customer_name=customer_name,
            phone_number=phone_number,
            party_size=party_size,
            date=date,
            time=time,
            special_requests=special_requests,
            branch=branch,
        )

    def get_reservation(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Find existing reservation by reservation ID or phone number.
        """
        clean_id = identifier.strip().upper()
        # Check direct reservation ID
        if clean_id in self._reservations:
            return self._reservations[clean_id]
        if f"RES-{clean_id}" in self._reservations:
            return self._reservations[f"RES-{clean_id}"]

        # Search by phone number
        norm_phone = self._normalize_phone(identifier)
        for res in self._reservations.values():
            if self._normalize_phone(res.get("phone_number", "")) == norm_phone:
                return res
        return None

    def cancel_reservation(self, identifier: str) -> ToolResult:
        """
        Cancel an existing reservation.
        """
        res = self.get_reservation(identifier)
        if not res:
            return ToolResult(
                success=False,
                message=f"عذراً، لم نتمكن من العثور على أي حجز مسجل بالرقم أو الهاتف '{identifier}'.",
            )

        res["status"] = ReservationStatusEnum.CANCELLED
        res["status_arabic"] = "ملغي"
        return ToolResult(
            success=True,
            message=f"تم إلغاء حجزكم رقم {res['reservation_id']} بنجاح. نأمل أن نتشرف بخدمتكم في وقت لاحق.",
            data={"reservation_id": res["reservation_id"], "status": "cancelled"},
        )


# Singleton tool instance
reservation_tool = ReservationTool()


def book_reservation(
    customer_name: str,
    phone_number: str,
    party_size: int,
    date: str,
    time: str,
    special_requests: Optional[str] = None,
    branch: Optional[str] = None,
) -> ReservationOutput:
    """
    Convenience function to book a table reservation.

    Args:
        customer_name: Full name of caller.
        phone_number: Contact phone.
        party_size: Number of guests (1-30).
        date: Reservation date string.
        time: Requested time slot.
        special_requests: Optional seating notes or occasions.
        branch: Optional restaurant branch.

    Returns:
        ReservationOutput with confirmation details and voice message.
    """
    return reservation_tool.execute(
        customer_name=customer_name,
        phone_number=phone_number,
        party_size=party_size,
        date=date,
        time=time,
        special_requests=special_requests,
        branch=branch,
    )


async def async_book_reservation(
    customer_name: str,
    phone_number: str,
    party_size: int,
    date: str,
    time: str,
    special_requests: Optional[str] = None,
    branch: Optional[str] = None,
) -> ReservationOutput:
    """
    Asynchronous convenience function to book a table reservation.
    """
    return await reservation_tool.aexecute(
        customer_name=customer_name,
        phone_number=phone_number,
        party_size=party_size,
        date=date,
        time=time,
        special_requests=special_requests,
        branch=branch,
    )
