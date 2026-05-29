"""
Unit tests for AuthService.logout and method delegation.

The authenticate and rotate flows are tested via property tests already.
These tests focus on the logout path (lines 150-159) and the delegation
wiring that other tests don't exercise.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.service import (
    AuthService,
    MAX_FAILED_ATTEMPTS,
    LOCKOUT_DURATION_MINUTES,
    LOCKOUT_WINDOW_MINUTES,
)


# ---------------------------------------------------------------------------
# Constant re-exports
# ---------------------------------------------------------------------------
def test_max_failed_attempts_is_positive_int():
    assert isinstance(MAX_FAILED_ATTEMPTS, int)
    assert MAX_FAILED_ATTEMPTS > 0


def test_lockout_durations_are_positive_ints():
    assert isinstance(LOCKOUT_DURATION_MINUTES, int)
    assert LOCKOUT_DURATION_MINUTES > 0
    assert isinstance(LOCKOUT_WINDOW_MINUTES, int)
    assert LOCKOUT_WINDOW_MINUTES > 0


# ---------------------------------------------------------------------------
# AuthService.logout
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_logout_executes_update_and_commits():
    """logout() hashes the token, runs UPDATE, and commits."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.commit = AsyncMock()

    svc = AuthService()
    await svc.logout(mock_db, "raw.refresh.token.value")

    mock_db.execute.assert_called_once()
    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_logout_hashes_token_before_query():
    """logout() must not pass the raw token to the SQL query (only its hash)."""
    raw_token = "very.secret.refresh.token"
    captured_sql = []

    async def capture_execute(stmt, *args, **kwargs):
        captured_sql.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))

    mock_db = AsyncMock()
    mock_db.execute = capture_execute
    mock_db.commit = AsyncMock()

    svc = AuthService()
    await svc.logout(mock_db, raw_token)

    # Raw token must NOT appear in compiled SQL
    combined = "\n".join(captured_sql)
    assert raw_token not in combined


# ---------------------------------------------------------------------------
# AuthService.authenticate delegates to authenticate.authenticate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_authenticate_delegates_to_module_function():
    """authenticate() calls the module-level _authenticate with all args."""
    mock_db = AsyncMock()
    fake_result = {
        "access_token": "a",
        "refresh_token": "r",
        "token_type": "bearer",
        "expires_in": 900,
    }

    with patch("app.modules.auth.service._authenticate", new=AsyncMock(return_value=fake_result)) as mock_auth:
        svc = AuthService()
        result = await svc.authenticate(
            db=mock_db,
            email="doc@x.com",
            password="secret",
            ip_address="1.2.3.4",
            user_agent="ua",
        )

    assert result == fake_result
    mock_auth.assert_called_once()
    kwargs = mock_auth.call_args.kwargs
    assert kwargs["email"] == "doc@x.com"
    assert kwargs["password"] == "secret"
    assert kwargs["ip_address"] == "1.2.3.4"
    assert kwargs["user_agent"] == "ua"


@pytest.mark.asyncio
async def test_rotate_refresh_token_delegates_to_module_function():
    """rotate_refresh_token() calls the module-level _rotate_refresh_token."""
    mock_db = AsyncMock()
    fake_result = {
        "access_token": "a2",
        "refresh_token": "r2",
        "token_type": "bearer",
        "expires_in": 900,
    }

    with patch("app.modules.auth.service._rotate_refresh_token", new=AsyncMock(return_value=fake_result)) as mock_rot:
        svc = AuthService()
        result = await svc.rotate_refresh_token(
            db=mock_db,
            refresh_token_value="old.token",
            ip_address="1.2.3.4",
            user_agent="ua",
        )

    assert result == fake_result
    mock_rot.assert_called_once()
    kwargs = mock_rot.call_args.kwargs
    assert kwargs["refresh_token_value"] == "old.token"
