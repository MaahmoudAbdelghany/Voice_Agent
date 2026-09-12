"""
Unit Tests for Table Reservation and Availability Tool.
"""

import pytest
from src.tools.reservation import (
    ReservationTool,
    book_reservation,
    async_book_reservation,
)
from src.tools.schemas import ReservationStatusEnum


@pytest.fixture
def res_tool():
    """Create a fresh ReservationTool instance."""
    return ReservationTool()


def test_book_valid_reservation(res_tool):
    """Test standard table booking for a normal party size."""
    output = res_tool.execute(
        customer_name="طارق يوسف",
        phone_number="+966501239876",
        party_size=4,
        date="2026-09-15",
        time="20:00",
        special_requests="طاولة قريبة من النافذة",
        branch="فرع التجمع الخامس",
    )
    assert output.status == ReservationStatusEnum.CONFIRMED
    assert output.customer_name == "طارق يوسف"
    assert output.party_size == 4
    assert output.table_number is not None
    assert output.table_number >= 1
    assert "RES-" in output.reservation_id
    assert "RES-" in output.confirmation_code
    assert "تم تأكيد حجزك بنجاح" in output.message
    assert "فرع التجمع الخامس" in output.message
    assert "15 دقيقة" in output.message


def test_book_reservation_party_over_capacity(res_tool):
    """Test booking for group > 30 triggers event catering policy."""
    output = res_tool.execute(
        customer_name="شركة التقنية",
        phone_number="01011223344",
        party_size=45,
        date="2026-09-20",
        time="19:00",
    )
    assert output.status == ReservationStatusEnum.REJECTED
    assert "REQ-EVENT" in output.reservation_id
    assert "تتعدى 30 فرداً" in output.message


def test_book_reservation_invalid_party_size(res_tool):
    """Test party size < 1 returns invalid status."""
    output = res_tool.execute(
        customer_name="سعيد",
        phone_number="01000000000",
        party_size=0,
        date="2026-09-15",
        time="18:00",
    )
    assert output.status == ReservationStatusEnum.REJECTED
    assert "يرجى تحديد عدد أفراد صحيح" in output.message


def test_book_reservation_colloquial_dates(res_tool):
    """Test colloquial Arabic/English dates like 'today', 'tomorrow', 'اليوم', 'بكرة'."""
    output_today = res_tool.execute(
        customer_name="منى سامي",
        phone_number="0551234567",
        party_size=2,
        date="اليوم",
        time="21:00",
    )
    assert output_today.status == ReservationStatusEnum.CONFIRMED
    assert len(output_today.date.split("-")) == 3  # Valid YYYY-MM-DD format

    output_tomorrow = res_tool.execute(
        customer_name="منى سامي",
        phone_number="0551234567",
        party_size=2,
        date="بكرة",
        time="21:00",
    )
    assert output_tomorrow.status == ReservationStatusEnum.CONFIRMED
    assert len(output_tomorrow.date.split("-")) == 3


def test_check_availability(res_tool):
    """Test checking table availability for date, time, and party size."""
    avail = res_tool.check_availability(
        date="2026-09-18",
        time="20:00",
        party_size=4,
    )
    assert avail["available"] is True
    assert avail["party_size"] == 4

    # Over 30 check
    over_limit = res_tool.check_availability(
        date="2026-09-18",
        time="20:00",
        party_size=35,
    )
    assert over_limit["available"] is False


def test_get_existing_reservation(res_tool):
    """Test finding an existing reservation by ID and by phone number."""
    res_by_id = res_tool.get_reservation("RES-1001")
    assert res_by_id is not None
    assert res_by_id["customer_name"] == "محمد حسن"
    assert res_by_id["party_size"] == 4

    res_by_phone = res_tool.get_reservation("+966509998877")
    assert res_by_phone is not None
    assert res_by_phone["customer_name"] == "نورة العلي"


def test_cancel_reservation(res_tool):
    """Test cancelling an active reservation."""
    cancel_res = res_tool.cancel_reservation("RES-1001")
    assert cancel_res.success is True
    assert "تم إلغاء حجزكم" in cancel_res.message

    # Verify status changed in store
    record = res_tool.get_reservation("RES-1001")
    assert record["status"] == ReservationStatusEnum.CANCELLED

    # Cancel non-existent reservation
    fail_res = res_tool.cancel_reservation("RES-99999")
    assert fail_res.success is False


@pytest.mark.asyncio
async def test_async_book_reservation():
    """Test asynchronous booking call."""
    output = await async_book_reservation(
        customer_name="يوسف عادل",
        phone_number="+966504433221",
        party_size=3,
        date="2026-09-16",
        time="19:00",
        branch="فرع الدقي",
    )
    assert output.status == ReservationStatusEnum.CONFIRMED
    assert output.customer_name == "يوسف عادل"
    assert "فرع الدقي" in output.message
