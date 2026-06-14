# Builder Brief: Task 14 — Alert and Notification System

## Your Mission

Build the Alert and Notification System module for PrescpHealth. Write all code to the **staging directory**: `backend/app/modules/alerts_staging/`. The main agent will review and import into `backend/app/modules/alerts/` at the next checkpoint.

---

## Infrastructure Context

- **Stack:** Python 3.14, FastAPI, SQLAlchemy 2.0 (async), PostgreSQL 18, Redis, Celery
- **Database:** localhost:5432, database: `prescphealth_test`, user: `postgres`, password: `2026victory`
- **Redis:** localhost:6379
- **Branch:** `feat/emr-layer1`
- **Working directory:** `C:\Users\babas\Dev_Projects\PrescpHealth\`

---

## What Already Exists (DO NOT modify these — read-only reference)

### Domain Events (subscribe to these in your module)
Located at `backend/app/core/events.py`:
- `MeasurementSaved(patient_id, tenant_id, measurement_type, value, recorded_at)`
- `RiskScoreComputed(patient_id, tenant_id, disease, score, stratum)`
- `ForecastCompleted(patient_id, forecast_id)`
- `HealthStatusChanged(patient_id, tenant_id, change_type, details)`

### Existing Patterns (follow these exactly)
- `backend/app/core/base_model.py` — TenantMixin for RLS
- `backend/app/core/events.py` — EventBus with `publish()` and `subscribe()`
- `backend/app/core/deps.py` — `get_db`, `get_current_user`, `get_tenant_id`, `get_request_id`
- `backend/app/modules/auth/rbac.py` — `require_role(Role.DOCTOR)` etc.
- `backend/app/modules/audit/service.py` — `AuditService(db)` with `log_action()`
- `backend/app/modules/risk_engine/` — example of a complete module (models, service, tasks, schemas, router)

### Alembic Migration Numbering
Next available migration number: **0015** (0001-0014 are taken)

---

## Requirements (from spec)

### Requirement 11: Alert and Notification System

1. THE Alert_System SHALL support configurable alert thresholds per Patient and per disease, settable by Doctors and Clinic_Admins.
2. THE Alert_System SHALL deliver alerts via the following channels: in-app notification, email (via SendGrid), SMS (via Twilio), and WhatsApp.
3. WHEN a validated Measurement causes a Risk_Score to enter the Critical stratum, THE Alert_System SHALL dispatch a Critical alert to the assigned Clinician within 60 seconds via all configured channels.
4. WHEN a forecast-based alert is generated, THE Alert_System SHALL include the forecasted metric, the projected threshold-crossing date, and the Confidence_Interval in the alert payload.
5. THE Alert_System SHALL support alert escalation: if a Nurse does not acknowledge a Critical alert within 15 minutes, escalate to Doctor; if Doctor does not acknowledge within 30 minutes, escalate to Clinic_Admin.
6. WHEN a Clinician acknowledges an alert, record the acknowledging user's identity, timestamp, and any notes in the Audit_Log.
7. THE Alert_System SHALL support a "missed follow-up" alert type: WHEN a Patient has no new Measurements within a Clinician-configured interval, notify the assigned Clinician.
8. THE Platform SHALL display an alert history per Patient showing all past alerts, their severity, dispatch channel, acknowledgment status, and resolution notes.

### Resilience Requirements (from Requirement 21)
- WHEN SendGrid is unavailable, queue email notifications and retry delivery for up to 24 hours before marking as failed.
- WHEN Twilio is unavailable, queue SMS notifications and retry delivery for up to 6 hours before marking as failed.

---

## Files to Create

Write ALL files to: `backend/app/modules/alerts_staging/`

### 1. `__init__.py`
- Module exports

### 2. `models.py` (~100-130 lines)
SQLAlchemy models:

**Alert:**
- id: UUID (PK)
- tenant_id: UUID (FK, RLS)
- patient_id: UUID (FK)
- alert_type: Enum (threshold_breach, risk_critical, forecast_warning, missed_followup, drug_interaction)
- severity: Enum (critical, high, moderate, low, info)
- title: str
- message: str
- payload: JSONB (structured data — risk scores, measurements, forecast data)
- status: Enum (active, acknowledged, escalated, resolved, expired)
- created_at: datetime
- acknowledged_at: datetime (nullable)
- acknowledged_by: UUID (nullable, FK users)
- acknowledgment_notes: str (nullable)
- escalation_level: int (default 0: 0=initial, 1=escalated to doctor, 2=escalated to admin)
- escalated_at: datetime (nullable)
- resolved_at: datetime (nullable)
- channels_dispatched: JSONB (e.g. ["in_app", "email", "sms"])
- dispatch_status: JSONB (e.g. {"email": "sent", "sms": "failed_retry_2"})

**AlertThreshold:**
- id: UUID (PK)
- tenant_id: UUID (FK, RLS)
- patient_id: UUID (nullable — NULL means tenant-wide default)
- measurement_type: str (nullable — for measurement-based thresholds)
- disease: str (nullable — for risk-score-based thresholds)
- condition: Enum (above, below, enters_stratum)
- threshold_value: float (nullable)
- target_stratum: str (nullable — for enters_stratum condition)
- severity: Enum
- is_active: bool (default True)
- created_by: UUID (FK users)
- created_at: datetime
- updated_at: datetime

**EscalationRecord:**
- id: UUID (PK)
- tenant_id: UUID (FK, RLS)
- alert_id: UUID (FK alerts)
- from_level: int
- to_level: int
- escalated_at: datetime
- target_user_id: UUID (FK users)
- reason: str (e.g. "unacknowledged_timeout")

### 3. `enums.py` (~40 lines)
- AlertType, AlertSeverity, AlertStatus, ThresholdCondition, DispatchChannel enums

### 4. `service.py` (~130-150 lines)
`AlertService` class:
- `evaluate_thresholds(patient_id, event)` — check event against thresholds, generate alerts
- `create_alert(data)` — create alert record, enqueue dispatch task
- `acknowledge(alert_id, user_id, notes)` — acknowledge + audit log
- `get_patient_alerts(patient_id, status_filter, limit)` — paginated alert history
- `get_unacknowledged(tenant_id)` — for dashboard/overview
- `configure_threshold(data)` — create/update threshold configuration

### 5. `rules_engine.py` (~100-120 lines)
`AlertRulesEngine` class:
- `evaluate_measurement(patient_id, measurement_type, value)` — check against thresholds
- `evaluate_risk_score(patient_id, disease, score, stratum)` — check stratum transitions
- `evaluate_forecast(patient_id, forecast_data)` — check for projected threshold crossings
- `check_missed_followup(patient_id)` — check if measurements are overdue
- Subscribe to domain events: MeasurementSaved, RiskScoreComputed, ForecastCompleted

### 6. `dispatcher.py` (~100-120 lines)
`AlertDispatcher` class:
- `dispatch(alert_id, channels)` — orchestrate multi-channel delivery
- `send_in_app(alert)` — store for in-app notification (always succeeds)
- `send_email(alert, recipient)` — call SendGrid API (STUB: log + mark dispatched)
- `send_sms(alert, recipient)` — call Twilio API (STUB: log + mark dispatched)
- `send_whatsapp(alert, recipient)` — call Twilio WhatsApp (STUB: log + mark dispatched)

NOTE: For external services (SendGrid, Twilio), implement as stubs that LOG the intent and mark as dispatched. Real integration comes later. The important thing is the interface and retry logic.

### 7. `escalation.py` (~80-100 lines)
`EscalationService` class:
- `check_and_escalate()` — find unacknowledged critical alerts past timeout, escalate
- `escalate_alert(alert_id)` — bump escalation level, create EscalationRecord, re-dispatch
- Escalation chain: Nurse (15min) → Doctor (30min) → Clinic_Admin

### 8. `tasks.py` (~80-100 lines)
Celery tasks:
- `dispatch_alert_task(alert_id, channels)` — async alert dispatch with retry
- `check_escalations_task()` — periodic task (beat schedule, every 5 minutes)
- `check_missed_followups_task(tenant_id)` — periodic task (daily)
- Retry config: email=24h window (backoff 30s, 2min, 8min, 30min), SMS=6h window

### 9. `schemas.py` (~80-100 lines)
Pydantic schemas:
- `AlertResponse` — full alert with all fields
- `AlertListResponse` — paginated list
- `AcknowledgeAlertRequest` — notes field
- `ConfigureThresholdRequest` — threshold configuration
- `ThresholdResponse` — configured threshold
- Standard response envelope (success, data, meta)

### 10. `router.py` (~100-120 lines)
FastAPI endpoints:
- `GET /api/v1/alerts` — list alerts for current tenant (filterable by status, severity, patient)
- `GET /api/v1/patients/{patient_id}/alerts` — patient-specific alert history
- `PUT /api/v1/alerts/{alert_id}/acknowledge` — acknowledge an alert
- `GET /api/v1/alerts/unacknowledged` — dashboard: all unacknowledged alerts
- `POST /api/v1/patients/{patient_id}/alert-thresholds` — configure threshold
- `GET /api/v1/patients/{patient_id}/alert-thresholds` — list configured thresholds
- `DELETE /api/v1/alert-thresholds/{threshold_id}` — remove threshold

RBAC:
- View alerts = Doctor, Nurse, Clinic_Admin
- Acknowledge = Doctor, Nurse
- Configure thresholds = Doctor, Clinic_Admin

### 11. `exceptions.py` (~30-40 lines)
- `AlertError` (base)
- `AlertNotFoundError`
- `ThresholdConfigurationError`
- `DispatchFailedError`
- `EscalationError`

### 12. `README.md` (~200 lines)
Module documentation following project conventions.

---

## Alembic Migration

Create: `backend/alembic/versions/0015_alert_system_tables.py`

Tables:
- `alerts` (with RLS policy on tenant_id)
- `alert_thresholds` (with RLS policy on tenant_id)
- `escalation_records` (with RLS policy on tenant_id)

Indexes:
- `(tenant_id, patient_id, status)` on alerts
- `(tenant_id, status, severity, created_at DESC)` on alerts
- `(tenant_id, patient_id, is_active)` on alert_thresholds
- `(alert_id)` on escalation_records

RLS policies: Same pattern as all other tenant-scoped tables. Look at `0011_risk_engine_tables.py` for the exact pattern.

---

## Coding Standards (MUST follow)

1. **Heavy commenting** — every function has a docstring, inline comments explain "why"
2. **150 line max per file** — split into multiple files if needed
3. **No PHI in logs** — log patient_id (UUID), alert_id, severity — NEVER patient names, measurements, or risk values
4. **HIPAA headers** — `Cache-Control: no-store` on all responses containing PHI
5. **Audit logging** — all mutations (create alert, acknowledge, configure threshold) logged via AuditService
6. **Standard response envelope** — `{"success": true, "data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}`
7. **Exact version imports** — use same import patterns as existing modules
8. **Type annotations** — full type hints on all functions
9. **Async all the way** — all DB operations use `await`, all services are async
10. **Use `datetime.now(timezone.utc)`** — NOT `datetime.utcnow()` (deprecated in Python 3.12+)

---

## What NOT to Do

- Do NOT modify any existing files
- Do NOT write to `backend/app/modules/alerts/` (that's the production location — main agent imports later)
- Do NOT implement actual SendGrid/Twilio API calls (use stub implementations that log the intent)
- Do NOT hard-delete data (soft delete only)
- Do NOT put PHI in error messages or logs
- Do NOT use `datetime.utcnow()` — use `datetime.now(timezone.utc)` instead
- Do NOT use `os.getcwd()` for path resolution in tests

---

## Testing

Write basic tests to verify your code compiles and the logic is sound:
- Place in `backend/tests/unit/test_alerts_staging.py`
- Test the rules engine logic (threshold evaluation)
- Test escalation chain logic (timing, level progression)
- Test schema validation (Pydantic models accept/reject correctly)
- Do NOT run integration tests against the real DB (main agent handles that at checkpoint)

---

## Delivery Checklist

Before declaring done, verify:
- [ ] All files in `backend/app/modules/alerts_staging/`
- [ ] Migration at `backend/alembic/versions/0015_alert_system_tables.py`
- [ ] All Python files pass `python -c "import ast; ast.parse(open('file.py').read())"` (syntax valid)
- [ ] All imports resolve (no circular dependencies)
- [ ] Every file under 150 lines (excluding comments/docstrings)
- [ ] Every function has a docstring
- [ ] No PHI in any log statement
- [ ] README.md documents the module
- [ ] Follows patterns from existing modules (especially risk_engine and drug_interactions)

---

## Reference Files to Study

Read these to match the patterns:
- `backend/app/modules/risk_engine/service.py` — service pattern
- `backend/app/modules/risk_engine/router.py` — router pattern with HIPAA headers
- `backend/app/modules/risk_engine/tasks.py` — Celery task pattern
- `backend/app/modules/drug_interactions/models.py` — model with RLS pattern
- `backend/app/core/events.py` — event bus and event class definitions
- `backend/app/modules/audit/service.py` — audit logging pattern
- `backend/alembic/versions/0011_risk_engine_tables.py` — migration with RLS pattern
- `backend/app/modules/risk_engine/enums.py` — enum pattern
- `backend/app/modules/risk_engine/exceptions.py` — exception hierarchy pattern
- `backend/app/modules/risk_engine/schemas.py` — Pydantic schema pattern

---

## Questions?

If anything is unclear, make reasonable assumptions following the patterns in existing modules. The main agent will review everything at checkpoint and fix any discrepancies. Prefer completeness over perfection — get all files written with correct structure, and minor bugs can be fixed during review.
