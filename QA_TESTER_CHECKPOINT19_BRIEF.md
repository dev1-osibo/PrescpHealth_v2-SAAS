# QA Tester Brief: Checkpoint 19 — Coverage Push

## Mission

Write tests for 5 newly imported modules to push coverage from **68% → 85%+**. All modules are at 0% coverage currently. You need to cover ~1,100 of the ~1,645 new statements to hit 85% overall.

---

## Current State

- **Branch:** `feat/emr-layer1`
- **Tests:** 832 passing, 0 failures
- **Coverage:** 68% (6,643 total statements, 4,500 covered)
- **Target:** 85% (need ~1,100 more statements covered)
- **Database:** PostgreSQL at localhost:5432, db: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\backend`
- **Run tests from:** `backend/` directory (NOT project root)

---

## Modules Needing Tests (All at 0%)

| Module | Statements | Priority | Difficulty |
|--------|-----------|----------|------------|
| `app.modules.alerts` | ~460 | HIGH | Medium (event-driven logic, escalation) |
| `app.modules.reports` | ~312 | MEDIUM | Easy (service stubs, CSV logic) |
| `app.modules.population` | ~243 | MEDIUM | Medium (aggregation queries) |
| `app.modules.admin` | ~367 | LOW | Easy (CRUD, no complex logic) |
| `app.modules.task_status` | ~109 | LOW | Very Easy (simple CRUD) |
| `app.core.tasks_tracker` | ~59 | LOW | Very Easy |

**Strategy:** Focus on alerts (highest statement count) and reports/population for maximum coverage gain.

---

## What to Write

### 1. Alerts Module Tests (`backend/tests/unit/test_alerts_module.py`)

Test the following (don't need real DB — mock SQLAlchemy session):

**Enums (already partially tested — extend):**
- All enum values present and correct

**Rules Engine:**
- `evaluate_measurement()` — threshold above/below triggers correctly
- `evaluate_risk_score()` — stratum change detection
- `evaluate_forecast()` — projected threshold crossing detection
- Edge cases: no thresholds configured, inactive thresholds ignored

**Escalation Service:**
- Escalation level progression (0 to 1 to 2)
- Timing logic (15min nurse, 30min doctor)
- EscalationRecord creation

**Dispatcher:**
- `dispatch()` calls correct channel methods
- `send_in_app()` always succeeds
- Stubbed email/SMS return expected status

**Service:**
- `create_alert()` creates record with correct fields
- `acknowledge()` sets acknowledged_at, acknowledged_by
- `configure_threshold()` validation

**Schemas:**
- Valid alert response serialization
- ConfigureThresholdRequest validation (reject invalid)
- AcknowledgeAlertRequest accepts notes

### 2. Reports Module Tests (`backend/tests/unit/test_reports_module.py`)

**CSV Exporter:**
- `export_measurements_csv()` produces valid CSV headers
- `export_population_csv()` produces valid CSV headers
- Empty data produces header-only CSV

**PDF Builder:**
- `build_clinical_pdf()` returns bytes (or placeholder)
- `build_referral_pdf()` returns bytes (or placeholder)
- Section builders called with correct data

**Service:**
- `generate_clinical_report()` enqueues Celery task
- `generate_referral_letter()` enqueues Celery task
- `stream_measurements_csv()` returns StreamingResponse

**Schemas:**
- ReportRequest validation
- ReferralRequest validation
- ReportTaskResponse structure

### 3. Population Module Tests (`backend/tests/unit/test_population_module.py`)

**Service:**
- `get_dashboard_metrics()` returns expected structure
- `get_watchlist()` filters High/Critical only
- `get_trends()` accepts valid time windows (1m, 3m, 6m, 12m)
- Rejects invalid time windows

**Schemas:**
- DashboardResponse structure
- WatchlistItem validation
- TrendDataPoint validation

**Models:**
- CachedPopulationMetric instantiation

### 4. Admin Module Tests (`backend/tests/unit/test_admin_module.py`)

**Service Tenant:**
- `create_tenant()` generates UUID
- `list_tenants()` returns list
- `update_tenant_settings()` validates settings

**Service Model:**
- `deploy_model()` records version metadata
- `rollback_model()` sets previous version active
- `get_model_metrics()` returns metric structure

**Schemas:**
- CreateTenantRequest validation
- DeployModelRequest validation
- TenantSettingsResponse structure

**Exceptions:**
- All exception types instantiate correctly
- Error codes are correct

### 5. Task Status Module Tests (`backend/tests/unit/test_task_status_module.py`)

**BackgroundTaskTracker (core utility):**
- `create_task()` returns UUID
- `update_status()` changes status field
- `mark_retry()` increments retry count
- Status transitions: pending to running to completed
- Status transitions: pending to running to failed

**Service:**
- `get_task_status()` returns correct fields
- Not-found raises appropriate error

**Schemas:**
- TaskStatusResponse validation

---

## Test Writing Rules

1. **No real DB required for unit tests** — mock `AsyncSession` with `AsyncMock`/`MagicMock`
2. **Use `pytest` + `pytest-asyncio`** for async tests
3. **Every test must have a docstring** explaining what it validates
4. **No PHI in test data** — use synthetic names like "Test Patient Alpha"
5. **Don't modify existing test files** — create new files only
6. **File naming:** `test_{module_name}_module.py` in `backend/tests/unit/`
7. **Mark async tests:** `@pytest.mark.asyncio`
8. **Do NOT use `os.getcwd()` for path resolution** — use `__file__`-relative if needed

---

## Running Tests

```bash
# Run from backend/ directory
cd backend

# Run just the new tests
python -m pytest tests/unit/test_alerts_module.py tests/unit/test_reports_module.py tests/unit/test_population_module.py tests/unit/test_admin_module.py tests/unit/test_task_status_module.py -v

# Run full suite with coverage
python -m pytest tests/ --cov=app --cov-config=.coveragerc -q --tb=line

# Check specific module coverage
python -m pytest tests/ --cov=app.modules.alerts --cov-config=.coveragerc --cov-report=term-missing -q
```

---

## Import Patterns for Mocking

```python
# For service tests — mock the DB session
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
import pytest

@pytest.mark.asyncio
async def test_something():
    """Docstring explaining the test."""
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        scalars=MagicMock(return_value=MagicMock(
            all=MagicMock(return_value=[])
        ))
    ))
    
    from app.modules.alerts.service import AlertService
    service = AlertService(db=mock_db, tenant_id=uuid.uuid4())
    # test the method...
```

```python
# For schema tests — just instantiate Pydantic models
from app.modules.alerts.schemas import ConfigureThresholdRequest
from pydantic import ValidationError
import pytest

def test_threshold_request_valid():
    """ConfigureThresholdRequest accepts valid threshold config."""
    req = ConfigureThresholdRequest(
        measurement_type="systolic_bp",
        condition="above",
        threshold_value=180.0,
        severity="critical",
    )
    assert req.threshold_value == 180.0

def test_threshold_request_rejects_invalid():
    """ConfigureThresholdRequest rejects missing required fields."""
    with pytest.raises(ValidationError):
        ConfigureThresholdRequest(condition="above")
```

```python
# For enum tests — verify values exist
from app.modules.alerts.enums import AlertType, AlertSeverity

def test_alert_type_values():
    """All alert types have expected string values."""
    assert AlertType.THRESHOLD_BREACH.value == "threshold_breach"
    assert AlertType.RISK_CRITICAL.value == "risk_critical"
```

```python
# For exception tests
from app.modules.admin.exceptions import AdminError, TenantNotFoundError

def test_tenant_not_found_error():
    """TenantNotFoundError stores tenant_id."""
    err = TenantNotFoundError("00000000-0000-0000-0000-000000000001")
    assert "00000000" in str(err)
```

---

## Coverage Target Math

Current: 4,500 / 6,643 = 68%
Target: 5,647 / 6,643 = 85%
Need: ~1,147 more statements covered

Estimated coverage gain per module if well-tested:
- Alerts: ~300 statements (65% of 460)
- Reports: ~200 statements (65% of 312)
- Population: ~160 statements (65% of 243)
- Admin: ~240 statements (65% of 367)
- Task Status: ~90 statements (80% of 109)
- Tasks Tracker: ~45 statements (75% of 59)

Total estimated: ~1,035 — gets us to ~83%. Push hard on alerts + reports to hit 85%.

---

## Delivery

When done, report:
1. Number of tests written per module
2. Number passing/failing
3. New coverage percentage (run: `python -m pytest tests/ --cov=app --cov-config=.coveragerc -q`)
4. Any bugs found in production code (list file:line + description)

Do NOT fix production code bugs — just report them. The main agent handles fixes.

---

## Important Notes

- The `.coveragerc` at `backend/.coveragerc` already excludes `*_staging` directories — your tests import from `app.modules.alerts` (production), not `app.modules.alerts_staging`
- The existing test file `backend/tests/unit/test_alerts_staging.py` already covers basic enum/exception/schema tests for alerts — don't duplicate those, extend them
- If you encounter import errors, the most likely cause is a missing function or wrong path — report it as a bug, don't fix
- All services expect `db` (AsyncSession) and `tenant_id` (UUID) as constructor args
