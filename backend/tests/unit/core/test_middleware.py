"""
Unit tests for core middleware (TenantMiddleware).

Validates that the TenantMiddleware correctly:
- Extracts tenant_id from valid JWT and sets request.state.tenant_id
- Sets tenant_id=None when no Authorization header is present
- Sets tenant_id=None for invalid/expired tokens
- Allows requests through to downstream handlers regardless

These tests use a minimal FastAPI app with the middleware applied,
testing the middleware in isolation without a real database.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tests.conftest import TEST_JWT_SECRET, generate_test_jwt, get_test_settings


# ---------------------------------------------------------------------------
# Minimal test app with TenantMiddleware applied
# ---------------------------------------------------------------------------
def _create_test_app() -> FastAPI:
    """Create a minimal FastAPI app with TenantMiddleware for unit testing."""
    app = FastAPI()

    # Import and apply TenantMiddleware with patched settings
    # so the JWT secret matches what generate_test_jwt() uses
    import importlib.util
    import sys
    import os

    # Resolve the tenant middleware path relative to the backend directory
    # __file__ is tests/unit/core/test_middleware.py
    # Go up 4 levels: core -> unit -> tests -> backend
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    tenant_path = os.path.join(base_dir, "app", "core", "middleware", "tenant.py")

    spec = importlib.util.spec_from_file_location(
        "app.core.middleware.tenant",
        tenant_path,
    )
    tenant_mod = importlib.util.module_from_spec(spec)
    sys.modules["app.core.middleware.tenant"] = tenant_mod

    with patch("app.config.get_settings", return_value=get_test_settings()):
        spec.loader.exec_module(tenant_mod)

    app.add_middleware(tenant_mod.TenantMiddleware)

    # Simple endpoint that returns request.state values
    @app.get("/test-endpoint")
    async def test_endpoint(request: Request):
        tenant_id = getattr(request.state, "tenant_id", "NOT_SET")
        user_id = getattr(request.state, "user_id", "NOT_SET")
        return JSONResponse({"tenant_id": tenant_id, "user_id": user_id})

    return app


# ---------------------------------------------------------------------------
# Test: TenantMiddleware sets tenant_id from valid JWT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_middleware_sets_tenant_from_jwt():
    """Verify middleware extracts tenant_id from a valid JWT token."""
    app = _create_test_app()
    token = generate_test_jwt(
        user_id="00000000-0000-0000-0000-000000000099",
        tenant_id="00000000-0000-0000-0000-000000000001",
        role="Doctor",
    )

    transport = ASGITransport(app=app)
    # Patch get_settings during the request so JWT decode uses test secret
    with patch("app.config.get_settings", return_value=get_test_settings()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/test-endpoint",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["user_id"] == "00000000-0000-0000-0000-000000000099"


# ---------------------------------------------------------------------------
# Test: TenantMiddleware sets None for missing auth header
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_middleware_sets_none_without_auth():
    """Verify middleware sets tenant_id=None when no Authorization header."""
    app = _create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-endpoint")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] is None


# ---------------------------------------------------------------------------
# Test: TenantMiddleware sets None for malformed token
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_middleware_sets_none_for_malformed_token():
    """Verify middleware sets tenant_id=None for a malformed JWT."""
    app = _create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/test-endpoint",
            headers={"Authorization": "Bearer not.a.valid.jwt.token"},
        )

    assert response.status_code == 200
    body = response.json()
    # Malformed token should result in None tenant_id
    assert body["tenant_id"] is None


# ---------------------------------------------------------------------------
# Test: Request without auth still gets processed (public endpoints)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_without_auth_still_processed():
    """Verify unauthenticated requests pass through middleware to handler."""
    app = _create_test_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Malformed auth header (not "Bearer ...")
        response = await client.get(
            "/test-endpoint",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )

    # Request should still reach the handler (middleware doesn't reject)
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] is None
