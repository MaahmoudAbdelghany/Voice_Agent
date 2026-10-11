"""
Asynchronous Database Engine and Session Management for Voice Agent.

Provides SQLAlchemy 2.0 AsyncEngine configuration, connection pooling,
session factory, and context managers supporting both SQLite (local development)
and PostgreSQL (cloud production).
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from src.config import settings
from src.db.base import Base

logger = logging.getLogger(__name__)

# Global singletons for engine and session factory
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(
    database_url: str | None = None,
    echo: bool | None = None,
) -> AsyncEngine:
    """
    Get or create the AsyncEngine instance.

    If database_url is not provided, defaults to settings.database_url.
    When called without arguments, caches and returns the singleton engine.
    """
    global _engine

    target_url = database_url or settings.database_url
    target_echo = echo if echo is not None else settings.database_echo

    # Return cached singleton if using default settings and already initialized
    if database_url is None and echo is None and _engine is not None:
        return _engine

    connect_args = {}
    engine_kwargs = {
        "echo": target_echo,
    }

    if "sqlite" in target_url:
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30
        engine_kwargs["connect_args"] = connect_args

        if ":memory:" in target_url:
            engine_kwargs["poolclass"] = StaticPool
        else:
            # Ensure file-based SQLite directory exists
            settings.get_sqlite_db_path()
            engine_kwargs["pool_pre_ping"] = True
    elif "postgresql" in target_url:
        engine_kwargs["pool_size"] = 10
        engine_kwargs["max_overflow"] = 20
        engine_kwargs["pool_pre_ping"] = True

    created_engine = create_async_engine(target_url, **engine_kwargs)

    # Cache singleton when using default URL
    if database_url is None:
        _engine = created_engine

    logger.debug(f"Initialized AsyncEngine with URL: {target_url.split('@')[-1]}")
    return created_engine


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """
    Get or create an async_sessionmaker factory bound to the provided or default engine.
    """
    global _session_factory

    if engine is None and _session_factory is not None:
        return _session_factory

    target_engine = engine or get_engine()
    factory = async_sessionmaker(
        bind=target_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    if engine is None:
        _session_factory = factory

    return factory


@asynccontextmanager
async def get_async_session(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Asynchronous context manager yielding a managed AsyncSession.

    Automatically rolls back uncommitted transactions if an exception occurs
    and guarantees session closure in the finally block.
    """
    factory = session_factory or get_session_factory()
    session = factory()

    try:
        yield session
    except Exception as exc:
        await session.rollback()
        logger.error(f"Transaction rolled back due to error: {exc}")
        raise
    finally:
        await session.close()


async def init_db(engine: AsyncEngine | None = None) -> None:
    """
    Initialize all tables registered with DeclarativeBase.
    """
    target_engine = engine or get_engine()
    logger.info("Initializing database schemas registered on Base.metadata...")
    async with target_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schemas initialized successfully.")


async def close_db(engine: AsyncEngine | None = None) -> None:
    """
    Dispose of the database engine connection pool.
    """
    global _engine, _session_factory

    target_engine = engine or _engine
    if target_engine is not None:
        logger.info("Disposing database engine connection pool...")
        await target_engine.dispose()

    if engine is None:
        _engine = None
        _session_factory = None
