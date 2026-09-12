"""
Order Status and Live Delivery Tracking Tool for Voice Agent.

Enables callers to query order progress, driver location/contact, estimated delivery time,
and order details by Order ID (e.g. ORD-1001) or customer phone number.
Supports both synchronous and asynchronous execution for LiveKit voice turns.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.tools.schemas import (
    OrderItem,
    OrderStatusEnum,
    OrderStatusInput,
    OrderStatusOutput,
    ToolResult,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# In-Memory Mock Orders Database
# ==============================================================================

MOCK_ORDERS: Dict[str, Dict[str, Any]] = {
    "ORD-1001": {
        "order_id": "ORD-1001",
        "customer_name": "أحمد السعيد",
        "phone_number": "+966501234567",
        "status": OrderStatusEnum.OUT_FOR_DELIVERY,
        "status_arabic": "في الطريق إليك مع السائق",
        "items": [
            OrderItem(name="شاورما دجاج عربي كبير", quantity=2, unit_price=28.0, notes="بدون مخلل، ثوم إضافي"),
            OrderItem(name="بطاطس مقلية بالجبن", quantity=1, unit_price=14.0),
        ],
        "total_amount": 70.0,
        "estimated_delivery_time_minutes": 12,
        "driver_name": "محمد الشمري",
        "driver_phone": "+966555123456",
        "delivery_address": "حي النخيل، شارع التخصصي، مبنى 14، الرياض",
        "created_at": "2026-09-12T11:20:00",
    },
    "ORD-1002": {
        "order_id": "ORD-1002",
        "customer_name": "سارة القحطاني",
        "phone_number": "+966509876543",
        "status": OrderStatusEnum.PREPARING,
        "status_arabic": "قيد التحضير في المطبخ",
        "items": [
            OrderItem(name="مشاوي مشكلة عائلي", quantity=1, unit_price=120.0),
            OrderItem(name="حمص بيروتي", quantity=1, unit_price=18.0),
        ],
        "total_amount": 138.0,
        "estimated_delivery_time_minutes": 25,
        "driver_name": None,
        "driver_phone": None,
        "delivery_address": "حي الياسمين، فيلا 22، الرياض",
        "created_at": "2026-09-12T11:35:00",
    },
    "ORD-1003": {
        "order_id": "ORD-1003",
        "customer_name": "خالد الحربي",
        "phone_number": "+966551122334",
        "status": OrderStatusEnum.DELIVERED,
        "status_arabic": "تم التوصيل بنجاح",
        "items": [
            OrderItem(name="سلطة فتوش بدبس الرمان", quantity=1, unit_price=22.0),
            OrderItem(name="عصير برتقال طازج", quantity=2, unit_price=15.0),
        ],
        "total_amount": 52.0,
        "estimated_delivery_time_minutes": 0,
        "driver_name": "عمر الخالد",
        "driver_phone": "+966555987654",
        "delivery_address": "حي الملقا، طريق أنس بن مالك، الرياض",
        "created_at": "2026-09-12T10:15:00",
    },
    "ORD-1004": {
        "order_id": "ORD-1004",
        "customer_name": "فاطمة العمري",
        "phone_number": "+966543219876",
        "status": OrderStatusEnum.READY_FOR_PICKUP,
        "status_arabic": "جاهز للاستلام من الفرع",
        "items": [
            OrderItem(name="وجبة فلافل عربي مشكل", quantity=2, unit_price=18.0),
        ],
        "total_amount": 36.0,
        "estimated_delivery_time_minutes": 0,
        "driver_name": None,
        "driver_phone": None,
        "delivery_address": "الاستلام من الفرع الرئيسي (السليمانية)",
        "created_at": "2026-09-12T11:30:00",
    },
    "ORD-1005": {
        "order_id": "ORD-1005",
        "customer_name": "عبدالله الدوسري",
        "phone_number": "+966567890123",
        "status": OrderStatusEnum.RECEIVED,
        "status_arabic": "تم استلام الطلب وبانتظار التأكيد",
        "items": [
            OrderItem(name="كباب لحم بالخلطة الخاصة", quantity=2, unit_price=45.0),
        ],
        "total_amount": 90.0,
        "estimated_delivery_time_minutes": 40,
        "driver_name": None,
        "driver_phone": None,
        "delivery_address": "حي العليا، الرياض",
        "created_at": "2026-09-12T11:48:00",
    },
    "ORD-1006": {
        "order_id": "ORD-1006",
        "customer_name": "ريما العتيبي",
        "phone_number": "+966503344556",
        "status": OrderStatusEnum.CANCELLED,
        "status_arabic": "تم إلغاء الطلب",
        "items": [
            OrderItem(name="ورق عنب بدبس الرمان", quantity=1, unit_price=24.0),
        ],
        "total_amount": 24.0,
        "estimated_delivery_time_minutes": None,
        "driver_name": None,
        "driver_phone": None,
        "delivery_address": "حي حطين، الرياض",
        "created_at": "2026-09-12T09:00:00",
    },
}


class OrderStatusTool:
    """
    Tool for retrieving real-time order status, tracking, and delivery details.
    """

    def __init__(self, orders_store: Optional[Dict[str, Dict[str, Any]]] = None):
        """Initialize with default or custom orders database dictionary."""
        self._orders = orders_store if orders_store is not None else MOCK_ORDERS

    def _normalize_identifier(self, identifier: str) -> str:
        """Strip non-alphanumeric noise and standardize string."""
        return identifier.strip().upper()

    def _normalize_phone(self, phone: str) -> str:
        """Strip spaces, hyphens, and leading plus/zeroes for flexible matching."""
        cleaned = re.sub(r"[^\d]", "", phone)
        # Convert local 05XXXXXXXX to 9665XXXXXXXX if relevant
        if cleaned.startswith("05") and len(cleaned) == 10:
            cleaned = "966" + cleaned[1:]
        return cleaned

    def _build_voice_message(self, order: Dict[str, Any]) -> str:
        """Generate a natural, friendly Arabic spoken message tailored to the status."""
        order_id = order["order_id"]
        status = order["status"]
        customer_name = order.get("customer_name", "عميلنا العزيز")
        eta = order.get("estimated_delivery_time_minutes")
        driver_name = order.get("driver_name")

        if status == OrderStatusEnum.OUT_FOR_DELIVERY:
            driver_info = f" مع السائق {driver_name}" if driver_name else ""
            eta_info = f"، والوقت المتوقع للوصول حوالي {eta} دقيقة" if eta else ""
            return (
                f"أهلاً بك يا {customer_name}. طلبك رقم {order_id} في الطريق إليك حالياً{driver_info}{eta_info}. "
                f"شكراً لصبرك ونتمنى لك وجبة شهية!"
            )
        elif status == OrderStatusEnum.PREPARING:
            eta_info = f" وسيصلك خلال {eta} دقيقة تقريباً" if eta else ""
            return (
                f"أهلاً بك يا {customer_name}. طلبك رقم {order_id} قيد التحضير الطازج في المطبخ حالياً{eta_info}. "
                f"سنقوم بإشعارك فور خروجه للتوصيل."
            )
        elif status == OrderStatusEnum.READY_FOR_PICKUP:
            address = order.get("delivery_address", "الفرع الرئيسي")
            return (
                f"أهلاً بك يا {customer_name}. يسعدنا إخبارك أن طلبك رقم {order_id} جاهز تماماً للاستلام الآن من {address}."
            )
        elif status == OrderStatusEnum.DELIVERED:
            return (
                f"أهلاً بك يا {customer_name}. تم تسليم طلبك رقم {order_id} بنجاح. "
                f"صحة وهنا على قلبك، ويسعدنا دائماً خدمتك!"
            )
        elif status == OrderStatusEnum.RECEIVED:
            return (
                f"أهلاً بك يا {customer_name}. تم استلام طلبك رقم {order_id} بنجاح وجارٍ تأكيده وإرساله إلى المطبخ."
            )
        elif status == OrderStatusEnum.CANCELLED:
            return (
                f"أهلاً بك يا {customer_name}. طلبك رقم {order_id} تم إلغاؤه في النظام. "
                f"إذا كان لديك أي استفسار أو ترغب في تقديم طلب جديد، نحن بخدمتك."
            )
        else:
            return f"طلبك رقم {order_id} حالته الحالية هي: {order.get('status_arabic', 'تحت المعالجة')}."

    def execute(
        self,
        order_id: str,
        phone_number: Optional[str] = None,
    ) -> OrderStatusOutput:
        """
        Synchronously lookup order status.

        Args:
            order_id: Unique order identifier (e.g. 'ORD-1001', '1001') or phone number.
            phone_number: Optional customer phone for identity lookup.

        Returns:
            OrderStatusOutput detailing items, status, delivery ETA, and spoken message.
        """
        raw_id = (order_id or "").strip()
        raw_phone = (phone_number or "").strip()

        logger.info(f"Looking up order status for order_id='{raw_id}', phone='{raw_phone}'")

        if not raw_id and not raw_phone:
            return OrderStatusOutput(
                order_id="UNKNOWN",
                customer_name="غير محدد",
                status=OrderStatusEnum.CANCELLED,
                status_arabic="غير موجود",
                items=[],
                total_amount=0.0,
                message="عذراً، يرجى تزويدي برقم الطلب أو رقم الهاتف المسجل لنتمكن من تتبع طلبك.",
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        matched_order: Optional[Dict[str, Any]] = None

        # 1. Direct match by Order ID
        norm_id = self._normalize_identifier(raw_id)
        if norm_id in self._orders:
            matched_order = self._orders[norm_id]
        elif not norm_id.startswith("ORD-") and f"ORD-{norm_id}" in self._orders:
            matched_order = self._orders[f"ORD-{norm_id}"]

        # 2. Match by phone number if order_id was not matched or is a phone number
        search_phone = raw_phone or (raw_id if re.search(r"\d{7,}", raw_id) else None)
        if not matched_order and search_phone:
            norm_search_phone = self._normalize_phone(search_phone)
            for order in self._orders.values():
                order_phone_norm = self._normalize_phone(order.get("phone_number", ""))
                if norm_search_phone and (norm_search_phone in order_phone_norm or order_phone_norm in norm_search_phone):
                    matched_order = order
                    break

        if not matched_order:
            search_term = raw_id or raw_phone
            logger.warning(f"Order not found for search term: {search_term}")
            return OrderStatusOutput(
                order_id=raw_id or "NOT_FOUND",
                customer_name="عميلنا العزيز",
                status=OrderStatusEnum.CANCELLED,
                status_arabic="غير موجود",
                items=[],
                total_amount=0.0,
                message=(
                    f"عذراً، لم أتمكن من العثور على أي طلب مسجل برقم أو هاتف '{search_term}'. "
                    f"يرجى التأكد من الرقم والمحاولة مرة أخرى، أو التحدث مع موظف خدمة العملاء."
                ),
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        voice_msg = self._build_voice_message(matched_order)

        return OrderStatusOutput(
            order_id=matched_order["order_id"],
            customer_name=matched_order["customer_name"],
            status=matched_order["status"],
            status_arabic=matched_order["status_arabic"],
            items=matched_order.get("items", []),
            total_amount=float(matched_order.get("total_amount", 0.0)),
            estimated_delivery_time_minutes=matched_order.get("estimated_delivery_time_minutes"),
            driver_name=matched_order.get("driver_name"),
            driver_phone=matched_order.get("driver_phone"),
            delivery_address=matched_order.get("delivery_address"),
            created_at=matched_order.get("created_at", datetime.now(timezone.utc).isoformat()),
            message=voice_msg,
        )

    async def aexecute(
        self,
        order_id: str,
        phone_number: Optional[str] = None,
    ) -> OrderStatusOutput:
        """
        Asynchronously lookup order status (non-blocking for LiveKit voice loops).
        """
        return await asyncio.to_thread(
            self.execute,
            order_id=order_id,
            phone_number=phone_number,
        )

    def add_order(self, order_data: Dict[str, Any]) -> None:
        """Register or update an order in the store (useful for testing or order creation)."""
        order_id = self._normalize_identifier(order_data["order_id"])
        self._orders[order_id] = order_data


# Singleton instance
order_status_tool = OrderStatusTool()


def get_order_status(
    order_id: str,
    phone_number: Optional[str] = None,
) -> OrderStatusOutput:
    """
    Convenience function to check order status and tracking details.

    Args:
        order_id: Order number (e.g., 'ORD-1001', '1001') or customer phone number.
        phone_number: Optional phone number for lookup verification.

    Returns:
        OrderStatusOutput object with status, items, driver info, and natural spoken message.
    """
    return order_status_tool.execute(order_id=order_id, phone_number=phone_number)


async def async_get_order_status(
    order_id: str,
    phone_number: Optional[str] = None,
) -> OrderStatusOutput:
    """
    Asynchronous convenience function to check order status.
    """
    return await order_status_tool.aexecute(order_id=order_id, phone_number=phone_number)
