"""
PrescpHealth Backend — Async Database Engine and Session Management.

Provides the SQLAlchemy async engine, session factory, and FastAPI dependency
for database access. All database operations in the application go through
this module — no direct engine creation elsewhere.

Architecture:
    - AsyncEngine: Connection pool to PostgreSQL (asyncpg driver)
    - async_session_factory: Creates AsyncSession instances per request
    - get_db(): FastAPI dependency that yields a session and handles cleanup
    - set_tenant_context(): Sets RLS tenant variable on each session

Tenant Isolation:
    PostgreSQL Row-Level Security (RLS) is enforced at the database level.
    Before every query, we SET the session variable 'app.current_tenant'
    so RLS policies filter data automatically. This means even if application
    code has a bug, cross-tenant data access is IMPOSSIBLE.

Connection Pool:
    Pool size and overflow are configured via Settings. The pool is created
    once at startup (in lifespan) and shared across all requests.
"""

from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from app.config import get_settings

# ---------------------------------------------------------------------------
# Module logger — never logs PHI, only connection metadata
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Global engine and session factory — initialized at startup
# ---------------------------------------------------------------------------
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """
    Get the global async database engine.

    Raises RuntimeError if called before init_db() — this prevents
    accidental use before the application lifespan has started.

    Returns:
        AsyncEngine: The SQLAlchemy async engine instance.
    """
    if _engine is None:
        raise RuntimeError(
            "Database engine not initialized. Call init_db() first "
            "(this happens automatically during app startup)."
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Get the global async session factory.

    Returns:
        async_sessionmaker: Factory for creating AsyncSession instances.
    """
    if _async_session_factory is None:
        raise RuntimeError(
            "Session factory not initialized. Call init_db() first."
        )
    return _async_session_factory


async def init_db() -> None:
    """
    Initialize the database engine and session factory.

    Called once during application startup (in lifespan handler).
    Creates the connection pool with settings from environment config.

    Pool Configuration:
        - pool_size: Number of persistent connections (default 20)
        - max_overflow: Extra connections allowed under load (default 10)
        - pool_timeout: Seconds to wait for a connection before error (default 30)
        - pool_pre_ping: Verify connections are alive before using them
    """
    global _engine, _async_session_factory

    settings = get_settings()

    logger.info(
        "initializing_database",
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )

    _engine = create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        # Verify connections are alive before handing them to a request.
        # Prevents "connection closed" errors from idle pool connections.
        pool_pre_ping=True,
        # Echo SQL in development only (NEVER in production — may log PHI)
        echo=settings.is_development,
    )

    _async_session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    logger.info("database_initialized")


async def close_db() -> None:
    """
    Close the database engine and release all connections.

    Called during application shutdown (in lifespan handler).
    Ensures all connections are returned to the pool and closed cleanly.
    """
    global _engine, _async_session_factory

    if _engine is not None:
        await _engine.dispose()
        logger.info("database_connections_closed")

    _engine = None
    _async_session_factory = None


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """
    Set the PostgreSQL session variable for Row-Level Security.

    This MUST be called before any query on a tenant-scoped table.
    RLS policies use: tenant_id = current_setting('app.current_tenant')::uuid

    Args:
        session: The active database session.
        tenant_id: UUID string of the current tenant.

    Security:
        This is the mechanism that makes cross-tenant access IMPOSSIBLE
        at the database level. Even if application code has a bug that
        doesn't filter by tenant_id, RLS will block the query.
    """
    await session.execute(
        text("SET LOCAL app.current_tenant = :tenant_id"),
        {"tenant_id": tenant_id},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.

    Yields an AsyncSession and ensures it's closed after the request
    completes (whether successful or not). Transaction management:
    - Commits are explicit (service layer calls session.commit())
    - Rollback happens automatically on unhandled exceptions
    - Session is always closed in the finally block

    Usage:
        @router.get("/patients")
        async def list_patients(db: AsyncSession = Depends(get_db)):
            ...

    Yields:
        AsyncSession: A database session for the current request.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
