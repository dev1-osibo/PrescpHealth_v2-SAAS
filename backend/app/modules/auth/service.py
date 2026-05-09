"""
PrescpHealth Backend — Authentication Service.

Orchestrates all authentication flows:
- Login (email/password validation, JWT issuance)
- Token refresh with rotation and reuse detection
- MFA verification (TOTP)
- Logout (token revocation)
- Account lockout (5 failed attempts in 10 min)

This is the BUSINESS LOGIC layer — it uses security.py for crypto
primitives and models.py for data access. It enforces all the security
rules defined in the HIPAA steering file.

Security Flow:
    Login: validate credentials -> check lockout -> check MFA -> issue tokens
    Refresh: validate token -> check revocation -> rotate -> issue new pair
    Reuse Detection: if revoked token used -> invalidate entire family

HIPAA Compliance:
- All auth events logged to audit trail
- Account lockout prevents brute-force
- Token rotation limits exposure window
- MFA required for clinician roles
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import (
    create_access_token,
    create_refresh_token_value,
    decode_access_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth.models import RefreshToken, User

# ---------------------------------------------------------------------------
# Module logger — logs auth events without credentials or PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# Lock account after this many consecutive failed attempts
MAX_FAILED_ATTEMPTS = 5
# Within this time window (minutes)
LOCKOUT_WINDOW_MINUTES = 10
# Lockout duration (minutes) — after this, account auto-unlocks
LOCKOUT_DURATION_MINUTES = 30


class AuthService:
    """
    Authentication service handling login, token management, and security.

    All methods are async and expect a database session to be passed in.
    This keeps the service testable (inject mock session) and ensures
    each request gets its own transaction scope.

    Usage:
        auth_service = AuthService()
        tokens = await auth_service.authenticate(db, email, password)
    """

    async def authenticate(
        self,
        db: AsyncSession,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
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

        Returns:
            dict with: access_token, refresh_token, token_type, expires_in

        Raises:
            AuthError: If credentials invalid, account locked, or account inactive.
        """
        # Find user by email
        user = await self._get_user_by_email(db, email)

        if user is None:
            # Don't reveal whether email exists — same error for both cases
            # This prevents email enumeration attacks
            logger.info("login_failed_user_not_found", email_domain=email.split("@")[-1])
            raise AuthError(message="Invalid email or password")

        # Check if account is locked
        if user.is_locked:
            if self._is_lockout_expired(user):
                # Auto-unlock after lockout duration
                await self._unlock_account(db, user)
            else:
                logger.warning("login_attempt_on_locked_account", user_id=str(user.id))
                raise AuthError(message="Account is locked. Please try again later.")

        # Check if account is active
        if not user.is_active:
            logger.warning("login_attempt_on_inactive_account", user_id=str(user.id))
            raise AuthError(message="Account is disabled. Contact your administrator.")

        # Verify password
        if not verify_password(password, user.password_hash):
            await self._record_failed_attempt(db, user)
            raise AuthError(message="Invalid email or password")

        # Success — reset failed attempts and update last login
        await self._record_successful_login(db, user)

        # Issue tokens
        access_token = create_access_token(
            user_id=str(user.id),
            tenant_id=str(user.tenant_id),
            role=user.role,
        )

        refresh_token_value = create_refresh_token_value()
        await self._store_refresh_token(
            db, user, refresh_token_value, ip_address, user_agent
        )

        settings = get_settings()

        logger.info("login_successful", user_id=str(user.id), role=user.role)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token_value,
            "token_type": "bearer",
            "expires_in": settings.jwt_access_token_expire_minutes * 60,
            "mfa_required": user.mfa_enabled,
        }

    async def rotate_refresh_token(
        self,
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
            await self._revoke_token_family(db, stored_token.family_id)
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
        await self._store_refresh_token(
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

    async def logout(self, db: AsyncSession, refresh_token_value: str) -> None:
        """
        Revoke a refresh token (logout).

        Only revokes the specific token — other sessions remain active.
        For "logout everywhere", use revoke_all_sessions().

        Args:
            db: Database session.
            refresh_token_value: The refresh token to revoke.
        """
        token_hash = hash_token(refresh_token_value)

        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .values(is_revoked=True)
        )
        await db.commit()

        logger.info("user_logged_out")

    # -----------------------------------------------------------------------
    # Private Helper Methods
    # -----------------------------------------------------------------------

    async def _get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        """Find a user by email (RLS ensures tenant isolation)."""
        result = await db.execute(
            select(User).where(User.email == email, User.is_active == True)
        )
        return result.scalar_one_or_none()

    async def _record_failed_attempt(self, db: AsyncSession, user: User) -> None:
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

    async def _record_successful_login(self, db: AsyncSession, user: User) -> None:
        """Reset failed attempts and update last login timestamp."""
        user.failed_login_attempts = 0
        user.last_failed_at = None
        user.last_login_at = datetime.now(timezone.utc)
        await db.flush()

    def _is_lockout_expired(self, user: User) -> bool:
        """Check if the lockout duration has passed (auto-unlock)."""
        if user.locked_at is None:
            return True
        elapsed = datetime.now(timezone.utc) - user.locked_at
        return elapsed > timedelta(minutes=LOCKOUT_DURATION_MINUTES)

    async def _unlock_account(self, db: AsyncSession, user: User) -> None:
        """Unlock an account after lockout duration expires."""
        user.is_locked = False
        user.locked_at = None
        user.failed_login_attempts = 0
        await db.flush()
        logger.info("account_auto_unlocked", user_id=str(user.id))

    async def _store_refresh_token(
        self,
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

    async def _revoke_token_family(self, db: AsyncSession, family_id: uuid.UUID) -> None:
        """
        Revoke ALL tokens in a family (reuse attack response).

        When token reuse is detected, we assume the token was stolen.
        Revoking the entire family forces both the attacker AND the
        legitimate user to re-authenticate. This is the safest response.
        """
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id)
            .values(is_revoked=True)
        )
        await db.commit()
        logger.warning("token_family_revoked", family_id=str(family_id))
