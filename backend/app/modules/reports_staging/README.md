# Reports Staging Module

**Task 15 — PrescpHealth Backend**

Provides on-demand PDF report generation (clinical summaries and referral letters) and
streaming CSV export (measurements and population risk snapshots) with full HIPAA
compliance, RBAC enforcement, and audit logging.

---

## Table of Contents

1. [Purpose](#purpose)
2. [Architecture](#architecture)
3. [File Overview](#file-overview)
4. [PDF Generation (reportlab stub)](#pdf-generation-reportlab-stub)
5. [CSV Streaming](#csv-streaming)
6. [Celery Tasks & Retry Policy](#celery-tasks--retry-policy)
7. [RBAC](#rbac)
8. [HIPAA Compliance](#hipaa-compliance)
9. [API Reference](#api-reference)
10. [Adding a New Section](#adding-a-new-section)
11. [Dependencies](#dependencies)

---

## Purpose

The reports module gives clinical staff two classes of data export:

| Export Type | Format | Delivery |
|-------------|--------|----------|
| Clinical Summary | PDF | Async (Celery task) |
| Referral Letter | PDF | Async (Celery task) |
| Patient Measurements | CSV | Synchronous streaming |
| Population Risk Snapshot | CSV | Synchronous streaming |

PDF generation is offloaded to Celery workers because document rendering can take
several seconds for patients with large measurement histories. The HTTP response
returns immediately with a `task_id` for polling.

CSV exports use `StreamingResponse` so that large datasets (up to 50 000 rows for
population exports) are flushed to the client row-by-row without buffering in server
memory.

---

## Architecture

```
router.py          ← FastAPI endpoints; RBAC; headers; StreamingResponse
   │
   ├── service.py  ← Business logic; audit logging; orchestration
   │      ├── pdf_builder.py  ← Clinical & referral PDF construction (reportlab)
   │      ├── csv_exporter.py ← Measurement & population CSV streaming
   │      └── tasks.py        ← Celery tasks enqueued by service methods
   │
   └── schemas.py  ← Pydantic v2 request/response models
```

The service layer is instantiated per-request with injected dependencies
(`db`, `audit_service`, `request_id`, `tenant_id`, `user_id`), matching the
pattern established in `alerts_staging/service.py`.

---

## File Overview

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | ~15 | Public exports: `ReportService`, `router` |
| `exceptions.py` | ~40 | `ReportError`, `ReportNotFoundError`, `ReportGenerationError`, `ExportError` |
| `schemas.py` | ~70 | `ReportRequest`, `ReferralRequest`, `ReportTaskResponse`, `CSVExportMeta` |
| `pdf_builder.py` | ~150 | `PDFBuilder` class — clinical and referral PDF construction |
| `csv_exporter.py` | ~130 | `CSVExporter` class — async generator CSV exports |
| `service.py` | ~160 | `ReportService` — orchestration and audit logging |
| `tasks.py` | ~200 | Celery tasks for PDF generation with retry |
| `router.py` | ~180 | FastAPI router — 4 endpoints |

---

## PDF Generation (reportlab stub)

The `PDFBuilder` class attempts to import `reportlab` at module load time:

```python
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.pagesizes import letter
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
```

**If reportlab is installed:** full PDF documents are generated with section headers,
placeholder content blocks, and a chart placeholder for the risk scores section.

**If reportlab is not installed:** the methods return `b"PDF_PLACEHOLDER: reportlab not installed"`
so the Celery task completes without crashing. Install reportlab with:

```bash
pip install reportlab
```

### Clinical PDF sections

Default sections: `["demographics", "medications", "risk_scores", "alerts"]`

Each section renders as:
- A heading (`Section Name`)
- A placeholder paragraph `[Section: {key} - data loaded on render]`
- For `risk_scores`: an additional line `[Chart: Risk Score Trend - SVG embedded on render]`

Callers can override `include_sections` in the request body to include a subset
or custom ordering.

---

## CSV Streaming

Both exporters use async generators and are consumed via FastAPI's `StreamingResponse`:

```python
# In router
return StreamingResponse(
    content=generator,          # AsyncGenerator[str, None]
    media_type="text/csv",
    headers={"Content-Disposition": 'attachment; filename="..."'},
)
```

### Measurements export

- **Endpoint:** `GET /api/v1/patients/{patient_id}/export/measurements`
- **Header row:** `date,measurement_type,value,unit,validated`
- **Limit:** 10 000 rows (configurable via `CSVExporter.export_measurements`)
- **Fallback:** yields an empty dataset (header only) if the measurements model is
  not yet importable.

### Population export

- **Endpoint:** `GET /api/v1/population/export`
- **Header row:** `patient_id,disease,score,stratum,computed_at`
- **Limit:** 50 000 rows
- **Fallback:** yields an empty dataset if the risk_engine model is not importable.

---

## Celery Tasks & Retry Policy

### Tasks

| Task name | Triggered by |
|-----------|-------------|
| `reports.generate_clinical_pdf` | `POST /reports/clinical` |
| `reports.generate_referral_pdf` | `POST /reports/referral` |

### Retry policy

```
max_retries = 3
time_limit  = 30 seconds
acks_late   = True   # prevents task loss on worker crash
```

Exponential backoff delays (same formula as alerts module):
```
delay = 30 * (4 ** retry_count)
→ 30 s, 120 s (2 min), 480 s (8 min)
```

### Task status updates

Tasks update a `BackgroundTaskTracker` record on completion/failure.
The tracker is imported from `app.core.tasks_tracker_staging`. If that module
is not yet available the update is silently skipped (logged as a warning).

---

## RBAC

| Endpoint | Required role |
|----------|--------------|
| `POST /reports/clinical` | `Doctor` (and above) |
| `POST /reports/referral` | `Doctor` (and above) |
| `GET /export/measurements` | `Doctor` (and above) |
| `GET /population/export` | `Clinic_Admin` (and above) |

Role hierarchy (monotonic inheritance):
`Patient_User < Nurse < Doctor < Clinic_Admin < Super_Admin`

Enforced via `require_role(Role.DOCTOR)` / `require_role(Role.CLINIC_ADMIN)`
from `app.modules.auth.rbac`.

---

## HIPAA Compliance

| Control | Implementation |
|---------|---------------|
| PHI caching prevention | `Cache-Control: no-store` on all 4 endpoints |
| PHI-safe logging | Logs only UUIDs (`patient_id`, `task_id`, `tenant_id`); never names, values, or reasons |
| Audit trail | `audit_service.log_audit()` called on every report request and CSV export |
| Tenant isolation | All DB queries scoped by `tenant_id`; RLS enforced at PostgreSQL layer |
| No hard deletes | Reports are ephemeral (Celery result); underlying patient data is soft-deleted only |

---

## API Reference

### POST `/api/v1/patients/{patient_id}/reports/clinical`

**Role:** Doctor | **Response:** 202 Accepted

```json
// Request body
{
  "patient_id": "uuid",
  "include_sections": ["demographics", "medications", "risk_scores", "alerts"]
}

// Response
{
  "success": true,
  "data": {"task_id": "uuid", "estimated_seconds": 10},
  "meta": {"request_id": "uuid", "timestamp": "2026-06-01T00:00:00Z"}
}
```

### POST `/api/v1/patients/{patient_id}/reports/referral`

**Role:** Doctor | **Response:** 202 Accepted

```json
// Request body
{
  "patient_id": "uuid",
  "referring_physician": "Dr. Jane Smith",
  "referral_reason": "Persistent hypertension unresponsive to first-line treatment."
}

// Response — same envelope as clinical report
```

### GET `/api/v1/patients/{patient_id}/export/measurements`

**Role:** Doctor | **Response:** `text/csv` stream

```
date,measurement_type,value,unit,validated
2026-05-01T09:00:00Z,blood_pressure_systolic,145,mmHg,true
...
```

### GET `/api/v1/population/export`

**Role:** Clinic_Admin | **Response:** `text/csv` stream

```
patient_id,disease,score,stratum,computed_at
550e8400-...,diabetes,72.4,high,2026-05-31T18:00:00Z
...
```

---

## Adding a New Section

1. Add the section key to `include_sections` in the request (it's a free-form list).
2. In `PDFBuilder._build_clinical_with_reportlab`, add an `elif section == "your_key":` block.
3. Update `ReportRequest.include_sections` default if the section should be on by default.

---

## Dependencies

| Package | Purpose | Required |
|---------|---------|----------|
| `reportlab` | PDF generation | Optional (stub if absent) |
| `fastapi` | HTTP routing and `StreamingResponse` | Yes |
| `sqlalchemy` | Async DB queries in CSV exporter | Yes |
| `celery` | Background PDF tasks | Yes |
| `structlog` | PHI-safe structured logging | Yes |
| `pydantic` v2 | Request/response validation | Yes |
