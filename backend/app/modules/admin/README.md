# admin_staging — Admin Module

## Purpose

The `admin_staging` module provides Super_Admin and Clinic_Admin level
operations for PrescpHealth:

- **Tenant management** — create, list, read, and update tenant organisations
- **Model lifecycle** — deploy, roll back, and inspect ML model versions
- **Tenant settings** — manage timezone, language, and notification preferences per tenant

This module does **not** run any migrations. It manages data in tables
that already exist:
- `tenants` — created by migration 0002 (auth module)
- `model_versions` — created by migration 0011 (risk_engine module)

---

## Architecture

```
admin_staging/
├── __init__.py          # Re-exports: AdminService, router, tenant_router
├── exceptions.py        # AdminError hierarchy
├── schemas.py           # Pydantic v2 request/response models
├── service_tenant.py    # TenantManagementService
├── service_model.py     # ModelManagementService
├── service.py           # AdminService facade
├── router_tenant.py     # tenant_router — /api/v1/admin/tenants/*
├── router.py            # router — /api/v1/admin/models/* + settings
└── README.md
```

---

## RBAC Matrix

| Endpoint | Required Role |
|---|---|
| `POST /api/v1/admin/tenants` | `Super_Admin` |
| `GET /api/v1/admin/tenants` | `Super_Admin` |
| `GET /api/v1/admin/tenants/{id}` | `Super_Admin` |
| `PUT /api/v1/admin/tenants/{id}` | `Super_Admin` |
| `POST /api/v1/admin/models/deploy` | `Super_Admin` |
| `POST /api/v1/admin/models/rollback` | `Super_Admin` |
| `GET /api/v1/admin/models/{disease}/metrics` | `Super_Admin` |
| `POST /api/v1/admin/models/{disease}/recompute` | `Super_Admin` |
| `GET /api/v1/admin/settings` | `Clinic_Admin` (own tenant) |
| `PUT /api/v1/admin/settings` | `Clinic_Admin` (own tenant) |

Role hierarchy (ascending): `Patient_User < Nurse < Doctor < Clinic_Admin < Super_Admin`.
Higher roles inherit all lower permissions.

---

## Tenant Management

### Create Tenant
```http
POST /api/v1/admin/tenants
Authorization: Bearer <super_admin_jwt>

{
  "name": "Acme Health",
  "region": "us-east-1",
  "settings": {}
}
```

### List Tenants
```http
GET /api/v1/admin/tenants?limit=50&offset=0
Authorization: Bearer <super_admin_jwt>
```

### Get Tenant
```http
GET /api/v1/admin/tenants/{tenant_id}
Authorization: Bearer <super_admin_jwt>
```

### Update Tenant
```http
PUT /api/v1/admin/tenants/{tenant_id}
Authorization: Bearer <super_admin_jwt>

{
  "is_active": false,
  "settings": {"feature_flags": {"beta_dashboard": true}}
}
```

---

## Model Lifecycle

### Deploy Model Version
```http
POST /api/v1/admin/models/deploy
Authorization: Bearer <super_admin_jwt>

{
  "disease": "diabetes",
  "version": "1.3.0",
  "artifact_path": "s3://models/diabetes/1.3.0/model.pkl",
  "metrics": {"auc": 0.91, "f1": 0.87}
}
```

The service automatically deactivates the previous active version for the
same disease before inserting the new one.

### Roll Back Model
```http
POST /api/v1/admin/models/rollback
Authorization: Bearer <super_admin_jwt>

{
  "disease": "diabetes",
  "target_version": "1.2.0"
}
```

Returns `404` if `target_version` does not exist in `model_versions`.

### Get Metrics
```http
GET /api/v1/admin/models/diabetes/metrics
Authorization: Bearer <super_admin_jwt>
```

Returns all versions and their recorded evaluation metrics.

### Trigger Recomputation (Stub)
```http
POST /api/v1/admin/models/diabetes/recompute
Authorization: Bearer <super_admin_jwt>
```

Returns HTTP `202 Accepted` with a `task_id`. In the current stub
implementation this is a mock UUID. Task 20 (ML pipeline) will replace
this with a real Celery enqueue call.

---

## Tenant Settings

### Get Current Tenant Settings
```http
GET /api/v1/admin/settings
Authorization: Bearer <clinic_admin_jwt>
```

### Update Settings
```http
PUT /api/v1/admin/settings
Authorization: Bearer <clinic_admin_jwt>

{
  "timezone": "America/New_York",
  "language": "en-US",
  "notification_channels": ["email", "sms"]
}
```

Only non-null fields are applied; missing fields are left unchanged.

---

## Standard Response Envelope

All endpoints return:
```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-01-01T00:00:00+00:00"
  }
}
```

All responses include `Cache-Control: no-store` to prevent caching of
sensitive operational metadata.

---

## Audit Logging

Every mutation is recorded via `AuditService.log_audit()`:

| Action | Trigger |
|---|---|
| `tenant_created` | `POST /admin/tenants` |
| `tenants_listed` | `GET /admin/tenants` |
| `tenant_updated` | `PUT /admin/tenants/{id}` |
| `model_deployed` | `POST /admin/models/deploy` |
| `model_rolled_back` | `POST /admin/models/rollback` |
| `model_metrics_accessed` | `GET /admin/models/{disease}/metrics` |
| `historical_recomputation_triggered` | `POST /admin/models/{disease}/recompute` |
| `tenant_settings_read` | `GET /admin/settings` |
| `tenant_updated` | `PUT /admin/settings` |

Audit records contain only UUIDs and non-PHI field names. Clinical data,
patient identifiers, and measurement values are **never** logged.

---

## Stub Notes

### Tenant Table
The exact column schema of the `tenants` table is owned by the auth
module. `TenantManagementService` uses raw SQL guarded by `try/except`
blocks that warn and return stub data on failure rather than crashing.
Once the tenant model is importable, replace the raw SQL with ORM calls.

### Model Recomputation
`trigger_recomputation()` is a stub that returns a random UUID as
`task_id`. Task 20 will implement:
```python
enqueue_recompute_task.delay(disease, task_id)
```
The endpoint already returns `202 Accepted` and the `queued` status field
to match the production contract.

---

## HIPAA / Security Notes

- `Cache-Control: no-store` on **every** response
- No PHI in any log line — only UUIDs and structural field names
- All mutations audit-logged before returning to caller
- RBAC enforced via `require_role()` FastAPI dependency
- Tenant isolation enforced: Clinic_Admin can only touch own tenant settings
