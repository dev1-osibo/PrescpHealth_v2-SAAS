"""
PrescpHealth Backend — Tenant Middleware.

Extracts the tenant_id from the authenticated user's JWT token and sets
the PostgreSQL session variable 'app.current_tenant' for Row-Level Security.

This is the CRITICAL security boundary for multi-tenancy:
- Every request that touches tenant-scoped data MUST pass through this middleware
- The PostgreSQL RLS policy checks: tenant_id = current_setting('app.current_tenant')
- Even if application code has a bug, cross-tenant access is IMPOSSIBLE at DB level

Flow:
    1. Extract JWT from Authorization header
    2. Decode JWT to get tenant_id claim
    3. Store tenant_id on request.state for downstream access
    4. The actual SET LOCAL happens in get_db() dependency (per-session)

Excluded paths (no tenant context needed):
    - /health (load balancer check)
    - /docs, /redoc, /openapi.json (development only)
    - /api/v1/auth/login, /api/v1/auth/refresh (pre-authentication)
"""

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import get_settings

# ---------------------------------------------------------------------------
# Module logger — logs tenant context operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Paths that don't require tenant context (pre-auth or system endpoints)
EXCLUDED_PATHS = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
}

# Auth paths that are pre-authentication (no JWT yet)
AUTH_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
}


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Middleware that extracts tenant_id from JWT and makes it available
    for Row-Level Security enforcement on every database query.

    The tenant_id is stored on request.state.tenant_id so that:
    1. The get_db() dependency can call set_tenant_context() with it
    2. Services can access it without re-decoding the JWT
    3. Audit logging can include it without additional DB lookups

    If no valid tenant_id is found on a protected route, the request
    is rejected with 401 (handled by auth dependency, not here).
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize middleware with the ASGI application."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Extract tenant_id from JWT and attach to request state.

        For excluded paths (health check, docs, auth endpoints), we skip
        tenant extraction since these don't access tenant-scoped data.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            Response from downstream handler.
        """
        path = request.url.path

        # Skip tenant extraction for system and pre-auth endpoints
        # These don't access tenant-scoped data so RLS context isn't needed
        if path in EXCLUDED_PATHS or path in AUTH_PATHS:
            return await call_next(request)

        # Extract tenant_id from JWT claims (if present)
        # The actual JWT validation happens in the auth dependency —
        # here we just extract the claim for RLS context setting
        tenant_id = self._extract_tenant_from_token(request)

        if tenant_id:
            # Store on request.state so get_db() can set RLS context
            request.state.tenant_id = tenant_id
        else:
            # No tenant_id found — downstream auth dependency will reject
            # if the route requires authentication. We don't reject here
            # because some routes might be public.
            request.state.tenant_id = None

        return await call_next(request)

    def _extract_tenant_from_token(self, request: Request) -> str | None:
        """
        Extract tenant_id claim from the Authorization Bearer token.

        Decodes the JWT to extract tenant_id for RLS context. Also sets
        user_id and user_role on request.state for downstream middleware
        (e.g., RateLimitMiddleware uses user_role for limit tiers).

        Does NOT validate the token for auth purposes (that's the auth
        dependency's job). Just extracts claims for RLS context.

        Returns None if:
        - No Authorization header present
        - Header format is invalid
        - Token can't be decoded (expired, malformed)
        - Token doesn't contain tenant_id claim

        Args:
            request: The incoming HTTP request.

        Returns:
            str | None: The tenant_id UUID string, or None.
        """
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Strip "Bearer " prefix

        try:
            from jose import jwt

            settings = get_settings()
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
            )

            tenant_id = payload.get("tenant_id")
            user_id = payload.get("sub")
            role = payload.get("role")

            if not tenant_id or not user_id:
                return None

            # Set additional claims on request.state for downstream middleware
            # (e.g., RateLimitMiddleware uses user_role for limit tiers)
            request.state.user_id = user_id
            request.state.user_role = role

            return tenant_id

        except Exception:
            # Invalid/expired token — return None, let auth dependency handle rejection
            return None
