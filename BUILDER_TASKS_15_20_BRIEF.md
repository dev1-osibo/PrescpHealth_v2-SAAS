# Builder Brief: Tasks 15-18 (Reports, Population, Admin, Background Tasks)

## Overview

Build 4 backend modules + 1 core utility. Write all code to **staging directories**. The main agent imports at checkpoint.

**Important:** Tasks 20-21 (ML Engine) are NOT included here — those require a separate ML-focused session with different dependencies (PyTorch, XGBoost, etc.) and go in the `ml/` directory, not `backend/`.

---

## Infrastructure Context (Same as Task 14)

- **Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 18, Redis, Celery
- **Database:** localhost:5432, database: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Branch:** `feat/emr-layer1`
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\`
- **Migration numbering:** 0016+ (0015 is taken by alerts)

---

## Existing Patterns (read-only reference)

- `backend/app/modules/risk_engine/` — complete module example
- `backend/app/modules/alerts_staging/` — just-completed Task 14 (similar patterns)
- `backend/app/core/events.py` — domain event bus
- `backend/app/core/deps.py` — FastAPI dependencies
- `backend/app/modules/auth/rbac.py` — role-based access control
- `backend/app/modules/audit/service.py` — audit logging
- `backend/app/core/base_model.py` — TenantMixin for RLS

---

## TASK 15: Report Generation Module

**Write to:** `backend/app/modules/reports_staging/`

### Requirements (Requirement 14)

1. Generate PDF clinical report (demographics, meds, risk scores + SHAP, forecast charts, measurements, alerts)
2. Generate referral letter PDF (AI-generated clinical summary)
3. Export patient measurements as CSV
4. Export population patient list with risk scores as CSV
5. PDF generation must complete within 30 seconds (async via Celery)
6. Charts embedded as SVG in PDF for print legibility

### Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `__init__.py` | Module exports | 5 |
| `service.py` | ReportService — orchestrate PDF/CSV generation | 120-140 |
| `pdf_builder.py` | PDF generation logic (use reportlab or weasyprint stub) | 100-120 |
| `csv_exporter.py` | CSV export logic (measurements + population) | 80-100 |
| `tasks.py` | Celery tasks for async report generation | 60-80 |
| `schemas.py` | Pydantic request/response schemas | 60-80 |
| `router.py` | FastAPI endpoints (4 endpoints) | 100-120 |
| `exceptions.py` | ReportError hierarchy | 30 |
| `README.md` | Module documentation | 150 |

### Endpoints

- `POST /api/v1/patients/{id}/reports/clinical` — generate clinical PDF (202 Accepted + task_id)
- `POST /api/v1/patients/{id}/reports/referral` — generate referral PDF (202 Accepted + task_id)
- `GET /api/v1/patients/{id}/export/measurements` — download CSV (200 + file)
- `GET /api/v1/population/export` — download population CSV (200 + file)

### RBAC
- Clinical/referral reports = Doctor
- Measurement export = Doctor
- Population export = Clinic_Admin

### Notes
- PDF libraries: Use `reportlab` for PDF generation. If import fails, stub it (the structure matters, not the rendering).
- SVG chart embedding: Stub this — just include a placeholder text "[Chart: Risk Score Trend]" in the PDF. Real chart rendering will come with frontend.
- The CSV export should stream results for large datasets (use StreamingResponse).

---

## TASK 16: Population Analytics Module

**Write to:** `backend/app/modules/population_staging/`

### Requirements (Requirement 12)

1. Display total active patients, risk distribution per disease, prevalence rates, average risk scores
2. Display high-risk watchlist (High/Critical stratum patients, sortable)
3. Display trend charts for cohort-level metrics over 1/3/6/12 month windows
4. Display outcome tracking (% of High/Critical predictions followed by clinical event within 90 days)
5. Refresh aggregate metrics at intervals no greater than 1 hour
6. Population report PDF (produced within 30 seconds)

### Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `__init__.py` | Module exports | 5 |
| `models.py` | CachedPopulationMetric model | 60-80 |
| `service.py` | PopulationService — dashboard, watchlist, trends, outcome tracking | 130-150 |
| `tasks.py` | Celery periodic task — refresh metrics every hour | 60-80 |
| `schemas.py` | Pydantic schemas for dashboard, watchlist, trends | 80-100 |
| `router.py` | FastAPI endpoints (3 endpoints) | 80-100 |
| `exceptions.py` | PopulationError hierarchy | 25 |
| `README.md` | Module documentation | 150 |

### Migration

Create: `backend/alembic/versions/0016_population_metrics_tables.py`

Table: `cached_population_metrics`
- id: UUID (PK)
- tenant_id: UUID (RLS)
- metric_type: str (e.g., "risk_distribution", "watchlist_count", "prevalence")
- disease: str (nullable)
- time_window: str (nullable — "1m", "3m", "6m", "12m")
- value: JSONB (the computed metric data)
- computed_at: datetime
- expires_at: datetime

Index: `(tenant_id, metric_type, disease, time_window)`

### Endpoints

- `GET /api/v1/population/dashboard` — full dashboard metrics
- `GET /api/v1/population/watchlist` — high-risk patient list (paginated, sortable)
- `GET /api/v1/population/trends` — trend data for charts (query param: window=1m|3m|6m|12m)

### RBAC
- All endpoints = Doctor, Clinic_Admin

### Implementation Notes
- The dashboard/watchlist queries aggregate from `risk_scores` and `patients` tables
- Use Redis caching for frequently-accessed metrics (TTL = 1 hour)
- The periodic Celery task pre-computes and caches expensive aggregations
- Watchlist query: `SELECT patients + latest risk_scores WHERE stratum IN ('High', 'Critical') ORDER BY score DESC`

---

## TASK 17: Admin Module

**Write to:** `backend/app/modules/admin_staging/`

### Requirements (Requirements 1.2, 7.1-7.5)

1. Create/manage tenants (provision with unique ID, data residency region, settings)
2. Deploy new ML model versions (retain previous for rollback)
3. Rollback to previous model version without downtime
4. View model performance metrics (AUC-ROC, calibration, Brier score)
5. Trigger historical recomputation with new model version

### Files to Create

| File | Purpose | ~Lines |
|------|---------|--------|
| `__init__.py` | Module exports | 5 |
| `service.py` | AdminService — tenant CRUD + model lifecycle | 130-150 |
| `service_tenant.py` | TenantManagement — create, configure, list tenants | 80-100 |
| `service_model.py` | ModelManagement — deploy, rollback, metrics | 100-120 |
| `schemas.py` | Pydantic schemas for all admin operations | 80-100 |
| `router.py` | FastAPI endpoints | 100-120 |
| `router_tenant.py` | Tenant management endpoints | 80-100 |
| `exceptions.py` | AdminError hierarchy | 30 |
| `README.md` | Module documentation | 150 |

### Endpoints

**Tenant Management (Super_Admin only):**
- `POST /api/v1/admin/tenants` — create new tenant
- `GET /api/v1/admin/tenants` — list all tenants
- `GET /api/v1/admin/tenants/{id}` — get tenant details
- `PUT /api/v1/admin/tenants/{id}` — update tenant settings

**Model Management (Super_Admin only):**
- `POST /api/v1/admin/models/deploy` — deploy new model version
- `POST /api/v1/admin/models/rollback` — rollback to previous version
- `GET /api/v1/admin/models/{disease}/metrics` — get model performance metrics
- `POST /api/v1/admin/models/{disease}/recompute` — trigger historical recomputation

**Tenant Settings (Clinic_Admin):**
- `GET /api/v1/admin/settings` — get current tenant settings
- `PUT /api/v1/admin/settings` — update tenant settings (language, timezone, notification preferences)

### RBAC
- Tenant + Model operations = Super_Admin only
- Tenant settings = Clinic_Admin (own tenant only)

### Notes
- Model deployment is a STUB — the actual ML model loading happens in Task 20. Here we just manage the metadata (version, deploy date, artifact path, status).
- Tenant creation should generate a UUID, set default settings, and NOT create any database schema changes (multi-tenant via RLS, not separate schemas).

---

## TASK 18: Background Task Status Module

**Write to:** `backend/app/modules/task_status_staging/`

Also create: `backend/app/core/tasks_tracker_staging.py` (core utility)

### Requirements (Requirement 15.4, 15.5)

1. Track background task status (pending, running, completed, failed)
2. Provide polling endpoint for clients to check task progress
3. Retry logic: up to 3 retries with exponential backoff (30s, 120s, 480s)

### Files to Create

**Core utility:** `backend/app/core/tasks_tracker_staging.py` (~80 lines)
- `BackgroundTaskTracker` class
- `create_task(task_type, tenant_id, params)` — returns task_id
- `update_status(task_id, status, result=None, error=None)`
- `get_status(task_id)` — returns current status + result/error
- `mark_retry(task_id)` — increment retry count, update status to "retrying"

**Module:** `backend/app/modules/task_status_staging/`

| File | Purpose | ~Lines |
|------|---------|--------|
| `__init__.py` | Module exports | 5 |
| `models.py` | BackgroundTask SQLAlchemy model | 50-60 |
| `service.py` | TaskStatusService — get status, list tasks | 60-80 |
| `schemas.py` | Pydantic schemas | 40-50 |
| `router.py` | Status endpoint | 50-60 |
| `README.md` | Documentation | 80 |

### Migration

Create: `backend/alembic/versions/0017_background_tasks_table.py`

Table: `background_tasks`
- id: UUID (PK)
- tenant_id: UUID (RLS)
- task_type: str (e.g., "risk_computation", "forecast", "report_generation")
- status: Enum (pending, running, completed, failed, retrying)
- params: JSONB (input parameters)
- result: JSONB (nullable — output on completion)
- error: str (nullable — error message on failure)
- retry_count: int (default 0)
- max_retries: int (default 3)
- created_at: datetime
- started_at: datetime (nullable)
- completed_at: datetime (nullable)
- celery_task_id: str (nullable — for correlation)

Index: `(tenant_id, status, created_at DESC)`

### Endpoint

- `GET /api/v1/tasks/{task_id}/status` — returns task status, progress, result or error

### RBAC
- Any authenticated user can check status of their own tenant's tasks

---

## Coding Standards (MUST follow — same as Task 14)

1. Heavy commenting — every function has a docstring
2. 150 line max per file
3. No PHI in logs — only UUIDs and metadata
4. HIPAA headers (Cache-Control: no-store) on PHI responses
5. Audit logging for all mutations
6. Standard response envelope: `{"success": true, "data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}`
7. Full type annotations
8. Async all the way
9. Use `datetime.now(timezone.utc)` — NOT `datetime.utcnow()`
10. Imports: `from datetime import datetime, timezone` (not `__import__`)

---

## What NOT to Do

- Do NOT modify any existing files
- Do NOT write to production directories (only `*_staging/`)
- Do NOT implement actual PDF rendering with real data (stub with placeholder content)
- Do NOT implement actual ML model loading (stub with metadata management)
- Do NOT hard-delete data
- Do NOT put PHI in logs or error messages
- Do NOT use `datetime.utcnow()`
- Do NOT use `os.getcwd()` for path resolution

---

## Execution Order (Suggested)

1. **Task 18** first (smallest, provides task tracking that other modules reference)
2. **Task 15** (Reports — uses Celery tasks + task tracker)
3. **Task 16** (Population — aggregates from existing data)
4. **Task 17** (Admin — tenant/model management)

---

## Delivery Checklist

For EACH module:
- [ ] All files in correct staging directory
- [ ] Migration file(s) with correct numbering (0016, 0017)
- [ ] All Python files pass syntax check: `python -c "import ast; ast.parse(open('file.py').read())"`
- [ ] All imports resolve (no circular dependencies)
- [ ] Every file under 150 lines (excluding comments/docstrings)
- [ ] Every function has a docstring
- [ ] No PHI in logs
- [ ] README.md present
- [ ] Patterns match existing modules

---

## Reference Files to Study

- `backend/app/modules/risk_engine/` — full module pattern
- `backend/app/modules/alerts_staging/` — recently completed Task 14
- `backend/app/modules/drug_interactions/router.py` — router with HIPAA headers
- `backend/app/core/events.py` — event bus
- `backend/app/modules/audit/service.py` — audit logging
- `backend/alembic/versions/0015_alert_system_tables.py` — latest migration pattern

---

## Note on Tasks 19-21

- **Task 19** is a checkpoint — the main agent handles this (not the builder)
- **Tasks 20-21** are the ML Engine (risk prediction + forecasting pipelines) — these go in the `ml/` directory, need ML dependencies, and will be briefed separately
