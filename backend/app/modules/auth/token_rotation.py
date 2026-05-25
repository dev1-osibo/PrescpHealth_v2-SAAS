"""
PrescpHealth Backend — Token Rotation Logic.

Contains the rotate_refresh_token() method and its helpers for:
- Storing new refresh tokens in the database
- Revoking token families on reuse detection
- Token rotation with family lineage tracking

This module is extracted from the AuthService class to comply with the
~150 lines of logic per file rule. The AuthService orchestrator in
service.py delegates token rotation to this module.

Token Rotation Security:
- Old token is revoked immediately on use
- New token inherits the same family_id (session lineage)
- If a REVOKED token is presented (reuse attack), the entire
  family is invalidated — both attacker and legitimate user lose access
- The legitimate user must re-login (acceptable security tradeoff)

HIPAA Compliance:
- Token values are never logged (only hashes stored)
- All rotation events logged for audit trail
- Reuse detection logged as security event
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AuthError
from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    hash_token,
)
from app.modules.auth.models import RefreshToken, User

# ---------------------------------------------------------------------------
# Module logger — logs token operations without token values
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Core Token Rotation Logic
# ---------------------------------------------------------------------------
async def rotate_refresh_token(
    db: AsyncSession,
    refresh_token_value: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    """
    Rotate a refresh token — issue new pair, invalidate old.

    Token Rotation Security:
    - Old token is revoked immediately
    - New token inherits the same family_id
    - If a REVOKED token is presented (reuse attack), the entire
      family is invalidated (all sessions from that login)

    Args:
        db: Database session.
        refresh_token_value: The current refresh token from the client.
        ip_address: Client IP for the new token.
        user_agent: Client user-agent for the new token.

    Returns:
        dict with: access_token, refresh_token, token_type, expires_in

    Raises:
        AuthError: If token invalid, expired, or reuse detected.
    """
    token_hash = hash_token(refresh_token_value)

    # Find the token in database
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored_token = result.scalar_one_or_none()

    if stored_token is None:
        # Token not found — could be expired and cleaned up, or never existed
        raise AuthError(message="Invalid refresh token")

    # CRITICAL: Check for token reuse attack
    # If this token was already revoked, someone is using a stolen token
    if stored_token.is_revoked:
        # Revoke ALL tokens in this family — attacker and legitimate user both lose access
        # The legitimate user will need to re-login (acceptable security tradeoff)
        await _revoke_token_family(db, stored_token.family_id)
        logger.error(
            "refresh_token_reuse_detected",
            family_id=str(stored_token.family_id),
            user_id=str(stored_token.user_id),
        )
        raise AuthError(message="Session invalidated for security. Please log in again.")

    # Check expiry
    if stored_token.expires_at < datetime.now(timezone.utc):
        raise AuthError(message="Refresh token expired. Please log in again.")

    # Revoke the current token (it's been used, can't be used again)
    stored_token.is_revoked = True
    await db.flush()

    # Load the user for new token claims
    user_result = await db.execute(
        select(User).where(User.id == stored_token.user_id)
    )
    user = user_result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise AuthError(message="Account no longer active")

    # Issue new token pair with SAME family_id (maintains session lineage)
    access_token = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role,
    )

    new_refresh_value = create_refresh_token_value()
    await store_refresh_token(
        db, user, new_refresh_value, ip_address, user_agent,
        family_id=stored_token.family_id,  # Same family — rotation, not new session
    )

    await db.commit()

    settings = get_settings()

    logger.info("token_rotated", user_id=str(user.id))

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_value,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
async def store_refresh_token(
    db: AsyncSession,
    user: User,
    token_value: str,
    ip_address: str | None,
    user_agent: str | None,
    family_id: uuid.UUID | None = None,
) -> None:
    """
    Store a new refresh token in the database.

    If family_id is None, this is a new login session (new family).
    If family_id is provided, this is a rotation (same family).

    Args:
        db: Database session.
        user: The user this token belongs to.
        token_value: The raw token value (will be hashed for storage).
        ip_address: Client IP address for audit.
        user_agent: Client user-agent for audit.
        family_id: Token family ID (None for new session, UUID for rotation).
    """
    settings = get_settings()

    token = RefreshToken(
        token_hash=hash_token(token_value),
        family_id=family_id or uuid.uuid4(),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(token)
    await db.flush()


async def _revoke_token_family(db: AsyncSession, family_id: uuid.UUID) -> None:
    """
    Revoke ALL tokens in a family (reuse attack response).

    When token reuse is detected, we assume the token was stolen.
    Revoking the entire family forces both the attacker AND the
    legitimate user to re-authenticate. This is the safest response.

    Args:
        db: Database session.
        family_id: The token family to revoke.
    """
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id)
        .values(is_revoked=True)
    )
    await db.commit()
    logger.warning("token_family_revoked", family_id=str(family_id))
