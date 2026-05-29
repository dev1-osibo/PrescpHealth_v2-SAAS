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

**Status: 🔴 RESEARCH NEEDED — requires 2-3 sessions**

Need deep research into:
- How nurses work in African clinics (daily flow, tools, pain points)
- How doctors work (consultation flow, decision points, documentation)
- How lab technicians work (order receipt, processing, result entry)
- How patients interact with health systems (portal, self-reporting)

This will be completed in a separate research session.

---

## 7. Open Questions (To Be Resolved)

1. Should the patient portal show risk scores in plain language or just "healthy/at risk/needs attention"?
2. Should the system send SMS alerts to patients for missed follow-ups?
3. Should risk computation happen automatically after every new measurement, or only on-demand?
4. How do we handle the cold-start problem (new patient with no history)?
5. Should the LLM be able to suggest interventions, or only explain current state?

---

## Document History

| Date | Change |
|------|--------|
| 2026-05-28 | Initial draft — diseases, scoring, intelligence, presentation, ML decisions captured |
