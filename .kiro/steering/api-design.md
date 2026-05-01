---
inclusion: always
---

# API Design Standards — PrescpHealth Rebuild

## Endpoint Naming

- Use plural nouns for resources: `/patients`, `/measurements`, `/alerts`
- Use kebab-case for multi-word paths: `/risk-scores`, `/drug-interactions`
- Nest sub-resources under parents: `/patients/{id}/measurements`
- Actions use verbs as sub-paths: `/patients/{id}/risk/compute`, `/alerts/{id}/acknowledge`
- Version prefix on all routes: `/api/v1/`

## HTTP Methods

- `GET` — read (never mutates state)
- `POST` — create or trigger action
- `PUT` — full update (idempotent)
- `PATCH` — partial update
- `DELETE` — soft delete (never hard delete patient data — HIPAA retention)

## Response Envelope

All API responses MUST use this consistent envelope:

```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "ISO-8601",
    "pagination": { "cursor": "...", "has_more": true }
  }
}
```

Error responses:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable description",
    "details": [ ... ],
    "request_id": "uuid"
  }
}
```

## Status Codes

- `200` — success (GET, PUT, PATCH)
- `201` — created (POST that creates a resource)
- `202` — accepted (async task enqueued — risk computation, forecast, report generation)
- `204` — no content (successful DELETE)
- `400` — validation error (bad input)
- `401` — unauthenticated (missing/expired token)
- `403` — forbidden (insufficient role/wrong tenant)
- `404` — not found
- `409` — conflict (duplicate/idempotency violation)
- `429` — rate limited
- `500` — internal server error (never expose stack traces)

## Pagination

- Use cursor-based pagination (not offset) for scalability
- Default page size: 25, max: 100
- Return `meta.pagination.cursor` and `meta.pagination.has_more`

## HIPAA-Specific API Rules

- NEVER return PHI in error messages or logs
- NEVER include patient names/identifiers in URL paths beyond opaque UUIDs
- All list endpoints MUST be tenant-scoped (enforced by RLS, not just application logic)
- Audit every data access — not just mutations
- Rate limit all endpoints to prevent data harvesting
- No caching of PHI in CDN or browser-accessible cache headers
  - Set `Cache-Control: no-store, no-cache, must-revalidate` on all PHI responses
  - Redis caching is internal only, encrypted at rest
