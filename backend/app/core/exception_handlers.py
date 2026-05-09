"""
PrescpHealth Backend — Exception Handlers for FastAPI.

Registers exception handlers that convert our custom exceptions into
consistent JSON error responses matching the API design steering rule.

Response format (all errors):
{
    "success": false,
    "error": {
        "code": "MACHINE_READABLE_CODE",
        "message": "Human-readable description",
        "details": [...],
        "request_id": "uuid for support correlation"
    }
}

Security Rules:
- NEVER include stack traces in responses (attackers use them to map internals)
- NEVER include PHI in error messages (even if the error is about a patient)
- ALWAYS include request_id (so support can correlate with server-side logs)
- Log full error context server-side for debugging (minus PHI)

Usage:
    from app.core.exception_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)
"""

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import PrescpHealthError

# ---------------------------------------------------------------------------
# Module logger — logs error details server-side (no PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register all exception handlers on the FastAPI application.

    Called during app creation in create_app(). Handles:
    1. PrescpHealthError (our custom exceptions) -> appropriate status code
    2. RequestValidationError (Pydantic validation) -> 400 with field details
    3. Exception (catch-all for unexpected errors) -> generic 500

    Args:
        app: The FastAPI application instance.
    """

    @app.exception_handler(PrescpHealthError)
    async def handle_app_error(request: Request, exc: PrescpHealthError) -> JSONResponse:
        """
        Handle all PrescpHealth custom exceptions.

        Converts our exception hierarchy into consistent JSON responses.
        Each exception type already carries its status_code and error code.
        """
        request_id = getattr(request.state, "request_id", "unknown")

        # Log at appropriate level based on status code
        # 4xx = client error (info level — expected behavior)
        # 5xx = server error (error level — needs investigation)
        if exc.status_code >= 500:
            logger.error(
                "server_error",
                request_id=request_id,
                error_code=exc.code,
                status_code=exc.status_code,
                path=request.url.path,
            )
        else:
            logger.info(
                "client_error",
                request_id=request_id,
                error_code=exc.code,
                status_code=exc.status_code,
                path=request.url.path,
            )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                },
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Handle Pydantic/FastAPI request validation errors.

        Converts Pydantic's detailed validation errors into our standard
        error format. Includes field-level error details so the frontend
        can highlight specific form fields.

        Note: We sanitize error details to ensure no PHI leaks through
        validation messages (e.g., "value 'John Smith' is not valid" would
        expose a patient name — we strip the actual values).
        """
        request_id = getattr(request.state, "request_id", "unknown")

        # Convert Pydantic errors to our format, stripping input values
        # to prevent PHI leakage in error responses
        sanitized_details = []
        for error in exc.errors():
            sanitized_details.append({
                "field": " -> ".join(str(loc) for loc in error["loc"]),
                "type": error["type"],
                "message": error["msg"],
                # Deliberately NOT including error["input"] — may contain PHI
            })

        logger.info(
            "validation_error",
            request_id=request_id,
            path=request.url.path,
            error_count=len(sanitized_details),
        )

        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": sanitized_details,
                    "request_id": request_id,
                },
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all for unexpected/unhandled exceptions.

        Returns a generic 500 error. Logs the full exception type and path
        server-side for debugging, but NEVER exposes internals to the client.

        This handler catches everything that isn't a PrescpHealthError or
        RequestValidationError — meaning it's a genuine bug in our code
        or an unexpected library error.
        """
        request_id = getattr(request.state, "request_id", "unknown")

        # Log as error — this is unexpected and needs investigation
        logger.error(
            "unhandled_exception",
            request_id=request_id,
            error_type=type(exc).__name__,
            path=request.url.path,
            method=request.method,
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                    "details": [],
                    "request_id": request_id,
                },
            },
        )
