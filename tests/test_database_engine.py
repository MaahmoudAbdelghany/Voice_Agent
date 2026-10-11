"""
Unit and Integration Tests for Configuration and Async Database Engine.
"""

import shutil
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from src.config import Settings
from src.db.base import Base
from src.db.session import (
    close_db,
    get_async_session,
    get_engine,
    get_session_factory,
    init_db,
)


class DummyTable(Base):
    """Temporary test entity to verify schema creation and transactions."""

    __tablename__ = "dummy_test_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)


# --- Tier 1: Unit Verification ---


def test_clinic_settings_defaults():
    """Verify clinic settings default values and helpers."""
    app_settings = Settings()

    assert "النور" in app_settings.clinic_name
    assert app_settings.agent_name == "نور"
    assert app_settings.emergency_phone == "123"
    assert "+20" in app_settings.clinic_phone
    assert "المعادي" in app_settings.clinic_address
    assert "9:00" in app_settings.clinic_working_hours
    assert app_settings.qdrant_collection == "clinic_kb"
    assert "sqlite+aiosqlite" in app_settings.database_url
    assert app_settings.is_database_configured() is True


def test_legacy_restaurant_aliases():
    """Verify backward compatibility aliases delegate to clinic fields."""
    app_settings = Settings()

    assert app_settings.restaurant_name == app_settings.clinic_name
    assert app_settings.restaurant_phone == app_settings.clinic_phone
    assert app_settings.restaurant_address == app_settings.clinic_address
    assert app_settings.restaurant_hours == app_settings.clinic_working_hours


def test_legacy_dict_initialization_mapping():
    """Verify legacy dictionary keys map to clinic fields when initialized directly."""
    legacy_settings = Settings(
        restaurant_name="مطعم الأندلس",
        restaurant_phone="01011112222",
        restaurant_address="الدقي، الجيزة",
        restaurant_hours="10:00 - 24:00",
    )

    assert legacy_settings.clinic_name == "مطعم الأندلس"
    assert legacy_settings.clinic_phone == "01011112222"
    assert legacy_settings.clinic_address == "الدقي، الجيزة"
    assert legacy_settings.clinic_working_hours == "10:00 - 24:00"


def test_declarative_base_naming_conventions():
    """Verify Base has naming conventions configured for constraints."""
    convention = Base.metadata.naming_convention
    assert "pk" in convention
    assert "fk" in convention
    assert "ix" in convention
    assert "uq" in convention
    assert "ck" in convention


def test_engine_and_session_factory_creation():
    """Verify get_engine and get_session_factory return valid asynchronous instances."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    assert isinstance(test_engine, AsyncEngine)

    factory = get_session_factory(engine=test_engine)
    session = factory()
    assert isinstance(session, AsyncSession)


# --- Tier 2: Integration Verification ---


@pytest.mark.asyncio
async def test_async_session_execution():
    """Verify async query execution inside get_async_session context manager."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    test_factory = get_session_factory(engine=test_engine)

    async with get_async_session(session_factory=test_factory) as session:
        result = await session.execute(text("SELECT 1 AS num"))
        scalar = result.scalar()
        assert scalar == 1

    await close_db(engine=test_engine)


@pytest.mark.asyncio
async def test_init_db_and_close_db():
    """Verify init_db creates registered tables and close_db disposes engine."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")

    # Initialize tables
    await init_db(engine=test_engine)

    # Insert and query dummy entity to prove schema exists
    test_factory = get_session_factory(engine=test_engine)
    async with get_async_session(session_factory=test_factory) as session:
        new_item = DummyTable(name="Consultation Room 1")
        session.add(new_item)
        await session.commit()

        queried = await session.execute(
            text("SELECT name FROM dummy_test_items WHERE name = 'Consultation Room 1'")
        )
        assert queried.scalar() == "Consultation Room 1"

    # Close and dispose
    await close_db(engine=test_engine)


# --- Tier 3: Error & Edge-Case Verification ---


@pytest.mark.asyncio
async def test_transaction_rollback_on_exception():
    """Verify uncommitted transactions are rolled back when an error is raised."""
    test_engine = get_engine(database_url="sqlite+aiosqlite:///:memory:")
    await init_db(engine=test_engine)
    test_factory = get_session_factory(engine=test_engine)

    # Attempt to insert an item and simulate failure before commit
    with pytest.raises(RuntimeError, match="Simulated appointment error"):
        async with get_async_session(session_factory=test_factory) as session:
            item = DummyTable(name="Rolled Back Item")
            session.add(item)
            # Raise exception before committing
            raise RuntimeError("Simulated appointment error")

    # Verify item was not persisted in database
    async with get_async_session(session_factory=test_factory) as session:
        result = await session.execute(
            text("SELECT count(*) FROM dummy_test_items WHERE name = 'Rolled Back Item'")
        )
        assert result.scalar() == 0

    await close_db(engine=test_engine)


def test_sqlite_directory_auto_creation():
    """Verify get_sqlite_db_path automatically creates parent directory if missing."""
    temp_dir = tempfile.mkdtemp()
    target_subpath = Path(temp_dir) / "nested_subfolder" / "test_clinic.db"

    try:
        custom_settings = Settings(
            database_url=f"sqlite+aiosqlite:///{target_subpath.as_posix()}"
        )
        resolved_path = custom_settings.get_sqlite_db_path()

        assert resolved_path is not None
        assert Path(resolved_path).parent.exists()
        assert Path(resolved_path).parent.is_dir()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
