"""
PrescpHealth Backend — Auth API Router.

Defines the authentication endpoints:
- POST /api/v1/auth/login — authenticate with email/password
- POST /api/v1/auth/refresh — rotate refresh token for new pair
- POST /api/v1/auth/logout — revoke refresh token (end session)
- POST /api/v1/auth/mfa/verify — verify TOTP code after login

These endpoints are PRE-AUTHENTICATION (no JWT required) except logout
which requires a valid session. They're excluded from tenant middleware
since the user hasn't been authenticated yet.

Per API design steering rule:
- All responses use the standard envelope format
- Errors include machine-readable code + request_id
- No PHI in any auth endpoint response
"""

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.deps import get_db
from app.core.exceptions import AuthError
from app.modules.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    MFAVerifyRequest,
    RefreshRequest,
    TokenResponse,
    AuthMessageResponse,
)
from app.modules.auth.service import AuthService

# ---------------------------------------------------------------------------
# Module logger — logs auth endpoint access without credentials or PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Router definition — all auth routes under /api/v1/auth
# ---------------------------------------------------------------------------
router = APIRouter(
    prefix="/api/v1/auth",
    tags=["authentication"],
)

# Service instance (stateless — safe to reuse across requests)
auth_service = AuthService()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------
@router.post(
    "/login",
    response_model=None,
    summary="Authenticate with email and password",
    description=(
        "Validates credentials and returns JWT access token + refresh token. "
        "If MFA is enabled, returns mfa_required=true and the client must "
        "call /mfa/verify before accessing protected endpoints."
    ),
)
async def login(request: Request, body: LoginRequest):
    """
    Authenticate a user and issue tokens.

    Flow:
    1. Validate email/password against stored credentials
    2. Check account lockout status
    3. Issue access token (15 min) + refresh token (7 days)
    4. If MFA enabled, flag that verification is still needed

    Returns 401 for invalid credentials (same message whether email
    doesn't exist or password is wrong — prevents email enumeration).
    """
    # Extract client metadata for audit trail and anomaly detection
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    # Get database session (no tenant context needed for login)
    async for db in get_db():
        result = await auth_service.authenticate(
            db=db,
            email=body.email,
            password=body.password,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        request_id = getattr(request.state, "request_id", "unknown")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": result,
                "meta": {
                    "request_id": request_id,
                },
            },
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/refresh
# ---------------------------------------------------------------------------
@router.post(
    "/refresh",
    response_model=None,
    summary="Refresh access token using refresh token",
    description=(
        "Rotates the refresh token and issues a new access token + refresh token pair. "
        "The old refresh token is immediately invalidated. If a revoked token is "
        "presented (reuse attack), ALL tokens in that session family are invalidated."
    ),
)
async def refresh(request: Request, body: RefreshRequest):
    """
    Rotate refresh token and issue new token pair.

    Security: If a revoked token is reused (indicates theft), the entire
    token family is invalidated — both attacker and user must re-login.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    async for db in get_db():
        result = await auth_service.rotate_refresh_token(
            db=db,
            refresh_token_value=body.refresh_token,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        request_id = getattr(request.state, "request_id", "unknown")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": result,
                "meta": {
                    "request_id": request_id,
                },
            },
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/logout
# ---------------------------------------------------------------------------
@router.post(
    "/logout",
    response_model=None,
    summary="Revoke refresh token (end session)",
    description=(
        "Revokes the specified refresh token. The associated access token "
        "will naturally expire within 15 minutes. For immediate access "
        "revocation, the client should also discard the access token."
    ),
)
async def logout(request: Request, body: LogoutRequest):
    """
    Revoke a refresh token to end the session.

    Only revokes the specific token — other sessions (devices) remain active.
    The access token continues working until its 15-min expiry (stateless JWT).
    """
    async for db in get_db():
        await auth_service.logout(db=db, refresh_token_value=body.refresh_token)

        request_id = getattr(request.state, "request_id", "unknown")

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {"message": "Successfully logged out"},
                "meta": {
                    "request_id": request_id,
                },
            },
        )


# ---------------------------------------------------------------------------
# POST /api/v1/auth/mfa/verify
# ---------------------------------------------------------------------------
@router.post(
    "/mfa/verify",
    response_model=None,
    summary="Verify MFA TOTP code",
    description=(
        "Verifies the 6-digit TOTP code from the user's authenticator app. "
        "Must be called after login when mfa_required=true. Accepts codes "
        "from current and previous time window (30s tolerance for clock drift)."
    ),
)
async def verify_mfa(request: Request, body: MFAVerifyRequest):
    """
    Verify TOTP MFA code after login.

    This endpoint is called when login returns mfa_required=true.
    The client must present a valid 6-digit TOTP code to complete
    authentication and gain full access.

    TODO: Implement in full when MFA service methods are added.
    Currently returns a placeholder — MFA verification logic will be
    completed when the TOTP secret management is implemented.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    # TODO: Implement full MFA verification (Task 3.2 continuation)
    # For now, return not-implemented response
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
