"""
Unit tests for token rotation logic (structural verification).

Tests that the token rotation module exposes the expected API surface
and that key security functions (family revocation, token storage) exist
and are callable. Also verifies cryptographic primitives used by rotation.

Validates:
- rotate_refresh_token function exists and is callable
- Token family revocation logic (_revoke_token_family) exists
- store_refresh_token creates a new token record via db.add
- create_refresh_token_value produces 64-char hex string
- hash_token is deterministic (same input → same output)
- Token family_id is preserved across rotations
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest

from app.modules.auth.token_rotation import (
    rotate_refresh_token,
    store_refresh_token,
    _revoke_token_family,
)
from app.core.security import create_refresh_token_value, hash_token


# ---------------------------------------------------------------------------
# Test: Module API surface exists and is callable
# ---------------------------------------------------------------------------
class TestTokenRotationApiSurface:
    """Verify token rotation module exposes expected functions."""

    def test_rotate_refresh_token_is_callable(self):
        """rotate_refresh_token must be an async callable function."""
        assert callable(rotate_refresh_token)
        # Verify it's a coroutine function (async def)
        import asyncio
        assert asyncio.iscoroutinefunction(rotate_refresh_token)

    def test_revoke_token_family_exists_and_is_callable(self):
        """_revoke_token_family must exist for reuse attack response."""
        assert callable(_revoke_token_family)
        import asyncio
        assert asyncio.iscoroutinefunction(_revoke_token_family)


# ---------------------------------------------------------------------------
# Test: Cryptographic primitives used by token rotation
# ---------------------------------------------------------------------------
class TestTokenCryptoPrimitives:
    """Verify create_refresh_token_value and hash_token behavior."""

    def test_create_refresh_token_value_produces_64_char_hex(self):
        """Refresh token must be a 64-character hex string (256 bits entropy)."""
        token = create_refresh_token_value()

        assert isinstance(token, str)
        assert len(token) == 64
        # Verify it's valid hex (only 0-9, a-f characters)
        int(token, 16)  # Raises ValueError if not valid hex

    def test_hash_token_is_deterministic(self):
        """hash_token must return the same hash for the same input (SHA-256)."""
        token_value = "test-token-deterministic-check"

        hash1 = hash_token(token_value)
        hash2 = hash_token(token_value)

        assert hash1 == hash2
        # SHA-256 produces a 64-char hex digest
        assert len(hash1) == 64

    def test_hash_token_different_inputs_produce_different_hashes(self):
        """Different token values must produce different hashes."""
        hash_a = hash_token("token-alpha")
        hash_b = hash_token("token-beta")

        assert hash_a != hash_b


# ---------------------------------------------------------------------------
# Test: Token family concept (family_id preserved across rotations)
# ---------------------------------------------------------------------------
class TestTokenFamilyConcept:
    """Verify family_id is preserved when storing rotated tokens."""

    @pytest.mark.asyncio
    async def test_family_id_preserved_across_rotation(self):
        """store_refresh_token preserves family_id for session lineage tracking."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())
        family_id = uuid.uuid4()

        with patch("app.modules.auth.token_rotation.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(
                jwt_refresh_token_expire_days=7,
            )
            with patch("app.modules.auth.token_rotation.hash_token", return_value="hashed"):
                await store_refresh_token(
                    db=mock_db,
                    user=mock_user,
                    token_value="rotated-token",
                    ip_address="10.0.0.1",
                    user_agent="TestAgent/2.0",
                    family_id=family_id,
                )

        # The token record passed to db.add should have the same family_id
        added_token = mock_db.add.call_args[0][0]
        assert added_token.family_id == family_id


# ---------------------------------------------------------------------------
# Test: store_refresh_token creates a new token record
# ---------------------------------------------------------------------------
class TestStoreRefreshToken:
    """Verify store_refresh_token adds a token to the database session."""

    @pytest.mark.asyncio
    async def test_store_refresh_token_calls_db_add(self):
        """store_refresh_token must call db.add() to persist the new token."""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        # Create a mock user with required attributes
        mock_user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())

        with patch("app.modules.auth.token_rotation.get_settings") as mock_settings:
            mock_settings.return_value = SimpleNamespace(
                jwt_refresh_token_expire_days=7,
            )
            with patch("app.modules.auth.token_rotation.hash_token", return_value="hashed"):
                await store_refresh_token(
                    db=mock_db,
                    user=mock_user,
                    token_value="test-token-value",
                    ip_address="127.0.0.1",
                    user_agent="TestAgent/1.0",
                    family_id=uuid.uuid4(),
                )

        # Verify db.add was called (token record created)
        mock_db.add.assert_called_once()
        # Verify db.flush was called (persist within transaction)
        mock_db.flush.assert_awaited_once()
