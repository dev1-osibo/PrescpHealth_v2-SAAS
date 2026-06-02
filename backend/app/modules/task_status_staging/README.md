# task_status_staging — Background Task Status Module

Provides persistent tracking and status querying for all asynchronous background
tasks (Celery jobs, batch processing, report generation) within PrescpHealth.

---

## Purpose

Async tasks need a durable state store so:

- The API can return an immediate `202 Accepted` response and a `task_id`
- Clients can poll `GET /api/v1/tasks/{task_id}/status` to track progress
- Workers can record progress, errors, and final results without blocking HTTP
- Operators can audit task history, retry counts, and failure reasons

---

## Model: `BackgroundTask`

| Column          | Type          | Notes                                              |
|-----------------|---------------|----------------------------------------------------|
| `id`            | UUID PK       | UUID4, never sequential                            |
| `tenant_id`     | UUID NOT NULL | RLS-enforced tenant scope                          |
| `task_type`     | String(50)    | Logical label, e.g. `risk_score_batch`             |
| `status`        | String(20)    | See lifecycle below                                |
| `params`        | JSONB         | Input parameters — **may contain PHI; never log**  |
| `result`        | JSONB         | Output payload — **may contain PHI; never log**    |
| `error`         | Text          | Last error string — must NOT contain PHI           |
| `retry_count`   | Integer       | Incremented on each retry attempt                  |
| `max_retries`   | Integer       | Default 3; permanent failure after this            |
| `celery_task_id`| String(200)   | Celery UUID for broker-level polling               |
| `started_at`    | Timestamptz   | Set when worker picks up the task                  |
| `completed_at`  | Timestamptz   | Set when task reaches terminal state               |
| `created_at`    | Timestamptz   | From `TenantMixin` — set on INSERT                 |
| `updated_at`    | Timestamptz   | From `TenantMixin` — set on UPDATE                 |

---

## Status Lifecycle

```
pending ──► running ──► completed   (happy path)
                   └──► failed ──► retrying ──► running   (retry loop)
                                           └──► failed     (max_retries exhausted)
```

| Status      | Meaning                                              |
|-------------|------------------------------------------------------|
| `pending`   | Task created; not yet picked up by a worker          |
| `running`   | Worker has started execution; `started_at` is set    |
| `completed` | Task finished successfully; `result` is populated    |
| `failed`    | Task errored; `error` field contains reason          |
| `retrying`  | Retry scheduled; `retry_count` incremented           |

---

## API Endpoint

### `GET /api/v1/tasks/{task_id}/status`

Returns current status of a background task.

**RBAC:** Requires `Nurse` role or higher (any clinical user).

**Response:**
```json
{
  "success": true,
  "data": {
    "id": "...",
    "tenant_id": "...",
    "task_type": "risk_score_batch",
    "status": "completed",
    "retry_count": 0,
    "max_retries": 3,
    "celery_task_id": "...",
    "created_at": "2026-06-01T00:00:00Z",
    "started_at": "2026-06-01T00:00:01Z",
    "completed_at": "2026-06-01T00:00:05Z",
    "result": { ... },
    "error": null
  },
  "meta": {
    "request_id": "...",
    "timestamp": "2026-06-01T00:00:06Z"
  }
}
```

**Headers set on every response:**
```
Cache-Control: no-store
```

---

## Retry Policy

- Default `max_retries = 3`
- On each retry: `retry_count` incremented, status set to `retrying`
- After `retry_count >= max_retries`, status transitions to `failed` (permanent)
- The `BackgroundTaskTracker.mark_retry()` helper handles this transition atomically

---

## HIPAA Notes

1. **`params` and `result` are PHI-bearing** — they are stored in encrypted JSONB
   columns but must **never** appear in application logs or error messages.
2. **`error` strings must not contain PHI** — use UUIDs and error codes only.
3. **Cache-Control: no-store** is set on all API responses to prevent
   intermediary caching of task results.
4. **RLS policies** on `background_tasks` ensure cross-tenant data leakage is
   impossible at the PostgreSQL layer.
5. **Audit logging** is available via `TaskStatusService.audit_service` for
   any future mutation endpoints.
