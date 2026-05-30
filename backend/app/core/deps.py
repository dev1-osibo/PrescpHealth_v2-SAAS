"""
PrescpHealth Backend — FastAPI Dependencies.

Centralized dependency injection functions used across all routers.
These are the building blocks that every endpoint uses:
- get_db: Database session per request
- get_current_user: Authenticated user from JWT
- get_tenant: Current tenant context for RLS

Why centralize dependencies:
- Single source of truth for how resources are obtained
- Easy to mock in tests (override the dependency)
- Consistent behavior across all endpoints
- Changes propagate automatically to all consumers

Usage in routers:
    from app.core.deps import get_db, get_current_user

    @router.get("/patients")
    async def list_patients(
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_current_user),
    ):
        ...
"""

from typing import AsyncGenerator
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory, set_tenant_context
from app.core.request_context import get_request_id  # noqa: F401 — re-exported for router convenience

# ---------------------------------------------------------------------------
# Module logger
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Database Session Dependency
# ---------------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session for the current request.

    Yields an AsyncSession and ensures cleanup after the request.
    Transaction management:
    - Commits are explicit (service layer calls session.commit())
    - Rollback happens automatically on unhandled exceptions
    - Session is always closed in the finally block

    The tenant context (RLS) is set by get_tenant_db() which wraps this.

    Yields:
        AsyncSession: Database session for the current request.
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


# ---------------------------------------------------------------------------
# Tenant-Scoped Database Session Dependency
# ---------------------------------------------------------------------------
async def get_tenant_db(
    tenant_id: UUID,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Provide a database session with tenant RLS context set.

    This is the dependency that most endpoints should use — it ensures
    the PostgreSQL session variable is set BEFORE any queries run,
    so RLS policies filter data to the current tenant automatically.

    Args:
        tenant_id: The authenticated user's tenant UUID.

    Yields:
        AsyncSession: Tenant-scoped database session.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            # Set RLS context BEFORE any queries — this is the security boundary
            await set_tenant_context(session, str(tenant_id))
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Current User Dependency (Stub — implemented in Task 3)
# ---------------------------------------------------------------------------
async def get_current_user():
    """
    Extract and validate the current authenticated user from JWT.

    This is a STUB — full implementation comes in Task 3 (Auth module).
    Once implemented, this will:
    1. Extract JWT from Authorization header
    2. Validate token signature and expiry
    3. Load user from database
    4. Return User model instance

    Raises:
        AuthError: If token is missing, expired, or invalid.

    Returns:
        User: The authenticated user model instance.
    """
    # TODO: Implement in Task 3.2 (Auth service)
    # For now, raise to prevent accidental use before auth is wired
    from app.core.exceptions import AuthError
    raise AuthError(message="Authentication not yet implemented")


# ---------------------------------------------------------------------------
# Current Tenant Dependency (Stub — implemented in Task 3)
# ---------------------------------------------------------------------------
async def get_tenant() -> UUID:
    """
    Extract the current tenant_id from the authenticated user's context.

    This is a STUB — full implementation comes in Task 3 (Auth module).
    Once implemented, this will extract tenant_id from the JWT claims
    that were decoded by get_current_user().

    Returns:
        UUID: The current tenant's unique identifier.
    """
    # TODO: Implement in Task 3.2 (Auth service)
    from app.core.exceptions import AuthError
    raise AuthError(message="Tenant context not yet implemented")


# ---------------------------------------------------------------------------
# Alias: get_tenant_id (used by newer modules that expect this name)
# ---------------------------------------------------------------------------
get_tenant_id = get_tenant
