"""Unit tests for app.core.exceptions hierarchy."""

import pytest

from app.core.exceptions import (
    PrescpHealthError,
    AuthError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
    ConflictError,
    RateLimitError,
    MLEngineError,
    ExternalServiceError,
)


class TestPrescpHealthError:
    def test_default_construction(self):
        e = PrescpHealthError()
        assert e.message == "An error occurred"
        assert e.code == "INTERNAL_ERROR"
        assert e.status_code == 500
        assert e.details == []

    def test_custom_construction(self):
        e = PrescpHealthError(message="custom", code="X", status_code=418, details={"k": "v"})
        assert e.message == "custom"
        assert e.code == "X"
        assert e.status_code == 418
        assert e.details == {"k": "v"}

    def test_details_default_is_empty_list(self):
        e = PrescpHealthError()
        assert isinstance(e.details, list)
        assert e.details == []

    def test_inherits_from_exception(self):
        assert isinstance(PrescpHealthError(), Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(PrescpHealthError):
            raise PrescpHealthError("boom")


class TestAuthError:
    def test_status_401(self):
        assert AuthError().status_code == 401

    def test_code(self):
        assert AuthError().code == "AUTH_ERROR"

    def test_default_message(self):
        assert AuthError().message == "Authentication failed"

    def test_inherits_base(self):
        assert isinstance(AuthError(), PrescpHealthError)


class TestForbiddenError:
    def test_status_403(self):
        assert ForbiddenError().status_code == 403

    def test_code(self):
        assert ForbiddenError().code == "FORBIDDEN"


class TestNotFoundError:
    def test_status_404(self):
        assert NotFoundError().status_code == 404

    def test_code(self):
        assert NotFoundError().code == "NOT_FOUND"

    def test_details_passthrough(self):
        e = NotFoundError(details={"id": "abc"})
        assert e.details == {"id": "abc"}


class TestValidationError:
    def test_status_400(self):
        assert ValidationError().status_code == 400

    def test_code(self):
        assert ValidationError().code == "VALIDATION_ERROR"


class TestConflictError:
    def test_status_409(self):
        assert ConflictError().status_code == 409

    def test_code(self):
        assert ConflictError().code == "CONFLICT"


class TestRateLimitError:
    def test_status_429(self):
        assert RateLimitError().status_code == 429

    def test_code(self):
        assert RateLimitError().code == "RATE_LIMIT_EXCEEDED"


class TestMLEngineError:
    def test_status_503(self):
        assert MLEngineError().status_code == 503

    def test_code(self):
        assert MLEngineError().code == "ML_ENGINE_ERROR"


class TestExternalServiceError:
    def test_status_502(self):
        assert ExternalServiceError().status_code == 502

    def test_code(self):
        assert ExternalServiceError().code == "EXTERNAL_SERVICE_ERROR"


class TestNoPHIInExceptionMessages:
    """All default exception messages must be generic — no PHI placeholders."""

    @pytest.mark.parametrize(
        "cls",
        [
            PrescpHealthError, AuthError, ForbiddenError, NotFoundError,
            ValidationError, ConflictError, RateLimitError,
            MLEngineError, ExternalServiceError,
        ],
    )
    def test_default_message_is_generic(self, cls):
        e = cls()
        # Default messages must not contain placeholders that hint at real values
        lowered = e.message.lower()
        forbidden = ["patient_id=", "mrn=", "ssn", "phone="]
        for term in forbidden:
            assert term not in lowered, f"{cls.__name__} default message contains {term!r}"
