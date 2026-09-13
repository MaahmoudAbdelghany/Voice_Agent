"""
Unit Tests for Human Escalation & Supervisor Handoff Tool.
"""

import pytest
from src.tools.human_handoff import (
    HumanHandoffTool,
    escalate_to_human,
    async_escalate_to_human,
)
from src.tools.schemas import HandoffDepartmentEnum, HandoffUrgencyEnum


@pytest.fixture
def handoff_tool():
    """Create a fresh HumanHandoffTool instance."""
    return HumanHandoffTool()


def test_standard_escalation(handoff_tool):
    """Test standard human escalation with customer name and phone."""
    output = handoff_tool.execute(
        reason="العميل يرغب في التحدث مع موظف خدمة العملاء بخصوص استفسار عام",
        customer_name="علي محمود",
        customer_phone="01023456789",
        urgency=HandoffUrgencyEnum.MEDIUM,
        department=HandoffDepartmentEnum.CUSTOMER_SUPPORT,
    )

    assert "ESC-" in output.handoff_id
    assert output.status == "queued"
    assert output.urgency == HandoffUrgencyEnum.MEDIUM
    assert output.department == "خدمة العملاء والدعم المباشر"
    assert output.assigned_agent is not None
    assert output.estimated_wait_seconds > 0
    assert "علي محمود" in output.message
    assert "خدمة العملاء" in output.message


def test_critical_allergy_escalation_immediate_transfer(handoff_tool):
    """Test critical allergy or medical concern triggers immediate direct transfer."""
    output = handoff_tool.execute(
        reason="العميل أكل وجبة ويشعر بحساسية مفرطة ويريد التحدث فوراً مع الشيف أو الإدارة",
        customer_name="خالد سعيد",
        customer_phone="0501234567",
    )

    assert output.urgency == HandoffUrgencyEnum.CRITICAL
    assert output.status == "transferred"
    assert output.estimated_wait_seconds <= 15
    assert "فوراً" in output.message
    assert "سلامتكم" in output.message


def test_infer_delivery_department(handoff_tool):
    """Test automatic keyword inference for delivery dispatch department."""
    dept, urg = handoff_tool.infer_department_and_urgency(
        reason="السائق لم يصل ومندوب التوصيل لا يجيب على الهاتف والأوردر متأخر",
    )
    assert dept == HandoffDepartmentEnum.DELIVERY_DISPATCH
    assert urg in [HandoffUrgencyEnum.HIGH, HandoffUrgencyEnum.CRITICAL]

    output = handoff_tool.execute(
        reason="مندوب التوصيل ضل العنوان والأكل متأخر جداً",
        customer_name="طارق",
    )
    assert "التوصيل" in output.department


def test_infer_kitchen_department(handoff_tool):
    """Test automatic keyword inference for kitchen and food quality."""
    dept, urg = handoff_tool.infer_department_and_urgency(
        reason="الطعام وصل غير ناضج ومحروق ومكونات الصوص غير مطابقة",
    )
    assert dept == HandoffDepartmentEnum.KITCHEN_MANAGER

    output = handoff_tool.execute(
        reason="الأكل ني ومحروق والشيف لم يضع المكونات المطلوبة",
    )
    assert "المطبخ" in output.department


def test_infer_billing_department(handoff_tool):
    """Test automatic keyword inference for billing issues."""
    dept, urg = handoff_tool.infer_department_and_urgency(
        reason="تم خصم الفاتورة مرتين من البطاقة الائتمانية وأريد استرداد المبلغ",
    )
    assert dept == HandoffDepartmentEnum.BILLING

    output = handoff_tool.execute(
        reason="مشكلة في دفع الفاتورة بالفيزا ومبلغ مالي مخصوم بالخطأ",
    )
    assert "الحسابات" in output.department


def test_get_handoff_status(handoff_tool):
    """Test retrieving existing escalation ticket status."""
    existing = handoff_tool.get_handoff_status("ESC-1001")
    assert existing is not None
    assert existing["customer_name"] == "سامح فوزي"
    assert existing["department"] == HandoffDepartmentEnum.DELIVERY_DISPATCH

    not_found = handoff_tool.get_handoff_status("ESC-99999")
    assert not_found is None


def test_schedule_callback(handoff_tool):
    """Test scheduling a customer callback."""
    res = handoff_tool.schedule_callback(
        customer_phone="01155443322",
        customer_name="ياسر إبراهيم",
        preferred_time="10 دقائق",
        reason="انشغال الخطوط في ساعات الذروة",
    )
    assert res.success is True
    assert "ESC-" in res.message
    assert "ياسر إبراهيم" in res.message
    assert "10 دقائق" in res.message
    assert res.data["status"] == "callback_scheduled"


@pytest.mark.asyncio
async def test_async_escalate_to_human():
    """Test async convenience function for LiveKit pipeline turns."""
    output = await async_escalate_to_human(
        reason="العميل يرغب في تقديم شكوى بشأن جودة الخدمة",
        customer_name="أحمد فتحي",
        customer_phone="0556677889",
    )
    assert "ESC-" in output.handoff_id
    assert output.status in ["queued", "transferred"]
    assert "أحمد فتحي" in output.message
