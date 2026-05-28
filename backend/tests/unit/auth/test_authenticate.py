"""
Unit tests for authentication logic (lockout, helpers).

Tests the authenticate module's helper functions and lockout policy
without requiring a real database. Uses mocked AsyncSession and User
objects to verify business rules.

Validates:
- _is_lockout_expired returns True when lockout duration has passed
- _is_lockout_expired returns False when lockout is still active
- _record_failed_attempt increments counter and locks at threshold
- _record_successful_login resets failed attempts
- authenticate raises AuthError for unknown email
- authenticate raises AuthError for locked account
- authenticate raises AuthError for inactive account
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.auth.authenticate import (
    LOCKOUT_DURATION_MINUTES,
    MAX_FAILED_ATTEMPTS,
    _is_lockout_expired,
    _record_failed_attempt,
    _record_successful_login,
    _unlock_account,
    authenticate,
)
from app.core.exceptions import AuthError


# ---------------------------------------------------------------------------
# Test: Lockout expiry detection
# ---------------------------------------------------------------------------
class TestLockoutExpiry:
    """Verify _is_lockout_expired correctly detects expired lockouts."""

    def test_expired_when_locked_at_is_none(self):
        """If locked_at is None, lockout is considered expired (edge case)."""
        user = SimpleNamespace(locked_at=None)
        assert _is_lockout_expired(user) is True

    def test_expired_when_duration_passed(self):
        """Lockout is expired when LOCKOUT_DURATION_MINUTES have elapsed."""
        past = datetime.now(timezone.utc) - timedelta(
            minutes=LOCKOUT_DURATION_MINUTES + 1
        )
        user = SimpleNamespace(locked_at=past)
        assert _is_lockout_expired(user) is True

    def test_not_expired_when_within_duration(self):
        """Lockout is NOT expired when within LOCKOUT_DURATION_MINUTES."""
        recent = datetime.now(timezone.utc) - timedelta(
            minutes=LOCKOUT_DURATION_MINUTES - 5
        )
        user = SimpleNamespace(locked_at=recent)
        assert _is_lockout_expired(user) is False


# ---------------------------------------------------------------------------
# Test: Failed attempt recording and lockout trigger
# ---------------------------------------------------------------------------
class TestRecordFailedAttempt:
    """Verify _record_failed_attempt increments counter and locks."""

    @pytest.mark.asyncio
    async def test_increments_failed_attempts(self):
        """Each failed attempt increments the counter."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        user = SimpleNamespace(
            id=uuid.uuid4(),
            failed_login_attempts=0,
            last_failed_at=None,
            is_locked=False,
            locked_at=None,
        )

        await _record_failed_attempt(mock_db, user)

        assert user.failed_login_attempts == 1
        assert user.last_failed_at is not None

    @pytest.mark.asyncio
    async def test_locks_account_at_threshold(self):
        """Account is locked after MAX_FAILED_ATTEMPTS consecutive failures."""
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        now = datetime.now(timezone.utc)
        user = SimpleNamespace(
            id=uuid.uuid4(),
            failed_login_attempts=MAX_FAILED_ATTEMPTS - 1,
            last_failed_at=now - timedelta(minutes=1),
            is_locked=False,
            locked_at=None,
        )

        await _record_failed_attempt(mock_db, user)

        assert user.is_locked is True
        assert user.locked_at is not None


# ---------------------------------------------------------------------------
# Test: Successful login resets state
# ---------------------------------------------------------------------------
class TestRecordSuccessfulLogin:
    """Verify _record_successful_login resets failed attempts."""

    @pytest.mark.asyncio
    async def test_resets_failed_attempts_on_success(self):
        """Successful login resets failed_login_attempts to 0."""
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        user = SimpleNamespace(
            failed_login_attempts=3,
            last_failed_at=datetime.now(timezone.utc),
            last_login_at=None,
        )

        await _record_successful_login(mock_db, user)

        assert user.failed_login_attempts == 0
        assert user.last_failed_at is None
        assert user.last_login_at is not None


# ---------------------------------------------------------------------------
# Test: Unlock account helper
# ---------------------------------------------------------------------------
class TestUnlockAccount:
    """Verify _unlock_account resets lockout state."""

    @pytest.mark.asyncio
    async def test_unlock_resets_all_lockout_fields(self):
        """Unlocking resets is_locked, locked_at, and failed_login_attempts."""
        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        user = SimpleNamespace(
            id=uuid.uuid4(),
            is_locked=True,
            locked_at=datetime.now(timezone.utc),
            failed_login_attempts=5,
        )

        await _unlock_account(mock_db, user)

        assert user.is_locked is False
        assert user.locked_at is None
        assert user.failed_login_attempts == 0


# ---------------------------------------------------------------------------
# Test: authenticate raises AuthError for various failure modes
# ---------------------------------------------------------------------------
class TestAuthenticateErrors:
    """Verify authenticate raises AuthError for invalid scenarios."""

    @pytest.mark.asyncio
    async def test_raises_for_unknown_email(self):
        """authenticate raises AuthError when email not found."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError, match="Invalid email or password"):
            await authenticate(
                db=mock_db,
                email="unknown@example.com",
                password="password123",
                store_refresh_token_fn=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_raises_for_locked_account(self):
        """authenticate raises AuthError when account is locked."""
        locked_user = SimpleNamespace(
            id=uuid.uuid4(),
            is_locked=True,
            locked_at=datetime.now(timezone.utc),  # Recently locked
            is_active=True,
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = locked_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError, match="Account is locked"):
            await authenticate(
                db=mock_db,
                email="locked@example.com",
                password="password123",
                store_refresh_token_fn=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_raises_for_inactive_account(self):
        """authenticate raises AuthError when account is inactive."""
        inactive_user = SimpleNamespace(
            id=uuid.uuid4(),
            is_locked=False,
            is_active=False,
        )
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = inactive_user
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError, match="Account is disabled"):
            await authenticate(
                db=mock_db,
                email="inactive@example.com",
                password="password123",
                store_refresh_token_fn=AsyncMock(),
            )
