"""
Unit Tests for Order Status and Live Delivery Tracking Tool.
"""

import pytest
from src.tools.order_status import (
    OrderStatusTool,
    get_order_status,
    async_get_order_status,
)
from src.tools.schemas import OrderStatusEnum, OrderItem


@pytest.fixture
def order_tool():
    """Returns an isolated instance of OrderStatusTool for testing."""
    return OrderStatusTool()


def test_order_lookup_by_exact_id(order_tool):
    """Test retrieving an order using exact order ID."""
    result = order_tool.execute(order_id="ORD-1001")
    assert result.order_id == "ORD-1001"
    assert result.customer_name == "أحمد السعيد"
    assert result.status == OrderStatusEnum.OUT_FOR_DELIVERY
    assert result.driver_name == "محمد الشمري"
    assert result.estimated_delivery_time_minutes == 12
    assert result.total_amount == 70.0
    assert len(result.items) == 2
    assert "في الطريق إليك" in result.message


def test_order_lookup_by_short_id(order_tool):
    """Test retrieving order using only the numeric part (e.g. '1002')."""
    result = order_tool.execute(order_id="1002")
    assert result.order_id == "ORD-1002"
    assert result.customer_name == "سارة القحطاني"
    assert result.status == OrderStatusEnum.PREPARING
    assert result.estimated_delivery_time_minutes == 25
    assert "قيد التحضير" in result.message


def test_order_lookup_by_phone_number(order_tool):
    """Test retrieving order by customer phone number."""
    result = order_tool.execute(order_id="", phone_number="+966501234567")
    assert result.order_id == "ORD-1001"
    assert result.customer_name == "أحمد السعيد"

    # Test local Saudi format "0501234567"
    result_local = order_tool.execute(order_id="", phone_number="0501234567")
    assert result_local.order_id == "ORD-1001"


def test_order_lookup_when_phone_entered_in_order_id_field(order_tool):
    """Test when caller mentions their phone number instead of an order ID."""
    result = order_tool.execute(order_id="0509876543")
    assert result.order_id == "ORD-1002"
    assert result.customer_name == "سارة القحطاني"


def test_order_status_ready_for_pickup(order_tool):
    """Test order status READY_FOR_PICKUP."""
    result = order_tool.execute(order_id="ORD-1004")
    assert result.status == OrderStatusEnum.READY_FOR_PICKUP
    assert "جاهز تماماً للاستلام" in result.message


def test_order_status_delivered(order_tool):
    """Test order status DELIVERED."""
    result = order_tool.execute(order_id="ORD-1003")
    assert result.status == OrderStatusEnum.DELIVERED
    assert "تم تسليم طلبك" in result.message


def test_order_status_cancelled(order_tool):
    """Test order status CANCELLED."""
    result = order_tool.execute(order_id="ORD-1006")
    assert result.status == OrderStatusEnum.CANCELLED
    assert "تم إلغاؤه" in result.message


def test_order_not_found(order_tool):
    """Test fallback when an order ID does not exist."""
    result = order_tool.execute(order_id="ORD-9999")
    assert result.order_id == "ORD-9999"
    assert "لم أتمكن من العثور" in result.message


def test_add_custom_order(order_tool):
    """Test adding a dynamic order to the store."""
    custom_order = {
        "order_id": "ORD-7777",
        "customer_name": "ياسر الحربي",
        "phone_number": "+966512340000",
        "status": OrderStatusEnum.PREPARING,
        "status_arabic": "قيد التجهيز",
        "items": [OrderItem(name="بيتزا خضار", quantity=1, unit_price=40.0)],
        "total_amount": 40.0,
        "estimated_delivery_time_minutes": 20,
        "driver_name": None,
        "driver_phone": None,
        "delivery_address": "حي المروج، الرياض",
        "created_at": "2026-09-12T12:00:00",
    }
    order_tool.add_order(custom_order)

    res = order_tool.execute(order_id="ORD-7777")
    assert res.order_id == "ORD-7777"
    assert res.customer_name == "ياسر الحربي"


@pytest.mark.asyncio
async def test_async_order_lookup():
    """Test asynchronous execution of order lookup."""
    result = await async_get_order_status(order_id="ORD-1001")
    assert result.order_id == "ORD-1001"
    assert result.status == OrderStatusEnum.OUT_FOR_DELIVERY
