# Requirements Document

## Introduction

PrescpHealth is a greenfield rebuild of an AI-powered clinical decision support and predictive health SaaS platform targeting clinicians (doctors, nurses, primary healthcare practitioners) in Africa and other underserved communities. The platform predicts disease risk across six conditions simultaneously, forecasts individual health trajectories, and provides a conversational AI clinical assistant — all using basic clinical measurements without requiring imaging. It is a multi-tenant, cloud-hosted system with a React/TypeScript frontend, FastAPI backend, PostgreSQL + Redis data layer, and a Python-based ML/AI engine.

The six diseases covered from day one are: Stroke, Cardiovascular Disease (heart attack, heart failure, AFib), Type 2 Diabetes progression, Chronic Kidney Disease (CKD), Hypertensive Crisis, and COPD progression.

---

## Glossary

- **Platform**: The PrescpHealth SaaS system as a whole.
- **Tenant**: A clinic or healthcare organization with its own isolated data namespace.
- **Super_Admin**: A platform-level administrator with cross-tenant access.
- **Clinic_Admin**: A tenant-level administrator managing users and settings within one clinic.
- **Clinician**: A Doctor or Nurse user who manages patients and reviews AI outputs.
- **Doctor**: A Clinician role with full read/write access to patient data and AI recommendations.
- **Nurse**: A Clinician role with measurement entry and alert acknowledgment permissions.
- **Patient_User**: A limited-access user who can view their own simplified health summary and log basic vitals.
- **Patient**: A healthcare subject whose data is stored and analyzed in the Platform.
- **Risk_Engine**: The ensemble ML service that computes per-disease risk scores.
- **Forecasting_Engine**: The time-series ML service that projects future health metrics and risk trajectories.
- **AI_Assistant**: The conversational AI service (GPT-4o primary, Claude fallback) providing per-patient clinical support.
- **Alert_System**: The notification and escalation service for threshold breaches and forecast-based warnings.
- **Measurement**: A recorded clinical data point (vital sign, lab result, lifestyle factor) for a Patient.
- **Risk_Score**: A numeric value (0–100) representing a Patient's predicted probability of a disease event.
- **SHAP_Explanation**: A feature-importance breakdown produced by SHAP that attributes each input's contribution to a Risk_Score.
- **Confidence_Interval**: A statistical range expressing uncertainty around a predicted value.
- **Intervention_Simulation**: A what-if analysis projecting how a clinical change (medication, weight loss) would alter a Patient's Risk_Score or forecast.
- **Survival_Analysis**: Time-to-event modeling using Cox Proportional Hazards or DeepSurv.
- **Tenant_Isolation**: The guarantee that one Tenant's data is never accessible to another Tenant.
- **Audit_Log**: An immutable, timestamped record of all data-modifying actions.
- **MFA**: Multi-Factor Authentication.
- **JWT**: JSON Web Token used for stateless authentication.
- **RBAC**: Role-Based Access Control.
- **eGFR**: Estimated Glomerular Filtration Rate (kidney function marker).
- **HbA1c**: Glycated haemoglobin (diabetes marker).
- **FEV1/FVC**: Forced Expiratory Volume / Forced Vital Capacity (spirometry markers for COPD).
- **SpO2**: Peripheral oxygen saturation.
- **TFT**: Temporal Fusion Transformer (time-series forecasting model).
- **LSTM**: Long Short-Term Memory neural network.
- **Background_Worker**: A Celery worker process handling async ML inference and notification dispatch.
- **Report_Generator**: The service that produces PDF and CSV exports.
- **Patient_Portal**: The limited-access web interface for Patient_Users.
- **Population_Dashboard**: The clinic-level analytics view available to Clinic_Admin and Doctor roles.
- **Drug_Interaction_Engine**: The service that checks a Patient's current medication list against a structured drug interaction database and the Patient's health history to identify and classify potential interactions.
- **DDI**: Drug-Drug Interaction — an adverse or altered effect caused by two or more drugs taken concurrently.
- **DHI**: Drug-Health Interaction — an adverse or altered drug effect caused by a Patient's existing condition, organ function status (e.g., reduced eGFR), or biomarker level (e.g., elevated potassium).
- **Interaction_Severity**: A classification of a detected interaction: Contraindicated (do not co-administer), Major (significant risk, requires clinical decision), Moderate (monitor closely), Minor (low clinical significance).
- **Medication_Record**: A stored entry representing a drug prescribed or reported for a Patient, including drug name, dosage, frequency, route, start date, and prescribing clinician.

---

## Requirements

### Requirement 1: Multi-Tenant Architecture

**User Story:** As a Clinic_Admin, I want my clinic's data to be completely isolated from other clinics, so that patient confidentiality and regulatory compliance are maintained.

#### Acceptance Criteria

1. THE Platform SHALL enforce Tenant_Isolation such that no API endpoint returns data belonging to a different Tenant than the authenticated user's Tenant.
2. WHEN a new Tenant is registered, THE Platform SHALL provision a unique tenant identifier and associate all subsequent data created by that Tenant's users with that identifier.
3. THE Platform SHALL support a minimum of 500 concurrent Tenants without degradation of per-Tenant query performance beyond 200ms at the 95th percentile.
4. WHEN a Super_Admin performs a cross-tenant operation, THE Platform SHALL record the action in the Audit_Log with the Super_Admin's identity, target Tenant, timestamp, and operation type.
5. IF a request is received that attempts to access a resource belonging to a different Tenant, THEN THE Platform SHALL reject the request with HTTP 403 and log the violation.

---

### Requirement 2: Authentication and Session Management

**User Story:** As a Clinician, I want to securely log in with multi-factor authentication, so that patient data is protected from unauthorized access.

#### Acceptance Criteria

1. THE Platform SHALL authenticate users using JWT access tokens with a maximum lifetime of 15 minutes and refresh tokens with a maximum lifetime of 7 days.
2. WHEN a user submits valid credentials, THE Platform SHALL issue a JWT access token and a refresh token, and record the login event in the Audit_Log.
3. WHEN a refresh token is used, THE Platform SHALL rotate the refresh token and invalidate the previous one.
4. WHERE MFA is enabled for a user account, THE Platform SHALL require a valid TOTP code before issuing tokens.
5. IF a refresh token is presented that has been previously invalidated, THEN THE Platform SHALL reject the request with HTTP 401 and invalidate all active sessions for that user.
6. WHEN a user logs out, THE Platform SHALL invalidate the current refresh token and record the logout event in the Audit_Log.
7. THE Platform SHALL lock a user account after 5 consecutive failed authentication attempts within a 10-minute window and notify the Clinic_Admin via email.

---

### Requirement 3: Role-Based Access Control

**User Story:** As a Clinic_Admin, I want to assign roles to staff members, so that each user can only access the functionality appropriate to their responsibilities.

#### Acceptance Criteria

1. THE Platform SHALL enforce RBAC with the following roles in ascending privilege order: Patient_User, Nurse, Doctor, Clinic_Admin, Super_Admin.
2. WHEN a Clinic_Admin assigns a role to a user, THE Platform SHALL apply the new permissions on the user's next authenticated request without requiring a platform restart.
3. THE Platform SHALL prevent a Nurse from modifying AI-generated Risk_Scores or overriding clinical recommendations.
4. THE Platform SHALL prevent a Patient_User from accessing any other Patient's data.
5. WHEN a Doctor validates a Patient_User-submitted Measurement, THE Platform SHALL record the validating Doctor's identity and timestamp in the Audit_Log before the Measurement affects any Risk_Score.
6. IF a user attempts an action outside their role's permissions, THEN THE Platform SHALL return HTTP 403 and log the attempt.

---

### Requirement 4: Patient Profile Management

**User Story:** As a Doctor, I want to create and maintain comprehensive patient profiles, so that the AI engine has complete context for accurate risk prediction.

#### Acceptance Criteria

1. THE Platform SHALL store the following demographic fields per Patient: full name, date of birth, biological sex, ethnicity, country, contact phone number, and emergency contact.
2. THE Platform SHALL store the following medical history fields per Patient: existing diagnoses (ICD-10 coded), surgical history, family history flags for each of the six covered diseases, known allergies (drug and non-drug), and current medications with dosage and start date.
3. WHEN a Patient profile is created, THE Platform SHALL assign a unique patient identifier that is immutable for the lifetime of the record.
4. THE Platform SHALL support Patient search within a Tenant by: name (partial match), risk level (Low/Moderate/High/Critical), primary disease flag, age range, and biological sex.
5. WHEN a Patient profile field is updated, THE Platform SHALL preserve the previous value in a versioned history accessible to Doctors and Clinic_Admins.
6. THE Platform SHALL display a Patient timeline view showing all Measurements, Risk_Scores, alert events, and AI_Assistant interactions in reverse-chronological order.
7. WHERE wearable device integration hooks are configured, THE Platform SHALL accept inbound data payloads conforming to the defined wearable data schema and queue them for Clinician validation before inclusion in risk computation.

---

### Requirement 5: Clinical Measurement Entry

**User Story:** As a Nurse, I want to record comprehensive clinical measurements for a patient, so that the risk engine has accurate and up-to-date input data.

#### Acceptance Criteria

1. THE Platform SHALL accept the following Measurement types: systolic BP (mmHg), diastolic BP (mmHg), BMI (kg/m²), fasting glucose (mmol/L), HbA1c (%), total cholesterol (mmol/L), HDL cholesterol (mmol/L), LDL cholesterol (mmol/L), triglycerides (mmol/L), creatinine (µmol/L), eGFR (mL/min/1.73m²), SpO2 (%), heart rate (bpm), FEV1 (L), FVC (L), smoking status (categorical), alcohol consumption (units/week), physical activity level (categorical), diet quality score (1–10), and family history flags (boolean per disease).
2. WHEN a Measurement is submitted, THE Platform SHALL validate that the value falls within a physiologically plausible range for the Measurement type and reject out-of-range values with a descriptive error message.
3. THE Platform SHALL record the submitting user's identity, submission timestamp, and data source (clinician-entered, patient-self-reported, wearable) with every Measurement.
4. WHEN a Patient_User submits a self-reported Measurement, THE Platform SHALL mark it as unvalidated and exclude it from Risk_Score computation until a Clinician validates it.
5. THE Platform SHALL display Measurement history for each type as a time-series chart with at least 24 months of data visible.
6. WHEN a Measurement value deviates from the Patient's personal baseline by more than two standard deviations, THE Platform SHALL flag the entry for Clinician review before saving.
7. THE Platform SHALL support bulk Measurement import via CSV upload with a defined column schema, validating each row and reporting per-row errors.

---

### Requirement 6: AI Risk Engine — Core Prediction

**User Story:** As a Doctor, I want to see simultaneous risk scores for all six diseases with explainability, so that I can prioritize clinical attention and justify decisions to patients.

#### Acceptance Criteria

1. THE Risk_Engine SHALL compute Risk_Scores for all six diseases (Stroke, Cardiovascular Disease, Type 2 Diabetes, CKD, Hypertensive Crisis, COPD) simultaneously for a given Patient using the most recent validated Measurements.
2. THE Risk_Engine SHALL use an ensemble architecture comprising: XGBoost (primary), LightGBM, Random Forest, and a neural network, combined by a meta-learner, to produce each Risk_Score.
3. THE Risk_Engine SHALL produce a SHAP_Explanation for each Risk_Score identifying the top contributing features and their directional impact (positive/negative contribution).
4. THE Risk_Engine SHALL produce a Confidence_Interval (95%) for each Risk_Score.
5. THE Risk_Engine SHALL classify each Risk_Score into one of four strata: Low (0–24), Moderate (25–49), High (50–74), Critical (75–100).
6. WHEN a Risk_Score computation is requested, THE Risk_Engine SHALL return results within 3 seconds for a single Patient under normal load.
7. IF a Patient has fewer validated Measurements than the minimum feature set for a disease model, THEN THE Risk_Engine SHALL use population-level Bayesian priors for missing features and indicate which features were imputed in the SHAP_Explanation.
8. WHEN new validated Measurements are saved for a Patient, THE Background_Worker SHALL recompute Risk_Scores asynchronously and update the stored scores within 60 seconds.
9. THE Platform SHALL store each Risk_Score computation result with its input snapshot, model version, timestamp, and SHAP_Explanation for audit and reproducibility.

---

### Requirement 7: AI Risk Engine — Model Quality and Versioning

**User Story:** As a Super_Admin, I want the ML models to be versioned and auditable, so that I can track model changes and ensure clinical reliability.

#### Acceptance Criteria

1. THE Risk_Engine SHALL version every deployed model with a semantic version identifier and deployment timestamp.
2. WHEN a new model version is deployed, THE Platform SHALL retain the previous version and allow rollback by a Super_Admin without downtime.
3. THE Risk_Engine SHALL log the model version used for every Risk_Score computation.
4. THE Platform SHALL expose model performance metrics (AUC-ROC, calibration score, Brier score) per disease per model version to Super_Admins.
5. WHEN a model version is retired, THE Platform SHALL recompute historical Risk_Scores using the new model version only if explicitly triggered by a Super_Admin, and record the recomputation event in the Audit_Log.

---

### Requirement 8: Advanced Forecasting Engine

**User Story:** As a Doctor, I want to see a patient's predicted health trajectory over the next 12 months, so that I can plan proactive interventions before deterioration occurs.

#### Acceptance Criteria

1. THE Forecasting_Engine SHALL forecast individual health metrics (BP, glucose, HbA1c, eGFR, BMI) at 3-month, 6-month, and 12-month horizons for each Patient.
2. THE Forecasting_Engine SHALL use an ensemble of TFT, LSTM, and Prophet models, combining outputs with uncertainty quantification to produce forecast values and Confidence_Intervals.
3. THE Forecasting_Engine SHALL forecast disease Risk_Score trajectories at 3-month, 6-month, and 12-month horizons for all six diseases.
4. THE Forecasting_Engine SHALL perform Survival_Analysis using Cox Proportional Hazards and DeepSurv to estimate time-to-event probabilities for each covered disease.
5. WHEN a Patient has only one validated Measurement, THE Forecasting_Engine SHALL produce forecasts using population-level Bayesian priors and indicate the low-data confidence level in the output.
6. WHEN additional validated Measurements are recorded for a Patient, THE Forecasting_Engine SHALL update forecast accuracy estimates and reduce reliance on population priors proportionally.
7. THE Forecasting_Engine SHALL support Intervention_Simulation: given a specified clinical change (e.g., medication addition, weight reduction target, smoking cessation), THE Forecasting_Engine SHALL produce a revised forecast showing projected metric and Risk_Score changes versus the baseline forecast.
8. WHEN a forecast predicts that a Patient's Risk_Score will cross a High or Critical threshold within 90 days, THE Alert_System SHALL generate a forecast-based alert for the assigned Clinician.
9. WHEN a Forecasting_Engine computation is requested, THE Forecasting_Engine SHALL return results within 10 seconds for a single Patient under normal load.

---

### Requirement 9: AI Clinical Assistant

**User Story:** As a Doctor, I want to have a conversational AI assistant with full patient context, so that I can quickly get evidence-based clinical support without leaving the patient record.

#### Acceptance Criteria

1. THE AI_Assistant SHALL maintain a per-patient conversation thread accessible only to Clinicians assigned to that Patient within the same Tenant.
2. WHEN a Clinician sends a message in a patient conversation, THE AI_Assistant SHALL respond using the full context of that Patient's profile, Measurements, Risk_Scores, medications, and conversation history.
3. THE AI_Assistant SHALL use GPT-4o as the primary language model and automatically fall back to Anthropic Claude when GPT-4o is unavailable or returns an error.
4. WHEN the AI_Assistant provides a clinical recommendation, THE AI_Assistant SHALL include the reasoning chain and reference the specific Patient data points that informed the recommendation.
5. THE AI_Assistant SHALL flag potential drug interactions when a new medication is mentioned in the conversation and cite the interaction mechanism.
6. THE AI_Assistant SHALL clearly label all outputs as advisory and indicate that the Clinician retains final clinical authority.
7. THE Platform SHALL persist all AI_Assistant conversation history per patient with message timestamps, model version used, and the Clinician's identity.
8. WHEN the AI_Assistant is queried, THE AI_Assistant SHALL return a response within 8 seconds under normal load.
9. IF the AI_Assistant cannot produce a confident response due to insufficient data, THEN THE AI_Assistant SHALL state the limitation explicitly rather than speculate.

---

### Requirement 10: Drug Interaction Safety Engine

**User Story:** As a Doctor, I want the platform to automatically check for drug-drug and drug-health interactions whenever I prescribe or review a patient's medications, so that I can prevent adverse events caused by dangerous combinations.

#### Acceptance Criteria

1. THE Drug_Interaction_Engine SHALL maintain a structured interaction database covering DDIs and DHIs, sourced from a recognized pharmacological reference (e.g., DrugBank, RxNorm, or WHO Essential Medicines List).
2. WHEN a new Medication_Record is added to a Patient's profile, THE Drug_Interaction_Engine SHALL automatically check the new drug against all of the Patient's active Medication_Records and return all detected DDIs classified by Interaction_Severity within 2 seconds.
3. WHEN a new Medication_Record is added, THE Drug_Interaction_Engine SHALL also check the drug against the Patient's current health conditions (diagnoses, organ function markers such as eGFR, liver function, and relevant biomarkers) and return all detected DHIs classified by Interaction_Severity.
4. WHEN a Contraindicated or Major interaction is detected, THE Platform SHALL display a blocking alert to the prescribing Clinician that requires explicit acknowledgment before the Medication_Record is saved, and record the acknowledgment decision and rationale in the Audit_Log.
5. WHEN a Moderate or Minor interaction is detected, THE Platform SHALL display a non-blocking warning to the Clinician with the interaction mechanism, affected drugs, and recommended monitoring actions.
6. THE Drug_Interaction_Engine SHALL consider the Patient's age, biological sex, weight, renal function (eGFR), and hepatic function when assessing DHIs, flagging dose adjustments required for impaired organ function.
7. THE Drug_Interaction_Engine SHALL provide for each detected interaction: the interacting drugs or drug-condition pair, the Interaction_Severity, the clinical mechanism, the potential adverse outcome, and a recommended action (e.g., avoid combination, reduce dose, monitor specific lab value).
8. THE Platform SHALL display a consolidated medication safety summary on the Patient dashboard showing all active medications, any current interactions, and an overall medication safety status (Safe, Caution, Action Required).
9. WHEN the AI_Assistant is queried about a Patient's medications, THE AI_Assistant SHALL incorporate the Drug_Interaction_Engine's findings into its response, referencing specific interactions and their severity.
10. THE Platform SHALL support manual override of interaction alerts by a Doctor with a mandatory free-text clinical justification, recorded in the Audit_Log.
11. WHEN a Patient's health status changes (e.g., new diagnosis, significant eGFR decline, new lab result), THE Drug_Interaction_Engine SHALL re-evaluate all active Medication_Records against the updated health profile and generate new DHI alerts if applicable.

---

### Requirement 11: Alert and Notification System

**User Story:** As a Nurse, I want to receive immediate alerts when a patient's metrics cross critical thresholds, so that I can escalate care before a clinical emergency occurs.

#### Acceptance Criteria

1. THE Alert_System SHALL support configurable alert thresholds per Patient and per disease, settable by Doctors and Clinic_Admins.
2. THE Alert_System SHALL deliver alerts via the following channels: in-app notification, email (via SendGrid), SMS (via Twilio), and WhatsApp.
3. WHEN a validated Measurement causes a Risk_Score to enter the Critical stratum, THE Alert_System SHALL dispatch a Critical alert to the assigned Clinician within 60 seconds via all configured channels.
4. WHEN a forecast-based alert is generated, THE Alert_System SHALL include the forecasted metric, the projected threshold-crossing date, and the Confidence_Interval in the alert payload.
5. THE Alert_System SHALL support alert escalation: if a Nurse does not acknowledge a Critical alert within 15 minutes, THE Alert_System SHALL escalate the alert to the assigned Doctor; if the Doctor does not acknowledge within 30 minutes, THE Alert_System SHALL escalate to the Clinic_Admin.
6. WHEN a Clinician acknowledges an alert, THE Alert_System SHALL record the acknowledging user's identity, timestamp, and any notes in the Audit_Log.
7. THE Alert_System SHALL support a "missed follow-up" alert type: WHEN a Patient has no new Measurements recorded within a Clinician-configured interval, THE Alert_System SHALL notify the assigned Clinician.
8. THE Platform SHALL display an alert history per Patient showing all past alerts, their severity, dispatch channel, acknowledgment status, and resolution notes.

---

### Requirement 12: Population Analytics Dashboard

**User Story:** As a Clinic_Admin, I want a clinic-wide analytics view, so that I can monitor population health trends and identify high-risk cohorts for proactive outreach.

#### Acceptance Criteria

1. THE Population_Dashboard SHALL display the following clinic-level metrics: total active Patients, risk distribution (count and percentage per stratum per disease), disease prevalence rates, and average Risk_Score per disease.
2. THE Population_Dashboard SHALL display a high-risk watchlist showing all Patients currently in the High or Critical stratum for any disease, sortable by Risk_Score and last-updated timestamp.
3. THE Population_Dashboard SHALL display trend charts for cohort-level metrics over selectable time windows of 1 month, 3 months, 6 months, and 12 months.
4. THE Population_Dashboard SHALL display outcome tracking: for each disease, the percentage of High/Critical predictions that were followed by a recorded clinical event within 90 days.
5. WHEN a Clinic_Admin requests a population report, THE Report_Generator SHALL produce a PDF report containing all dashboard metrics, trend charts, and the high-risk watchlist within 30 seconds.
6. THE Population_Dashboard SHALL refresh its aggregate metrics at intervals no greater than 1 hour.

---

### Requirement 13: Patient Portal

**User Story:** As a Patient_User, I want to view a simplified summary of my health status and log my own vitals, so that I can stay engaged in my care between clinic visits.

#### Acceptance Criteria

1. THE Patient_Portal SHALL display to the Patient_User a simplified risk summary using plain language (e.g., "Your heart health risk is moderate") without exposing raw numeric Risk_Scores or clinical model details.
2. THE Patient_Portal SHALL allow a Patient_User to submit self-reported Measurements for: systolic BP, diastolic BP, fasting glucose, and body weight.
3. WHEN a Patient_User submits a self-reported Measurement, THE Patient_Portal SHALL display a confirmation that the entry is pending Clinician validation and will not affect their risk summary until validated.
4. THE Patient_Portal SHALL display upcoming follow-up appointments and reminder notifications configured by the assigned Clinician.
5. THE Patient_Portal SHALL display Clinician-entered Measurements in a read-only timeline view.
6. THE Patient_Portal SHALL be fully functional on mobile viewports with a minimum width of 320px.
7. WHERE wearable device integration is configured for a Patient, THE Patient_Portal SHALL display the most recent wearable data sync timestamp and pending validation status.

---

### Requirement 14: PDF and Report Generation

**User Story:** As a Doctor, I want to generate a comprehensive clinical report for a patient, so that I can share findings with specialists or include them in referral letters.

#### Acceptance Criteria

1. THE Report_Generator SHALL produce a per-patient PDF clinical report containing: patient demographics, current medications, all Risk_Scores with SHAP_Explanations, forecast charts, Measurement history charts, and active alerts.
2. THE Report_Generator SHALL produce a referral letter PDF with an AI-generated clinical summary, configurable by the Doctor before export.
3. THE Report_Generator SHALL support CSV export of a Patient's full Measurement history.
4. THE Report_Generator SHALL support CSV export of the Population_Dashboard's patient list with risk scores.
5. WHEN a PDF report is requested, THE Report_Generator SHALL produce the file within 15 seconds for a single-patient report.
6. THE Report_Generator SHALL embed all charts as vector graphics (SVG rendered to PDF) to ensure legibility at any print resolution.

---

### Requirement 15: Background Task Processing

**User Story:** As a Clinic_Admin, I want ML inference and notifications to run asynchronously, so that the user interface remains responsive during computationally intensive operations.

#### Acceptance Criteria

1. THE Background_Worker SHALL process Risk_Score recomputation tasks using a Celery task queue backed by Redis.
2. THE Background_Worker SHALL process Forecasting_Engine tasks using the same Celery queue with a separate priority lane from Risk_Score tasks.
3. THE Background_Worker SHALL process notification dispatch tasks with higher priority than ML inference tasks.
4. WHEN a Background_Worker task fails, THE Platform SHALL retry the task up to 3 times with exponential backoff before marking it as failed and alerting the Super_Admin.
5. THE Platform SHALL expose a task status endpoint allowing the frontend to poll for completion of long-running Background_Worker tasks using a task identifier.

---

### Requirement 16: API Design and Documentation

**User Story:** As a developer integrating with PrescpHealth, I want a well-documented RESTful API, so that I can build integrations reliably.

#### Acceptance Criteria

1. THE Platform SHALL expose all functionality through a RESTful API with OpenAPI 3.0 specification auto-generated from code annotations.
2. THE Platform SHALL version the API with a URL path prefix (e.g., /api/v1/) and maintain backward compatibility within a major version.
3. WHEN an API request fails validation, THE Platform SHALL return HTTP 422 with a structured error body identifying each invalid field and the reason for rejection.
4. THE Platform SHALL enforce API rate limiting per authenticated user: 1000 requests per minute for Clinician roles and 100 requests per minute for Patient_User roles.
5. IF a rate limit is exceeded, THEN THE Platform SHALL return HTTP 429 with a Retry-After header indicating when the limit resets.

---

### Requirement 17: Non-Functional — Performance

**User Story:** As a Clinician in a low-bandwidth environment, I want the platform to respond quickly, so that I can use it effectively during busy clinic hours.

#### Acceptance Criteria

1. THE Platform SHALL serve all non-ML API responses within 200ms at the 95th percentile under a load of 200 concurrent users per Tenant.
2. THE Platform SHALL serve the React frontend initial page load within 3 seconds on a 3G mobile connection (simulated at 1.6 Mbps).
3. THE Platform SHALL cache frequently accessed read-only data (patient demographics, static reference data) in Redis with a TTL of 300 seconds.
4. WHEN Redis cache is unavailable, THE Platform SHALL fall back to direct PostgreSQL queries and log the cache miss without returning an error to the user.

---

### Requirement 18: Non-Functional — Security

**User Story:** As a Clinic_Admin, I want the platform to meet healthcare data security standards, so that my clinic can comply with applicable regulations.

#### Acceptance Criteria

1. THE Platform SHALL encrypt all data at rest using AES-256 and all data in transit using TLS 1.2 or higher.
2. THE Platform SHALL store passwords using bcrypt with a minimum cost factor of 12.
3. THE Platform SHALL sanitize all user-supplied input to prevent SQL injection and cross-site scripting (XSS) attacks.
4. THE Platform SHALL produce an Audit_Log entry for every create, update, and delete operation on Patient data, including the user identity, timestamp, changed fields, and previous values.
5. THE Audit_Log SHALL be append-only; no user role including Super_Admin SHALL be able to delete or modify Audit_Log entries through the application API.
6. THE Platform SHALL support IP allowlisting per Tenant, configurable by Clinic_Admin, rejecting requests from non-allowlisted IPs with HTTP 403.

---

### Requirement 19: Non-Functional — Scalability and Availability

**User Story:** As a Super_Admin, I want the platform to scale horizontally, so that it can serve a growing number of clinics without architectural changes.

#### Acceptance Criteria

1. THE Platform SHALL be deployable as Docker containers orchestrated by a container scheduler (Kubernetes or ECS) to support horizontal scaling of the API and Background_Worker tiers independently.
2. THE Platform SHALL maintain 99.5% monthly uptime for the API tier, excluding scheduled maintenance windows communicated at least 48 hours in advance.
3. WHEN the API tier scales horizontally, THE Platform SHALL maintain session consistency using Redis-backed token storage so that any API instance can validate any user's JWT.
4. THE Platform SHALL support zero-downtime deployments using rolling update strategies.

---

### Requirement 20: Non-Functional — Compliance and Data Governance

**User Story:** As a Clinic_Admin, I want the platform to support data export and deletion requests, so that my clinic can comply with patient data rights regulations.

#### Acceptance Criteria

1. THE Platform SHALL support full export of all data associated with a Patient in JSON format, producible by a Clinic_Admin within 24 hours of request.
2. THE Platform SHALL support logical deletion of a Patient record (soft delete with anonymization of PII fields) by a Clinic_Admin, preserving anonymized aggregate data for model training purposes.
3. THE Platform SHALL retain Audit_Log entries for a minimum of 7 years regardless of Patient deletion status.
4. THE Platform SHALL allow a Super_Admin to configure the data residency region for a Tenant's primary database at Tenant creation time.

---

### Requirement 21: Integration — External Services

**User Story:** As a Super_Admin, I want all external service integrations to be resilient, so that a third-party outage does not cause platform-wide failures.

#### Acceptance Criteria

1. WHEN SendGrid is unavailable, THE Alert_System SHALL queue email notifications and retry delivery for up to 24 hours before marking the notification as failed.
2. WHEN Twilio is unavailable, THE Alert_System SHALL queue SMS notifications and retry delivery for up to 6 hours before marking the notification as failed.
3. WHEN GPT-4o returns an error or times out after 8 seconds, THE AI_Assistant SHALL automatically retry the request using Anthropic Claude without user intervention.
4. THE Platform SHALL not expose raw API keys for SendGrid, Twilio, OpenAI, or Anthropic in any client-side code or API response.
5. THE Platform SHALL log all outbound calls to external services with request metadata, response status, and latency for observability.

---

## Correctness Properties for Property-Based Testing

### Property 1: Tenant Isolation Invariant

FOR ALL pairs of Tenants (T1, T2) where T1 ≠ T2, and FOR ALL API requests authenticated as a user of T1, THE Platform SHALL return zero records belonging to T2. This is an invariant: no sequence of valid API calls by a T1 user can produce a response containing T2 data.

### Property 2: Risk Score Range Invariant

FOR ALL valid Measurement inputs to THE Risk_Engine, each returned Risk_Score SHALL be a numeric value in the closed interval [0, 100]. This invariant holds regardless of the combination, magnitude, or sparsity of input features.

### Property 3: Risk Stratification Consistency

FOR ALL Risk_Scores produced by THE Risk_Engine, the assigned stratum SHALL be consistent with the score value: score in [0,24] → Low, [25,49] → Moderate, [50,74] → High, [75,100] → Critical. This is a deterministic mapping with no exceptions.

### Property 4: SHAP Explanation Completeness

FOR ALL Risk_Score computations, the sum of absolute SHAP values across all features SHALL account for the full difference between the model's base value and the predicted Risk_Score (within floating-point tolerance of 0.01). This is the SHAP additivity invariant.

### Property 5: Measurement Validation Round-Trip

FOR ALL Measurements submitted by a Clinician and accepted by THE Platform, a subsequent GET request for that Patient's Measurement history SHALL return the submitted value unchanged. This is a write-then-read round-trip property.

### Property 6: Audit Log Append-Only Invariant

FOR ALL sequences of create/update/delete operations on Patient data, the count of Audit_Log entries SHALL be monotonically non-decreasing. No operation available through the API SHALL reduce the Audit_Log entry count.

### Property 7: Forecast Confidence Interval Containment

FOR ALL forecasts produced by THE Forecasting_Engine, the point estimate SHALL fall within the returned 95% Confidence_Interval bounds. Formally: lower_bound ≤ point_estimate ≤ upper_bound for every forecast horizon.

### Property 8: Role Permission Monotonicity

FOR ALL role pairs (R_lower, R_higher) where R_higher has strictly greater privilege than R_lower, the set of permitted API actions for R_higher SHALL be a strict superset of those permitted for R_lower. No privilege escalation path SHALL exist that grants R_lower access to R_higher actions.

### Property 9: Patient Self-Report Exclusion Until Validated

FOR ALL unvalidated Patient_User-submitted Measurements, THE Risk_Engine SHALL produce identical Risk_Scores before and after the unvalidated Measurement is stored. The Risk_Score SHALL only change after a Clinician validation event is recorded.

### Property 10: Intervention Simulation Monotonicity (Directional)

FOR Intervention_Simulations involving risk-reducing interventions (e.g., weight loss, smoking cessation, medication addition with known efficacy), THE Forecasting_Engine SHALL produce a simulated Risk_Score trajectory that is less than or equal to the baseline trajectory at every forecast horizon. This is a metamorphic property: the direction of a known beneficial intervention must be reflected in the forecast direction.

### Property 11: Alert Escalation Ordering

FOR ALL Critical alerts generated by THE Alert_System, the escalation sequence SHALL strictly follow the order: Nurse → Doctor → Clinic_Admin. No alert SHALL skip a level in the escalation chain, and no escalation SHALL occur before the configured acknowledgment timeout for the current level has elapsed.

### Property 12: CSV Export Round-Trip

FOR ALL Patient Measurement histories exported as CSV by THE Report_Generator, re-importing the CSV via the bulk import endpoint SHALL produce Measurement records with values identical to the originals (within the precision of the CSV format). This is a serialization round-trip property.

### Property 13: Concurrent Measurement Idempotency

FOR ALL duplicate Measurement submissions (same Patient, same type, same timestamp, same value) submitted concurrently, THE Platform SHALL store exactly one Measurement record. The idempotency key is the combination of (patient_id, measurement_type, recorded_at, value).

### Property 14: Token Rotation Invalidation

FOR ALL refresh token rotation events, the previous refresh token SHALL be rejected on all subsequent uses. Formally: after a rotation event E producing token T_new from T_old, any request presenting T_old SHALL receive HTTP 401 regardless of T_old's original expiry time.
