"""
PrescpHealth Backend — Auth Request/Response Schemas.

Pydantic models for validating auth API requests and structuring responses.
These schemas enforce input validation at the API boundary — rejecting
invalid data before it reaches the service layer.

Schema Design:
- Request schemas validate incoming data (strict types, constraints)
- Response schemas structure outgoing data (consistent format)
- No PHI in auth schemas (only credentials and tokens)
- Error details never include input values (prevents credential leakage)

Per API design steering rule:
- All responses wrapped in success/error envelope
- Error responses include machine-readable code + request_id
"""

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    """
    Login request — email and password.

    Validation:
    - Email must be valid format (EmailStr handles this)
    - Password must be non-empty (min 1 char — actual strength
      validation happens at registration, not login)
    """

    email: EmailStr = Field(
        ...,
        description="User's email address",
        examples=["doctor@clinic.example.com"],
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="User's password (never logged or echoed back)",
    )


class RefreshRequest(BaseModel):
    """
    Token refresh request — current refresh token.

    The client sends their current refresh token to get a new
    access token + refresh token pair (rotation).
    """

    refresh_token: str = Field(
        ...,
        min_length=1,
        description="Current refresh token (will be rotated)",
    )


class LogoutRequest(BaseModel):
    """
    Logout request — refresh token to revoke.

    Revoking the refresh token ends the session. The access token
    will naturally expire in <=15 minutes.
    """

    refresh_token: str = Field(
        ...,
        min_length=1,
        description="Refresh token to revoke",
    )


class MFAVerifyRequest(BaseModel):
    """
    MFA verification request — TOTP code from authenticator app.

    The 6-digit code changes every 30 seconds. We accept codes
    from the current and previous time window (±30s tolerance)
    to account for clock drift.
    """

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        description="6-digit TOTP code from authenticator app",
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------
class TokenResponse(BaseModel):
    """
    Successful authentication response — access + refresh tokens.

    Returned after successful login or token refresh.
    The client stores these and uses the access_token for API calls.
    """

    access_token: str = Field(
        ...,
        description="JWT access token (include in Authorization: Bearer header)",
    )
    refresh_token: str = Field(
        ...,
        description="Refresh token (use to get new access token when expired)",
    )
    token_type: str = Field(
        default="bearer",
        description="Token type (always 'bearer')",
    )
    expires_in: int = Field(
        ...,
        description="Access token lifetime in seconds (900 = 15 minutes)",
    )
    mfa_required: bool = Field(
        default=False,
        description="Whether MFA verification is needed to complete login",
    )


class AuthMessageResponse(BaseModel):
    """
    Simple message response for auth operations (logout, MFA setup).

    Used when the operation succeeds but there's no data to return
    beyond a confirmation message.
    """

    message: str = Field(
        ...,
        description="Human-readable confirmation message",
    )
