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

This is OBSERVABILITY logging, not the clinical AUDIT LOG.
The clinical audit log (Task 4) records data access/mutations at the
service layer with full context. This middleware provides the outer
request envelope for operational monitoring.

Per logging-observability steering rule:
- All logs are structured JSON
- correlation_id flows through the entire request chain
- Duration is tracked for performance monitoring
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


class AuditMiddleware(BaseHTTPMiddleware):
    """
    Request-level audit logging for observability and compliance.

    Logs every request with timing, user context, and outcome.
    This provides the operational audit trail that security teams
    and compliance officers need for HIPAA audits.

    Does NOT replace the clinical audit log (Task 4) which tracks
    specific data access and mutations at the service layer.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize audit middleware."""
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Log request metadata and response timing.

        Captures start time, passes request through, then logs the
        complete request/response metadata including duration.

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

        return response

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
