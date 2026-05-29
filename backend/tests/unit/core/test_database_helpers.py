"""
Unit tests for app.core.database helper functions.

Tests:
- get_engine / get_session_factory raise RuntimeError before init
- set_tenant_context validates UUID and emits SET LOCAL
- close_db is safe to call when nothing is initialized
- get_db error path triggers rollback
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core import database


def test_get_engine_raises_when_not_initialized(monkeypatch):
    """get_engine raises RuntimeError if engine is None."""
    monkeypatch.setattr(database, "_engine", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        database.get_engine()


def test_get_engine_returns_engine_when_initialized(monkeypatch):
    """get_engine returns the engine when set."""
    sentinel = object()
    monkeypatch.setattr(database, "_engine", sentinel)
    assert database.get_engine() is sentinel


def test_get_session_factory_raises_when_not_initialized(monkeypatch):
    """get_session_factory raises RuntimeError if factory is None."""
    monkeypatch.setattr(database, "_async_session_factory", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        database.get_session_factory()


def test_get_session_factory_returns_factory_when_initialized(monkeypatch):
    """get_session_factory returns the factory when set."""
    sentinel = object()
    monkeypatch.setattr(database, "_async_session_factory", sentinel)
    assert database.get_session_factory() is sentinel


@pytest.mark.asyncio
async def test_close_db_safe_when_engine_is_none(monkeypatch):
    """close_db is a no-op when engine is None."""
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_async_session_factory", None)

    await database.close_db()  # Must not raise

    assert database._engine is None
    assert database._async_session_factory is None


@pytest.mark.asyncio
async def test_close_db_disposes_engine_when_set(monkeypatch):
    """close_db calls dispose on engine and resets globals."""
    mock_engine = AsyncMock()
    mock_engine.dispose = AsyncMock()

    monkeypatch.setattr(database, "_engine", mock_engine)
    monkeypatch.setattr(database, "_async_session_factory", MagicMock())

    await database.close_db()

    mock_engine.dispose.assert_called_once()
    assert database._engine is None
    assert database._async_session_factory is None


# ---------------------------------------------------------------------------
# set_tenant_context — UUID validation and SET LOCAL emission
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_tenant_context_executes_set_local():
    """set_tenant_context emits SET LOCAL app.current_tenant with validated UUID."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    tenant_id = str(uuid4())

    await database.set_tenant_context(mock_session, tenant_id)

    mock_session.execute.assert_called_once()
    # Inspect the text() argument
    args, _ = mock_session.execute.call_args
    sql_clause = args[0]
    rendered = str(sql_clause)
    assert "SET LOCAL app.current_tenant" in rendered
    assert tenant_id in rendered


@pytest.mark.asyncio
async def test_set_tenant_context_rejects_invalid_uuid():
    """set_tenant_context raises ValueError for non-UUID input (SQL injection guard)."""
    mock_session = AsyncMock()

    with pytest.raises(ValueError):
        await database.set_tenant_context(
            mock_session, "'; DROP TABLE patients; --"
        )


@pytest.mark.asyncio
async def test_set_tenant_context_rejects_empty_string():
    """set_tenant_context raises ValueError for empty string."""
    mock_session = AsyncMock()
    with pytest.raises(ValueError):
        await database.set_tenant_context(mock_session, "")


@pytest.mark.asyncio
async def test_set_tenant_context_rejects_random_garbage():
    """set_tenant_context raises ValueError for non-UUID garbage."""
    mock_session = AsyncMock()
    with pytest.raises(ValueError):
        await database.set_tenant_context(mock_session, "not-a-uuid")


# ---------------------------------------------------------------------------
# get_db — error path rollback
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception():
    """get_db rolls back the session when the caller raises."""
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()
    mock_session.rollback = AsyncMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_ctx)

    with patch.object(database, "get_session_factory", return_value=mock_factory):
        gen = database.get_db()
        await gen.__anext__()

        try:
            await gen.athrow(RuntimeError("simulated"))
        except RuntimeError:
            pass

    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()
