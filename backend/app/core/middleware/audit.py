"""
PrescpHealth Backend — Audit Middleware.

Logs request metadata for every API call — required for HIPAA compliance.
The audit trail captures WHO accessed WHAT, WHEN, and FROM WHERE.

What this middleware logs:
- Request: method, path, user_id, tenant_id, client IP, correlation_id
- Response: status code, duration in milliseconds
- Timing: request start and end timestamps

What this middleware does NOT log (HIPAA PHI protection):
- Request bodies (may contain patient data)
- Response bodies (may contain PHI)
- Query parameters (may contain search terms with patient names)
- Authorization header values (contains JWT token)

This middleware serves TWO purposes:
1. OBSERVABILITY logging — structured logs for operational monitoring
2. AUDIT SERVICE integration — writes authenticated request events to the
   audit_logs table via AuditService for HIPAA compliance trail

The clinical audit log at the service layer records specific data mutations
with full context (changes, resource IDs). This middleware provides the
outer request envelope: who accessed what endpoint, when, from where.

Per logging-observability steering rule:
- All logs are structured JSON
- correlation_id flows through the entire request chain
- Duration is tracked for performance monitoring

Paths excluded from audit DB writes (not authenticated / not relevant):
- /health — load balancer health checks
- /docs, /redoc, /openapi.json — API documentation
- /api/v1/auth/login — pre-authentication (no user context yet)
"""

import time

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ---------------------------------------------------------------------------
# Module logger — structured JSON, never contains PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths to skip for audit DB writes (unauthenticated or infrastructure)
# These still get observability logging, just not written to audit_logs table
# ---------------------------------------------------------------------------
_SKIP_AUDIT_PATHS = frozenset({
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
})

# Path prefixes to skip (login is pre-auth, no user context available)
_SKIP_AUDIT_PREFIXES = (
    "/api/v1/auth/login",
)


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Request-level audit logging for observability and compliance.

    Logs every request with timing, user context, and outcome.
    This provides the operational audit trail that security teams
    and compliance officers need for HIPAA audits.

    For authenticated requests, also writes to the audit_logs table
    via AuditService — capturing the request as a formal audit entry
    with tenant isolation, user identity, and request metadata.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize audit middleware."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Log request metadata and response timing.

        Flow:
        1. Record start time
        2. Pass request through all downstream handlers
        3. On completion, log structured observability data
        4. If authenticated, write audit entry to database
        5. Flag slow requests for performance investigation

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            Response from downstream handler (unmodified).
        """
        # Record start time for duration calculation
        start_time = time.perf_counter()

        # Let the request flow through all downstream handlers
        response = await call_next(request)

        # Calculate request duration in milliseconds
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # Extract context from request.state (set by other middleware)
        request_id = getattr(request.state, "request_id", "unknown")
        tenant_id = getattr(request.state, "tenant_id", None)
        user_id = getattr(request.state, "user_id", None)

        # Get client IP — may be behind proxy, check X-Forwarded-For
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("User-Agent", "unknown")

        # Log the request with full context (but NO PHI)
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            tenant_id=str(tenant_id) if tenant_id else None,
            user_id=str(user_id) if user_id else None,
            client_ip=client_ip,
        )

        # Flag slow requests for investigation (per performance budget steering rule)
        if duration_ms > 500:
            logger.warning(
                "slow_request",
                request_id=request_id,
                path=request.url.path,
                duration_ms=duration_ms,
                threshold_ms=500,
            )

        # Write to audit_logs table for authenticated requests only
        # Skip health checks, docs, and pre-auth endpoints
        if self._should_write_audit(request.url.path, user_id, tenant_id):
            await self._write_audit_entry(
                tenant_id=tenant_id,
                user_id=user_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                client_ip=client_ip,
                user_agent=user_agent,
                correlation_id=request_id,
                duration_ms=duration_ms,
            )

        return response

    def _should_write_audit(
        self, path: str, user_id, tenant_id
    ) -> bool:
        """
        Determine if this request should be written to the audit_logs table.

        Only authenticated requests (with user_id and tenant_id) are written.
        Infrastructure paths (health, docs) are skipped even if authenticated.

        Args:
            path: The request URL path.
            user_id: The authenticated user's ID (None if unauthenticated).
            tenant_id: The tenant context (None if unauthenticated).

        Returns:
            True if the request should be audit-logged to the database.
        """
        # Must have authentication context
        if not user_id or not tenant_id:
            return False

        # Skip infrastructure/documentation paths
        if path in _SKIP_AUDIT_PATHS:
            return False

        # Skip pre-authentication paths
        for prefix in _SKIP_AUDIT_PREFIXES:
            if path.startswith(prefix):
                return False

        return True

    async def _write_audit_entry(
        self,
        tenant_id,
        user_id,
        method: str,
        path: str,
        status_code: int,
        client_ip: str,
        user_agent: str,
        correlation_id: str,
        duration_ms: float,
    ) -> None:
        """
        Write an audit entry to the database via AuditService.

        This is fire-and-forget — if the write fails, the error is logged
        but the response has already been sent to the client. Audit failures
        must NEVER affect the user's request.

        The action is formatted as "{METHOD} {path}" to capture the full
        request context in a single string (e.g., "GET /api/v1/patients").

        Args:
            tenant_id: Tenant UUID from auth context.
            user_id: User UUID from auth context.
            method: HTTP method (GET, POST, PUT, DELETE, PATCH).
            path: Request URL path.
            status_code: Response HTTP status code.
            client_ip: Client's IP address.
            user_agent: Client's User-Agent header.
            correlation_id: Request correlation ID for tracing.
            duration_ms: Request duration in milliseconds.
        """
        try:
            # Import here to avoid circular imports at module load time
            # (middleware is loaded before modules are fully initialized)
            from app.modules.audit.service import AuditService
            from app.core.database import get_session_factory

            audit_service = AuditService()
            factory = get_session_factory()

            async with factory() as db:
                await audit_service.log(
                    db=db,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    action=f"{method} {path}",
                    resource_type="http_request",
                    resource_id=None,
                    metadata={
                        "ip": client_ip,
                        "user_agent": user_agent,
                        "correlation_id": correlation_id,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                    },
                )
                await db.commit()

        except Exception as exc:
            # CRITICAL: Never let audit DB writes crash the middleware.
            # The response is already sent — this is best-effort persistence.
            logger.error(
                "middleware_audit_write_failed",
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=path,
            )

    def _get_client_ip(self, request: Request) -> str:
        """
        Extract the real client IP, accounting for reverse proxies.

        In production behind a load balancer, the real client IP is in
        X-Forwarded-For header. We take the first (leftmost) IP which
        is the original client. Direct connections use request.client.host.

        Args:
            request: The incoming HTTP request.

        Returns:
            str: The client's IP address.
        """
        # Check X-Forwarded-For first (set by reverse proxy/load balancer)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP (original client) — subsequent are proxies
            return forwarded_for.split(",")[0].strip()

        # Direct connection (no proxy)
        if request.client:
            return request.client.host

        return "unknown"
