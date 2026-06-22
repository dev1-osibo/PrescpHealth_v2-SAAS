"""
PrescpHealth Backend — In-Memory Rate Limiter.

Provides a simple sliding-window rate limiter backed by an in-memory store.
This serves as a FALLBACK when Redis is unavailable (the primary Redis-based
rate limiter lives in app.core.middleware.rate_limit).

Design Decisions:
- In-memory: No external dependency, works even if Redis is down
- Thread-safe: Uses a lock for concurrent access in multi-threaded workers
- Sliding window: More fair than fixed windows (no burst at boundary)
- Per-client: Tracks each client_id independently

Limitations:
- Not shared across multiple worker processes (each worker has own state)
- Memory grows linearly with number of tracked clients
- Use Redis-based limiter for production multi-instance deployments

HIPAA NOTE:
    Rate limiting prevents data harvesting attacks. A compromised account
    limited to 1000 req/min can only exfiltrate data slowly, giving time
    for anomaly detection to trigger.
"""

from __future__ import annotations

import time
import threading
from collections import defaultdict

# ---------------------------------------------------------------------------
# Module-level state — shared across all calls within this process
# ---------------------------------------------------------------------------

# Maps client_id -> list of request timestamps (epoch seconds)
_request_log: dict[str, list[float]] = defaultdict(list)

# Thread safety for concurrent access to _request_log
_lock = threading.Lock()


def check_rate_limit(
    client_id: str,
    max_requests: int,
    window_seconds: int,
) -> bool:
    """
    Check if a client is within their rate limit using sliding window.

    Tracks request timestamps per client_id. Removes expired entries
    outside the window, then checks if the count exceeds max_requests.

    Args:
        client_id: Unique identifier for the client (user_id, IP, API key).
        max_requests: Maximum number of requests allowed in the window.
        window_seconds: Size of the sliding window in seconds.

    Returns:
        bool: True if within limit (request allowed), False if exceeded.

    Example:
        >>> check_rate_limit("user-123", max_requests=100, window_seconds=60)
        True  # First request, well within limit
    """
    now = time.time()
    window_start = now - window_seconds

    with _lock:
        # Get existing timestamps for this client
        timestamps = _request_log[client_id]

        # Prune expired entries outside the sliding window
        _request_log[client_id] = [
            ts for ts in timestamps if ts > window_start
        ]

        # Check if adding this request would exceed the limit
        if len(_request_log[client_id]) >= max_requests:
            return False

        # Within limit — record this request
        _request_log[client_id].append(now)
        return True


def reset_rate_limit(client_id: str) -> None:
    """
    Reset the rate limit counter for a specific client.

    Used in testing and when an admin explicitly clears a lockout.

    Args:
        client_id: The client whose counter should be cleared.
    """
    with _lock:
        _request_log.pop(client_id, None)


def reset_all() -> None:
    """
    Clear all rate limit state. Used in testing only.

    WARNING: Do not call in production — would reset all limits globally.
    """
    with _lock:
        _request_log.clear()
