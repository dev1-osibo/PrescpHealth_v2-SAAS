# QA Tester Brief: EMR Layer 2 Checkpoint — Coverage Push

## Mission

Write tests for 4 newly imported EMR Layer 2 modules to push coverage from **67% → 85%+**. These modules are at low coverage because only property tests and basic unit tests exist — no router tests, no deep service path tests.

---

## Current State

- **Branch:** `feat/emr-layer1`
- **Tests:** 1,255 passing, 0 failures
- **Coverage:** 67% (7,787 total statements, ~5,217 covered)
- **Target:** 85% (need ~1,400 more statements covered)
- **Database:** PostgreSQL at localhost:5432, db: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\backend`
- **Run tests from:** `backend/` directory (NOT project root)

---

## Modules Needing Tests

| Module | Statements | Current Coverage | Target | Priority |
|--------|-----------|-----------------|--------|----------|
| `app.modules.appointments` | ~350 | ~20% | 80%+ | HIGH |
| `app.modules.documents` | ~280 | ~25% | 80%+ | HIGH |
| `app.modules.referrals` | ~220 | ~20% | 80%+ | MEDIUM |
| `app.modules.registration` | ~250 | ~20% | 80%+ | MEDIUM |
| `app.modules.encounters` (router_detail) | ~102 | 61% | 85%+ | MEDIUM |
| `app.modules.lab_orders` (router, service) | ~180 | 74-79% | 85%+ | LOW |

**Strategy:** Focus on appointments and documents first (highest statement count), then referrals and registration.

---

## What to Write

### 1. Appointments Module (`backend/tests/unit/test_appointments_coverage.py`)

**AppointmentService:**
- `book_appointment()` — happy path (no conflict, appointment created)
- `reschedule()` — updates scheduled_start/end, records reason
- `cancel()` — sets CANCELLED, sets cancellation_reason
- `check_in()` — valid from SCHEDULED, sets CHECKED_IN
- `complete()` — valid from CHECKED_IN/IN_PROGRESS, sets COMPLETED
- `get_schedule()` — returns appointments for clinician within date range

**WaitlistService:**
- `add_to_waitlist()` — creates waitlist entry with correct fields
- `promote_from_waitlist()` — finds highest priority waiting entry, sets to OFFERED

**RecurrenceService:**
- `generate_recurring()` — creates correct number of children with parent_appointment_id set

**Schemas:** All request/response schemas validate correctly
**Enums:** All enum values present (AppointmentStatus, AppointmentType, WaitlistStatus)
**Exceptions:** All exception types instantiate correctly

### 2. Documents Module (`backend/tests/unit/test_documents_coverage.py`)

**DocumentService:**
- `upload_document()` — happy path (valid MIME + valid size, document created + file stored)
- `get_document()` — returns document metadata by ID
- `download_document()` — calls storage.get() and returns bytes
- `search_documents()` — filters by patient_id, document_type, date range
- `delete_document()` — soft deletes (marks as deleted, doesn't remove file)

**StorageBackend (LocalStorageBackend):**
- `save()` — returns storage path
- `get()` — returns file bytes (mock filesystem)
- `delete()` — marks file as deleted

**Schemas:** UploadDocumentRequest, DocumentResponse, DocumentListResponse
**Enums:** DocumentType, ALLOWED_MIME_TYPES, MAX_FILE_SIZE_BYTES

### 3. Referrals Module (`backend/tests/unit/test_referrals_coverage.py`)

**ReferralService:**
- `create_referral()` — sets status PENDING, stores clinical_summary
- `update_status()` — all valid transitions: pending to accepted, accepted to scheduled, scheduled to in_progress, in_progress to completed
- `update_status()` — all invalid transitions raise InvalidStatusTransitionError
- `complete_referral()` — sets specialist_findings, specialist_recommendations, completed_at
- `list_referrals()` — returns referrals filtered by tenant_id
- `get_referral()` — returns single referral by ID

**Schemas:** CreateReferralRequest, ReferralResponse, UpdateStatusRequest
**Enums:** ReferralStatus, ReferralUrgency, VALID_TRANSITIONS

### 4. Registration Module (`backend/tests/unit/test_registration_coverage.py`)

**RegistrationService:**
- `start_intake()` — creates patient record with partial data
- `update_registration()` — updates specified fields
- `complete_registration()` — validates required fields, sets status Active
- `complete_registration()` — raises RegistrationIncompleteError if fields missing
- `generate_mrn()` — returns MRN in format MRN-{TENANT_SHORT}-{PADDED_SEQ}

**ConsentService:**
- `capture_consent()` — creates consent record with digital_signature, consent_type, version
- `get_active_consents()` — returns non-revoked, non-expired consents
- `revoke_consent()` — sets revoked_at and revocation_reason
- `revoke_consent()` — raises ConsentAlreadyRevokedError for already-revoked
- `check_consent()` — returns True if active consent exists for type

**Schemas:** IntakeRequest, ConsentRequest, RegistrationResponse
**Enums:** ConsentType, VerificationType

### 5. Encounters Router Gap (`backend/tests/unit/test_encounters_router_coverage.py`)

The encounters `router_detail.py` is at 61%. Write tests for:
- SOAP note endpoints (POST, GET, PUT)
- Diagnosis endpoints (POST, GET)
- Procedure endpoints (POST)
- Discharge endpoint (POST)

Verify: correct HTTP status codes, RBAC, HIPAA headers, audit logging

---

## Test Writing Rules

1. **No real DB required** — mock `AsyncSession` with `AsyncMock`/`MagicMock`
2. **Use `pytest` + `pytest-asyncio`** for async tests
3. **Every test must have a docstring**
4. **No PHI in test data** — use synthetic names like "Test Patient Alpha"
5. **Don't modify existing test files** — create new files only
6. **File naming:** `test_{module}_coverage.py` in `backend/tests/unit/`
7. **Mark async tests:** `@pytest.mark.asyncio`
8. **Do NOT use `os.getcwd()` for path resolution**
9. **Do NOT allocate large byte arrays** (>1MB) in tests — use small synthetic data
10. **Patch audit at module level:** `patch("app.modules.{module}.service._audit", MagicMock(log_action=AsyncMock()))`

---

## Running Tests

```bash
# Run from backend/ directory

# Run just the new tests
python -m pytest tests/unit/test_appointments_coverage.py tests/unit/test_documents_coverage.py tests/unit/test_referrals_coverage.py tests/unit/test_registration_coverage.py tests/unit/test_encounters_router_coverage.py -v

# Run unit + integration with coverage (fastest way to check %)
python -m pytest tests/unit/ tests/integration/ --cov=app --cov-config=.coveragerc -q --tb=line

# Check specific module
python -m pytest tests/ --cov=app.modules.appointments --cov-report=term-missing -q
```

---

## Coverage Target Math

Current: ~5,217 / 7,787 = 67%
Target: 6,619 / 7,787 = 85%
Need: ~1,400 more statements covered

Estimated per module (at 70% coverage of uncovered lines):
- Appointments: ~250 statements
- Documents: ~200 statements
- Referrals: ~155 statements
- Registration: ~175 statements
- Encounters router: ~40 statements
- Other gaps: ~100 statements
- Total: ~920

Write MORE tests if initial pass doesn't hit 85%. Push hard on appointments and documents.

---

## Delivery

When done, report:
1. Number of tests written per file
2. Number passing/failing
3. New coverage percentage
4. Any bugs found in production code (list file:line + description)

Do NOT fix production code bugs — just report them.

---

## Important Notes

- `.coveragerc` excludes `*_staging` — import from `app.modules.appointments` (production)
- Existing tests in `test_appointments_unit.py`, `test_documents_unit.py`, `test_referrals_unit.py`, `test_registration_unit.py` cover basic flows — extend, don't duplicate
- Audit service patching: `patch("app.modules.{module}.service._audit", MagicMock(log_action=AsyncMock()))`
- Some services use module-level instances — patch at module level
- If import errors occur, report as bug (don't fix)
