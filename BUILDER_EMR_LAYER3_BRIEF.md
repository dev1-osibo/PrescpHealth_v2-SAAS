# Builder Brief: EMR Layer 3 — Advanced Operations (Tasks 13-16)

## Overview

Build 4 advanced EMR modules. Write all code to **staging directories**. The main agent imports at the Layer 3 checkpoint.

These modules add billing, bed management, FHIR interoperability, and external system integrations on top of existing Layer 1 (encounters, prescriptions, lab orders) and Layer 2 (appointments, referrals, documents, registration).

---

## Infrastructure Context

- **Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 18, Redis, Celery
- **Database:** localhost:5432, database: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Branch:** `feat/emr-layer1`
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\`
- **Migration numbering:** 0022+ (0001-0021 are taken)

---

## Existing Patterns (read-only reference)

- `backend/app/modules/encounters/` — full EMR module (models, service, enums, schemas, router, FHIR mapper)
- `backend/app/modules/appointments/` — service with conflict detection + recurrence
- `backend/app/modules/alerts/` — rules engine + escalation + multi-channel dispatch
- `backend/app/core/base_model.py` — TenantMixin for RLS (all models MUST use this)
- `backend/app/core/events.py` — domain event bus
- `backend/app/core/database.py` — `get_async_session_context()` for Celery tasks
- `backend/app/core/deps.py` — `get_db`, `get_current_user`, `get_tenant_id`, `get_request_id`
- `backend/app/modules/auth/rbac.py` — `require_role(Role.DOCTOR)`, `Role.NURSE`, `Role.CLINIC_ADMIN`, `Role.SUPER_ADMIN`
- `backend/app/modules/audit/service.py` — `AuditService` with `log_action()`
- `backend/app/modules/measurements/models.py` — Measurement model (bed_management vitals create these)
- `backend/app/modules/encounters/fhir_mapper.py` — existing FHIR mapper pattern

---

## TASK 13: Billing Module

**Write to:** `backend/app/modules/billing_staging/`
**Migration:** `backend/alembic/versions/0022_billing_tables.py`

### Models

**Invoice:** id, tenant_id (RLS), patient_id (FK patients), encounter_id (FK encounters), invoice_number (unique per tenant), status (draft/issued/paid/partially_paid/overdue/cancelled/void), total_amount Decimal(10,2), paid_amount Decimal(10,2) default 0, currency str default "USD", issued_at datetime nullable, due_date date nullable, notes str nullable, created_by (FK users), created_at, updated_at

**InvoiceLineItem:** id, tenant_id (RLS), invoice_id (FK invoices), item_type (consultation/procedure/lab_test/medication/supply/other), description str, quantity int default 1, unit_price Decimal(10,2), total_price Decimal(10,2), code str nullable, created_at

**Payment:** id, tenant_id (RLS), invoice_id (FK invoices), amount Decimal(10,2), payment_method (cash/card/bank_transfer/mobile_money/insurance), reference_number str nullable, paid_at datetime, recorded_by (FK users), notes str nullable, created_at

**InsuranceClaim:** id, tenant_id (RLS), invoice_id (FK invoices), patient_id (FK patients), insurance_provider str, policy_number str, claim_number str nullable, status (submitted/pending_review/approved/partially_approved/denied/resubmitted), submitted_amount Decimal(10,2), approved_amount Decimal(10,2) nullable, denial_reason str nullable, submitted_at datetime, resolved_at datetime nullable, created_at

### Service Methods
- `generate_invoice(encounter_id)` — pull encounter billable items, create invoice + line items, compute total
- `record_payment(invoice_id, payment_data)` — create payment, update paid_amount and status
- `get_invoice_detail(invoice_id)` — invoice with line items and payments
- `list_invoices(tenant_id, filters)` — filterable list
- `void_invoice(invoice_id, reason)` — mark as void
- `submit_claim(invoice_id, insurance_data)` — create insurance claim
- `update_claim_status(claim_id, status, reason)` — handle approval/denial

### Endpoints (7)
- `POST /api/v1/invoices` — generate from encounter
- `GET /api/v1/invoices` — list
- `GET /api/v1/invoices/{id}` — detail
- `POST /api/v1/invoices/{id}/payments` — record payment
- `POST /api/v1/insurance-claims` — submit claim
- `GET /api/v1/insurance-claims` — list claims
- `PUT /api/v1/insurance-claims/{id}/status` — update claim status

### RBAC: All = Clinic_Admin

### Files (~10): `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`, `service.py`, `service_claims.py`, `router.py`, `README.md`

---

## TASK 14: Bed Management Module

**Write to:** `backend/app/modules/bed_management_staging/`
**Migration:** `backend/alembic/versions/0023_bed_management_tables.py`

### Models

**Ward:** id, tenant_id (RLS), name str, floor int nullable, specialty str nullable, total_beds int, is_active bool default True, created_at

**Bed:** id, tenant_id (RLS), ward_id (FK wards), bed_number str, status (available/occupied/maintenance/reserved), bed_type (standard/icu/isolation/pediatric/maternity), notes str nullable, updated_at. Unique constraint: (tenant_id, ward_id, bed_number)

**Admission:** id, tenant_id (RLS), patient_id (FK patients), bed_id (FK beds), encounter_id (FK encounters nullable), admitting_doctor_id (FK users), admitted_at datetime, discharged_at datetime nullable, discharge_type (routine/against_medical_advice/transfer/deceased) nullable, discharge_plan JSONB nullable, status (active/discharged/transferred), reason str, notes str nullable, created_at

**NursingNote:** id, tenant_id (RLS), admission_id (FK admissions), nurse_id (FK users), content text, note_type (assessment/intervention/evaluation/handoff/general), recorded_at datetime, created_at

### Service Methods
- `admit_patient(data)` — verify bed available, set bed occupied, create admission
- `discharge_patient(admission_id, discharge_data)` — generate discharge plan, set bed available
- `transfer_patient(admission_id, new_bed_id)` — move patient
- `get_bed_availability(ward_id)` — counts per status
- `get_ward_overview(tenant_id)` — all wards with bed counts
- `add_nursing_note(admission_id, content, note_type)` — record note
- `chart_vitals(admission_id, vitals_data)` — create Measurement records, publish MeasurementSaved events

### Endpoints (6)
- `POST /api/v1/admissions` — admit patient
- `GET /api/v1/beds` — bed availability
- `GET /api/v1/admissions/{id}` — admission details
- `POST /api/v1/admissions/{id}/nursing-notes` — add note
- `POST /api/v1/admissions/{id}/vitals` — chart vitals
- `POST /api/v1/admissions/{id}/discharge` — discharge

### RBAC: Admit/discharge = Doctor; Notes/vitals = Nurse; Bed status = Nurse, Doctor

### Files (~10): `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`, `service.py`, `service_nursing.py`, `router.py`, `README.md`

---

## TASK 15: FHIR API Module

**Write to:** `backend/app/modules/fhir_api_staging/`
**No migration needed** (reads/writes through existing tables)

### Service Methods
- `validate_resource(resource_type, fhir_json)` — validate FHIR R4, return OperationOutcome on failure
- `parse_to_internal(resource_type, fhir_json)` — FHIR to internal dict
- `print_to_fhir(resource_type, internal_record)` — internal to FHIR JSON
- `search(resource_type, params)` — FHIR search (_id, patient, date, status, code)

### Additional Files
- `validator.py` — FHIR R4 required field validation per resource type
- `search.py` — FHIR search parameter parsing
- `auth_oauth.py` — OAuth 2.0 client credentials (STUB — validates format only)
- `subscriptions.py` — Webhook subscription management (STUB — stores config, logs intent)
- `router_bulk.py` — `GET /fhir/r4/$export` bulk data export

### Supported Resources: Encounter, MedicationRequest, ServiceRequest, DiagnosticReport, Patient

### Endpoints (6)
- `GET /api/v1/fhir/r4/{resourceType}` — search
- `GET /api/v1/fhir/r4/{resourceType}/{id}` — read
- `POST /api/v1/fhir/r4/{resourceType}` — create
- `PUT /api/v1/fhir/r4/{resourceType}/{id}` — update
- `GET /api/v1/fhir/r4/$export` — bulk export (async, returns task_id)
- `POST /api/v1/fhir/r4/Subscription` — create webhook subscription

### RBAC: OAuth 2.0 for external; Doctor/Clinic_Admin for internal

### Files (~10): `__init__.py`, `service.py`, `validator.py`, `search.py`, `auth_oauth.py`, `subscriptions.py`, `router.py`, `router_bulk.py`, `schemas.py`, `README.md`

---

## TASK 16: Integrations Module

**Write to:** `backend/app/modules/integrations_staging/`
**Migration:** `backend/alembic/versions/0024_integrations_tables.py`

### Models

**ConnectorConfig:** id, tenant_id (RLS), connector_type (openmrs/dhis2/generic_fhir), name str, base_url str, auth_type (basic/oauth2/api_key), credentials JSONB (encrypted, NEVER logged), sync_direction (inbound/outbound/bidirectional), sync_schedule str nullable (cron), is_active bool, last_sync_at datetime nullable, created_by (FK users), created_at, updated_at

**SyncLog:** id, tenant_id (RLS), connector_id (FK connector_configs), direction (inbound/outbound), status (started/completed/failed/partial), records_processed int, records_succeeded int, records_failed int, error_summary str nullable (NO PHI), started_at datetime, completed_at datetime nullable, duration_ms int nullable

### Connector Stubs (log intent, don't make real HTTP calls)
- `connectors/openmrs.py` — pull_patients(), push_encounters(), resolve_conflict()
- `connectors/dhis2.py` — push_aggregate_data(), format_dhis2_payload()
- `connectors/generic_fhir.py` — sync_resource(), handle_bundle()

### SyncEngine
- `execute_sync(connector_id)` — orchestrate sync
- `resolve_conflict(local, remote)` — last-write-wins + audit trail
- `retry_with_backoff(func, max_retries=5)` — 30s, 2min, 8min, 30min, 2h

### Celery Tasks
- `run_sync_task(connector_id)` — async execution
- `scheduled_sync_check()` — periodic task checking schedules

### Endpoints (6)
- `POST /api/v1/integrations/connectors` — create config
- `GET /api/v1/integrations/connectors` — list
- `GET /api/v1/integrations/connectors/{id}` — details
- `PUT /api/v1/integrations/connectors/{id}` — update
- `POST /api/v1/integrations/connectors/{id}/sync` — trigger sync
- `GET /api/v1/integrations/connectors/{id}/logs` — sync history

### RBAC: All = Clinic_Admin, Super_Admin

### Files (~14): `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`, `service.py`, `sync_engine.py`, `connectors/__init__.py`, `connectors/openmrs.py`, `connectors/dhis2.py`, `connectors/generic_fhir.py`, `tasks.py`, `router.py`, `README.md`

---

## Coding Standards (MANDATORY — enforced at checkpoint)

1. **Heavy commenting** — every module/class/function has a docstring. Inline comments explain "why".
2. **150 line max per file** — split into multiple files as needed.
3. **No PHI in logs** — log UUIDs and metadata ONLY. Never patient names, measurements, insurance numbers, credentials.
4. **HIPAA headers** — `Cache-Control: no-store, no-cache, must-revalidate` + `Pragma: no-cache` on all PHI responses.
5. **Audit logging** — ALL mutations via `from app.modules.audit.service import AuditService`.
6. **Standard response envelope** — `{"success": true, "data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}`.
7. **Full type annotations** — every param and return typed.
8. **Async all the way** — all DB ops use `await`.
9. **`datetime.now(timezone.utc)`** — NEVER `datetime.utcnow()`.
10. **RLS on every tenant-scoped table** — use TenantMixin.
11. **No hard deletes** — soft delete or void only.
12. **FK via string syntax** — `ForeignKey("patients.id")` not model imports.
13. **Decimal for money** — NEVER float for currency. Use `Decimal(10,2)`.

---

## What NOT to Do

- Do NOT modify any existing files
- Do NOT write to production directories (only `*_staging/`)
- Do NOT implement real OpenMRS/DHIS2/external API calls (STUB only)
- Do NOT implement real OAuth token issuance (STUB — validate format only)
- Do NOT hard-delete data
- Do NOT put PHI in logs, errors, or exceptions
- Do NOT use `datetime.utcnow()`
- Do NOT use float for money
- Do NOT use `os.getcwd()` for paths
- Do NOT allocate large byte arrays (>1MB) in any code path

---

## Migration Chain

```
0021 (registration) -> 0022 (billing) -> 0023 (bed_management) -> 0024 (integrations)
```

FHIR API needs NO migration. Each migration must have correct `down_revision` and be reversible.

---

## Delivery Checklist

For EACH module:
- [ ] All files in correct staging directory
- [ ] Migration with correct numbering and chain (if applicable)
- [ ] All Python files pass: `python -c "import ast; ast.parse(open('file.py').read())"`
- [ ] All imports resolve (no circular deps)
- [ ] Every file under 150 lines (excluding comments/docstrings)
- [ ] Every function has a docstring
- [ ] No PHI in any log statement
- [ ] README.md present
- [ ] Patterns match existing modules (encounters, appointments, alerts)
- [ ] Enums in `enums.py`, exceptions in `exceptions.py`
- [ ] RLS policies in migrations
- [ ] Money uses Decimal, not float
- [ ] HIPAA headers on PHI responses
- [ ] `datetime.now(timezone.utc)` not `datetime.utcnow()`

---

## Expected Delivery

| Module | Files | ~LOC | Migration |
|--------|-------|------|-----------|
| Billing | 10 | 1,200-1,500 | 0022 |
| Bed Management | 10 | 1,200-1,500 | 0023 |
| FHIR API | 10 | 1,000-1,300 | None |
| Integrations | 14 | 1,400-1,700 | 0024 |
| **Total** | **~44** | **~5,000-6,000** | **3 migrations** |

---

## Reference Files to Study

- `backend/app/modules/encounters/service.py` — status transitions + discharge
- `backend/app/modules/encounters/fhir_mapper.py` — FHIR to/from pattern
- `backend/app/modules/appointments/service.py` — conflict detection
- `backend/app/modules/alerts/tasks.py` — Celery task with `get_async_session_context`
- `backend/app/modules/alerts/escalation.py` — time-based service logic
- `backend/app/core/events.py` — domain events
- `backend/alembic/versions/0021_registration_tables.py` — latest migration with RLS

---

## Note

Tasks 17-18 (Layer 3 tests + checkpoint) are handled by the main agent after delivery. You deliver the 4 modules only.
