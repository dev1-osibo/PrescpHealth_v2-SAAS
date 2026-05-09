# =============================================================================
# backend/app/core/request_context.py
# =============================================================================
# Request context utilities for correlation ID propagation.
#
# Every HTTP request gets a unique request_id (UUID4) that flows through:
#   HTTP Request -> Service call -> Celery task -> Domain event -> External API
#
# This enables end-to-end tracing of any operation across the entire system.
# The request_id is:
#   - Generated in middleware if not present in incoming headers
#   - Stored in contextvars for access anywhere in the same async context
#   - Included in all log entries via structlog contextvars integration
#   - Returned in response headers (X-Request-ID) for client-side correlation
#   - Included in all error responses for support ticket correlation
#
# HIPAA: request_id is an opaque UUID -- it contains no PHI and is safe to log.
#
# Requirements: observability steering rule (correlation ID flow)
# =============================================================================

import uuid
from contextvars import ContextVar

# ContextVar stores the request ID for the current async context.
# Each concurrent request gets its own isolated value -- no cross-contamination.
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def generate_request_id() -> str:
    """
    Generate a new UUID4 request ID.

    Returns:
        A new UUID4 string for use as a correlation/request ID.
    """
    return str(uuid.uuid4())


def get_request_id() -> str:
    """
    Retrieve the current request ID from context.

    Returns:
        The request ID for the current async context, or empty string if unset.
    """
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> None:
    """
    Set the request ID in the current async context.

    Called by the Request ID middleware at the start of each request.
    The value persists for the lifetime of that request's async context.

    Args:
        request_id: The UUID string to set as the current request ID.
    """
    _request_id_ctx.set(request_id)
