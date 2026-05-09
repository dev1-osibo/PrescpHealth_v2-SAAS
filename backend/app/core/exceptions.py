"""
PrescpHealth Backend — Custom Exception Hierarchy.

Defines all application-specific exceptions used across the platform.
Each exception maps to a specific HTTP status code and error response format.

Design Principles:
- Every exception has a machine-readable 'code' (for frontend error handling)
- Every exception has a human-readable 'message' (for display to users)
- Exceptions NEVER contain PHI — use generic messages with request_id for correlation
- The exception hierarchy is flat (no deep inheritance) for simplicity
- All exceptions inherit from PrescpHealthError for catch-all handling

Usage:
    from app.core.exceptions import NotFoundError, ValidationError

    raise NotFoundError(
        message="Patient not found",
        details={"patient_id": str(patient_id)}
    )

HTTP Status Code Mapping:
    AuthError           -> 401 Unauthorized
    ForbiddenError      -> 403 Forbidden
    NotFoundError       -> 404 Not Found
    ValidationError     -> 400 Bad Request
    ConflictError       -> 409 Conflict
    RateLimitError      -> 429 Too Many Requests
    MLEngineError       -> 503 Service Unavailable
    ExternalServiceError -> 502 Bad Gateway
"""


class PrescpHealthError(Exception):
    """
    Base exception for all PrescpHealth application errors.

    All custom exceptions inherit from this class, allowing catch-all
    handling in the global exception handler while still distinguishing
    our errors from unexpected Python exceptions.

    Attributes:
        code: Machine-readable error code (e.g., "AUTH_ERROR", "NOT_FOUND")
        message: Human-readable error description (safe to show to users)
        status_code: HTTP status code for the response
        details: Optional additional context (MUST NOT contain PHI)
    """

    def __init__(
        self,
        message: str = "An error occurred",
        code: str = "INTERNAL_ERROR",
        status_code: int = 500,
        details: dict | list | None = None,
    ) -> None:
        """
        Initialize the exception.

        Args:
            message: Human-readable error message (shown to user).
                     MUST NOT contain PHI — use generic descriptions.
            code: Machine-readable error code for frontend handling.
            status_code: HTTP status code for the response.
            details: Optional structured details (field errors, etc.).
                     MUST NOT contain PHI.
        """
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []
        super().__init__(self.message)


class AuthError(PrescpHealthError):
    """
    Authentication failure — invalid credentials, expired token, etc.

    Maps to HTTP 401 Unauthorized.
    Used when: login fails, JWT expired, JWT malformed, MFA code invalid.
    """

    def __init__(self, message: str = "Authentication failed", details=None):
        super().__init__(
            message=message,
            code="AUTH_ERROR",
            status_code=401,
            details=details,
        )


class ForbiddenError(PrescpHealthError):
    """
    Authorization failure — user authenticated but lacks permission.

    Maps to HTTP 403 Forbidden.
    Used when: role insufficient, wrong tenant, resource not owned by user.
    """

    def __init__(self, message: str = "Access denied", details=None):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
            details=details,
        )


class NotFoundError(PrescpHealthError):
    """
    Resource not found — requested entity doesn't exist or is soft-deleted.

    Maps to HTTP 404 Not Found.
    Used when: patient_id invalid, measurement not found, etc.
    Note: Don't reveal WHETHER a resource exists in another tenant —
    always return 404 (not 403) to prevent tenant enumeration attacks.
    """

    def __init__(self, message: str = "Resource not found", details=None):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=404,
            details=details,
        )


class ValidationError(PrescpHealthError):
    """
    Input validation failure — request data doesn't meet requirements.

    Maps to HTTP 400 Bad Request.
    Used when: measurement out of physiological range, missing required field,
    invalid date format, etc.
    """

    def __init__(self, message: str = "Validation failed", details=None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=400,
            details=details,
        )


class ConflictError(PrescpHealthError):
    """
    Resource conflict — duplicate or idempotency violation.

    Maps to HTTP 409 Conflict.
    Used when: duplicate measurement (same patient/type/time/value),
    email already registered, concurrent modification detected.
    """

    def __init__(self, message: str = "Resource conflict", details=None):
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=409,
            details=details,
        )


class RateLimitError(PrescpHealthError):
    """
    Rate limit exceeded — too many requests in the time window.

    Maps to HTTP 429 Too Many Requests.
    Used by RateLimitMiddleware when sliding window count exceeds threshold.
    """

    def __init__(self, message: str = "Too many requests. Please try again later.", details=None):
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details=details,
        )


class MLEngineError(PrescpHealthError):
    """
    ML engine failure — model inference failed or timed out.

    Maps to HTTP 503 Service Unavailable.
    Used when: risk computation fails, forecast model errors, SHAP explainer crashes.
    Per error-handling steering rule: return stale data with timestamp when possible.
    """

    def __init__(self, message: str = "Risk computation temporarily unavailable", details=None):
        super().__init__(
            message=message,
            code="ML_ENGINE_ERROR",
            status_code=503,
            details=details,
        )


class ExternalServiceError(PrescpHealthError):
    """
    External service failure — third-party API unavailable or errored.

    Maps to HTTP 502 Bad Gateway.
    Used when: OpenAI/Anthropic timeout, SendGrid failure, Twilio error.
    Per error-handling steering rule: circuit breaker should prevent cascading failures.
    """

    def __init__(self, message: str = "External service temporarily unavailable", details=None):
        super().__init__(
            message=message,
            code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details=details,
        )
