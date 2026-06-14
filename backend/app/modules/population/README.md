# Population Analytics Module — `population_staging`

## Purpose

The **Population Analytics** module (Task 16) provides population-level risk
analytics for the PrescpHealth clinical dashboard. It surfaces three categories
of insight:

1. **Dashboard Metrics** — aggregate risk distribution, total active patients,
   high/critical counts, and per-disease average risk scores.
2. **Watchlist** — paginated list of High- and Critical-stratum patients for
   immediate clinical attention.
3. **Trends** — monthly average risk score per disease across configurable
   rolling time windows (1 month to 12 months).

---

## Data Model

### `cached_population_metrics`

Pre-computed metrics with a **1-hour TTL**. Each row represents one computed
metric keyed by `(tenant_id, metric_type, disease, time_window)`.

| Column        | Type              | Description                              |
|---------------|-------------------|------------------------------------------|
| id            | UUID PK           | Surrogate key                            |
| tenant_id     | UUID NOT NULL     | Tenant isolation (RLS)                   |
| metric_type   | String(50)        | `risk_distribution`, `trend`, etc.       |
| disease       | String(50) NULL   | Disease filter; NULL = all diseases      |
| time_window   | String(10) NULL   | `1m`, `3m`, `6m`, `12m`; NULL = snapshot|
| value         | JSONB             | Serialised metric payload                |
| computed_at   | Timestamptz       | When computed                            |
| expires_at    | Timestamptz       | After this timestamp the cache is stale  |
| created_at    | Timestamptz       | Row creation (from TenantMixin)          |
| updated_at    | Timestamptz       | Last update (from TenantMixin)           |

**Index:** `ix_pop_metric_lookup` on `(tenant_id, metric_type, disease, time_window)`.

---

## Caching Strategy

- All three metric types are cached with a **1-hour TTL**.
- On cache hit the stored JSONB value is deserialised and returned directly.
- On cache miss the metric is computed from the live `risk_scores` table, then
  stored via upsert (delete-then-insert pattern for simplicity).
- The Celery beat task `refresh_population_metrics_task` proactively refreshes
  all metric types every hour so that the cache is warm for dashboard loads.
- If the `risk_scores` table is unavailable (e.g., test environment, migration
  in progress), the service returns a safe stub response rather than failing.

---

## Watchlist Definition

A patient appears on the watchlist when their **latest risk score** for any
disease has a `stratum` value of `'High'` or `'Critical'`.  Watchlist rows
are ordered by `score DESC` and paginated with `limit`/`offset`.

---

## Trend Windows

| Code | Duration |
|------|----------|
| `1m` | 1 month  |
| `3m` | 3 months |
| `6m` | 6 months |
| `12m`| 12 months|

Trends are grouped by `(disease, month)` using `DATE_TRUNC('month', computed_at)`.

---

## RBAC

All endpoints require **Doctor** or **Clinic_Admin** role (or higher).

| Role            | Dashboard | Watchlist | Trends |
|-----------------|-----------|-----------|--------|
| Patient_User    | ✗         | ✗         | ✗      |
| Nurse           | ✗         | ✗         | ✗      |
| Doctor          | ✓         | ✓         | ✓      |
| Clinic_Admin    | ✓         | ✓         | ✓      |
| Super_Admin     | ✓         | ✓         | ✓      |

---

## API Reference

### `GET /api/v1/population/dashboard`

Returns aggregate population metrics.

**Response (200)**
```json
{
  "success": true,
  "data": {
    "total_active_patients": 1240,
    "risk_distribution": [
      {"disease": "diabetes", "stratum": "High", "count": 87, "percentage": 7.02}
    ],
    "high_risk_count": 312,
    "critical_risk_count": 41,
    "avg_risk_scores": {"diabetes": 0.6734, "hypertension": 0.5218},
    "last_updated": "2026-06-01T15:00:00Z"
  },
  "meta": {"request_id": "...", "timestamp": "..."}
}
```

---

### `GET /api/v1/population/watchlist`

Returns paginated High/Critical risk patients.

**Query params**

| Param    | Default | Description              |
|----------|---------|--------------------------|
| `limit`  | 50      | Page size (max 200)      |
| `offset` | 0       | Pagination offset        |
| `sort_by`| `score` | Sort column              |

**Response (200)**
```json
{
  "success": true,
  "data": [
    {
      "patient_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "disease": "diabetes",
      "score": 0.94,
      "stratum": "Critical",
      "computed_at": "2026-06-01T14:30:00Z"
    }
  ],
  "meta": {"total": 1, "limit": 50, "offset": 0, "request_id": "...", "timestamp": "..."}
}
```

---

### `GET /api/v1/population/trends?window=3m`

Returns monthly risk score trends per disease.

**Query params**

| Param    | Default | Allowed              |
|----------|---------|----------------------|
| `window` | `3m`    | `1m`, `3m`, `6m`, `12m` |

**Response (200)**
```json
{
  "success": true,
  "data": {
    "diabetes": [
      {"date": "2026-04-01T00:00:00Z", "value": 0.61, "stratum": "mixed"},
      {"date": "2026-05-01T00:00:00Z", "value": 0.63, "stratum": "mixed"}
    ]
  },
  "meta": {"window": "3m", "request_id": "...", "timestamp": "..."}
}
```

---

## HIPAA Compliance

- **Cache-Control: no-store** is set on all responses.
- No PHI appears in log entries — only UUIDs (tenant_id, request_id, patient_id in watchlist
  are not logged; only aggregate counts are logged).
- Cached values contain aggregate statistics only — no individual patient records.
- Row-Level Security (RLS) is enabled on `cached_population_metrics` at the
  PostgreSQL level (see migration `0016_population_metrics_tables.py`).
- Audit events are emitted for every endpoint access.

---

## Celery Beat Configuration

Add the following entry to the main Celery beat schedule to enable hourly
pre-computation of all population metrics:

```python
CELERY_BEAT_SCHEDULE = {
    # ... other tasks ...
    "refresh-population-metrics": {
        "task": "app.modules.population_staging.tasks.refresh_population_metrics_task",
        "schedule": 3600,  # every hour (seconds)
        "kwargs": {"tenant_id": "<tenant-uuid-string>"},
    },
}
```

For multi-tenant deployments, register one beat entry per tenant or use a
tenant-dispatch wrapper task that iterates over all active tenants.

---

## File Structure

```
backend/app/modules/population_staging/
├── __init__.py       # Public exports: PopulationService, router
├── exceptions.py     # PopulationError, MetricNotFoundError, ComputationError
├── models.py         # CachedPopulationMetric SQLAlchemy model
├── schemas.py        # Pydantic v2 request/response schemas
├── service.py        # PopulationService — core business logic + caching
├── tasks.py          # Celery task: refresh_population_metrics_task
├── router.py         # FastAPI router with RBAC-protected endpoints
└── README.md         # This file

backend/alembic/versions/
└── 0016_population_metrics_tables.py  # Migration: table + RLS
```
