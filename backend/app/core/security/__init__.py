"""
PrescpHealth Backend — Security Package.

This package consolidates all security utilities:
- JWT token creation and validation (access + refresh tokens)
- Password hashing and verification (bcrypt, cost 12)
- Input sanitization (HTML, SQL injection, XSS prevention)
- In-memory rate limiting (backup to Redis-based limiter)
- Per-tenant IP allowlisting

HIPAA Compliance:
- Tokens contain NO PHI (only opaque IDs and role)
- Password hashes are irreversible (bcrypt)
- Token secrets loaded from environment (never hardcoded)
- Input sanitization prevents injection attacks on PHI stores

Usage:
    from app.core.security import create_access_token, hash_password
    from app.core.security import sanitize_string, validate_uuid
    from app.core.security import check_rate_limit, IPAllowlist
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

import bcrypt
from jose import JWTError, jwt
import structlog

from app.config import get_settings

# Re-export new security hardening submodules
from app.core.security.sanitization import (
    check_sql_injection,
    sanitize_string,
    validate_uuid,
)
from app.core.security.rate_limiter import check_rate_limit
from app.core.security.ip_allowlist import IPAllowlist

# ---------------------------------------------------------------------------
# Module logger — logs auth operations without secrets or PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Password Hashing (bcrypt)
# ---------------------------------------------------------------------------
def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Uses the cost factor from settings (default 12, ~250ms per hash).
    This slowness is intentional — it makes brute-force attacks infeasible.

    Args:
        plain_password: The user's plaintext password.

    Returns:
        str: The bcrypt hash string (includes salt and cost factor).
    """
    settings = get_settings()
    salt = bcrypt.gensalt(rounds=settings.bcrypt_cost_factor)
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.

    Timing-safe comparison (bcrypt handles this internally) to prevent
    timing attacks that could reveal whether a hash prefix matches.

    Args:
        plain_password: The password attempt to verify.
        hashed_password: The stored bcrypt hash to check against.

    Returns:
        bool: True if password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# JWT Token Creation
# ---------------------------------------------------------------------------
def create_access_token(user_id: str, tenant_id: str, role: str) -> str:
    """
    Create a short-lived JWT access token.

    Contains only the minimum claims needed for authorization.
    Short-lived (15 min) to limit damage window if token is stolen.

    Args:
        user_id: The user's UUID string.
        tenant_id: The user's tenant UUID string.
        role: The user's role (e.g., "Doctor", "Nurse").

    Returns:
        str: Signed JWT token string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }

    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def create_refresh_token_value() -> str:
    """
    Generate a cryptographically random refresh token value.

    Returns:
        str: A 64-character hex string (256 bits of entropy).
    """
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# JWT Token Validation
# ---------------------------------------------------------------------------
def decode_access_token(token: str) -> dict | None:
    """
    Decode and validate a JWT access token.

    Checks signature validity, expiration, and token type.

    Args:
        token: The JWT token string from the Authorization header.

    Returns:
        dict | None: The decoded payload if valid, None if invalid/expired.
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        if payload.get("type") != "access":
            logger.warning(
                "token_type_mismatch", expected="access", got=payload.get("type")
            )
            return None

        return payload

    except JWTError as e:
        logger.info("token_decode_failed", error_type=type(e).__name__)
        return None


# ---------------------------------------------------------------------------
# Token Hash Utility
# ---------------------------------------------------------------------------
def hash_token(token_value: str) -> str:
    """
    Create a SHA-256 hash of a refresh token value for storage.

    We never store raw refresh tokens in the database — only their hash.

    Args:
        token_value: The raw refresh token string.

    Returns:
        str: SHA-256 hex digest of the token.
    """
    return hashlib.sha256(token_value.encode("utf-8")).hexdigest()


__all__ = [
    # Original JWT/password utilities
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token_value",
    "decode_access_token",
    "hash_token",
    # New security hardening utilities
    "sanitize_string",
    "validate_uuid",
    "check_sql_injection",
    "check_rate_limit",
    "IPAllowlist",
]
