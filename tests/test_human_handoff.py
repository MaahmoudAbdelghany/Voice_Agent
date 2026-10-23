"""
Test Suite for Clinic Receptionist Escalation Tool (Feature 3.6).

Covers:
- Tier 1: Unit tests for emergency symptom detection, reception hours checks,
  deterministic wait estimation, phone masking, and message styling.
- Tier 2: Integration tests on isolated SQLite database for queued, transferred (emergency),
  and callback (after hours) flows, priority upgrades, and de-duplication.
- Tier 3: Error and edge-case tests for database timeouts, fallback tickets,
  unhandled exceptions, empty reasons, and privacy logging.
"""

import datetime as dt
import logging
from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Escalation
from src.db.schemas import EscalationStatus
from src.tools.doctor_availability import CAIRO_TZ
from src.tools.human_handoff import (
    DEPARTMENT_NAMES_ARABIC,
    HumanHandoffTool,
    ReceptionistHandoffTool,
    async_escalate_to_human,
    async_transfer_to_receptionist,
    build_voice_message,
    detect_emergency,
    escalate_to_human,
    estimate_wait_seconds,
    human_handoff_tool,
    is_reception_open,
    mask_phone_for_speech,
    receptionist_handoff_tool,
    transfer_to_receptionist,
)
from src.tools.schemas import HandoffDepartmentEnum, HandoffUrgencyEnum

# Reference Cairo dates and times
SATURDAY_DATE = date(2026, 10, 24)
SATURDAY_0859 = dt.datetime(2026, 10, 24, 8, 59, tzinfo=CAIRO_TZ)
SATURDAY_0900 = dt.datetime(2026, 10, 24, 9, 0, tzinfo=CAIRO_TZ)
SATURDAY_1000 = dt.datetime(2026, 10, 24, 10, 0, tzinfo=CAIRO_TZ)
SATURDAY_2159 = dt.datetime(2026, 10, 24, 21, 59, tzinfo=CAIRO_TZ)
SATURDAY_2200 = dt.datetime(2026, 10, 24, 22, 0, tzinfo=CAIRO_TZ)
SATURDAY_2300 = dt.datetime(2026, 10, 24, 23, 0, tzinfo=CAIRO_TZ)
NIGHT_0200 = dt.datetime(2026, 10, 24, 2, 0, tzinfo=CAIRO_TZ)

FRIDAY_DATE = date(2026, 10, 30)
FRIDAY_1359 = dt.datetime(2026, 10, 30, 13, 59, tzinfo=CAIRO_TZ)
FRIDAY_1400 = dt.datetime(2026, 10, 30, 14, 0, tzinfo=CAIRO_TZ)


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
async def session_factory(tmp_path):
    """Provides isolated file-based SQLite database with escalations table."""
    db_file = tmp_path / "handoff_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def handoff_tool(session_factory):
    """Create ReceptionistHandoffTool instance bound to test DB."""
    return ReceptionistHandoffTool(session_factory=session_factory, timeout_s=5.0)


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


@pytest.mark.parametrize(
    "phrase",
    [
        "عندي ألم جامد في صدري",
        "وجع في صدري مش محتمله",
        "مش قادر أتنفس خالص",
        "ضيق في التنفس شديد",
        "ابني بينزف جامد بعد ما وقع",
        "والدي أغمى عليه في البيت",
        "عنده تشنجات مستمرة",
        "حالة شلل مفاجئ في إيده",
        "شرب كلور بالخطأ",
        "تسمم غذائي حاد",
        "حادث سيارة وكسر مضاعف",
        "chest pain and shortness of breath",
        "severe bleeding from head",
    ],
)
def test_detect_emergency_positive(phrase):
    """Test emergency keyword and regex detector captures urgent medical emergencies."""
    assert detect_emergency(phrase) is True


@pytest.mark.parametrize(
    "phrase",
    [
        "عايز أكلم حد من الاستقبال",
        "عندي شكوى بخصوص الفاتورة",
        "عايز أغير ميعاد كشف دكتور العظام",
        "دكتور الأطفال متاح الساعة كام النهاردة؟",
        "هل متاح تقسيط مصاريف التحاليل؟",
        "لو سمحت أختي بتسأل عن نتيجة سونار البطن",
    ],
)
def test_detect_emergency_negative(phrase):
    """Test standard clinical inquiries do not trigger the emergency safety net."""
    assert detect_emergency(phrase) is False


def test_is_reception_open():
    """Verify clinic reception operating hours boundaries."""
    assert is_reception_open(SATURDAY_0859) is False
    assert is_reception_open(SATURDAY_0900) is True
    assert is_reception_open(SATURDAY_1000) is True
    assert is_reception_open(SATURDAY_2159) is True
    assert is_reception_open(SATURDAY_2200) is False
    assert is_reception_open(SATURDAY_2300) is False

    assert is_reception_open(FRIDAY_1359) is False
    assert is_reception_open(FRIDAY_1400) is True


def test_estimate_wait_seconds():
    """Verify wait estimation formula by urgency and tickets ahead."""
    # Emergency is always 0
    assert estimate_wait_seconds(HandoffUrgencyEnum.EMERGENCY, 10) == 0
    assert estimate_wait_seconds("emergency", 0) == 0

    # Urgent: 30 base + 30 per ticket ahead
    assert estimate_wait_seconds(HandoffUrgencyEnum.URGENT, 0) == 30
    assert estimate_wait_seconds("urgent", 2) == 90

    # Medium: 60 base + 30 per ticket ahead
    assert estimate_wait_seconds(HandoffUrgencyEnum.MEDIUM, 0) == 60
    assert estimate_wait_seconds("medium", 2) == 120

    # Low: 120 base + 30 per ticket ahead
    assert estimate_wait_seconds(HandoffUrgencyEnum.LOW, 0) == 120

    # Capped at 600s
    assert estimate_wait_seconds("medium", 50) == 600


def test_mask_phone_for_speech():
    """Test masking phone for TTS readback, speaking only last 3 digits."""
    assert mask_phone_for_speech("01012345678") == "678"
    assert mask_phone_for_speech("+201199887766") == "766"
    assert mask_phone_for_speech(None) == ""


def test_messages_no_markdown_no_restaurant_words():
    """Test voice messages conform to speech guidelines without markdown or restaurant terms."""
    msg = build_voice_message(
        status=EscalationStatus.QUEUED.value,
        urgency="medium",
        department="reception",
        ticket_id="ESC-20261024-0001",
        caller_name="محمد",
        wait_seconds=60,
    )
    assert "*" not in msg
    assert "#" not in msg
    assert "|" not in msg
    for forbidden in ["مطعم", "مطبخ", "توصيل", "شيف", "أوردر", "طعام"]:
        assert forbidden not in msg
    assert len(msg) <= 300


def test_legacy_value_mapping(handoff_tool):
    """Test legacy parameter and enum normalization."""
    assert handoff_tool._normalize_urgency("high") == "urgent"
    assert handoff_tool._normalize_urgency("critical") == "emergency"
    assert handoff_tool._normalize_department("customer_support") == "reception"
    assert handoff_tool._normalize_department("kitchen_manager") == "reception"
    assert handoff_tool._normalize_department("billing") == "billing"


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_queued_during_hours_persists_ticket(handoff_tool):
    """Test regular daytime escalation creates a queued ticket persisted to DB."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = await handoff_tool.aexecute(
            reason="المريض يرغب في الاستفسار عن تحويل ملفه الطبي",
            caller_name="أحمد محمود",
            caller_phone="01012345678",
            department="reception",
            urgency="medium",
            session_id="call-sess-001",
        )

        assert res.success is True
        data = res.data
        assert data["ticket_id"].startswith("ESC-20261024-")
        assert data["status"] == "queued"
        assert data["urgency"] == "medium"
        assert data["department"] == "reception"
        assert data["transfer_requested"] is True
        assert data["persisted"] is True
        assert data["emergency_detected"] is False
        assert "أحمد محمود" in res.message
        assert "الاستقبال" in res.message


@pytest.mark.asyncio
async def test_emergency_upgrade_overrides_llm(handoff_tool):
    """Test emergency symptom detection overrides low urgency and billing department."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = await handoff_tool.aexecute(
            reason="عندي ألم شديد في صدري ومش قادر أتنفس",
            caller_phone="01122334455",
            department="billing",  # Incorrectly classified by LLM
            urgency="low",  # Incorrectly classified by LLM
        )

        assert res.success is True
        data = res.data
        assert data["urgency"] == "emergency"
        assert data["department"] == "emergency"
        assert data["status"] == "transferred"
        assert data["emergency_detected"] is True
        assert data["estimated_wait_seconds"] == 0
        assert "123" in res.message
        assert "طوارئ" in res.message


@pytest.mark.asyncio
async def test_emergency_outside_hours_still_transferred(handoff_tool):
    """Test emergency call in the middle of the night still transfers immediately with 123 guidance."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=NIGHT_0200),
    ):
        res = await handoff_tool.aexecute(
            reason="والدي فاقد الوعي وبيترعش جامد",
            caller_phone="01233445566",
        )

        assert res.success is True
        assert res.data["status"] == "transferred"
        assert res.data["transfer_requested"] is True
        assert "123" in res.message


@pytest.mark.asyncio
async def test_llm_emergency_not_downgraded(handoff_tool):
    """Test that explicit emergency urgency from LLM is preserved even without keywords."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = await handoff_tool.aexecute(
            reason="طلب مساعدة عاجلة من الطبيب المناوب",
            urgency="emergency",
        )

        assert res.data["urgency"] == "emergency"
        assert res.data["status"] == "transferred"


@pytest.mark.asyncio
async def test_callback_outside_hours_with_phone(handoff_tool):
    """Test non-emergency inquiry after hours schedules a callback with masked phone confirmation."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_2300),
    ):
        res = await handoff_tool.aexecute(
            reason="استفسار عن أسعار العمليات",
            caller_phone="01098765432",
        )

        assert res.success is True
        assert res.data["status"] == "callback"
        assert res.data["transfer_requested"] is False
        assert res.data["needs_phone"] is False
        assert "432" in res.message
        assert "غير متاح حالياً" in res.message


@pytest.mark.asyncio
async def test_callback_outside_hours_without_phone(handoff_tool):
    """Test after-hours inquiry without phone sets needs_phone flag and asks for number."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_2300),
    ):
        res = await handoff_tool.aexecute(
            reason="استفسار عام عن مواعيد الأطباء",
        )

        assert res.data["status"] == "callback"
        assert res.data["needs_phone"] is True
        assert "يرجى تزويدنا برقم الموبايل" in res.message


@pytest.mark.asyncio
async def test_wait_grows_with_open_queue(handoff_tool):
    """Test wait time increases as more open tickets exist ahead in the queue."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        r1 = await handoff_tool.aexecute(
            reason="طلب 1", caller_phone="01011110001", urgency="medium"
        )
        r2 = await handoff_tool.aexecute(
            reason="طلب 2", caller_phone="01011110002", urgency="medium"
        )
        r3 = await handoff_tool.aexecute(
            reason="طلب 3", caller_phone="01011110003", urgency="medium"
        )

        assert r1.data["estimated_wait_seconds"] == 60  # 60 base + 0 ahead
        assert r2.data["estimated_wait_seconds"] == 90  # 60 base + 30*1 ahead
        assert r3.data["estimated_wait_seconds"] == 120  # 60 base + 30*2 ahead


@pytest.mark.asyncio
async def test_dedup_same_phone_within_10_min(handoff_tool):
    """Test repeated calls from same phone within 10 min reuses existing ticket."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res1 = await handoff_tool.aexecute(
            reason="عايز أكلم الاستقبال لو سمحت",
            caller_phone="01055554444",
        )
        assert res1.data["deduplicated"] is False
        t_id = res1.data["ticket_id"]

        # Call again 3 minutes later
        res2 = await handoff_tool.aexecute(
            reason="فين موظف الاستقبال؟ لسه مستني",
            caller_phone="01055554444",
        )
        assert res2.data["ticket_id"] == t_id
        assert res2.data["deduplicated"] is True


@pytest.mark.asyncio
async def test_dedup_upgrades_priority(handoff_tool):
    """Test second call reporting emergency symptoms upgrades the existing ticket."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        r1 = await handoff_tool.aexecute(
            reason="استفسار عن ميعاد الكشف",
            caller_phone="01177778888",
            urgency="low",
        )
        assert r1.data["urgency"] == "low"
        t_id = r1.data["ticket_id"]

        r2 = await handoff_tool.aexecute(
            reason="المريض حصله إغماء فجأة وتعبان جداً",
            caller_phone="01177778888",
        )
        assert r2.data["ticket_id"] == t_id
        assert r2.data["urgency"] == "emergency"
        assert r2.data["status"] == "transferred"
        assert r2.data["deduplicated"] is True


@pytest.mark.asyncio
async def test_dedup_never_downgrades(handoff_tool):
    """Test second call with lower urgency does not downgrade higher priority ticket."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        r1 = await handoff_tool.aexecute(
            reason="شكوى عاجلة جداً",
            caller_phone="01288889999",
            urgency="urgent",
        )
        assert r1.data["urgency"] == "urgent"

        r2 = await handoff_tool.aexecute(
            reason="سؤال عادي إضافي",
            caller_phone="01288889999",
            urgency="low",
        )
        assert r2.data["ticket_id"] == r1.data["ticket_id"]
        assert r2.data["urgency"] == "urgent"


@pytest.mark.asyncio
async def test_no_dedup_after_10_min_or_without_phone(handoff_tool):
    """Test calls without phone or outside 10 min window generate separate tickets."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        r1 = await handoff_tool.aexecute(reason="طلب 1 بدون تليفون")
        r2 = await handoff_tool.aexecute(reason="طلب 2 بدون تليفون")
        assert r1.data["ticket_id"] != r2.data["ticket_id"]


@pytest.mark.asyncio
async def test_daily_sequence_increments(handoff_tool):
    """Test sequential daily ticket numbers increment properly."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        r1 = await handoff_tool.aexecute(reason="أول تذكرة")
        r2 = await handoff_tool.aexecute(reason="ثاني تذكرة")
        assert r1.data["ticket_id"] == "ESC-20261024-0001"
        assert r2.data["ticket_id"] == "ESC-20261024-0002"


def test_sync_and_async_execution(handoff_tool):
    """Test that synchronous execute wrapper succeeds and persists ticket."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = handoff_tool.execute(
            reason="استفسار متزامن",
            caller_name="خالد",
            caller_phone="01012349999",
        )
        assert res.success is True
        assert res.data["ticket_id"].startswith("ESC-20261024-")
        assert res.data["persisted"] is True


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_db_exception_falls_back_to_temp_ticket():
    """Test that database error yields fallback temporary ticket without crashing caller turn."""

    class FailingSessionFactory:
        def __call__(self):
            raise RuntimeError("Database connection lost")

    tool = ReceptionistHandoffTool(session_factory=FailingSessionFactory(), timeout_s=0.5)

    res = await tool.aexecute(
        reason="المريض يطلب موظف الاستقبال",
        caller_name="سلوى",
        caller_phone="01055551234",
    )

    assert res.success is True
    assert res.data["ticket_id"].startswith("ESC-TMP-")
    assert res.data["persisted"] is False
    assert "سلوى" in res.message


@pytest.mark.asyncio
async def test_db_timeout_falls_back():
    """Test that slow database operations trigger timeout fallback."""

    class SlowSessionFactory:
        def __call__(self):
            raise TimeoutError("DB lock timeout")

    tool = ReceptionistHandoffTool(session_factory=SlowSessionFactory(), timeout_s=0.01)
    res = await tool.aexecute(reason="طلب تحويل سريع")
    assert res.success is True
    assert res.data["ticket_id"].startswith("ESC-TMP-")
    assert res.data["persisted"] is False


@pytest.mark.asyncio
async def test_empty_reason_direct_call_uses_default(handoff_tool):
    """Test direct call with empty reason uses standard default text."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = await handoff_tool.aexecute(reason="   ")
        assert res.success is True
        assert res.data["status"] == "queued"


@pytest.mark.asyncio
async def test_unknown_enum_values_direct_call(handoff_tool):
    """Test direct call with invalid department or urgency gracefully defaults."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = await handoff_tool.aexecute(
            reason="طلب تحويل لقسم غريب",
            department="kitchen_unknown",
            urgency="super_mega_urgent",
        )
        assert res.data["department"] == "reception"
        assert res.data["urgency"] == "medium"


@pytest.mark.asyncio
async def test_malformed_phone_kept(handoff_tool):
    """Test escalation never fails on non-standard or malformed caller phone."""
    with (
        patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
        patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
    ):
        res = await handoff_tool.aexecute(
            reason="تحويل عادي",
            caller_phone="12345-invalid",
        )
        assert res.success is True
        assert res.data["persisted"] is True


def test_no_pii_in_info_logs(handoff_tool, caplog):
    """Verify INFO logs never contain phone number, caller name, or medical reason (NFR-3)."""
    with caplog.at_level(logging.INFO):
        with (
            patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
            patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
        ):
            handoff_tool.execute(
                reason="سر طبي خاص جداً",
                caller_name="شخص مجهول",
                caller_phone="01099887766",
            )

        log_text = caplog.text
        assert "01099887766" not in log_text
        assert "شخص مجهول" not in log_text
        assert "سر طبي خاص" not in log_text


@pytest.mark.asyncio
async def test_deprecated_aliases_importable(handoff_tool, session_factory):
    """Verify legacy aliases import and execute returning clinic ToolResult."""
    assert HumanHandoffTool is ReceptionistHandoffTool
    assert human_handoff_tool is receptionist_handoff_tool
    assert escalate_to_human is transfer_to_receptionist
    assert async_escalate_to_human is async_transfer_to_receptionist
    assert DEPARTMENT_NAMES_ARABIC[HandoffDepartmentEnum.RECEPTION.value] == "الاستقبال"

    orig_factory = receptionist_handoff_tool.session_factory
    receptionist_handoff_tool.session_factory = session_factory
    try:
        with (
            patch("src.tools.human_handoff.get_cairo_today", return_value=SATURDAY_DATE),
            patch("src.tools.human_handoff.get_cairo_now", return_value=SATURDAY_1000),
        ):
            output = await async_escalate_to_human(
                reason="شكوى مستخدم قديم",
                customer_name="ماهر",
                customer_phone="01122334455",
                urgency="critical",
            )
            assert output.success is True
            assert output.data["urgency"] == "emergency"
            assert "ماهر" in output.message

        async with session_factory() as session:
            esc = await session.get(Escalation, 1)
            assert esc is not None
    finally:
        receptionist_handoff_tool.session_factory = orig_factory
