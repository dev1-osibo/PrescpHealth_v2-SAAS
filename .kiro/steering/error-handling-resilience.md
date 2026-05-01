---
inclusion: always
---

# Error Handling & Resilience Standards — PrescpHealth Rebuild

## Core Principle

Clinical software must NEVER crash silently or leave users without feedback. Every failure mode must be anticipated, handled gracefully, and communicated clearly to the clinician.

## External Service Failure Handling

### LLM Providers (OpenAI GPT-4o / Anthropic Claude)
- **Primary**: GPT-4o with 8-second timeout
- **Fallback**: Claude with 12-second timeout
- **Both down**: Return structured response: "AI assistant temporarily unavailable. Clinical data and risk scores remain accessible."
- **Never block clinical workflows** — AI is advisory, not gating

### Email/SMS (SendGrid / Twilio)
- **Retry policy**: Exponential backoff — 30s, 2min, 8min, 30min (max 5 retries)
- **Email retry window**: 24 hours before marking as failed
- **SMS retry window**: 6 hours before marking as failed
- **Fallback**: If SMS fails, attempt email. If email fails, ensure in-app alert is always delivered.
- **Never lose a critical alert** — in-app delivery is the guaranteed channel

### Redis (Cache/Queue)
- **Cache miss**: Fall through to database (Redis is acceleration, not requirement)
- **Queue unavailable**: Log error, attempt direct synchronous processing for critical tasks (alerts), queue non-critical tasks for retry
- **Connection recovery**: Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)

### PostgreSQL
- **Connection pool exhaustion**: Return 503 with retry-after header
- **Query timeout (>30s)**: Kill query, return error, log for investigation
- **Replication lag**: Read replicas may serve stale data — critical reads (risk scores, alerts) always hit primary

## ML Engine Failure Handling

When the ML engine fails mid-computation:
1. **Return stale data with timestamp** — show the last successful risk scores with "Last computed: [datetime]" label
2. **Never show partial results** — either all 6 disease scores compute or none are updated
3. **Queue for retry** — automatic retry in 5 minutes
4. **Alert the clinician** — "Risk scores are being recalculated. Showing last available results."
5. **Log the failure** — include model version, input feature count, error type (not PHI)

## Circuit Breaker Pattern

Implement circuit breakers on all external service calls:

```
States: CLOSED → OPEN → HALF_OPEN → CLOSED

CLOSED (normal): Requests flow through. Track failure count.
OPEN (tripped): After 5 failures in 60s, stop calling service. Return fallback immediately.
HALF_OPEN (testing): After 30s cooldown, allow 1 test request through.
  - If succeeds → CLOSED
  - If fails → OPEN (reset cooldown)
```

Apply to: OpenAI, Anthropic, SendGrid, Twilio, any future external integrations.

## Graceful Degradation Hierarchy

When services degrade, the platform degrades gracefully in this order:

1. **Always available**: Patient records, measurements, historical risk scores, alerts
2. **Degraded without Redis**: Slower responses, no rate limiting (accept the risk temporarily)
3. **Degraded without LLM**: No AI assistant, but all other features work
4. **Degraded without Celery**: Synchronous risk computation (slower but functional for critical cases)
5. **Degraded without email/SMS**: In-app alerts only, queue notifications for later delivery

## Error Response Rules

- Never expose stack traces to the client (500 errors return generic message + request_id)
- Always include `request_id` for support correlation
- Distinguish between user errors (4xx) and system errors (5xx) clearly
- Log full error context server-side (minus PHI) for debugging
- Rate limit error responses too (prevent error-based information leakage)

## Timeout Budgets

| Operation | Timeout | Action on Timeout |
|-----------|---------|-------------------|
| API request total | 30s | Return 504 |
| Database query | 10s | Kill query, return 503 |
| Redis operation | 2s | Skip cache, fall through |
| LLM call (primary) | 8s | Failover to secondary |
| LLM call (secondary) | 12s | Return "unavailable" |
| Celery task | 300s | Mark failed, queue retry |
| External API (SendGrid/Twilio) | 10s | Queue for retry |
