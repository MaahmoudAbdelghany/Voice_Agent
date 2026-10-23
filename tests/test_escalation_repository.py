"""
Unit and Integration Tests for ClinicRepository Escalations and Handoffs.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.repository import (
    ClinicRepository,
    ClinicRepositoryError,
    EscalationNotFoundError,
)
from src.db.schemas import EscalationStatus


@pytest.fixture
async def session_factory(tmp_path):
    """Provides isolated file-based SQLite database with escalations table."""
    db_file = tmp_path / "escalation_repo_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_find_recent_open(session_factory):
    """Test creating an escalation and finding it by phone within the time threshold."""
    async with session_factory() as session:
        repo = ClinicRepository(session)
        c_date = date(2026, 10, 24)
        esc = await repo.create_escalation(
            reason="استفسار عن عملية جراحية",
            caller_name="عمرو خالد",
            caller_phone="01011112222",
            department="reception",
            urgency="medium",
            status="queued",
            cairo_date=c_date,
        )

        assert esc.ticket_id == "ESC-20261024-0001"
        assert esc.caller_name == "عمرو خالد"
        assert esc.status == "queued"

        # Search recent within 10 minutes
        since = datetime.now(timezone.utc) - timedelta(minutes=10)
        found = await repo.find_recent_open_escalation("01011112222", since=since)
        assert found is not None
        assert found.ticket_id == "ESC-20261024-0001"

        # Search older time threshold
        future_since = datetime.now(timezone.utc) + timedelta(minutes=5)
        not_found = await repo.find_recent_open_escalation("01011112222", since=future_since)
        assert not_found is None


@pytest.mark.asyncio
async def test_count_open_with_min_urgency(session_factory):
    """Test counting open tickets with optional minimum urgency filtering."""
    async with session_factory() as session:
        repo = ClinicRepository(session)
        c_date = date(2026, 10, 24)

        await repo.create_escalation(
            reason="طلب عادي", urgency="low", status="queued", cairo_date=c_date
        )
        await repo.create_escalation(
            reason="طلب متوسط 1", urgency="medium", status="queued", cairo_date=c_date
        )
        await repo.create_escalation(
            reason="طلب متوسط 2", urgency="medium", status="queued", cairo_date=c_date
        )
        await repo.create_escalation(
            reason="طلب عاجل", urgency="urgent", status="queued", cairo_date=c_date
        )
        await repo.create_escalation(
            reason="طلب طارئ", urgency="emergency", status="transferred", cairo_date=c_date
        )

        total_open = await repo.count_open_escalations()
        assert total_open == 5

        med_and_above = await repo.count_open_escalations(min_urgency="medium")
        assert med_and_above == 4  # medium (2) + urgent (1) + emergency (1)

        urgent_and_above = await repo.count_open_escalations(min_urgency="urgent")
        assert urgent_and_above == 2  # urgent (1) + emergency (1)

        emergency_only = await repo.count_open_escalations(min_urgency="emergency")
        assert emergency_only == 1


@pytest.mark.asyncio
async def test_list_open_order_emergency_first_then_oldest(session_factory):
    """Test listing open tickets sorted by priority (emergency first) then FIFO."""
    async with session_factory() as session:
        repo = ClinicRepository(session)
        c_date = date(2026, 10, 24)

        t1 = await repo.create_escalation(
            reason="أول تذكرة متوسطة", urgency="medium", status="queued", cairo_date=c_date
        )
        t2 = await repo.create_escalation(
            reason="ثاني تذكرة منخفضة", urgency="low", status="queued", cairo_date=c_date
        )
        t3 = await repo.create_escalation(
            reason="ثالث تذكرة طارئة جداً",
            urgency="emergency",
            status="transferred",
            cairo_date=c_date,
        )
        t4 = await repo.create_escalation(
            reason="رابع تذكرة عاجلة", urgency="urgent", status="queued", cairo_date=c_date
        )

        results = await repo.list_open_escalations()
        assert len(results) == 4
        assert results[0].ticket_id == t3.ticket_id  # emergency
        assert results[1].ticket_id == t4.ticket_id  # urgent
        assert results[2].ticket_id == t1.ticket_id  # medium
        assert results[3].ticket_id == t2.ticket_id  # low


@pytest.mark.asyncio
async def test_update_status_acknowledged_and_resolved_sets_timestamps(session_factory):
    """Test updating escalation status updates status and sets acknowledged_at / resolved_at."""
    async with session_factory() as session:
        repo = ClinicRepository(session)
        c_date = date(2026, 10, 24)

        esc = await repo.create_escalation(
            reason="شكوى", urgency="medium", status="queued", cairo_date=c_date
        )
        assert esc.status == "queued"
        assert esc.acknowledged_at is None
        assert esc.resolved_at is None

        # Acknowledge
        ack = await repo.update_escalation_status(esc.ticket_id, EscalationStatus.ACKNOWLEDGED)
        assert ack.status == "acknowledged"
        assert ack.acknowledged_at is not None
        assert ack.resolved_at is None

        # Resolve
        resolved = await repo.update_escalation_status(esc.ticket_id, EscalationStatus.RESOLVED)
        assert resolved.status == "resolved"
        assert resolved.resolved_at is not None

        # Resolved ticket excluded from open list
        open_list = await repo.list_open_escalations()
        assert len(open_list) == 0


@pytest.mark.asyncio
async def test_update_status_unknown_ticket_raises(session_factory):
    """Test updating non-existent escalation ticket raises EscalationNotFoundError."""
    async with session_factory() as session:
        repo = ClinicRepository(session)
        with pytest.raises(EscalationNotFoundError):
            await repo.update_escalation_status("ESC-99999999-9999", EscalationStatus.ACKNOWLEDGED)


@pytest.mark.asyncio
async def test_resolved_cannot_reopen(session_factory):
    """Test that an already resolved ticket cannot have its status updated."""
    async with session_factory() as session:
        repo = ClinicRepository(session)
        c_date = date(2026, 10, 24)

        esc = await repo.create_escalation(
            reason="شكوى", urgency="medium", status="queued", cairo_date=c_date
        )
        await repo.update_escalation_status(esc.ticket_id, EscalationStatus.RESOLVED)

        with pytest.raises(ClinicRepositoryError, match="already resolved"):
            await repo.update_escalation_status(esc.ticket_id, EscalationStatus.ACKNOWLEDGED)
