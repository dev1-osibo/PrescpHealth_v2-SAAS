"""
PrescpHealth Backend — Authentication Logic.

Contains the core authenticate() method and its helper functions for:
- User lookup by email
- Failed login attempt recording and account lockout
- Successful login recording
- Lockout expiry checking and auto-unlock

This module is extracted from the AuthService class to comply with the
~150 lines of logic per file rule. The AuthService orchestrator in
service.py delegates authentication to this module.

Security Flow:
    1. Find user by email (don't reveal if email exists)
    2. Check lockout status (auto-unlock if expired)
    3. Check account active status
    4. Verify password (record failure or success)
    5. Issue tokens on success

HIPAA Compliance:
- Never reveals whether an email exists in the system
- Account lockout prevents brute-force attacks
- All auth events logged without credentials or PHI
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AuthError
from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    verify_password,
)
from app.modules.auth.models import User

# ---------------------------------------------------------------------------
# Module logger — logs auth events without credentials or PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants — lockout policy parameters
# ---------------------------------------------------------------------------
# Lock account after this many consecutive failed attempts
MAX_FAILED_ATTEMPTS = 5
# Within this time window (minutes)
LOCKOUT_WINDOW_MINUTES = 10
# Lockout duration (minutes) — after this, account auto-unlocks
LOCKOUT_DURATION_MINUTES = 30


# ---------------------------------------------------------------------------
# Core Authentication Logic
# ---------------------------------------------------------------------------
async def authenticate(
    db: AsyncSession,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    store_refresh_token_fn=None,
) -> dict:
    """
    Authenticate a user with email and password.

    Flow:
    1. Find user by email (within tenant context — RLS handles isolation)
    2. Check if account is locked
    3. Verify password
    4. Reset failed attempts on success
    5. Issue access token + refresh token

    Args:
        db: Database session (tenant-scoped via RLS).
        email: User's email address.
        password: Plaintext password attempt.
        ip_address: Client IP for audit and anomaly detection.
        user_agent: Client user-agent for audit.
        store_refresh_token_fn: Callable to store the refresh token
            (injected from token_rotation module).

    Returns:
        dict with: access_token, refresh_token, token_type, expires_in

    Raises:
        AuthError: If credentials invalid, account locked, or account inactive.
    """
    # Find user by email
    user = await _get_user_by_email(db, email)

    if user is None:
        # Don't reveal whether email exists — same error for both cases
        # This prevents email enumeration attacks
        logger.info("login_failed_user_not_found", email_domain=email.split("@")[-1])
        raise AuthError(message="Invalid email or password")

    # Check if account is locked
    if user.is_locked:
        if _is_lockout_expired(user):
            # Auto-unlock after lockout duration
            await _unlock_account(db, user)
        else:
            logger.warning("login_attempt_on_locked_account", user_id=str(user.id))
            raise AuthError(message="Account is locked. Please try again later.")

    # Check if account is active
    if not user.is_active:
        logger.warning("login_attempt_on_inactive_account", user_id=str(user.id))
        raise AuthError(message="Account is disabled. Contact your administrator.")

    # Verify password
    if not verify_password(password, user.password_hash):
        await _record_failed_attempt(db, user)
        raise AuthError(message="Invalid email or password")

    # Success — reset failed attempts and update last login
    await _record_successful_login(db, user)

    # Issue tokens
    access_token = create_access_token(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role,
    )

    refresh_token_value = create_refresh_token_value()
    await store_refresh_token_fn(
        db, user, refresh_token_value, ip_address, user_agent
    )

    settings = get_settings()

    # Commit all state changes: reset failed attempts, last_login_at,
    # and the stored refresh token. The router's session context manager
    # does NOT auto-commit, so we must commit explicitly here.
    await db.commit()

    logger.info("login_successful", user_id=str(user.id), role=user.role)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_value,
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "mfa_required": user.mfa_enabled,
    }


# ---------------------------------------------------------------------------
# Private Helper Functions
# ---------------------------------------------------------------------------
async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """
    Find a user by email regardless of active status.

    Active status is checked separately in authenticate() so that
    inactive accounts get a specific error message rather than the
    generic "Invalid email or password" response.

    RLS ensures tenant isolation at the database level.
    """
    result = await db.execute(
        select(User).where(User.email == email)
    )
    return result.scalar_one_or_none()


async def _record_failed_attempt(db: AsyncSession, user: User) -> None:
    """
    Record a failed login attempt and lock if threshold reached.

    Lockout rule: 5 failed attempts within a 10-minute sliding window.
    After lockout, account auto-unlocks after 30 minutes.
    """
    now = datetime.now(timezone.utc)

    # Reset counter if outside the window
    if user.last_failed_at and (now - user.last_failed_at) > timedelta(minutes=LOCKOUT_WINDOW_MINUTES):
        user.failed_login_attempts = 0

    user.failed_login_attempts += 1
    user.last_failed_at = now

    # Lock if threshold reached
    if user.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
        user.is_locked = True
        user.locked_at = now
        logger.warning(
            "account_locked",
            user_id=str(user.id),
            attempts=user.failed_login_attempts,
        )

    await db.commit()


async def _record_successful_login(db: AsyncSession, user: User) -> None:
    """Reset failed attempts and update last login timestamp."""
    user.failed_login_attempts = 0
    user.last_failed_at = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()


def _is_lockout_expired(user: User) -> bool:
    """Check if the lockout duration has passed (auto-unlock)."""
    if user.locked_at is None:
        return True
    elapsed = datetime.now(timezone.utc) - user.locked_at
    return elapsed > timedelta(minutes=LOCKOUT_DURATION_MINUTES)


async def _unlock_account(db: AsyncSession, user: User) -> None:
    """Unlock an account after lockout duration expires."""
    user.is_locked = False
    user.locked_at = None
    user.failed_login_attempts = 0
    await db.flush()
    logger.info("account_auto_unlocked", user_id=str(user.id))
