# Builder Brief: EMR Layer 2 — Operational Features (Tasks 7-10)

## Overview

Build 4 EMR modules for PrescpHealth's hospital workflow. Write all code to **staging directories**. The main agent imports at the Layer 2 checkpoint.

These modules add operational clinical workflow features on top of the existing Layer 1 (encounters, prescriptions, lab orders).

---

## Infrastructure Context

- **Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 18, Redis, Celery
- **Database:** localhost:5432, database: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Branch:** `feat/emr-layer1`
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\`
- **Migration numbering:** 0018+ (0001-0017 are taken)

---

## Existing Patterns (read-only reference)

- `backend/app/modules/encounters/` — complete EMR module (models, service, enums, schemas, router, FHIR mapper)
- `backend/app/modules/prescriptions/` — service with DDI integration
- `backend/app/modules/lab_orders/` — service with status machine + measurement creation
- `backend/app/modules/alerts/` — recently imported (router, service, rules engine, escalation, dispatcher)
- `backend/app/core/base_model.py` — TenantMixin for RLS (all models use this)
- `backend/app/core/events.py` — domain event bus
- `backend/app/core/deps.py` — `get_db`, `get_current_user`, `get_tenant_id`, `get_request_id`
- `backend/app/modules/auth/rbac.py` — `require_role(Role.DOCTOR)`, `Role.NURSE`, `Role.CLINIC_ADMIN`
- `backend/app/modules/audit/service.py` — `AuditService(db)` with `log_action()`
- `backend/app/modules/patients/patient_model.py` — Patient model (you'll FK to this)

---

## TASK 7: Appointments Module

**Write to:** `backend/app/modules/appointments_staging/`
**Migration:** `backend/alembic/versions/0018_appointments_tables.py`

### Models

**Appointment:**
- id: UUID (PK)
- tenant_id: UUID (RLS)
- patient_id: UUID (FK patients)
- clinician_id: UUID (FK users)
- appointment_type: Enum (consultation, follow_up, procedure, screening, urgent)
- status: Enum (scheduled, confirmed, checked_in, in_progress, completed, cancelled, no_show)
- scheduled_start: datetime (UTC)
- scheduled_end: datetime (UTC)
- actual_start: datetime (nullable)
- actual_end: datetime (nullable)
- reason: str
- notes: str (nullable)
- cancellation_reason: str (nullable)
- is_recurring: bool (default False)
- recurrence_rule: JSONB (nullable — {frequency: "weekly", interval: 1, count: 8})
- parent_appointment_id: UUID (nullable — FK self, for recurring instances)
- created_by: UUID (FK users)
- created_at: datetime
- updated_at: datetime

**Waitlist:**
- id: UUID (PK)
- tenant_id: UUID (RLS)
- patient_id: UUID (FK patients)
- clinician_id: UUID (nullable — preferred clinician)
- appointment_type: Enum
- preferred_date_start: date
- preferred_date_end: date (nullable)
- preferred_time_start: time (nullable)
- preferred_time_end: time (nullable)
- priority: int (default 0, higher = more urgent)
- status: Enum (waiting, offered, booked, expired, cancelled)
- notes: str (nullable)
- created_at: datetime

### Key Constraint
- **Double-booking prevention** for same clinician: no two appointments can overlap in time for the same clinician_id. Enforce in service layer with a SELECT query checking for overlaps before INSERT.

### Indexes
- `(tenant_id, clinician_id, scheduled_start)`
- `(tenant_id, patient_id, status)`
- `(tenant_id, status, scheduled_start)` for upcoming appointments query

### Service Methods
- `book_appointment(data)` — check for double-booking, create appointment
- `reschedule(appointment_id, new_time)` — update time, check conflicts, record reason
- `cancel(appointment_id, reason)` — cancel, offer slot to waitlist
- `check_in(appointment_id)` — mark as checked_in
- `complete(appointment_id)` — mark as completed
- `generate_recurring(appointment_id, rule)` — create N future instances from recurrence rule
- `get_schedule(clinician_id, date_range)` — clinician's schedule
- `add_to_waitlist(data)` — add patient to waitlist
- `promote_from_waitlist(slot)` — offer freed slot to highest-priority waitlisted patient

### Endpoints (7)
- `POST /api/v1/appointments` — book new appointment
- `GET /api/v1/appointments` — list (filterable by clinician, patient, date range, status)
- `GET /api/v1/appointments/{id}` — get details
- `PUT /api/v1/appointments/{id}` — reschedule
- `DELETE /api/v1/appointments/{id}` — cancel (with reason)
- `POST /api/v1/appointments/waitlist` — add to waitlist
- `GET /api/v1/patients/{id}/appointments` — patient's appointment history

### RBAC
- Book/reschedule/cancel = Nurse, Clinic_Admin
- Read = all clinical roles (Doctor, Nurse, Clinic_Admin)

### Files to Create (~10)
- `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`
- `service.py`, `service_waitlist.py`, `service_recurrence.py`
- `router.py`, `README.md`

---

## TASK 8: Referrals Module

**Write to:** `backend/app/modules/referrals_staging/`
**Migration:** `backend/alembic/versions/0019_referrals_table.py`

### Models

**Referral:**
- id: UUID (PK)
- tenant_id: UUID (RLS)
- patient_id: UUID (FK patients)
- encounter_id: UUID (nullable, FK encounters)
- referring_clinician_id: UUID (FK users)
- receiving_clinician_id: UUID (nullable, FK users)
- specialty: str (e.g., "Cardiology", "Nephrology", "Endocrinology")
- urgency: Enum (routine, urgent, emergent)
- status: Enum (pending, accepted, scheduled, in_progress, completed, cancelled, declined)
- reason: str (clinical indication)
- clinical_summary: text (auto-generated from patient's recent data)
- referral_letter: JSONB (structured referral letter content)
- specialist_findings: text (nullable — filled on completion)
- specialist_recommendations: text (nullable)
- scheduled_date: date (nullable)
- completed_at: datetime (nullable)
- created_at: datetime
- updated_at: datetime

### Status Transitions (enforce in service)
- pending -> accepted, declined, cancelled
- accepted -> scheduled, cancelled
- scheduled -> in_progress, cancelled
- in_progress -> completed
- completed and cancelled are terminal

### Endpoints (5)
- `POST /api/v1/referrals` — create referral
- `GET /api/v1/referrals` — list (filterable)
- `GET /api/v1/referrals/{id}` — get details
- `PUT /api/v1/referrals/{id}/status` — update status
- `POST /api/v1/referrals/{id}/completion` — record specialist findings

### RBAC
- Create/complete = Doctor
- Read = Doctor, Nurse

### Files to Create (~8)
- `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`
- `service.py`, `router.py`, `README.md`

---

## TASK 9: Documents Module

**Write to:** `backend/app/modules/documents_staging/`
**Migration:** `backend/alembic/versions/0020_documents_table.py`

### Models

**Document:**
- id: UUID (PK)
- tenant_id: UUID (RLS)
- patient_id: UUID (FK patients)
- encounter_id: UUID (nullable, FK encounters)
- document_type: Enum (lab_report, radiology, discharge_summary, consent_form, referral_letter, clinical_note, imaging, other)
- title: str
- description: str (nullable)
- file_name: str (original filename)
- mime_type: str (validated against allowed set)
- file_size_bytes: int
- storage_path: str (S3 key or local path)
- storage_backend: str (default "local")
- is_encrypted: bool (default True)
- uploaded_by: UUID (FK users)
- uploaded_at: datetime
- metadata: JSONB (nullable)

### Allowed MIME Types
- application/pdf
- image/jpeg
- image/png
- image/tiff
- application/dicom

### Max File Size: 25 MB (25 * 1024 * 1024 bytes)

### Storage Abstraction (`storage.py`)
- `StorageBackend` abstract class (save, get, delete)
- `LocalStorageBackend` — stores files in `backend/uploads/{tenant_id}/{document_id}`
- `S3StorageBackend` — stub that raises NotImplementedError

### Endpoints (5)
- `POST /api/v1/documents` — upload (multipart/form-data)
- `GET /api/v1/documents` — list (filterable by patient, type, date)
- `GET /api/v1/documents/{id}` — get metadata
- `GET /api/v1/documents/{id}/download` — download file (streamed)
- `GET /api/v1/patients/{id}/documents` — patient's documents

### RBAC
- Upload = Doctor, Nurse, Clinic_Admin
- Read/download = Doctor, Nurse

### Files to Create (~9)
- `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`
- `storage.py`, `service.py`, `router.py`, `README.md`

---

## TASK 10: Registration Module

**Write to:** `backend/app/modules/registration_staging/`
**Migration:** `backend/alembic/versions/0021_registration_tables.py`

### Models

**Consent:**
- id: UUID (PK)
- tenant_id: UUID (RLS)
- patient_id: UUID (FK patients)
- consent_type: Enum (treatment, data_sharing, research, hipaa_notice, telehealth)
- version: str (consent form version)
- is_granted: bool
- granted_at: datetime
- expires_at: datetime (nullable)
- digital_signature: str (nullable — base64 encoded)
- witness_name: str (nullable)
- captured_by: UUID (FK users)
- revoked_at: datetime (nullable)
- revocation_reason: str (nullable)
- metadata: JSONB (nullable)

**IdentityVerification:**
- id: UUID (PK)
- tenant_id: UUID (RLS)
- patient_id: UUID (FK patients)
- verification_type: Enum (government_id, passport, insurance_card, biometric, other)
- document_number: str (nullable — stored encrypted, NOT logged)
- issuing_authority: str (nullable)
- expiry_date: date (nullable)
- is_verified: bool (default False)
- verified_by: UUID (nullable, FK users)
- verified_at: datetime (nullable)
- notes: str (nullable)
- created_at: datetime

### Service Methods

**RegistrationService:**
- `start_intake(data)` — create partial patient record (name + DOB only)
- `update_registration(patient_id, data)` — add fields incrementally
- `complete_registration(patient_id)` — validate required fields, set status Active
- `generate_mrn(tenant_id)` — unique MRN format: `MRN-{TENANT_SHORT}-{SEQUENCE}`

**ConsentService:**
- `capture_consent(patient_id, consent_data)` — store with digital signature
- `get_active_consents(patient_id)` — non-revoked, non-expired
- `revoke_consent(consent_id, reason)` — mark revoked
- `check_consent(patient_id, consent_type)` — returns True if active consent exists

### Endpoints (5)
- `POST /api/v1/registration/intake` — start new patient intake
- `PUT /api/v1/registration/{patient_id}` — update registration fields
- `POST /api/v1/registration/{patient_id}/consent` — capture consent
- `POST /api/v1/registration/{patient_id}/identity` — record identity verification
- `POST /api/v1/registration/{patient_id}/complete` — finalize registration

### RBAC
- All endpoints = Nurse, Clinic_Admin

### Files to Create (~9)
- `__init__.py`, `enums.py`, `exceptions.py`, `models.py`, `schemas.py`
- `service.py`, `service_consent.py`, `router.py`, `README.md`

---

## Coding Standards (MUST follow)

1. **Heavy commenting** — every function has a docstring
2. **150 line max per file** — split into multiple files
3. **No PHI in logs** — UUIDs only, never names/DOB/document numbers
4. **HIPAA headers** — `Cache-Control: no-store` on all PHI responses
5. **Audit logging** — all mutations via `from app.modules.audit.service import AuditService`
6. **Standard response envelope** — `{"success": true, "data": {...}, "meta": {...}}`
7. **Full type annotations**
8. **Async all the way**
9. **Use `datetime.now(timezone.utc)`** — NOT `datetime.utcnow()`
10. **RLS on every table with tenant_id**

---

## What NOT to Do

- Do NOT modify any existing files
- Do NOT write to production directories (only `*_staging/`)
- Do NOT implement real S3 uploads (use local filesystem stub)
- Do NOT implement real file encryption (stub — just mark `is_encrypted=True`)
- Do NOT hard-delete data
- Do NOT put PHI in logs or error messages
- Do NOT use `datetime.utcnow()`
- Do NOT use `os.getcwd()` for path resolution

---

## Migration Chain

```
0017 (background_tasks) -> 0018 (appointments) -> 0019 (referrals) -> 0020 (documents) -> 0021 (registration)
```

Each migration's `down_revision` must point to the previous one. All must be reversible.

---

## Cross-Module FK References

Use string syntax to avoid circular imports:
- `ForeignKey("patients.id")` — not `Patient.id`
- `ForeignKey("users.id")` — not `User.id`
- `ForeignKey("encounters.id")` — not `Encounter.id`

---

## Delivery Checklist

For EACH module:
- [ ] All files in correct staging directory
- [ ] Migration with correct numbering and down_revision chain
- [ ] All Python files pass syntax check
- [ ] Every file under 150 lines
- [ ] Every function has a docstring
- [ ] No PHI in any log statement
- [ ] README.md present
- [ ] Patterns match existing modules

---

## Expected Delivery

| Module | Files | ~LOC | Migration |
|--------|-------|------|-----------|
| Appointments | 10 | 1,200-1,500 | 0018 |
| Referrals | 8 | 800-1,000 | 0019 |
| Documents | 9 | 900-1,100 | 0020 |
| Registration | 9 | 900-1,100 | 0021 |
| **Total** | **36** | **~4,000-4,700** | **4 migrations** |

---

## Note

Tasks 11-12 (Layer 2 property/unit tests + checkpoint) are handled by the main agent after import. You just deliver the 4 modules.
