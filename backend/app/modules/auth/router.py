"""
PrescpHealth Backend — Auth API Router.

Defines the authentication endpoints:
- POST /api/v1/auth/login — authenticate with email/password
- POST /api/v1/auth/refresh — rotate refresh token for new token pair
- POST /api/v1/auth/logout — revoke refresh token (end session)
- POST /api/v1/auth/mfa/verify — verify TOTP code after login

These endpoints are PUBLIC (no JWT required) because they're used
to OBTAIN authentication. The exception is /mfa/verify which requires
a partial auth state (login succeeded but MFA pending).

Per API design steering rule:
- All responses use the standard envelope format
- Errors include machine-readable code + request_id
- No PHI in any auth endpoint response

Per security-hipaa steering rule:
- Never reveal whether an email exists (same error for both cases)
- Never log passwords or token values
- Rate limit login attempts (handled by RateLimitMiddleware)
"""

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.database import get_session_factory
from app.modules.auth.schemas import (
    AuthMessageResponse,
    LoginRequest,
    LogoutRequest,
    MFAVerifyRequest,
    RefreshRequest,
    TokenResponse,
)
from app.modules.auth.service import AuthService

# ---------------------------------------------------------------------------
# Module logger — logs auth endpoint activity without credentials
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/api/v1/auth",
    tags=["authentication"],
)

# Service instance (stateless — safe to share across requests)
auth_service = AuthService()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=None,
    summary="Authenticate with email and password",
    description="Validates credentials and returns JWT access token + refresh token. "
    "Account is locked after 5 failed attempts within 10 minutes.",
)
async def login(request: Request, body: LoginRequest) -> JSONResponse:
    """
    Authenticate a user and issue tokens.

    On success: returns access_token (15min) + refresh_token (7d).
    On failure: returns 401 with generic message (never reveals if email exists).

    If MFA is enabled, mfa_required=true in response — client must call
    /mfa/verify before the access token is fully activated.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # Extract client metadata for audit trail and anomaly detection
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    # Get a database session for this request
    factory = get_session_factory()
    async with factory() as db:
        try:
            result = await auth_service.authenticate(
                db=db,
                email=body.email,
                password=body.password,
                ip_address=client_ip,
                user_agent=user_agent,
            )

            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "data": result,
                    "meta": {"request_id": request_id},
                },
            )

        except Exception as e:
            # Re-raise — global exception handler will format the response
            raise


# ---------------------------------------------------------------------------
# POST /api/v1/auth/refresh
# ---------------------------------------------------------------------------
@router.post(
    "/refresh",
    response_model=None,
    summary="Refresh access token using refresh token",
    description="Rotates the refresh token and issues a new access token. "
    "If the submitted token was already revoked (reuse attack), "
    "the entire token family is invalidated for security.",
)
async def refresh_token(request: Request, body: RefreshRequest) -> JSONResponse:
    """
    Rotate refresh token and issue new token pair.

    Token rotation security:
    - Old token is revoked immediately
    - New token inherits the same family_id
    - If a revoked token is reused → entire family invalidated
    """
    request_id = getattr(request.state, "request_id", "unknown")
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    factory = get_session_factory()
    async with factory() as db:
        result = await auth_service.rotate_refresh_token(
            db=db,
            refresh_token_value=body.refresh_token,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": result,
                "meta": {"request_id": request_id},
            },
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout
# ---------------------------------------------------------------------------
@router.post(
    "/logout",
    response_model=None,
    summary="Revoke refresh token (end session)",
    description="Revokes the specified refresh token. The access token "
    "will naturally expire within 15 minutes. For immediate "
    "access revocation, the client should discard the access token.",
)
async def logout(request: Request, body: LogoutRequest) -> JSONResponse:
    """
    Revoke a refresh token to end the session.

    Only revokes the specific token — other sessions (devices) remain active.
    The access token continues working until its 15-min expiry (stateless JWT).
    """
    request_id = getattr(request.state, "request_id", "unknown")

    factory = get_session_factory()
    async with factory() as db:
        await auth_service.logout(db=db, refresh_token_value=body.refresh_token)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {"message": "Successfully logged out"},
                "meta": {"request_id": request_id},
            },
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/mfa/verify
# ---------------------------------------------------------------------------
@router.post(
    "/mfa/verify",
    response_model=None,
    summary="Verify MFA TOTP code",
    description="Verifies the 6-digit TOTP code from the user's authenticator app. "
    "Required after login if MFA is enabled for the user.",
)
async def verify_mfa(request: Request, body: MFAVerifyRequest) -> JSONResponse:
    """
    Verify TOTP MFA code after login.

    This endpoint is called after a successful login when mfa_required=true.
    The client must present the 6-digit code from their authenticator app.

    TODO: Full implementation in Task 3.2 (MFA verification logic).
    Currently returns a stub response.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # MFA verification logic will be fully implemented when the
    # MFA service methods are completed. For now, acknowledge the endpoint exists.
    return JSONResponse(
        status_code=501,
        content={
            "success": False,
            "error": {
                "code": "NOT_IMPLEMENTED",
                "message": "MFA verification not yet implemented",
                "details": [],
                "request_id": request_id,
            },
        },
    )
