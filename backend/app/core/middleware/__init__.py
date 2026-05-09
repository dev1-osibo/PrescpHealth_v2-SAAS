"""
PrescpHealth Backend — Middleware Package.

Contains the core middleware stack applied to every request:
- TenantMiddleware: Extracts tenant_id from JWT, sets PostgreSQL RLS context
- RateLimitMiddleware: Redis-backed sliding window rate limiting per user/role
- AuditMiddleware: Logs request metadata for observability and compliance

Middleware execution order (outermost to innermost):
    1. AuditMiddleware (logs request start, measures duration)
    2. RateLimitMiddleware (rejects if over limit before hitting business logic)
    3. TenantMiddleware (sets DB context for RLS before any queries run)

Import all middleware from this package:
    from app.core.middleware import TenantMiddleware, RateLimitMiddleware, AuditMiddleware
"""

from app.core.middleware.tenant import TenantMiddleware
from app.core.middleware.rate_limit import RateLimitMiddleware
from app.core.middleware.audit import AuditMiddleware

__all__ = ["TenantMiddleware", "RateLimitMiddleware", "AuditMiddleware"]
