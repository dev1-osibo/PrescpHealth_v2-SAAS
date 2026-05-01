---
inclusion: always
---

# Logging & Observability Standards — PrescpHealth Rebuild

## Core Principle

Every request, task, and event must be traceable end-to-end across the entire system — from API call through Celery task through event handler — without ever exposing PHI.

## Structured Logging Format

All logs MUST be structured JSON with these mandatory fields:

```json
{
  "timestamp": "2025-01-15T10:30:00.123Z",
  "level": "info|warning|error|critical",
  "service": "backend|celery-worker|ml-engine",
  "correlation_id": "uuid — ties entire request chain together",
  "tenant_id": "uuid",
  "user_id": "uuid (if authenticated)",
  "module": "auth|patients|measurements|risk|forecast|alerts|...",
  "action": "what happened (verb phrase)",
  "duration_ms": 42,
  "metadata": { "...additional context..." }
}
```

## Correlation ID Flow

A single `correlation_id` must flow through the entire chain:

```
HTTP Request (generates correlation_id in middleware)
  → Service call (passes correlation_id)
    → Celery task (correlation_id in task headers)
      → Domain event (correlation_id in event payload)
        → Event handler (logs with same correlation_id)
          → External API call (correlation_id in request headers for our tracking)
```

Implementation:
- Generate in `AuditMiddleware` if not present in request headers
- Pass via `contextvars` within the same process
- Include in Celery task kwargs as `_correlation_id`
- Include in domain event payload

## What to Log (Always)

- Request received: method, path, user_id, tenant_id, correlation_id
- Request completed: status code, duration_ms, correlation_id
- Authentication events: login success/failure, token refresh, MFA verify, lockout
- Authorization failures: role denied, tenant mismatch
- Database operations: query duration (if >100ms), connection pool stats
- Celery task lifecycle: enqueued, started, completed, failed, retried
- External service calls: service name, duration_ms, success/failure, circuit breaker state
- Domain events: event type, source module, correlation_id
- ML computations: model version, feature count, computation duration, result summary (score count, not values)
- Alert generation: alert type, severity, channel dispatched to

## What to NEVER Log

- Patient names, dates of birth, addresses, phone numbers
- Measurement values (blood pressure, glucose, BMI, etc.)
- Risk score values
- Diagnosis or condition details
- Medication names or dosages
- AI assistant conversation content
- Any field that constitutes PHI
- Full request/response bodies (may contain PHI)
- Passwords, tokens, API keys, secrets

## Log Levels

- **CRITICAL**: System is unusable — database down, all external services failed
- **ERROR**: Operation failed — unhandled exception, task failure, data corruption detected
- **WARNING**: Degraded operation — cache miss, retry triggered, circuit breaker opened, slow query
- **INFO**: Normal operations — request completed, task finished, event published
- **DEBUG**: Development only — never in production (may accidentally contain PHI)

## Performance Metrics to Track

- API response times (p50, p95, p99) per endpoint
- Database query durations per query type
- Redis hit/miss ratio
- Celery queue depths per queue (risk, forecast, notification, report)
- Celery task durations per task type
- External service response times and error rates
- ML computation durations per disease model
- Active WebSocket connections (if applicable)
- Memory and CPU usage per service

## Alerting Thresholds (Operational)

| Metric | Warning | Critical |
|--------|---------|----------|
| API p95 latency | >500ms | >2000ms |
| DB query duration | >100ms | >1000ms |
| Celery queue depth | >100 tasks | >500 tasks |
| Error rate | >1% of requests | >5% of requests |
| External service failures | >3 in 5min | Circuit breaker open |
| Redis connection failures | Any | >3 in 1min |

## Log Retention

- Application logs: 90 days (rotated daily)
- Security/audit logs: 7 years (separate stream, append-only)
- Performance metrics: 1 year (aggregated after 30 days)
- Error logs: 180 days (for post-incident analysis)
