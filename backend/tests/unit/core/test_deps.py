"""
Unit tests for app.core.deps.

Tests FastAPI dependency injection helpers:
- get_db: yields session, rolls back on error, always closes
- get_tenant_db: sets RLS tenant context before yielding session
- get_current_user / get_tenant: stub functions that raise AuthError
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.core import deps
from app.core.exceptions import AuthError


# ---------------------------------------------------------------------------
# Test: get_current_user() and get_tenant() stubs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_current_user_raises_auth_error():
    """get_current_user stub raises AuthError."""
    with pytest.raises(AuthError) as exc_info:
        await deps.get_current_user()
    assert "not yet implemented" in str(exc_info.value).lower() or "authentication" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_get_tenant_raises_auth_error():
    """get_tenant stub raises AuthError."""
    with pytest.raises(AuthError):
        await deps.get_tenant()


# ---------------------------------------------------------------------------
# Test: get_db() — session lifecycle
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_db_yields_session_and_closes():
    """get_db yields a session and closes it after consumption."""
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.rollback = AsyncMock()

    # Build async context manager that yields mock_session
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_ctx)

    with patch.object(deps, "get_session_factory", return_value=mock_factory):
        gen = deps.get_db()
        session = await gen.__anext__()
        assert session is mock_session

        # Close the generator
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception():
    """get_db rolls back the session if the caller raises."""
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_ctx)

    with patch.object(deps, "get_session_factory", return_value=mock_factory):
        gen = deps.get_db()
        await gen.__anext__()

        # Simulate exception during request handling
        try:
            await gen.athrow(ValueError("simulated request error"))
        except ValueError:
            pass

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# Test: get_tenant_db() — RLS context is set before yielding
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_tenant_db_sets_tenant_context_before_yield():
    """get_tenant_db calls set_tenant_context BEFORE yielding session."""
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_ctx)
    mock_set_tenant = AsyncMock()

    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    with patch.object(deps, "get_session_factory", return_value=mock_factory):
        with patch.object(deps, "set_tenant_context", mock_set_tenant):
            gen = deps.get_tenant_db(tenant_id)
            session = await gen.__anext__()
            assert session is mock_session

            # Verify set_tenant_context was called with the tenant UUID as a string
            mock_set_tenant.assert_called_once_with(mock_session, str(tenant_id))

            # Close generator
            try:
                await gen.__anext__()
            except StopAsyncIteration:
                pass

    mock_session.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_tenant_db_rolls_back_on_exception():
    """get_tenant_db rolls back when caller raises."""
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_ctx)
    mock_set_tenant = AsyncMock()

    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    with patch.object(deps, "get_session_factory", return_value=mock_factory):
        with patch.object(deps, "set_tenant_context", mock_set_tenant):
            gen = deps.get_tenant_db(tenant_id)
            await gen.__anext__()

            try:
                await gen.athrow(RuntimeError("simulated"))
            except RuntimeError:
                pass

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
