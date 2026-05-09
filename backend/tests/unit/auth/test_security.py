"""
Unit Tests: Auth Module — Security Utilities.

Tests the low-level cryptographic functions used by the auth service:
- Password hashing and verification (bcrypt)
- JWT access token creation and decoding
- Refresh token generation and hashing
- Token expiry enforcement

These tests are FAST (no database, no Redis) and validate that the
security primitives work correctly in isolation.

Validates: Requirements 2.1, 2.4, 2.7
"""

import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    decode_access_token,
    hash_password,
    hash_token,
    verify_password,
)


class TestPasswordHashing:
    """Tests for bcrypt password hashing and verification."""

    def test_hash_password_produces_bcrypt_hash(self):
        """Hashed password should be a valid bcrypt string."""
        hashed = hash_password("SecurePassword123!")
        # bcrypt hashes start with $ (or $, $)
        assert hashed.startswith("$") or hashed.startswith("$")

    def test_hash_password_different_each_time(self):
        """Same password should produce different hashes (unique salt each time)."""
        hash1 = hash_password("SamePassword")
        hash2 = hash_password("SamePassword")
        # Different salts mean different hashes
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Correct password should verify successfully."""
        password = "MySecurePassword!2024"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Wrong password should fail verification."""
        hashed = hash_password("CorrectPassword")
        assert verify_password("WrongPassword", hashed) is False

    def test_verify_password_empty_string(self):
        """Empty password should not match any hash."""
        hashed = hash_password("SomePassword")
        assert verify_password("", hashed) is False

    def test_verify_password_malformed_hash(self):
        """Malformed hash should return False (not crash)."""
        assert verify_password("password", "not-a-valid-hash") is False

    def test_verify_password_none_hash(self):
        """None hash should return False (not crash)."""
        assert verify_password("password", None) is False


class TestJWTAccessToken:
    """Tests for JWT access token creation and decoding."""

    def test_create_access_token_returns_string(self):
        """Access token should be a non-empty string."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            role="Doctor",
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_access_token_valid(self):
        """Valid token should decode to correct claims."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            role="Doctor",
        )
        payload = decode_access_token(token)

        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["tenant_id"] == "tenant-456"
        assert payload["role"] == "Doctor"
        assert payload["type"] == "access"

    def test_decode_access_token_invalid_signature(self):
        """Token with wrong signature should return None."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            role="Doctor",
        )
        # Tamper with the token (change last character)
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        payload = decode_access_token(tampered)
        assert payload is None

    def test_decode_access_token_garbage_input(self):
        """Completely invalid token should return None (not crash)."""
        assert decode_access_token("not.a.valid.token") is None
        assert decode_access_token("") is None
        assert decode_access_token("abc123") is None

    def test_access_token_contains_no_phi(self):
        """Token claims should never contain PHI — only IDs and role."""
        token = create_access_token(
            user_id="user-123",
            tenant_id="tenant-456",
            role="Nurse",
        )
        payload = decode_access_token(token)

        # Only these keys should be present (no patient data, no names, no email)
        allowed_keys = {"sub", "tenant_id", "role", "type", "iat", "exp"}
        assert set(payload.keys()) == allowed_keys


class TestRefreshToken:
    """Tests for refresh token generation and hashing."""

    def test_create_refresh_token_value_length(self):
        """Refresh token should be 64 hex characters (256 bits)."""
        token = create_refresh_token_value()
        assert len(token) == 64
        # Should be valid hex
        int(token, 16)

    def test_create_refresh_token_value_unique(self):
        """Each generated token should be unique."""
        tokens = {create_refresh_token_value() for _ in range(100)}
        assert len(tokens) == 100, "All 100 tokens should be unique"

    def test_hash_token_deterministic(self):
        """Same token value should always produce same hash."""
        token = create_refresh_token_value()
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        assert hash1 == hash2

    def test_hash_token_different_for_different_tokens(self):
        """Different tokens should produce different hashes."""
        token1 = create_refresh_token_value()
        token2 = create_refresh_token_value()
        assert hash_token(token1) != hash_token(token2)

    def test_hash_token_is_sha256_length(self):
        """Token hash should be 64 hex chars (SHA-256 output)."""
        token = create_refresh_token_value()
        hashed = hash_token(token)
        assert len(hashed) == 64


class TestAccountLockout:
    """Tests for lockout-related constants and logic."""

    def test_lockout_threshold_is_five(self):
        """Account should lock after exactly 5 failed attempts."""
        from app.modules.auth.service import MAX_FAILED_ATTEMPTS
        assert MAX_FAILED_ATTEMPTS == 5

    def test_lockout_window_is_ten_minutes(self):
        """Lockout window should be 10 minutes."""
        from app.modules.auth.service import LOCKOUT_WINDOW_MINUTES
        assert LOCKOUT_WINDOW_MINUTES == 10

    def test_lockout_duration_is_thirty_minutes(self):
        """Lockout duration should be 30 minutes before auto-unlock."""
        from app.modules.auth.service import LOCKOUT_DURATION_MINUTES
        assert LOCKOUT_DURATION_MINUTES == 30
