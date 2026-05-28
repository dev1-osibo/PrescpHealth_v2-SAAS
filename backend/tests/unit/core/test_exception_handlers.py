"""
Unit tests for core exception handlers (HTTP error envelope format).

Validates that registered exception handlers return the correct
JSON envelope format for each error type:
- PrescpHealthError subclasses → appropriate status code + envelope
- RequestValidationError → 422/400 with field details
- Unhandled Exception → 500 with generic message (no stack trace)

These tests use a minimal FastAPI app with exception handlers registered,
verifying the response format without needing a real database.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    NotFoundError,
    ForbiddenError,
    ValidationError,
    ConflictError,
)
from app.core.exception_handlers import register_exception_handlers


# ---------------------------------------------------------------------------
# Minimal test app with exception handlers registered
# ---------------------------------------------------------------------------
def _create_error_app() -> FastAPI:
    """Create a minimal FastAPI app with exception handlers for testing."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raise-not-found")
    async def raise_not_found(request: Request):
        raise NotFoundError(message="Patient not found")

    @app.get("/raise-forbidden")
    async def raise_forbidden(request: Request):
        raise ForbiddenError(message="Insufficient permissions")

    @app.get("/raise-validation")
    async def raise_validation(request: Request):
        raise ValidationError(
            message="Invalid measurement value",
            details=[{"field": "value", "message": "Must be between 0 and 300"}],
        )

    @app.get("/raise-unhandled")
    async def raise_unhandled(request: Request):
        raise RuntimeError("Unexpected internal failure")

    return app


# ---------------------------------------------------------------------------
# Test: NotFoundError returns 404 with envelope
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_not_found_error_returns_404_envelope():
    """Verify NotFoundError produces 404 with standard error envelope."""
    app = _create_error_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"] == "Patient not found"
    assert "request_id" in body["error"]


# ---------------------------------------------------------------------------
# Test: ForbiddenError returns 403 with envelope
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forbidden_error_returns_403_envelope():
    """Verify ForbiddenError produces 403 with standard error envelope."""
    app = _create_error_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-forbidden")

    assert response.status_code == 403
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"
    assert body["error"]["message"] == "Insufficient permissions"
    assert "request_id" in body["error"]


# ---------------------------------------------------------------------------
# Test: ValidationError returns 400 with envelope and details
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_validation_error_returns_400_envelope():
    """Verify ValidationError produces 400 with field-level details."""
    app = _create_error_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-validation")

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Invalid measurement value"
    assert len(body["error"]["details"]) == 1
    assert body["error"]["details"][0]["field"] == "value"


# ---------------------------------------------------------------------------
# Test: Unhandled Exception returns 500 with generic message (no stack trace)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unhandled_exception_returns_500_no_stacktrace():
    """Verify unhandled exceptions produce 500 without exposing internals."""
    app = _create_error_app()

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/raise-unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_ERROR"
    # Must NOT contain the actual error message or stack trace
    assert "RuntimeError" not in body["error"]["message"]
    assert "Unexpected internal failure" not in body["error"]["message"]
    assert "request_id" in body["error"]
