# PrescpHealth — Product Design Document

## Status: DRAFT (In Progress)

This document captures product-level decisions about how PrescpHealth works from the user's perspective. It guides frontend design, ML behavior, and UX patterns.

---

## 1. Global Positioning

**Decision: Built for underserved communities, works everywhere.**

PrescpHealth is NOT an "Africa-only" app. It is a global clinical decision support platform that:
- Launches in Africa (where the need is greatest and competition is lowest)
- Works in any country, any clinic, any healthcare system
- Adapts to local standards, regulations, and workflows via configuration

### What's Configurable Per Tenant (Region-Adaptive)

| Feature | Africa Config | US Config | UK Config | Any Country |
|---------|--------------|-----------|-----------|-------------|
| Risk scoring system | WHO/ISH Risk Charts | Framingham | QRISK3 | Configurable per tenant |
| Languages | English, French, Portuguese | English, Spanish | English | Any (i18n framework) |
| Insurance providers | NHIS (Nigeria), NHIF (Kenya) | Medicare, Aetna, UHC | NHS | Configurable list |
| Regulatory compliance | NDPR, POPIA | HIPAA | UK GDPR | Toggle per regulation |
| Measurement units | Metric (SI) | Imperial option | Metric | Configurable |
| Currency | NGN, KES, ZAR | USD | GBP | Configurable |
| Data residency | Africa region | US region | EU region | Per-tenant setting |
| Performance baseline | 3G optimized | Broadband | Broadband | Adapts to connection |

### What's Already Global (No Configuration Needed)

- **FHIR R4** — international health data exchange standard
- **ICD-10** — used in 144 countries for disease coding
- **ATC** — WHO drug classification (global)
- **LOINC** — universal lab test coding
- **SNOMED CT** — international clinical terminology
- **HIPAA-level security** — strictest standard, covers all lesser regulations
- **Multi-tenant architecture** — each clinic is isolated regardless of country
- **ML models** — trained on diverse populations, not region-locked

### Market Strategy

1. **Launch market:** Africa (underserved, high NCD burden, low competition)
2. **Expansion:** Southeast Asia, Latin America (similar profiles)
3. **Premium market:** US/UK/EU (compete on AI + UX, not just EMR)

The same codebase serves all markets. Regional differences are configuration, not code.

---

## 2. Disease Selection

**Decision: 6 Non-Communicable Diseases (NCDs)**

**Decision: 6 Non-Communicable Diseases (NCDs)**

| # | Disease | Why | Standard Used |
|---|---------|-----|---------------|
| 1 | Stroke | #1 preventable killer, subset of CVD | WHO/ISH Risk Charts |
| 2 | Cardiovascular Disease (CVD) | #1 NCD killer in Africa (37% of NCD deaths) | WHO/ISH + Framingham |
| 3 | Type 2 Diabetes | #3 NCD killer, rising fast in Africa | FINDRISC + HbA1c thresholds |
| 4 | Chronic Kidney Disease (CKD) | Downstream of diabetes + hypertension | KDIGO 2024 (eGFR + ACR staging) |
| 5 | Hypertensive Crisis | #1 risk factor for CVD and stroke | ACC/AHA BP Guidelines |
| 6 | COPD | #4 NCD killer (chronic respiratory) | GOLD 2026 (FEV1/FVC staging) |

**Why NCDs?** The leading causes of death in Africa have shifted from communicable diseases (HIV, malaria, TB) to non-communicable diseases in adults. NCDs now account for the majority of adult mortality. These 6 are all:
- Predictable from basic clinical measurements (BP, glucose, cholesterol, lung function)
- Preventable with early intervention
- Interconnected (hypertension → stroke → CVD → CKD is one cascade)

**What's excluded and why:**
- Cancer — requires imaging/pathology data we don't collect from vitals
- HIV/Malaria/TB — infectious diseases requiring different prediction models (viral load, parasite counts)

---

## 2. Scoring Standards

**Decision: Hybrid approach — established standards + ML + unified 0-100 gauge**

### Foundation Layer (Established Clinical Standards)
Each disease uses a recognized, validated clinical scoring system as its baseline:

| Disease | Standard | Output Format |
|---------|----------|---------------|
| CVD/Stroke | WHO/ISH Risk Charts (designed for Africa) | 10-year % risk |
| CKD | KDIGO 2024 heat map | Stage G1-G5 + ACR category |
| Diabetes | FINDRISC + HbA1c | Risk category + lab threshold |
| COPD | GOLD 2026 | Stage 1-4 based on FEV1/FVC |
| Hypertensive Crisis | ACC/AHA BP Guidelines | Normal/Elevated/Stage1/Stage2/Crisis |

### ML Enhancement Layer
Our ensemble ML models learn from real patient outcomes and adjust predictions beyond what static formulas can do. The ML layer:
- Uses the standard score as a feature (not a replacement)
- Incorporates patient history, trends, and cross-disease interactions
- Produces a refined 0-100 score with confidence intervals
- Logs which standard was used and how much the ML adjusted

### Unified 0-100 Presentation
All 6 diseases are normalized to a consistent 0-100 scale:
- **0-24: Low** (green)
- **25-49: Moderate** (amber)
- **50-74: High** (orange)
- **75-100: Critical** (red)

---

## 3. Clinical Intelligence Behavior

**Decision: On-demand risk scores + ML-driven smart alerts**

### Risk Score Display
- Risk scores are NOT shown automatically when a patient record opens
- Clinician clicks a "Compute Risk" button to trigger computation
- Results appear after async computation (Celery task, ~5 seconds)
- Once computed, scores are cached and shown on subsequent visits until new data arrives

### Smart Alert System (ML-Driven)
- The system learns WHEN to speak and when to stay quiet
- **Always alert (critical scenarios):**
  - BP > 180/120 during vitals entry (hypertensive crisis)
  - Risk score jumps from Moderate to Critical between visits
  - Lab result flagged as abnormal (outside reference range)
  - Drug interaction severity = Contraindicated
- **Learn to alert (ML decides):**
  - Gradual risk trend upward over 3+ visits
  - Patient missed follow-up appointment
  - Measurement deviation > 2σ from baseline
- **Never alert (noise reduction):**
  - Normal readings within expected range
  - Stable risk scores with no change
  - Routine lab results within reference range

---

## 4. Presentation Design

**Decision: Layered information architecture — glance → read → deep dive**

### Layer 1: Glance (2 seconds)
- Clean 0-100 gauge with color gradient (green → amber → orange → red)
- Single number + stratum label ("72 — High Risk")
- Traffic light indicators on critical modules (red/yellow/green dots)

### Layer 2: Read (10 seconds)
- One-line plain-language summary ("Stroke risk elevated due to uncontrolled blood pressure")
- Top 3 contributing factors with direction arrows (↑ BP, ↑ cholesterol, ↑ age)
- Trend indicator (↑ rising, → stable, ↓ improving)

### Layer 3: Deep Dive (when clinician has time)
- Underlying clinical standard score (e.g., "WHO/ISH: 20-30% 10-year risk")
- Which standard was used as the baseline
- How the ML model adjusted it (e.g., "+12 points from personal history pattern")
- Full SHAP waterfall chart showing all feature contributions
- Historical risk score trend chart (last 12 months)
- Confidence interval bands

### Traffic Light System
- Used for modules/functions that need quick attention
- **Red** = critical, needs immediate action (e.g., hypertensive crisis alert)
- **Yellow** = caution, review when possible (e.g., moderate risk increase)
- **Green** = normal, no action needed
- Applied to: patient list badges, alert banners, measurement flags, drug interactions

---

## 5. ML Architecture

**Decision: Most powerful ensemble + local/cloud LLM integration**

### Ensemble (Prediction Engine)
- XGBoost + LightGBM + Random Forest + Neural Network
- Meta-learner (logistic regression) combines base model outputs
- Bayesian imputation for missing features
- SHAP explainability on every prediction
- Model versioning with rollback capability

### LLM Integration (Interpretation Engine)
- Primary: Cloud LLM (GPT-4o or Claude) for clinical interpretation
- Fallback: Local LLM (Ollama with medical-tuned model) for data sovereignty
- The LLM does NOT make predictions — it EXPLAINS them in natural language
- Clinician can ask questions about risk factors, interventions, patient history
- All LLM interactions are logged and auditable

### Data Sovereignty Options
- **Cloud mode**: LLM calls go to OpenAI/Anthropic (anonymized patient context)
- **Local mode**: Ollama runs on hospital infrastructure (full data stays on-premises)
- **Hybrid mode**: Predictions local, explanations cloud (best of both)
- Configurable per tenant (some hospitals require full local)

---

## 6. User Workflows

**Status: ✅ COMPLETE**

### Design Decisions

| Decision | Choice |
|----------|--------|
| Doctor morning routine | Configurable — includes ward rounds (hospital) OR dashboard review (office) |
| Consultation style | Configurable per tenant — walk-in, scheduled appointments, or both |
| AI assistant visibility | On-demand + proactive when something important changed (quiet by default) |
| Risk re-computation | Hybrid — auto-triggers on new measurements (with non-blocking notification popup), on-demand for full re-analysis |

---

### 6.1 Doctor Workflow

#### Morning Start — Depends on Setting

**Hospital setting (ward rounds):**
1. Open app → **Inpatient List** (admitted patients on their ward)
2. Sort by: most critical first (overnight alerts bubble up)
3. Tap patient → see overnight vitals summary, new lab results, risk changes
4. AI proactively surfaces: "BP spiked at 3am, stroke risk recalculated to 78 (was 62)"
5. Quick actions: order labs, adjust meds, add note — all from ward round view
6. Complete round → switch to outpatient appointments

**Office/clinic setting:**
1. Open app → **Dashboard** (today's schedule + critical alerts)
2. Review overnight alerts (patients whose risk changed significantly)
3. Pending lab results needing review
4. Start first appointment

#### Patient Consultation (Universal)

1. **Patient chart opens** → glance view:
   - 6 risk gauges (small, top of screen)
   - "Risk changed" badge if auto-recomputed since last visit
   - Active medications count + safety status indicator
   - AI notification dot (if AI has something proactive to say)

2. **During encounter:**
   - SOAP note (structured input)
   - Order labs (LOINC code search)
   - Write prescriptions (ATC code search → DDI fires immediately)
   - Enter measurements (auto-triggers risk re-computation in background)
   - **Popup notification:** "Risk scores updated — Stroke: 62→71 ⬆️" (non-blocking, dismissible)
   - Click AI dot → "Since last visit: HbA1c trending up (6.1→6.8), diabetes risk moved from Moderate to High. Key driver: weight gain +4kg. Consider metformin dose adjustment."

3. **Close encounter:**
   - Add/confirm diagnoses (ICD-10)
   - Set follow-up interval (drives missed follow-up alerts)
   - Discharge summary auto-generated
   - Click "Full Re-analysis" for deep re-computation with all updated factors

#### End of Day
- Review unsigned notes
- Review unacknowledged alerts
- Check population watchlist (optional — Clinic_Admin usually handles this)

---

### 6.2 Nurse Workflow

#### Morning Start
1. Open app → **Task Queue** (highest priority first)
   - Patients arriving for vitals
   - Pending medication administrations
   - Alerts needing acknowledgment (escalated to them)

#### Core Loop (All Day — High Volume)

2. **Patient arrives** (walk-in or appointment)
   - Scan/search patient → quick demographics confirmation
   - **Vitals entry screen** (optimized for speed):
     - BP (systolic/diastolic)
     - Heart rate
     - Temperature
     - Weight
     - SpO2
     - Blood glucose (if diabetic flag)
   - One-tap "Save All" → measurements saved → risk auto-recomputes in background
   - If any measurement out of range → immediate red flag on screen
   - **Popup:** "Critical: Systolic BP 195 — threshold breached. Alert generated for Dr. [Name]"

3. **Triage decisions:**
   - See risk summary (simplified — gauges only, no deep SHAP)
   - Flag patient as urgent if needed
   - Route to appropriate doctor

4. **Alert management:**
   - Acknowledge alerts assigned to them (15-min window before escalation)
   - Record brief notes on action taken
   - If they cannot handle → explicitly escalate to doctor

5. **Medication administration (hospital):**
   - View active prescriptions for patient
   - Record administration (time, dose, route)
   - Flag any patient-reported side effects

#### Nurse Does NOT:
- Write prescriptions
- Order labs (configurable by tenant — some settings allow it)
- Access AI assistant (Doctor-only in v1)
- Modify risk thresholds
- Access SHAP explanations or deep risk analysis

---

### 6.3 Lab Tech Workflow

#### Morning Start
1. Open app → **Lab Queue** (pending orders, sorted by priority)
   - STAT orders at top (red)
   - Routine orders below
   - Shows: patient name, test ordered, ordering doctor, time ordered

#### Core Loop (Batch Processing)

2. **Process samples:**
   - Mark order as "Specimen Collected"
   - Mark as "Processing"
   - Enter results when ready:
     - LOINC code pre-filled from order
     - Enter value + units
     - System auto-flags if abnormal (reference range comparison)
     - System auto-computes `is_abnormal` flag

3. **Result entry:**
   - Single result entry (one test at a time)
   - Batch result entry (multiple tests from same panel)
   - On save:
     - Creates Measurement record automatically
     - Publishes `MeasurementSaved` + `LabResultReceived` events
     - If abnormal → alert generated for ordering doctor
     - Risk auto-recomputes in background

4. **Critical value protocol:**
   - If result is critically abnormal (defined per test type):
     - System forces "Critical Value Acknowledgment" before saving
     - Immediate alert to ordering doctor (all channels)
     - Lab tech must document that they called the doctor

#### Lab Tech Does NOT:
- View risk scores or forecasts
- Access AI assistant
- Write prescriptions
- Access other patients' data (only those with pending lab orders)
- Modify patient demographics

---

### 6.4 Patient Workflow (Patient Portal)

#### Design Philosophy
- **Simple, reassuring, non-alarming**
- No raw numbers (no "72/100 stroke risk")
- Plain language only ("Your heart health is good")
- Encourage engagement without causing anxiety

#### First Visit (Onboarding)
1. Receive invitation link from clinic
2. Create account (email/phone + password)
3. MFA setup (TOTP or SMS)
4. See welcome screen: "Your health journey starts here"

#### Regular Use

5. **Home screen:**
   - Overall health status (traffic light: green/amber/red)
   - Plain language summary: "Your health markers are mostly stable. Your blood sugar needs attention."
   - Next appointment date
   - "Log Vitals" button (prominent)
   - Recent messages from care team

6. **Log vitals (self-reported):**
   - Weight
   - Blood pressure (if they have home monitor)
   - Blood glucose (if diabetic with glucometer)
   - Exercise minutes
   - Smoking status update
   - Symptoms (free text — reviewed by doctor later)
   - Note: Self-reported measurements marked `is_validated=False` — excluded from risk computation until validated by clinician

7. **View health summary:**
   - "Your Numbers" — latest measurements with trend arrows (↑↓→)
   - NO risk scores shown (only plain language interpretation)
   - NO SHAP explanations
   - Medication list with schedule reminders
   - "Tips for You" — AI-generated lifestyle suggestions (generic, not based on risk score)

8. **Notifications:**
   - Appointment reminders (24h before)
   - "Time to log your vitals" (configurable frequency)
   - "New message from your doctor"
   - NEVER: "Your stroke risk is critical" — this goes to the doctor, not the patient

#### Patient Does NOT:
- See numeric risk scores
- See SHAP explanations
- Access AI assistant
- View other patients' data
- Modify prescriptions or lab orders
- Acknowledge clinical alerts

---

### 6.5 Screen Map

#### Doctor Screens (9)
1. Dashboard (morning overview / today's schedule)
2. Inpatient List (ward round mode — hospital only)
3. Appointment Schedule
4. Patient Chart (main work screen)
   - Risk Dashboard (6 gauges + trend)
   - Measurements Timeline
   - Medications + Safety Status
   - AI Assistant Panel (on-demand)
   - Encounters History
   - Lab Results
   - Alerts History
5. SOAP Note Editor
6. Prescription Writer (with live DDI check)
7. Lab Order Form (LOINC search)
8. Population Watchlist
9. Reports (generate/download PDF/CSV)

#### Nurse Screens (6)
1. Task Queue (prioritized work list)
2. Vitals Entry (speed-optimized, one-tap save)
3. Patient Quick View (simplified chart — gauges + meds + alerts)
4. Alert Management (acknowledge / escalate)
5. Medication Administration (hospital — record doses)
6. Triage View (flag urgency, route to doctor)

#### Lab Tech Screens (5)
1. Lab Queue (pending orders by priority)
2. Result Entry Form (single test)
3. Batch Result Entry (panel of tests)
4. Critical Value Protocol Screen (forced acknowledgment)
5. Order History (their processed results)

#### Patient Portal Screens (7)
1. Home (health status traffic light + summary)
2. Log Vitals (weight, BP, glucose, exercise)
3. My Numbers (measurements history with trends)
4. My Medications (list + schedule reminders)
5. Messages (clinician communication)
6. Appointments (upcoming + history)
7. Settings (profile, notifications, language preference)

---

### 6.6 UX Principles

1. **Role-appropriate complexity** — Doctors get depth, Nurses get speed, Patients get simplicity
2. **Information on demand** — Show summary first, drill down when asked
3. **Non-blocking notifications** — Risk updates popup but don't stop workflow
4. **Clinical silence by default** — AI speaks only when it has something important
5. **Mobile-first for Nurses** — Walking between patients, need one-hand operation
6. **Desktop-first for Doctors** — Complex chart review needs screen real estate
7. **Accessibility always** — WCAG 2.1 AA minimum, high contrast, keyboard navigation
8. **3G baseline** — All screens must load and function on slow connections (Africa/rural)
9. **Offline tolerance** — Patient portal should have basic offline read access (service worker)

---

## 7. Open Questions (Resolved)

| # | Question | Answer |
|---|----------|--------|
| 1 | Should the patient portal show risk scores? | **No.** Plain language only ("Your heart health is good"). No raw numbers. |
| 2 | Should the system send SMS alerts to patients for missed follow-ups? | **No.** Missed follow-up alerts go to the CLINICIAN, not the patient. Patient gets "Time to log your vitals" reminders only. |
| 3 | Should risk computation happen automatically? | **Hybrid.** Auto-triggers on new measurements (with non-blocking popup notification to clinician). Full re-analysis is on-demand. |
| 4 | How to handle cold-start (new patient)? | **Bayesian prior fallback.** Use population-level priors from public datasets. Get better as local data accumulates. (Patent Candidate 3) |
| 5 | Should the LLM suggest interventions? | **Yes, but advisory only.** AI can say "Consider metformin dose adjustment" but always with "⚠️ AI-generated — verify independently" label. Never presented as instructions. |

---

## Document History

| Date | Change |
|------|--------|
| 2026-05-28 | Initial draft — diseases, scoring, intelligence, presentation, ML decisions captured |
| 2026-06-01 | User workflows complete — all 4 roles (Doctor, Nurse, Lab Tech, Patient) with screen maps and UX principles |
| 2026-06-01 | Open questions resolved — all 5 answered with design decisions |
