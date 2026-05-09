"""
PrescpHealth Backend — Rate Limit Middleware.

Implements Redis-backed sliding window rate limiting per user and role.
Protects the platform from:
- Brute-force attacks (credential stuffing on login)
- Data harvesting (scraping patient records)
- Accidental DDoS (buggy client making infinite requests)

Rate limits per role (per steering rules):
- Clinician roles (Doctor, Nurse, Clinic_Admin): 1000 req/min
- Patient_User: 100 req/min (simpler access patterns, reserve capacity for clinical)
- Unauthenticated: 50 req/min (login attempts, public endpoints)

Algorithm: Sliding window counter using Redis sorted sets.
- Each request adds a timestamped entry to a sorted set keyed by user
- We count entries within the last 60 seconds
- If count exceeds limit, return 429 Too Many Requests
- Entries older than 60 seconds are pruned on each check

Graceful degradation: If Redis is unavailable, rate limiting is SKIPPED
(per error-handling steering rule: Redis is acceleration, not requirement).
We accept the temporary security risk over blocking all requests.
"""

import time

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import get_settings
from app.core.cache import get_redis

# ---------------------------------------------------------------------------
# Module logger — logs rate limit events without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-backed sliding window rate limiter.

    Tracks request counts per user (or IP for unauthenticated requests)
    within a 60-second sliding window. Returns 429 when limit exceeded.

    The rate limit is role-based:
    - Higher limits for clinicians (they need fast access during patient care)
    - Lower limits for patients (simpler workflows, protect system capacity)
    - Lowest for unauthenticated (prevent brute-force and scraping)
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize rate limit middleware."""
        super().__init__(app)
        self._settings = get_settings()

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Check rate limit before passing request to handler.

        If limit exceeded, returns 429 immediately without hitting business logic.
        If Redis unavailable, skips rate limiting (graceful degradation).

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            Response from downstream, or 429 JSONResponse if rate limited.
        """
        # Skip rate limiting for health checks (load balancers hit this constantly)
        if request.url.path == "/health":
            return await call_next(request)

        redis = await get_redis()

        # If Redis is down, skip rate limiting entirely
        # Per error-handling steering rule: accept temporary risk over blocking all traffic
        if redis is None:
            return await call_next(request)

        # Determine rate limit based on user role
        # Before auth is wired (Task 3), we use IP-based limiting
        identifier, limit = self._get_limit_params(request)

        # Check if request is within rate limit
        is_allowed = await self._check_rate_limit(redis, identifier, limit)

        if not is_allowed:
            request_id = getattr(request.state, "request_id", "unknown")
            logger.warning(
                "rate_limit_exceeded",
                identifier=identifier,
                limit=limit,
                request_id=request_id,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                        "details": [{"retry_after_seconds": 60}],
                        "request_id": request_id,
                    },
                },
                headers={"Retry-After": "60"},
            )

        return await call_next(request)

    def _get_limit_params(self, request: Request) -> tuple[str, int]:
        """
        Determine the rate limit identifier and limit for this request.

        Uses user_id + role if authenticated, falls back to client IP.
        Role determines the limit (clinician=1000, patient=100, anon=50).

        Args:
            request: The incoming HTTP request.

        Returns:
            Tuple of (identifier string, requests-per-minute limit).
        """
        # Once auth is wired (Task 3), we'll extract user_id and role from request.state
        # For now, use client IP as identifier
        client_ip = request.client.host if request.client else "unknown"
        identifier = f"ratelimit:ip:{client_ip}"

        # Default to unauthenticated limit until auth module is integrated
        # TODO: Check request.state.user_role once auth is wired (Task 3.4)
        limit = 50  # Unauthenticated default

        return identifier, limit

    async def _check_rate_limit(self, redis, identifier: str, limit: int) -> bool:
        """
        Check if the request is within the rate limit using sliding window.

        Algorithm:
        1. Get current timestamp in milliseconds
        2. Remove entries older than 60 seconds from the sorted set
        3. Count remaining entries (requests in current window)
        4. If under limit, add current request and allow
        5. If at/over limit, reject

        Args:
            redis: The async Redis client.
            identifier: Unique key for this user/IP.
            limit: Maximum requests allowed per 60-second window.

        Returns:
            True if request is allowed, False if rate limited.
        """
        try:
            now = time.time()
            window_start = now - 60  # 60-second sliding window

            # Use pipeline for atomic operation (all-or-nothing)
            pipe = redis.pipeline()

            # Remove entries older than the window (cleanup)
            pipe.zremrangebyscore(identifier, 0, window_start)

            # Count entries in current window
            pipe.zcard(identifier)

            # Add current request with timestamp as score
            pipe.zadd(identifier, {f"{now}": now})

            # Set key expiry to auto-cleanup (slightly longer than window)
            pipe.expire(identifier, 70)

            results = await pipe.execute()

            # results[1] is the count BEFORE adding current request
            current_count = results[1]

            return current_count < limit

        except Exception as e:
            # Any Redis error — skip rate limiting (graceful degradation)
            logger.warning("rate_limit_check_failed", error=str(e))
            return True  # Allow request through
