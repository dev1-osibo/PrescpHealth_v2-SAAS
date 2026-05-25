"""
PrescpHealth Backend — Authentication Service (Orchestrator).

Thin orchestrator that exposes the AuthService class and delegates to:
- authenticate.py — login flow, lockout, credential verification
- token_rotation.py — refresh token rotation, reuse detection, storage

This file maintains the public API surface that all consumers depend on:
- AuthService class with authenticate(), rotate_refresh_token(), logout()
- Lockout constants (MAX_FAILED_ATTEMPTS, LOCKOUT_WINDOW_MINUTES, LOCKOUT_DURATION_MINUTES)

Architecture:
    The AuthService class methods delegate to module-level functions in
    authenticate.py and token_rotation.py. This keeps each file under
    ~150 lines of logic while preserving the class-based interface that
    the router and tests depend on.

HIPAA Compliance:
- All auth events logged to audit trail
- Account lockout prevents brute-force
- Token rotation limits exposure window
- MFA required for clinician roles
"""

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.modules.auth.authenticate import (
    LOCKOUT_DURATION_MINUTES,
    LOCKOUT_WINDOW_MINUTES,
    MAX_FAILED_ATTEMPTS,
    authenticate as _authenticate,
)
from app.modules.auth.models import RefreshToken
from app.modules.auth.token_rotation import (
    rotate_refresh_token as _rotate_refresh_token,
    store_refresh_token,
)

# ---------------------------------------------------------------------------
# Re-export constants for backward compatibility (used by tests)
# ---------------------------------------------------------------------------
__all__ = [
    "AuthService",
    "MAX_FAILED_ATTEMPTS",
    "LOCKOUT_WINDOW_MINUTES",
    "LOCKOUT_DURATION_MINUTES",
]

# ---------------------------------------------------------------------------
# Module logger — logs auth events without credentials or PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


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

        Delegates to authenticate module. See authenticate.authenticate()
        for full documentation of the authentication flow.

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
        return await _authenticate(
            db=db,
            email=email,
            password=password,
            ip_address=ip_address,
            user_agent=user_agent,
            store_refresh_token_fn=store_refresh_token,
        )

    async def rotate_refresh_token(
        self,
        db: AsyncSession,
        refresh_token_value: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        """
        Rotate a refresh token — issue new pair, invalidate old.

        Delegates to token_rotation module. See
        token_rotation.rotate_refresh_token() for full documentation.

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
        return await _rotate_refresh_token(
            db=db,
            refresh_token_value=refresh_token_value,
            ip_address=ip_address,
            user_agent=user_agent,
        )

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
