"""
Unit tests for rotate_refresh_token logic.

Tests the token rotation flow with mocked database to verify:
- Invalid token raises AuthError
- Reuse detection revokes entire family
- Expired token raises AuthError
- Inactive user raises AuthError
- Successful rotation returns new token pair

Validates:
- Token not found → AuthError("Invalid refresh token")
- Revoked token → family revocation + AuthError
- Expired token → AuthError("Refresh token expired")
- Inactive user → AuthError("Account no longer active")
- Valid token → new access_token + refresh_token returned
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthError
from app.modules.auth.token_rotation import rotate_refresh_token


# ---------------------------------------------------------------------------
# Test: Token not found
# ---------------------------------------------------------------------------
class TestRotateTokenNotFound:
    """Verify rotate_refresh_token raises for unknown tokens."""

    @pytest.mark.asyncio
    async def test_raises_for_unknown_token(self):
        """rotate_refresh_token raises AuthError when token hash not in DB."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError, match="Invalid refresh token"):
            await rotate_refresh_token(
                db=mock_db,
                refresh_token_value="nonexistent-token-value",
            )


# ---------------------------------------------------------------------------
# Test: Reuse detection
# ---------------------------------------------------------------------------
class TestRotateTokenReuseDetection:
    """Verify reuse detection revokes entire token family."""

    @pytest.mark.asyncio
    async def test_revokes_family_on_reuse(self):
        """Presenting a revoked token triggers family-wide revocation."""
        family_id = uuid.uuid4()
        stored_token = SimpleNamespace(
            is_revoked=True,
            family_id=family_id,
            user_id=uuid.uuid4(),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stored_token
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with pytest.raises(AuthError, match="Session invalidated"):
            await rotate_refresh_token(
                db=mock_db,
                refresh_token_value="stolen-token-value",
            )

        # Verify db.execute was called (for the family revocation UPDATE)
        assert mock_db.execute.await_count >= 2


# ---------------------------------------------------------------------------
# Test: Expired token
# ---------------------------------------------------------------------------
class TestRotateTokenExpired:
    """Verify expired tokens are rejected."""

    @pytest.mark.asyncio
    async def test_raises_for_expired_token(self):
        """rotate_refresh_token raises AuthError for expired token."""
        stored_token = SimpleNamespace(
            is_revoked=False,
            family_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),  # Long expired
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stored_token
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(AuthError, match="expired"):
            await rotate_refresh_token(
                db=mock_db,
                refresh_token_value="expired-token-value",
            )


# ---------------------------------------------------------------------------
# Test: Inactive user
# ---------------------------------------------------------------------------
class TestRotateTokenInactiveUser:
    """Verify rotation fails for inactive users."""

    @pytest.mark.asyncio
    async def test_raises_for_inactive_user(self):
        """rotate_refresh_token raises AuthError if user is inactive."""
        stored_token = SimpleNamespace(
            is_revoked=False,
            family_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )

        mock_db = AsyncMock()
        # First call returns the token, second returns the user
        mock_token_result = MagicMock()
        mock_token_result.scalar_one_or_none.return_value = stored_token

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = None  # User not found

        mock_db.execute = AsyncMock(
            side_effect=[mock_token_result, mock_user_result]
        )
        mock_db.flush = AsyncMock()

        with pytest.raises(AuthError, match="no longer active"):
            await rotate_refresh_token(
                db=mock_db,
                refresh_token_value="valid-token-inactive-user",
            )


# ---------------------------------------------------------------------------
# Test: Successful rotation
# ---------------------------------------------------------------------------
class TestRotateTokenSuccess:
    """Verify successful rotation returns new token pair."""

    @pytest.mark.asyncio
    async def test_returns_new_tokens_on_success(self):
        """Successful rotation returns access_token and refresh_token."""
        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        family_id = uuid.uuid4()

        stored_token = SimpleNamespace(
            is_revoked=False,
            family_id=family_id,
            user_id=user_id,
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        )

        mock_user = SimpleNamespace(
            id=user_id,
            tenant_id=tenant_id,
            role="Doctor",
            is_active=True,
        )

        mock_db = AsyncMock()
        mock_token_result = MagicMock()
        mock_token_result.scalar_one_or_none.return_value = stored_token

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user

        mock_db.execute = AsyncMock(
            side_effect=[mock_token_result, mock_user_result]
        )
        mock_db.flush = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch("app.modules.auth.token_rotation.get_settings") as mock_s:
            mock_s.return_value = SimpleNamespace(
                jwt_access_token_expire_minutes=15,
                jwt_refresh_token_expire_days=7,
            )
            result = await rotate_refresh_token(
                db=mock_db,
                refresh_token_value="valid-token-value",
            )

        assert "access_token" in result
        assert "refresh_token" in result
        assert result["token_type"] == "bearer"
        assert result["expires_in"] == 15 * 60
