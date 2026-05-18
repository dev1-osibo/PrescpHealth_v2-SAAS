# Implementation Plan: PrescpHealth SaaS Rebuild

## Overview

This plan breaks the PrescpHealth greenfield rebuild into incremental, modular tasks grouped by system area: infrastructure/core, backend modules (auth â†’ patients â†’ measurements â†’ risk â†’ forecast â†’ AI assistant â†’ drugs â†’ alerts â†’ reports â†’ population â†’ admin â†’ patient portal), ML engine, frontend, and integration wiring. Each task builds on previous tasks. The backend uses Python/FastAPI, the frontend uses TypeScript/React, and the ML pipeline uses Python (scikit-learn, XGBoost, LightGBM, PyTorch, Prophet). All code should be well-commented and modular per user preference.

## Tasks

- [ ] 1. Project scaffolding and infrastructure setup
  - [x] 1.1 Initialize monorepo structure with backend, frontend, and ml directories
    - Create top-level `backend/`, `frontend/`, `ml/` directories
    - Create `backend/pyproject.toml` with dependencies: fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, pydantic, pydantic-settings, celery, redis, bcrypt, python-jose, httpx, hypothesis
    - Create `frontend/package.json` with dependencies: react, react-dom, react-router-dom, axios, zustand, recharts, vite, vitest, typescript, @testing-library/react, playwright
    - Create `ml/pyproject.toml` with dependencies: xgboost, lightgbm, scikit-learn, torch, shap, prophet, lifelines, pycox, hypothesis
    - Create `.env.example` with all required environment variables
    - _Requirements: 16.1, 16.2, 19.1_

  - [x] 1.2 Set up backend FastAPI application factory and configuration
    - Create `backend/app/main.py` with FastAPI app factory, CORS middleware, lifespan handler
    - Create `backend/app/config.py` using pydantic-settings for env-based configuration (DB URL, Redis URL, JWT secret, external API keys)
    - Create `backend/app/__init__.py`
    - _Requirements: 16.1, 16.2, 21.4_

  - [x] 1.3 Set up database layer with SQLAlchemy async engine and Alembic migrations
    - Create `backend/app/core/database.py` with async engine, session factory, `get_db` dependency
    - Create `backend/alembic.ini` and `backend/alembic/env.py` for async migrations
    - Create initial migration with tenant RLS setup: `SET app.current_tenant` session variable pattern
    - Create `backend/app/core/base_model.py` with TenantMixin (adds `tenant_id` column + RLS policy helper)
    - _Requirements: 1.1, 1.2, 17.3_

  - [x] 1.4 Set up Redis connection and caching utilities
    - Create `backend/app/core/cache.py` with Redis async client, `cache_get`, `cache_set`, `cache_invalidate` helpers
    - Implement cache fallback: if Redis unavailable, log warning and return None (caller falls back to DB)
    - Set default TTL of 300 seconds for read-only data
    - _Requirements: 17.3, 17.4_

  - [x] 1.5 Set up Celery worker configuration and queue definitions
    - Create `backend/app/workers/celery_app.py` with Celery app, Redis broker, queue definitions (risk, forecast, notification, report)
    - Create `backend/app/workers/beat_schedule.py` with periodic task stubs (population metrics refresh, escalation checks)
    - Define priority lanes: notification > risk > forecast > report
    - _Requirements: 15.1, 15.2, 15.3_

  - [x] 1.6 Create core middleware stack
    - Create `backend/app/core/middleware.py` with:
      - `TenantMiddleware`: extracts `tenant_id` from JWT, sets PostgreSQL session variable `app.current_tenant`
      - `RateLimitMiddleware`: 1000 req/min for Clinician roles, 100 req/min for Patient_User (Redis-backed sliding window)
      - `AuditMiddleware`: logs request metadata for observability
    - _Requirements: 1.1, 16.4, 16.5, 21.5_

  - [x] 1.7 Create core exception hierarchy and error response format
    - Create `backend/app/core/exceptions.py` with custom exceptions: `AuthError`, `ForbiddenError`, `NotFoundError`, `ValidationError`, `ConflictError`, `RateLimitError`, `MLEngineError`, `ExternalServiceError`
    - Create exception handlers in `main.py` returning consistent JSON error format with `code`, `message`, `details`, `request_id`
    - _Requirements: 16.3, 16.5_

  - [x] 1.8 Create domain event bus
    - Create `backend/app/core/events.py` with in-process pub/sub event bus
    - Define event types: `MeasurementSaved`, `RiskScoreComputed`, `ForecastCompleted`, `AlertGenerated`, `HealthStatusChanged`
    - Implement `publish(event)` and `subscribe(event_type, handler)` pattern
    - _Requirements: 11.3, 8.8, 10.11_

  - [x] 1.9 Create pagination and common utilities
    - Create `backend/app/core/pagination.py` with cursor-based pagination helpers
    - Create `backend/app/core/deps.py` with FastAPI dependencies: `get_db`, `get_current_user`, `get_tenant`
    - _Requirements: 16.1_

  - [x] 1.10 Set up test infrastructure
    - Create `backend/tests/conftest.py` with fixtures: test DB (testcontainers PostgreSQL), test Redis, async test client, auth helper (generate test JWTs for each role), tenant factory
    - Create `backend/tests/unit/`, `backend/tests/property/`, `backend/tests/integration/` directories
    - _Requirements: 17.1_

- [x] 2. Checkpoint â€” Verify infrastructure
  - Ensure all infrastructure components initialize correctly, run any existing tests, ask the user if questions arise.

- [ ] 3. Authentication and session management module
  - [x] 3.1 Create auth SQLAlchemy models and Alembic migration
    - Create `backend/app/modules/auth/models.py` with `User`, `RefreshToken`, `MFAConfig` models matching design schema
    - Create `backend/app/modules/auth/__init__.py`
    - Generate Alembic migration for `users`, `refresh_tokens` tables with RLS policies
    - _Requirements: 2.1, 2.4, 2.7_

  - [x] 3.2 Implement auth service with JWT, refresh token rotation, and MFA
    - Create `backend/app/modules/auth/service.py` with `AuthService`:
      - `authenticate(email, password)` â†’ validate credentials, check account lock, issue JWT (15min) + refresh token (7d)
      - `rotate_refresh_token(token)` â†’ invalidate old token, issue new pair, detect reuse (invalidate all sessions)
      - `verify_mfa(user_id, totp_code)` â†’ validate TOTP code
      - `logout(refresh_token)` â†’ revoke token
      - `lock_account(user_id)` â†’ lock after 5 failed attempts in 10min window
    - Create `backend/app/core/security.py` with JWT encode/decode (python-jose), bcrypt password hashing (cost 12)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.3 Create auth Pydantic schemas and router
    - Create `backend/app/modules/auth/schemas.py` with request/response schemas: `LoginRequest`, `TokenResponse`, `MFAVerifyRequest`, `RefreshRequest`
    - Create `backend/app/modules/auth/router.py` with endpoints: `POST /login`, `POST /refresh`, `POST /logout`, `POST /mfa/verify`
    - _Requirements: 2.1, 2.2, 2.6_

  - [x] 3.4 Implement RBAC system with role hierarchy and permission decorator
    - Create `backend/app/modules/auth/rbac.py` with:
      - Role enum: `Patient_User`, `Nurse`, `Doctor`, `Clinic_Admin`, `Super_Admin`
      - Permission definitions per role (which endpoints/actions each role can access)
      - `require_role(*roles)` FastAPI dependency decorator
      - Role hierarchy enforcement: higher roles inherit all lower role permissions
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6_

  - [x]* 3.5 Write property test for token rotation invalidation
    - **Property 13: Token Rotation Invalidation Chain**
    - **Validates: Requirements 2.3, 2.5**

  - [x]* 3.6 Write property test for role permission monotonicity
    - **Property 8: Role Permission Monotonicity**
    - **Validates: Requirements 3.1, 3.3, 3.4, 3.6**

  - [x]* 3.7 Write unit tests for auth module
    - Test MFA flow (enable, verify valid code, reject invalid code)
    - Test account lockout after 5 failed attempts within 10-minute window
    - Test logout token invalidation
    - Test JWT expiry enforcement (15min access, 7d refresh)
    - _Requirements: 2.1, 2.4, 2.7_

- [x] 4. Audit log module
  - [x] 4.1 Create audit log model and migration
    - Create `backend/app/core/audit.py` with `AuditLog` SQLAlchemy model matching design schema
    - Generate Alembic migration for `audit_logs` table with NO UPDATE/DELETE grants, insert-only via `audit_writer` role
    - Implement monthly partitioning for 7-year retention
    - _Requirements: 18.4, 18.5, 20.3_

  - [x] 4.2 Implement audit logging service and middleware integration
    - Create audit logging helper: `log_audit(tenant_id, user_id, action, resource_type, resource_id, changes, metadata)`
    - Integrate with domain event bus to auto-log CUD operations
    - Ensure append-only: no delete/update methods exposed
    - _Requirements: 18.4, 18.5, 1.4_

  - [x]* 4.3 Write property test for audit log append-only monotonicity
    - **Property 6: Audit Log Append-Only Monotonicity**
    - **Validates: Requirements 18.4, 18.5, 1.4, 11.6**

- [x] 5. Patient profile management module
  - [x] 5.1 Create patient SQLAlchemy models and migration
    - Create `backend/app/modules/patients/models.py` with `Patient`, `PatientVersion` models matching design schema
    - Create `backend/app/modules/patients/__init__.py`
    - Generate Alembic migration for `patients`, `patient_versions` tables with RLS policies
    - Add GIN trigram index on `(tenant_id, full_name)` for partial name search
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

  - [x] 5.2 Implement patient service with CRUD, search, versioning, and timeline
    - Create `backend/app/modules/patients/service.py` with `PatientService`:
      - `create_patient(data)` â†’ assign immutable UUID, store demographics + medical history
      - `update_patient(id, data)` â†’ update fields, create `PatientVersion` record with old/new values
      - `search_patients(filters)` â†’ search by name (partial), risk level, disease flag, age range, sex
      - `get_timeline(patient_id)` â†’ aggregate measurements, risk scores, alerts, AI interactions in reverse-chronological order
      - `soft_delete(patient_id)` â†’ set `is_deleted=True`, anonymize PII
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 20.1, 20.2_

  - [x] 5.3 Create patient schemas and router
    - Create `backend/app/modules/patients/schemas.py` with Pydantic schemas for all patient operations
    - Create `backend/app/modules/patients/router.py` with endpoints: `POST /patients`, `GET /patients`, `GET /patients/{id}`, `PUT /patients/{id}`, `GET /patients/{id}/timeline`
    - Apply RBAC: create/update = Doctor/Clinic_Admin, read = Doctor/Nurse/Clinic_Admin
    - _Requirements: 4.1, 4.4, 4.6_

  - [ ]* 5.4 Write property test for patient profile version history
    - **Property 16: Patient Profile Version History**
    - **Validates: Requirements 4.5**

  - [ ]* 5.5 Write unit tests for patient module
    - Test profile creation with all field types (JSONB diagnoses, family history, allergies)
    - Test search by each filter type (name partial match, risk level, age range, sex)
    - Test timeline ordering (reverse-chronological)
    - Test soft delete with PII anonymization
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [ ] 6. Checkpoint â€” Verify auth, audit, and patient modules
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Clinical measurement module
  - [ ] 7.1 Create measurement SQLAlchemy model and migration
    - Create `backend/app/modules/measurements/models.py` with `Measurement` model matching design schema
    - Create `backend/app/modules/measurements/__init__.py`
    - Generate Alembic migration for `measurements` table with RLS policy
    - Add unique constraint `(patient_id, measurement_type, recorded_at, value)` for idempotency
    - Add index `(patient_id, measurement_type, recorded_at DESC)` for time-series queries
    - _Requirements: 5.1, 5.3_

  - [ ] 7.2 Implement measurement validators with physiological ranges
    - Create `backend/app/modules/measurements/validators.py` with per-type validation ranges matching design table (systolic_bp: 60â€“300, diastolic_bp: 30â€“200, bmi: 10â€“80, etc.)
    - Implement `validate_measurement(type, value)` â†’ accept/reject with descriptive error
    - Implement `flag_deviation(patient_id, type, value)` â†’ flag if >2Ïƒ from patient's personal baseline
    - _Requirements: 5.2, 5.6_

  - [ ] 7.3 Implement measurement service with save, validate, bulk import, and history
    - Create `backend/app/modules/measurements/service.py` with `MeasurementService`:
      - `save_measurement(data)` â†’ validate range, check idempotency, save, publish `MeasurementSaved` event
      - `validate_patient_measurement(measurement_id, clinician_id)` â†’ mark as validated, record validator identity/timestamp
      - `bulk_import_csv(patient_id, file)` â†’ parse CSV, validate each row, report per-row errors, import valid rows
      - `get_history(patient_id, type, date_range)` â†’ return time-series data
    - Handle Patient_User submissions: mark as `is_validated=False`, exclude from risk computation until validated
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 5.7_

  - [ ] 7.4 Create measurement schemas and router
    - Create `backend/app/modules/measurements/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/measurements/router.py` with endpoints: `POST /patients/{id}/measurements`, `GET /patients/{id}/measurements`, `POST /patients/{id}/measurements/bulk`, `PUT /measurements/{id}/validate`
    - Apply RBAC: submit = Doctor/Nurse/Patient_User, validate = Doctor, history = Doctor/Nurse
    - _Requirements: 5.1, 5.3, 5.4, 5.7_

  - [ ]* 7.5 Write property test for measurement validation and round-trip
    - **Property 5: Measurement Validation and Round-Trip**
    - **Validates: Requirements 5.2, 5.3**

  - [ ]* 7.6 Write property test for measurement deviation flagging
    - **Property 15: Measurement Deviation Flagging**
    - **Validates: Requirements 5.6**

  - [ ]* 7.7 Write property test for concurrent measurement idempotency
    - **Property 13: Concurrent Measurement Idempotency**
    - Note: This is the idempotency key property from requirements, distinct from token rotation Property 13 in design
    - **Validates: Requirements 5.1**

  - [ ]* 7.8 Write unit tests for measurement module
    - Test each measurement type acceptance within valid range
    - Test rejection of out-of-range values with descriptive errors
    - Test bulk CSV import with mixed valid/invalid rows
    - Test Patient_User submission marked as unvalidated
    - _Requirements: 5.1, 5.2, 5.4, 5.7_

- [ ] 8. Checkpoint â€” Verify measurement module
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 9. Risk engine module (backend API layer)
  - [ ] 9.1 Create risk engine SQLAlchemy models and migration
    - Create `backend/app/modules/risk_engine/models.py` with `RiskScore`, `RiskComputation`, `ShapExplanation`, `ModelVersion` models matching design schema
    - Create `backend/app/modules/risk_engine/__init__.py`
    - Generate Alembic migration for `risk_scores`, `shap_explanations`, `model_versions` tables with RLS policies
    - Add index `(patient_id, disease, computed_at DESC)` for latest score lookup
    - Add unique constraint `(disease, version)` on `model_versions`
    - _Requirements: 6.1, 6.9, 7.1_

  - [ ] 9.2 Implement risk engine service and Celery task
    - Create `backend/app/modules/risk_engine/service.py` with `RiskService`:
      - `trigger_computation(patient_id)` â†’ enqueue Celery task, return task_id
      - `get_latest_scores(patient_id)` â†’ return latest risk scores for all 6 diseases
      - `get_score_history(patient_id, disease)` â†’ return historical scores
    - Create `backend/app/modules/risk_engine/tasks.py` with Celery task `compute_risk_scores`:
      - Fetch latest validated measurements for patient
      - Call ML engine (implemented in task 13)
      - Store results with input snapshot, model version, SHAP explanation
      - Publish `RiskScoreComputed` domain event
    - _Requirements: 6.1, 6.6, 6.8, 6.9, 7.3_

  - [ ] 9.3 Create risk engine schemas and router
    - Create `backend/app/modules/risk_engine/schemas.py` with Pydantic schemas for risk scores, SHAP explanations, computation requests
    - Create `backend/app/modules/risk_engine/router.py` with endpoints: `POST /patients/{id}/risk/compute`, `GET /patients/{id}/risk/scores`, `GET /patients/{id}/risk/history`
    - Apply RBAC: compute = Doctor/Nurse, read = Doctor/Nurse, history = Doctor
    - _Requirements: 6.1, 6.3, 6.4, 6.5_

  - [ ]* 9.4 Write property test for risk score range invariant
    - **Property 2: Risk Score Range Invariant**
    - **Validates: Requirements 6.1, 6.4, 6.7**

  - [ ]* 9.5 Write property test for risk stratification consistency
    - **Property 3: Risk Stratification Consistency**
    - **Validates: Requirements 6.5**

  - [ ]* 9.6 Write property test for SHAP explanation additivity
    - **Property 4: SHAP Explanation Additivity**
    - **Validates: Requirements 6.3, 6.9**

  - [ ]* 9.7 Write property test for risk computation audit completeness
    - **Property 17: Risk Computation Audit Completeness**
    - **Validates: Requirements 6.9, 7.3**

  - [ ]* 9.8 Write property test for unvalidated measurement exclusion
    - **Property 9: Unvalidated Measurement Exclusion**
    - **Validates: Requirements 5.4, 3.5**

  - [ ]* 9.9 Write unit tests for risk engine module
    - Test ensemble weight normalization
    - Test Bayesian prior fallback for sparse data
    - Test model version logging per computation
    - _Requirements: 6.1, 6.7, 7.3_

- [ ] 10. Forecast engine module (backend API layer)
  - [ ] 10.1 Create forecast engine SQLAlchemy models and migration
    - Create `backend/app/modules/forecast_engine/models.py` with `Forecast`, `InterventionSimulation` models matching design schema
    - Create `backend/app/modules/forecast_engine/__init__.py`
    - Generate Alembic migration for `forecasts`, `intervention_simulations` tables with RLS policies
    - _Requirements: 8.1, 8.7_

  - [ ] 10.2 Implement forecast engine service and Celery tasks
    - Create `backend/app/modules/forecast_engine/service.py` with `ForecastService`:
      - `trigger_forecast(patient_id)` â†’ enqueue Celery task, return task_id
      - `get_latest_forecast(patient_id)` â†’ return latest forecasts
      - `trigger_simulation(patient_id, intervention)` â†’ enqueue simulation task
    - Create `backend/app/modules/forecast_engine/tasks.py` with Celery tasks:
      - `compute_forecast` â†’ call ML forecasting pipeline, store results, publish `ForecastCompleted` event
      - `run_simulation` â†’ compute baseline vs intervention comparison
    - _Requirements: 8.1, 8.2, 8.3, 8.7, 8.9_

  - [ ] 10.3 Create forecast engine schemas and router
    - Create `backend/app/modules/forecast_engine/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/forecast_engine/router.py` with endpoints: `POST /patients/{id}/forecast`, `GET /patients/{id}/forecast/latest`, `POST /patients/{id}/forecast/simulate`
    - Apply RBAC: all endpoints = Doctor only
    - _Requirements: 8.1, 8.7_

  - [ ]* 10.4 Write property test for confidence interval containment
    - **Property 7: Confidence Interval Containment**
    - **Validates: Requirements 6.4, 8.1, 8.3**

  - [ ]* 10.5 Write property test for intervention simulation directional monotonicity
    - **Property 10: Intervention Simulation Directional Monotonicity**
    - **Validates: Requirements 8.7**

  - [ ]* 10.6 Write unit tests for forecast engine module
    - Test single-measurement patient handling (Bayesian prior fallback)
    - Test forecast at each horizon (3, 6, 12 months)
    - Test intervention simulation produces revised forecast
    - _Requirements: 8.1, 8.5, 8.7_

- [ ] 11. AI clinical assistant module
  - [ ] 11.1 Create AI assistant SQLAlchemy models and migration
    - Create `backend/app/modules/ai_assistant/models.py` with `Conversation`, `Message` models matching design schema
    - Create `backend/app/modules/ai_assistant/__init__.py`
    - Generate Alembic migration for `conversations`, `messages` tables with RLS policies
    - _Requirements: 9.1, 9.7_

  - [ ] 11.2 Implement LLM provider abstraction with GPT-4o and Claude fallback
    - Create `backend/app/modules/ai_assistant/providers.py` with:
      - `LLMProvider` abstract interface: `async send(messages, context) â†’ response`
      - `GPT4oProvider` implementation using OpenAI API
      - `ClaudeProvider` implementation using Anthropic API
      - `FailoverLLMProvider` that tries GPT-4o first, falls back to Claude on error or 8s timeout
    - _Requirements: 9.3, 21.3_

  - [ ] 11.3 Implement AI assistant service
    - Create `backend/app/modules/ai_assistant/service.py` with `AIAssistantService`:
      - `send_message(patient_id, clinician_id, message)` â†’ build context (patient profile, measurements, risk scores, medications, conversation history), call LLM, persist response
      - `get_history(patient_id)` â†’ return conversation history
      - Ensure all responses include advisory label and reasoning chain
      - Flag potential drug interactions mentioned in conversation
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9_

  - [ ] 11.4 Create AI assistant schemas and router
    - Create `backend/app/modules/ai_assistant/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/ai_assistant/router.py` with endpoints: `POST /patients/{id}/assistant/chat`, `GET /patients/{id}/assistant/history`
    - Apply RBAC: Doctor only
    - _Requirements: 9.1, 9.7_

  - [ ]* 11.5 Write unit tests for AI assistant module
    - Test GPT-4o â†’ Claude failover (mock both providers)
    - Test advisory label presence in all responses
    - Test conversation persistence with model version tracking
    - Test insufficient data handling (explicit limitation statement)
    - _Requirements: 9.3, 9.6, 9.7, 9.9_

- [ ] 12. Drug interaction safety engine module
  - [ ] 12.1 Create drug interaction SQLAlchemy models and migration
    - Create `backend/app/modules/drug_interactions/models.py` with `MedicationRecord`, `InteractionResult`, `DrugInteractionsDB` models matching design schema
    - Create `backend/app/modules/drug_interactions/__init__.py`
    - Generate Alembic migration for `medication_records`, `interaction_results`, `drug_interactions_db` tables with RLS policies
    - _Requirements: 10.1, 10.2_

  - [ ] 12.2 Implement drug interaction matching engine
    - Create `backend/app/modules/drug_interactions/engine.py` with core DDI/DHI matching logic:
      - `check_ddi(new_drug, active_medications)` â†’ check new drug against all active meds, return DDI results with severity
      - `check_dhi(drug, patient_health_profile)` â†’ check drug against patient conditions, eGFR, liver function, biomarkers
      - Consider patient age, sex, weight, renal function, hepatic function for DHI assessment
    - _Requirements: 10.2, 10.3, 10.6, 10.7_

  - [ ] 12.3 Implement drug interaction service
    - Create `backend/app/modules/drug_interactions/service.py` with `DrugInteractionService`:
      - `add_medication(patient_id, drug_data)` â†’ save medication, run DDI + DHI checks, return interaction results
      - `get_safety_summary(patient_id)` â†’ return consolidated medication safety summary (Safe/Caution/Action Required)
      - `override_interaction(interaction_id, doctor_id, justification)` â†’ record override with mandatory justification
      - `re_evaluate_on_health_change(patient_id)` â†’ re-check all active meds against updated health profile
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.8, 10.10, 10.11_

  - [ ] 12.4 Create drug interaction schemas and router
    - Create `backend/app/modules/drug_interactions/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/drug_interactions/router.py` with endpoints: `POST /patients/{id}/medications`, `GET /patients/{id}/medications/safety`, `POST /interactions/{id}/override`
    - Apply RBAC: add medication/override = Doctor, safety summary = Doctor/Nurse
    - _Requirements: 10.4, 10.5, 10.10_

  - [ ]* 12.5 Write property test for drug interaction severity-to-alert mapping
    - **Property 14: Drug Interaction Severity-to-Alert Mapping**
    - **Validates: Requirements 10.4, 10.5, 10.7**

  - [ ]* 12.6 Write unit tests for drug interaction module
    - Test DDI detection between known interacting drugs
    - Test DHI detection with impaired renal function (low eGFR)
    - Test override with justification recording
    - Test health status change re-evaluation
    - _Requirements: 10.2, 10.3, 10.10, 10.11_

- [ ] 13. Checkpoint â€” Verify risk, forecast, AI assistant, and drug interaction modules
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 14. Alert and notification system module
  - [ ] 14.1 Create alert SQLAlchemy models and migration
    - Create `backend/app/modules/alerts/models.py` with `Alert`, `AlertThreshold`, `EscalationRecord` models matching design schema
    - Create `backend/app/modules/alerts/__init__.py`
    - Generate Alembic migration for `alerts`, `alert_thresholds`, `escalation_records` tables with RLS policies
    - _Requirements: 11.1, 11.5_

  - [ ] 14.2 Implement alert service with threshold evaluation, escalation, and dispatch
    - Create `backend/app/modules/alerts/service.py` with `AlertService`:
      - `evaluate_thresholds(patient_id, event)` â†’ check measurement/risk score against configured thresholds, generate alerts
      - `escalate(alert_id)` â†’ escalate unacknowledged Critical alerts: Nurse (15min) â†’ Doctor (30min) â†’ Clinic_Admin
      - `acknowledge(alert_id, user_id, notes)` â†’ record acknowledgment in audit log
      - `configure_thresholds(patient_id, thresholds)` â†’ set per-patient or tenant-default thresholds
      - `check_missed_followup(patient_id)` â†’ generate alert if no measurements within configured interval
    - Subscribe to domain events: `MeasurementSaved`, `RiskScoreComputed`, `ForecastCompleted`
    - _Requirements: 11.1, 11.3, 11.4, 11.5, 11.6, 11.7, 11.8_

  - [ ] 14.3 Implement notification dispatch Celery tasks
    - Create `backend/app/modules/alerts/tasks.py` with Celery tasks:
      - `dispatch_notification(alert_id, channels)` â†’ send via in-app, email (SendGrid), SMS (Twilio), WhatsApp
      - `check_escalation()` â†’ periodic task checking for unacknowledged Critical alerts past timeout
    - Implement retry with exponential backoff: email (24h retry), SMS (6h retry)
    - _Requirements: 11.2, 11.3, 11.5, 21.1, 21.2_

  - [ ] 14.4 Create alert schemas and router
    - Create `backend/app/modules/alerts/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/alerts/router.py` with endpoints: `GET /alerts`, `POST /alerts/{id}/acknowledge`, `PUT /patients/{id}/alert-thresholds`
    - Apply RBAC: view alerts = all clinicians, acknowledge = Doctor/Nurse, configure thresholds = Doctor/Clinic_Admin
    - _Requirements: 11.1, 11.6, 11.8_

  - [ ]* 14.5 Write property test for alert escalation ordering
    - **Property 11: Alert Escalation Ordering**
    - **Validates: Requirements 11.5**

  - [ ]* 14.6 Write unit tests for alert module
    - Test threshold configuration per patient and tenant default
    - Test missed follow-up detection
    - Test multi-channel dispatch (in-app, email, SMS, WhatsApp)
    - Test escalation timeout enforcement
    - _Requirements: 11.1, 11.2, 11.5, 11.7_

- [ ] 15. Report generation module
  - [ ] 15.1 Create report service and Celery tasks
    - Create `backend/app/modules/reports/service.py` with `ReportService`:
      - `generate_clinical_pdf(patient_id)` â†’ produce PDF with demographics, medications, risk scores + SHAP, forecast charts, measurement history, active alerts
      - `generate_referral_letter(patient_id, config)` â†’ produce referral PDF with AI-generated clinical summary
      - `export_measurements_csv(patient_id)` â†’ export patient measurement history as CSV
      - `export_population_csv(tenant_id)` â†’ export population patient list with risk scores
    - Create `backend/app/modules/reports/__init__.py`
    - Create `backend/app/modules/reports/tasks.py` with Celery tasks for async PDF/CSV generation
    - Embed charts as SVG rendered to PDF for print legibility
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [ ] 15.2 Create report schemas and router
    - Create `backend/app/modules/reports/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/reports/router.py` with endpoints: `POST /patients/{id}/reports/clinical`, `POST /patients/{id}/reports/referral`, `GET /patients/{id}/export/measurements`, `GET /population/export`
    - Apply RBAC: clinical/referral reports = Doctor, measurement export = Doctor, population export = Clinic_Admin
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ]* 15.3 Write property test for CSV export round-trip
    - **Property 12: CSV Export Round-Trip**
    - **Validates: Requirements 14.3, 5.7**

  - [ ]* 15.4 Write unit tests for report module
    - Test PDF section completeness (all required sections present)
    - Test referral letter structure
    - Test SVG chart embedding in PDF
    - Test CSV export format matches bulk import schema
    - _Requirements: 14.1, 14.2, 14.6_

- [ ] 16. Population analytics module
  - [ ] 16.1 Create population SQLAlchemy models and migration
    - Create `backend/app/modules/population/models.py` with `CachedPopulationMetric` model
    - Create `backend/app/modules/population/__init__.py`
    - Generate Alembic migration
    - _Requirements: 12.1, 12.6_

  - [ ] 16.2 Implement population analytics service
    - Create `backend/app/modules/population/service.py` with `PopulationService`:
      - `get_dashboard_metrics(tenant_id)` â†’ total patients, risk distribution per disease, prevalence rates, average risk scores
      - `get_watchlist(tenant_id)` â†’ patients in High/Critical stratum, sortable by risk score and last-updated
      - `get_trends(tenant_id, time_window)` â†’ cohort-level metric trends over 1/3/6/12 month windows
      - `get_outcome_tracking(tenant_id)` â†’ percentage of High/Critical predictions followed by clinical event within 90 days
      - `refresh_metrics()` â†’ periodic task to refresh cached aggregate metrics (â‰¤1 hour interval)
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.6_

  - [ ] 16.3 Create population schemas and router
    - Create `backend/app/modules/population/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/population/router.py` with endpoints: `GET /population/dashboard`, `GET /population/watchlist`, `GET /population/trends`
    - Apply RBAC: Doctor and Clinic_Admin
    - _Requirements: 12.1, 12.2, 12.3_

  - [ ]* 16.4 Write unit tests for population module
    - Test watchlist filtering (High/Critical only)
    - Test metric aggregation correctness
    - Test trend calculation over different time windows
    - _Requirements: 12.1, 12.2, 12.3_

- [ ] 17. Admin module
  - [ ] 17.1 Implement admin service for tenant and model management
    - Create `backend/app/modules/admin/service.py` with `AdminService`:
      - `create_tenant(data)` â†’ provision tenant with unique ID, data residency region, settings
      - `deploy_model(disease, version, artifact_path)` â†’ deploy new model version, retain previous for rollback
      - `rollback_model(disease, target_version)` â†’ rollback to previous model version without downtime
      - `get_model_metrics(disease, version)` â†’ return AUC-ROC, calibration score, Brier score
      - `trigger_recomputation(disease, model_version)` â†’ recompute historical risk scores with new model
    - Create `backend/app/modules/admin/__init__.py`
    - _Requirements: 1.2, 7.1, 7.2, 7.4, 7.5_

  - [ ] 17.2 Create admin schemas and router
    - Create `backend/app/modules/admin/schemas.py` with Pydantic schemas
    - Create `backend/app/modules/admin/router.py` with endpoints for tenant management, model management, system configuration
    - Apply RBAC: Super_Admin only for cross-tenant and model operations, Clinic_Admin for tenant-level settings
    - _Requirements: 1.2, 7.1, 7.2_

- [ ] 18. Background task status endpoint
  - [ ] 18.1 Create background task model, migration, and status polling endpoint
    - Create `backend/app/core/tasks.py` with `BackgroundTask` model matching design schema
    - Generate Alembic migration for `background_tasks` table
    - Create `GET /api/v1/tasks/{task_id}/status` endpoint returning task status, result, or error
    - Implement retry logic: up to 3 retries with exponential backoff (30s, 120s, 480s)
    - _Requirements: 15.4, 15.5_

- [ ] 19. Checkpoint â€” Verify alerts, reports, population, admin, and task status modules
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 20. ML engine â€” Risk prediction pipeline
  - [ ] 20.1 Implement Bayesian imputation module for missing features
    - Create `ml/risk_engine/imputation.py` with:
      - Population-level Bayesian priors per measurement type (stratified by age, sex, ethnicity)
      - `impute_missing(patient_features, available_measurements)` â†’ fill missing features with priors
      - Track which features were imputed for SHAP explanation annotation
    - _Requirements: 6.7_

  - [ ] 20.2 Implement ensemble risk model with XGBoost, LightGBM, Random Forest, and Neural Network
    - Create `ml/risk_engine/models/` directory with:
      - `xgboost_model.py` â€” XGBoost classifier per disease
      - `lightgbm_model.py` â€” LightGBM classifier per disease
      - `random_forest_model.py` â€” Random Forest classifier per disease
      - `neural_net_model.py` â€” PyTorch neural network classifier per disease
    - Create `ml/risk_engine/ensemble.py` with meta-learner (logistic regression) combining base model outputs into final Risk Score (0â€“100)
    - Implement risk stratification: Low (0â€“24), Moderate (25â€“49), High (50â€“74), Critical (75â€“100)
    - _Requirements: 6.1, 6.2, 6.5_

  - [ ] 20.3 Implement SHAP explainer integration
    - Create `ml/risk_engine/explainer.py` with:
      - SHAP TreeExplainer for tree-based models, KernelExplainer for neural net
      - `explain(model, input_features)` â†’ return base value + per-feature SHAP contributions with direction
      - Validate SHAP additivity: |Î£(shap_values) - (prediction - base_value)| < 0.01
    - _Requirements: 6.3, 6.9_

  - [ ] 20.4 Implement risk engine orchestrator
    - Create `ml/risk_engine/orchestrator.py` that:
      - Loads model artifacts from versioned storage (S3/local path)
      - Runs imputation â†’ base models â†’ meta-learner â†’ SHAP explanation pipeline
      - Produces confidence intervals (95% CI) via bootstrap or model uncertainty
      - Returns structured result: scores, strata, SHAP explanations, CI bounds, model version
    - _Requirements: 6.1, 6.4, 6.6, 6.9_

  - [ ]* 20.5 Write unit tests for ML risk pipeline
    - Test ensemble weight normalization
    - Test imputation with various sparsity levels
    - Test score output always in [0, 100] range
    - Test stratification mapping correctness
    - _Requirements: 6.1, 6.2, 6.5, 6.7_

- [ ] 21. ML engine â€” Forecasting pipeline
  - [ ] 21.1 Implement forecasting ensemble with TFT, LSTM, and Prophet
    - Create `ml/forecast_engine/models/` directory with:
      - `tft_model.py` â€” Temporal Fusion Transformer for time-series forecasting
      - `lstm_model.py` â€” LSTM network for sequential prediction
      - `prophet_model.py` â€” Prophet model for trend/seasonality decomposition
    - Create `ml/forecast_engine/ensemble.py` with weighted ensemble combining outputs with uncertainty quantification
    - Support forecast horizons: 3, 6, 12 months
    - Handle sparse data: use Bayesian priors when patient has limited history
    - _Requirements: 8.1, 8.2, 8.5_

  - [ ] 21.2 Implement survival analysis with Cox PH and DeepSurv
    - Create `ml/forecast_engine/survival/` directory with:
      - `cox_ph.py` â€” Cox Proportional Hazards model (lifelines)
      - `deepsurv.py` â€” DeepSurv neural network (pycox)
    - Combine outputs for time-to-event probability estimates per disease
    - _Requirements: 8.4_

  - [ ] 21.3 Implement intervention simulation engine
    - Create `ml/forecast_engine/simulation.py` with:
      - `simulate_intervention(patient_features, intervention_type, parameters)` â†’ modify input features per intervention, re-run forecast, compare baseline vs simulated
      - Support intervention types: weight loss, smoking cessation, medication addition, exercise increase
      - Return delta between baseline and simulated trajectories at each horizon
    - _Requirements: 8.7_

  - [ ] 21.4 Implement forecast orchestrator
    - Create `ml/forecast_engine/orchestrator.py` that:
      - Loads patient measurement history
      - Runs TFT + LSTM + Prophet ensemble for metric forecasts
      - Runs Cox PH + DeepSurv for survival analysis
      - Produces point estimates + 95% CI for each horizon
      - Annotates data quality level: 'full_data', 'sparse_data', 'prior_only'
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.9_

  - [ ]* 21.5 Write unit tests for ML forecast pipeline
    - Test single-measurement patient handling (prior-only mode)
    - Test forecast at each horizon (3, 6, 12 months)
    - Test confidence interval containment (point estimate within CI)
    - Test intervention simulation produces directionally correct results
    - _Requirements: 8.1, 8.5, 8.7_

- [ ] 22. Checkpoint â€” Verify ML engine pipelines
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 23. Tenant isolation and security hardening
  - [ ] 23.1 Implement PostgreSQL RLS policies for all tenant-scoped tables
    - Create Alembic migration applying RLS policies to all tables with `tenant_id`
    - Policy: `tenant_id = current_setting('app.current_tenant')::uuid` on SELECT, INSERT, UPDATE, DELETE
    - Ensure `TenantMiddleware` sets session variable before every query
    - _Requirements: 1.1, 1.5_

  - [ ] 23.2 Implement input sanitization and security middleware
    - Add input sanitization layer: prevent SQL injection patterns and XSS payloads in all user-supplied input
    - Implement IP allowlisting per tenant (configurable by Clinic_Admin)
    - Ensure no external API keys exposed in client-side code or API responses
    - _Requirements: 18.3, 18.6, 21.4_

  - [ ]* 23.3 Write property test for tenant isolation invariant
    - **Property 1: Tenant Isolation Invariant**
    - **Validates: Requirements 1.1, 1.5, 4.4, 18.6**

  - [ ]* 23.4 Write property test for input sanitization
    - **Property 18: Input Sanitization**
    - **Validates: Requirements 18.3**

  - [ ]* 23.5 Write unit tests for security features
    - Test cross-tenant access rejection (HTTP 403)
    - Test IP allowlist enforcement
    - Test SQL injection patterns are neutralized
    - Test XSS payloads are sanitized
    - _Requirements: 1.5, 18.3, 18.6_

- [ ] 24. Checkpoint â€” Verify tenant isolation and security
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 25. Frontend â€” Project setup and core infrastructure
  - [ ] 25.1 Initialize React/TypeScript frontend with Vite
    - Create `frontend/` project with Vite + React + TypeScript template
    - Configure `vite.config.ts` with API proxy to backend
    - Configure `tsconfig.json` with strict mode
    - Set up ESLint + Prettier configuration
    - _Requirements: 17.2_

  - [ ] 25.2 Create API client layer with JWT interceptor
    - Create `frontend/src/api/client.ts` with Axios instance:
      - Attach JWT access token to all requests via interceptor
      - Auto-refresh token on 401 response using refresh token
      - Handle rate limit (429) with retry-after
    - Create API modules: `auth.ts`, `patients.ts`, `measurements.ts`, `risk.ts`, `forecast.ts`, `assistant.ts`, `alerts.ts`, `reports.ts`
    - _Requirements: 2.1, 16.4_

  - [ ] 25.3 Create auth context, Zustand stores, and route guards
    - Create `frontend/src/app/providers.tsx` with AuthProvider, TenantProvider, ThemeProvider
    - Create `frontend/src/store/` with Zustand stores: auth store, patient store, alert store
    - Create `frontend/src/app/routes.tsx` with route definitions and role-based guards
    - Create `frontend/src/hooks/useAuth.ts`, `usePolling.ts` (for background task status polling)
    - _Requirements: 2.1, 3.1_

  - [ ] 25.4 Create TypeScript type definitions mirroring backend schemas
    - Create `frontend/src/types/` with TypeScript interfaces for all backend response schemas:
      - `auth.ts`, `patient.ts`, `measurement.ts`, `risk.ts`, `forecast.ts`, `assistant.ts`, `drug.ts`, `alert.ts`, `report.ts`, `population.ts`
    - _Requirements: 16.1_

- [ ] 26. Frontend â€” Common components and auth UI
  - [ ] 26.1 Create common UI component library
    - Create `frontend/src/components/common/` with reusable components:
      - `Button`, `Input`, `Select`, `Modal`, `Table` (sortable, paginated), `Card`, `Badge`, `Spinner`, `Toast`
      - `Chart` wrapper component (using Recharts)
    - Ensure all components are accessible (ARIA labels, keyboard navigation, focus management)
    - _Requirements: 17.2_

  - [ ] 26.2 Create authentication UI components
    - Create `frontend/src/components/auth/`:
      - `LoginForm` â€” email/password form with error handling
      - `MFAInput` â€” TOTP code input during login flow
      - `RoleGuard` â€” component wrapper that checks user role before rendering children
    - _Requirements: 2.1, 2.4, 3.1_

- [ ] 27. Frontend â€” Patient management UI
  - [ ] 27.1 Create patient list and search components
    - Create `frontend/src/components/patients/`:
      - `PatientList` â€” searchable, filterable table with pagination
      - `PatientSearch` â€” search by name, risk level, disease, age range, sex
      - `PatientCard` â€” summary card with key demographics and risk indicators
    - _Requirements: 4.4_

  - [ ] 27.2 Create patient profile and timeline components
    - Create `frontend/src/components/patients/`:
      - `PatientProfile` â€” full profile view with demographics, medical history, medications
      - `PatientTimeline` â€” reverse-chronological timeline of measurements, risk scores, alerts, AI interactions
      - `PatientCreateForm` â€” form for creating new patient with all required fields
      - `PatientEditForm` â€” form for updating patient profile
    - _Requirements: 4.1, 4.2, 4.5, 4.6_

- [ ] 28. Frontend â€” Measurement and risk dashboard UI
  - [ ] 28.1 Create measurement entry and visualization components
    - Create `frontend/src/components/measurements/`:
      - `MeasurementForm` â€” form for entering individual measurements with type-specific validation
      - `MeasurementChart` â€” time-series chart for measurement history (24+ months)
      - `BulkImport` â€” CSV upload component with per-row error reporting
      - `MeasurementValidation` â€” component for clinicians to validate patient-submitted measurements
    - _Requirements: 5.1, 5.2, 5.4, 5.5, 5.7_

  - [ ] 28.2 Create risk dashboard and SHAP visualization components
    - Create `frontend/src/components/risk/`:
      - `RiskDashboard` â€” overview of all 6 disease risk scores with color-coded strata
      - `RiskGauge` â€” individual disease risk gauge (0â€“100 with stratum coloring)
      - `SHAPChart` â€” waterfall/bar chart showing top feature contributions per disease
      - `RiskHistory` â€” historical risk score trend chart
    - _Requirements: 6.1, 6.3, 6.5_

- [ ] 29. Frontend â€” Forecast, AI assistant, and drug interaction UI
  - [ ] 29.1 Create forecast and intervention simulation components
    - Create `frontend/src/components/forecast/`:
      - `ForecastChart` â€” line chart with point estimates and confidence interval bands at 3/6/12 month horizons
      - `InterventionSimulator` â€” form to configure intervention parameters, display baseline vs simulated trajectories
      - `SurvivalCurve` â€” Kaplan-Meier style survival curve visualization
    - _Requirements: 8.1, 8.3, 8.4, 8.7_

  - [ ] 29.2 Create AI assistant chat interface
    - Create `frontend/src/components/assistant/`:
      - `ChatPanel` â€” conversational interface with message input and history
      - `MessageBubble` â€” styled message display (user vs assistant) with advisory label
      - `ContextSidebar` â€” sidebar showing patient context being used by AI
    - _Requirements: 9.1, 9.6_

  - [ ] 29.3 Create drug interaction and medication management components
    - Create `frontend/src/components/drugs/`:
      - `MedicationList` â€” list of active medications with add/edit capability
      - `InteractionAlert` â€” blocking modal for Contraindicated/Major interactions, non-blocking toast for Moderate/Minor
      - `SafetySummary` â€” consolidated medication safety status (Safe/Caution/Action Required)
      - `OverrideForm` â€” form for doctor to override interaction with mandatory justification
    - _Requirements: 10.4, 10.5, 10.8, 10.10_

- [ ] 30. Frontend â€” Alerts, reports, and population dashboard UI
  - [ ] 30.1 Create alert management components
    - Create `frontend/src/components/alerts/`:
      - `AlertBanner` â€” top-of-page banner for critical alerts
      - `AlertHistory` â€” per-patient alert history with severity, channel, acknowledgment status
      - `ThresholdConfig` â€” form for configuring per-patient alert thresholds
    - _Requirements: 11.1, 11.6, 11.8_

  - [ ] 30.2 Create report builder and export components
    - Create `frontend/src/components/reports/`:
      - `ReportBuilder` â€” interface to generate clinical PDF or referral letter
      - `PDFPreview` â€” in-browser PDF preview before download
      - Export buttons for CSV measurement and population exports
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [ ] 30.3 Create population analytics dashboard components
    - Create `frontend/src/components/population/`:
      - `PopulationDashboard` â€” clinic-level metrics overview (total patients, risk distribution, prevalence)
      - `WatchlistTable` â€” high-risk patient watchlist (High/Critical), sortable
      - `TrendChart` â€” cohort-level trend charts with selectable time windows (1/3/6/12 months)
    - _Requirements: 12.1, 12.2, 12.3_

- [ ] 31. Frontend â€” Patient portal (mobile-first)
  - [ ] 31.1 Create patient portal components
    - Create `frontend/src/components/portal/`:
      - `PortalDashboard` â€” simplified risk summary in plain language (no raw scores)
      - `SelfReportForm` â€” form for Patient_User to submit BP, glucose, weight measurements
      - `PendingValidation` â€” display showing pending clinician validation status
      - `PortalTimeline` â€” read-only timeline of clinician-entered measurements
      - `AppointmentReminders` â€” upcoming appointments and reminders
    - Ensure mobile-first responsive design (minimum 320px viewport)
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_

- [ ] 32. Checkpoint â€” Verify frontend components
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 33. Integration wiring â€” Connect all modules end-to-end
  - [ ] 33.1 Wire backend routers into FastAPI app
    - Register all module routers in `backend/app/main.py` under `/api/v1/` prefix
    - Register all middleware (Tenant, RateLimit, Audit)
    - Register exception handlers
    - Configure OpenAPI auto-generation from code annotations
    - _Requirements: 16.1, 16.2_

  - [ ] 33.2 Wire domain event handlers
    - Connect `MeasurementSaved` event â†’ trigger async risk recomputation (Celery task)
    - Connect `RiskScoreComputed` event â†’ evaluate alert thresholds
    - Connect `ForecastCompleted` event â†’ check forecast-based alert conditions
    - Connect `HealthStatusChanged` event â†’ re-evaluate drug interactions
    - _Requirements: 6.8, 8.8, 10.11, 11.3_

  - [ ] 33.3 Wire frontend pages and navigation
    - Create page-level components in `frontend/src/app/`:
      - `LoginPage`, `DashboardPage`, `PatientDetailPage`, `PopulationPage`, `AdminPage`, `PortalPage`
    - Wire React Router with role-based route guards
    - Connect all API calls to backend endpoints
    - Implement background task polling for ML computation results
    - _Requirements: 3.1, 15.5_

  - [ ]* 33.4 Write integration tests for critical flows
    - Test: login â†’ create patient â†’ submit measurement â†’ trigger risk computation â†’ verify alert generation
    - Test: Celery task enqueue â†’ execute â†’ status polling lifecycle
    - Test: SendGrid/Twilio retry queuing on failure (mocked external services)
    - Test: GPT-4o timeout â†’ Claude fallback (mocked LLM providers)
    - _Requirements: 6.8, 11.3, 21.1, 21.3_

- [ ] 34. Dockerization and deployment configuration
  - [ ] 34.1 Create Docker configuration for all services
    - Create `backend/Dockerfile` for FastAPI app
    - Create `frontend/Dockerfile` for React SPA (multi-stage build with nginx)
    - Create `docker-compose.yml` with services: backend, frontend, postgres, redis, celery-worker, celery-beat
    - Configure environment variables, volume mounts, and health checks
    - _Requirements: 19.1, 19.4_

- [ ] 35. Final checkpoint â€” Full system verification
  - Ensure all tests pass across backend, ML engine, and frontend. Verify all module routers are registered, all domain events are wired, and all RBAC rules are enforced. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at logical boundaries
- Property tests validate the 18 correctness properties defined in the design document
- Unit tests validate specific examples and edge cases per module
- The backend uses Python/FastAPI, the frontend uses TypeScript/React, and the ML pipeline uses Python
- All code should be well-commented and modular per user preference
