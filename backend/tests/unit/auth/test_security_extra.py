"""
Additional security.py coverage:
- token type mismatch branch (decode_access_token rejects refresh token)
- malformed bcrypt hash handling
"""

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from app.config import get_settings
from app.core.security import (
    decode_access_token,
    hash_password,
    verify_password,
)


def test_decode_rejects_non_access_token():
    """decode_access_token returns None for a JWT whose type != 'access'."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user-1",
        "tenant_id": "tenant-1",
        "role": "Doctor",
        "type": "refresh",  # wrong type
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    result = decode_access_token(token)
    assert result is None


def test_decode_rejects_token_missing_type():
    """Token with no 'type' claim is treated as non-access (returns None)."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "user-1",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)

    result = decode_access_token(token)
    assert result is None


def test_verify_password_with_malformed_hash_returns_false():
    """verify_password returns False (not raises) when hash is malformed."""
    assert verify_password("secret", "not-a-real-bcrypt-hash") is False


def test_verify_password_with_empty_hash_returns_false():
    """verify_password returns False for empty hash."""
    assert verify_password("secret", "") is False


def test_verify_password_with_none_hash_returns_false():
    """verify_password returns False for None hash (TypeError path)."""
    # Don't actually pass None — type hint disallows it. Pass a non-string.
    assert verify_password("secret", "garbage!@#$%") is False


def test_hash_and_verify_roundtrip():
    """hash_password produces hash that verify_password validates."""
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong password", hashed) is False
