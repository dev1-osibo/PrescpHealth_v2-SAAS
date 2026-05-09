"""
PrescpHealth Backend — Security Utilities (JWT + Password Hashing).

Provides the cryptographic primitives used by the auth module:
- JWT token creation and validation (access + refresh tokens)
- Password hashing and verification (bcrypt, cost 12)

These are LOW-LEVEL utilities — they don't contain business logic.
The AuthService (service.py) orchestrates these into auth flows.

Security Decisions:
- HS256 (symmetric) for JWT: We're a single-service architecture.
  If we add microservices later, switch to RS256 (asymmetric).
- bcrypt cost 12: ~250ms per hash. Balances security (slow enough to
  resist brute-force) with UX (fast enough for login to feel instant).
- JWT claims are minimal: user_id, tenant_id, role. No PHI ever in tokens.
- Access tokens: 15 min (short-lived per HIPAA session requirements)
- Refresh tokens: 7 days (with rotation — each use creates a new one)

HIPAA Compliance:
- Tokens contain NO PHI (only opaque IDs and role)
- Password hashes are irreversible (bcrypt)
- Token secrets loaded from environment (never hardcoded)
"""

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

import structlog

from app.config import get_settings

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
    # Generate salt with configured cost factor
    salt = bcrypt.gensalt(rounds=settings.bcrypt_cost_factor)
    # Hash and return as string (bcrypt returns bytes)
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
    except (ValueError, TypeError):
        # Malformed hash — treat as non-match (don't crash)
        return False


# ---------------------------------------------------------------------------
# JWT Token Creation
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: str,
    tenant_id: str,
    role: str,
) -> str:
    """
    Create a short-lived JWT access token.

    The access token is used for API authentication on every request.
    It's short-lived (15 min) to limit the damage window if stolen.
    Contains only the minimum claims needed for authorization.

    Args:
        user_id: The user's UUID string.
        tenant_id: The user's tenant UUID string.
        role: The user's role (e.g., "Doctor", "Nurse").

    Returns:
        str: Signed JWT token string.

    Claims included:
        - sub: user_id (subject — who this token represents)
        - tenant_id: for RLS context setting
        - role: for RBAC permission checks
        - iat: issued at timestamp
        - exp: expiration timestamp (15 min from now)
        - type: "access" (distinguishes from refresh tokens)
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

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token_value() -> str:
    """
    Generate a cryptographically random refresh token value.

    This is the raw token value sent to the client. We store only
    its SHA-256 hash in the database (like a password — if the DB
    is compromised, the raw tokens aren't exposed).

    Returns:
        str: A 64-character hex string (256 bits of entropy).
    """
    import secrets
    return secrets.token_hex(32)


# ---------------------------------------------------------------------------
# JWT Token Validation
# ---------------------------------------------------------------------------
def decode_access_token(token: str) -> dict | None:
    """
    Decode and validate a JWT access token.

    Checks:
    - Signature is valid (not tampered with)
    - Token is not expired
    - Token type is "access" (not a refresh token being misused)

    Args:
        token: The JWT token string from the Authorization header.

    Returns:
        dict | None: The decoded payload if valid, None if invalid/expired.
        Payload contains: sub, tenant_id, role, type, iat, exp
    """
    settings = get_settings()

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )

        # Verify this is an access token (not a refresh token being misused)
        if payload.get("type") != "access":
            logger.warning("token_type_mismatch", expected="access", got=payload.get("type"))
            return None

        return payload

    except JWTError as e:
        # Covers: ExpiredSignatureError, InvalidTokenError, DecodeError
        # Don't log the token itself (security) — just the error type
        logger.info("token_decode_failed", error_type=type(e).__name__)
        return None


# ---------------------------------------------------------------------------
# Token Hash Utility
# ---------------------------------------------------------------------------
def hash_token(token_value: str) -> str:
    """
    Create a SHA-256 hash of a refresh token value for storage.

    We never store raw refresh tokens in the database — only their hash.
    This way, even if the database is compromised, the attacker can't
    use the stored hashes to impersonate users.

    Args:
        token_value: The raw refresh token string.

    Returns:
        str: SHA-256 hex digest of the token.
    """
    import hashlib
    return hashlib.sha256(token_value.encode("utf-8")).hexdigest()
