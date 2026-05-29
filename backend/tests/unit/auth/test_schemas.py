"""
Unit tests for app.modules.auth.schemas.

Tests Pydantic validation for all auth request/response schemas.
"""

import pytest
from pydantic import ValidationError

from app.modules.auth.schemas import (
    AuthMessageResponse,
    LoginRequest,
    LogoutRequest,
    MFAVerifyRequest,
    RefreshRequest,
    TokenResponse,
)


# ---------------------------------------------------------------------------
# LoginRequest
# ---------------------------------------------------------------------------
class TestLoginRequest:
    def test_valid_login_accepted(self):
        req = LoginRequest(email="doctor@clinic.example.com", password="secret123")
        assert req.email == "doctor@clinic.example.com"
        assert req.password == "secret123"

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="not-an-email", password="secret")

    def test_rejects_missing_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(password="secret")

    def test_rejects_missing_password(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="doc@x.com")

    def test_rejects_empty_password(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="doc@x.com", password="")

    def test_rejects_password_too_long(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="doc@x.com", password="x" * 129)

    def test_accepts_max_length_password(self):
        req = LoginRequest(email="doc@x.com", password="x" * 128)
        assert len(req.password) == 128


# ---------------------------------------------------------------------------
# RefreshRequest
# ---------------------------------------------------------------------------
class TestRefreshRequest:
    def test_valid_refresh_accepted(self):
        req = RefreshRequest(refresh_token="eyJhbGc.refreshToken.signature")
        assert req.refresh_token == "eyJhbGc.refreshToken.signature"

    def test_rejects_empty_token(self):
        with pytest.raises(ValidationError):
            RefreshRequest(refresh_token="")

    def test_rejects_missing_token(self):
        with pytest.raises(ValidationError):
            RefreshRequest()


# ---------------------------------------------------------------------------
# LogoutRequest
# ---------------------------------------------------------------------------
class TestLogoutRequest:
    def test_valid_logout_accepted(self):
        req = LogoutRequest(refresh_token="some.refresh.token")
        assert req.refresh_token == "some.refresh.token"

    def test_rejects_empty_token(self):
        with pytest.raises(ValidationError):
            LogoutRequest(refresh_token="")


# ---------------------------------------------------------------------------
# MFAVerifyRequest
# ---------------------------------------------------------------------------
class TestMFAVerifyRequest:
    def test_valid_six_digit_code_accepted(self):
        req = MFAVerifyRequest(code="123456")
        assert req.code == "123456"

    def test_rejects_five_digit_code(self):
        with pytest.raises(ValidationError):
            MFAVerifyRequest(code="12345")

    def test_rejects_seven_digit_code(self):
        with pytest.raises(ValidationError):
            MFAVerifyRequest(code="1234567")

    def test_rejects_non_numeric_code(self):
        with pytest.raises(ValidationError):
            MFAVerifyRequest(code="abc123")

    def test_rejects_empty_code(self):
        with pytest.raises(ValidationError):
            MFAVerifyRequest(code="")

    def test_rejects_code_with_spaces(self):
        with pytest.raises(ValidationError):
            MFAVerifyRequest(code="123 56")


# ---------------------------------------------------------------------------
# TokenResponse
# ---------------------------------------------------------------------------
class TestTokenResponse:
    def test_valid_token_response(self):
        resp = TokenResponse(
            access_token="access.jwt.token",
            refresh_token="refresh.jwt.token",
            expires_in=900,
        )
        assert resp.access_token == "access.jwt.token"
        assert resp.refresh_token == "refresh.jwt.token"
        assert resp.expires_in == 900
        assert resp.token_type == "bearer"  # default
        assert resp.mfa_required is False  # default

    def test_mfa_required_can_be_true(self):
        resp = TokenResponse(
            access_token="a",
            refresh_token="r",
            expires_in=900,
            mfa_required=True,
        )
        assert resp.mfa_required is True

    def test_token_type_default_is_bearer(self):
        resp = TokenResponse(
            access_token="a",
            refresh_token="r",
            expires_in=900,
        )
        assert resp.token_type == "bearer"

    def test_rejects_missing_access_token(self):
        with pytest.raises(ValidationError):
            TokenResponse(refresh_token="r", expires_in=900)

    def test_rejects_missing_refresh_token(self):
        with pytest.raises(ValidationError):
            TokenResponse(access_token="a", expires_in=900)

    def test_rejects_missing_expires_in(self):
        with pytest.raises(ValidationError):
            TokenResponse(access_token="a", refresh_token="r")


# ---------------------------------------------------------------------------
# AuthMessageResponse
# ---------------------------------------------------------------------------
class TestAuthMessageResponse:
    def test_valid_message_response(self):
        resp = AuthMessageResponse(message="Logged out successfully")
        assert resp.message == "Logged out successfully"

    def test_rejects_missing_message(self):
        with pytest.raises(ValidationError):
            AuthMessageResponse()
