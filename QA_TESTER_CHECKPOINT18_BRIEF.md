# QA Tester Brief: EMR Layer 3 Checkpoint (Task 18) — Coverage Push

## Mission

Write tests for 4 newly imported EMR Layer 3 modules to push coverage to **85%+**. These modules have basic property + unit tests but need deeper service path coverage.

---

## Current State

- **Branch:** `feat/emr-layer1`
- **Tests:** ~1,230 unit tests passing, 0 failures
- **Target:** 85% overall coverage
- **Database:** PostgreSQL at localhost:5432, db: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\backend`
- **Run tests from:** `backend/` directory

---

## Modules Needing Coverage

| Module | Current Coverage | Target | Priority |
|--------|-----------------|--------|----------|
| `app.modules.billing` | ~20% | 75%+ | HIGH |
| `app.modules.bed_management` | ~20% | 75%+ | HIGH |
| `app.modules.fhir_api` | ~25% | 75%+ | HIGH |
| `app.modules.integrations` | ~20% | 75%+ | MEDIUM |

---

## What to Write

### 1. Billing Coverage (`backend/tests/unit/test_billing_coverage.py`)

**BillingService additional paths:**
- `list_invoices()` — returns filtered list by tenant
- `get_invoice_detail()` — returns invoice with line items and payments
- `get_invoice_detail()` — raises InvoiceNotFoundError for missing invoice
- Invoice number generation (auto-incremented per tenant)

**ClaimsService additional paths:**
- `list_claims()` — returns filtered list
- Claim approval: updates status to APPROVED, sets approved_amount
- Partial approval: sets PARTIALLY_APPROVED with partial amount

**Schemas:** All request/response schemas validate correctly, reject negative amounts, reject invalid payment methods

**Enums:** InvoiceStatus, ClaimStatus, ItemType, PaymentMethod — all values present

**Exceptions:** InvoiceNotFoundError, InvoiceAlreadyVoidError, ClaimNotFoundError, InvalidPaymentError

### 2. Bed Management Coverage (`backend/tests/unit/test_bed_management_coverage.py`)

**BedManagementService additional paths:**
- `get_ward_overview()` — returns all wards with bed counts
- `list_active_admissions()` — returns currently active admissions
- Discharge already-discharged raises error
- Transfer to occupied bed raises error

**NursingService additional paths:**
- `get_nursing_notes()` — returns notes ordered by recorded_at
- Chart vitals with multiple measurement types
- Nursing note to discharged admission raises error

**Schemas:** AdmitPatientRequest, DischargeRequest, TransferRequest, NursingNoteRequest, ChartVitalsRequest, all responses

**Enums:** BedStatus, AdmissionStatus, DischargeType, NoteType, BedType

**Exceptions:** BedNotAvailableError, AdmissionNotFoundError, AdmissionAlreadyDischargedError, WardNotFoundError

### 3. FHIR API Coverage (`backend/tests/unit/test_fhir_api_coverage.py`)

**FHIRService:**
- `print_to_fhir()` — encounter and prescription conversion
- `parse_to_internal()` — FHIR to internal dict
- Unsupported resource type raises error

**FHIRValidator:**
- Validate MedicationRequest, ServiceRequest, Patient (valid + invalid)

**FHIRSearch:**
- Combined parameters, empty results, date 'le' prefix

**Subscriptions:**
- create_subscription, list_subscriptions, invalid callback rejected

**Schemas:** FHIRSearchResponse, OperationOutcome, BulkExportResponse

### 4. Integrations Coverage (`backend/tests/unit/test_integrations_coverage.py`)

**IntegrationService:**
- `trigger_sync()` — enqueues task, returns task_id
- `get_sync_logs()` — paginated logs
- Trigger on inactive connector raises error

**SyncEngine:**
- `execute_sync()` — success + failure paths, SyncLog created
- Conflict resolution edge cases

**Connectors (stubs):**
- OpenMRS pull_patients, push_encounters
- DHIS2 push_aggregate_data
- GenericFHIR sync_resource

**Schemas:** CreateConnectorRequest, ConnectorResponse, SyncLogResponse, TriggerSyncResponse

**Enums:** ConnectorType, AuthType, SyncDirection, SyncStatus

**Exceptions:** ConnectorNotFoundError, SyncInProgressError, ConnectorInactiveError

---

## Test Writing Rules

1. **No real DB** — mock AsyncSession with AsyncMock/MagicMock
2. **pytest + pytest-asyncio** for async tests
3. **Every test has a docstring**
4. **No PHI** — synthetic data only
5. **New files only** — don't modify existing tests
6. **File naming:** `test_{module}_coverage.py` in `backend/tests/unit/`
7. **@pytest.mark.asyncio** on async tests
8. **Do NOT allocate >1MB** byte arrays
9. **Use Decimal for money** (never float)
10. **Patch audit:** `patch("app.modules.{module}.service._audit", MagicMock(log=AsyncMock()))`

---

## Running Tests

```bash
# New tests only
python -m pytest tests/unit/test_billing_coverage.py tests/unit/test_bed_management_coverage.py tests/unit/test_fhir_api_coverage.py tests/unit/test_integrations_coverage.py -v

# Full unit + integration with coverage
python -m pytest tests/unit/ tests/integration/ --cov=app --cov-config=.coveragerc -q --tb=line
```

---

## Delivery

Report:
1. Tests written per file
2. Pass/fail count
3. Coverage percentage
4. Any bugs found (file:line + description) — do NOT fix

---

## Important Notes

- `.coveragerc` excludes `*_staging` — import from production paths
- Existing tests cover basic flows — extend to uncovered paths, don't duplicate
- FHIR API has no DB models — calls through existing FHIR mappers
- Integrations connectors are STUBS — test stub return values
- Money always uses `from decimal import Decimal`
- Audit patching: `patch("app.modules.{module}.service._audit", MagicMock(log=AsyncMock()))`
