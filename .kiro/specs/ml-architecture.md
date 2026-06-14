# PrescpHealth — ML Architecture: Novel Ensemble Design

## Status: RESEARCH IN PROGRESS — Patent Candidate

**Paper Title:** "An Adaptive AI Framework for Multi-Disease Risk Analytics: Confidence-Weighted Ensemble Learning with Disease Cascade Modeling"

**Target Journal:** npj Digital Medicine (Nature)

**Patent Claims:** 8 (see below)

This document captures the novel ML architecture that forms PrescpHealth's competitive moat and potential patent filing.

---

## Core Innovation: Adaptive Confidence-Weighted Disease Cascade Ensemble

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 1: DATA ASSESSMENT                       │
│  Per-patient data density → confidence weights per model         │
│  Per-feature staleness → freshness scores                        │
│  Data sufficiency check → which diseases can be predicted        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 2: DISEASE-SPECIFIC EXPERT MODELS              │
│                                                                   │
│  Stroke Expert ──────── TabNet (attention on BP/cholesterol)     │
│  CVD Expert ─────────── XGBoost (structured risk factors)        │
│  Diabetes Expert ────── CatBoost (categorical + missing values)  │
│  CKD Expert ─────────── LightGBM (eGFR trajectories)            │
│  Hypertensive Expert ── Neural Network (real-time patterns)      │
│  COPD Expert ────────── TFT (time-series spirometry)             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           LAYER 3: DISEASE CASCADE NETWORK (NOVEL)               │
│                                                                   │
│  Diseases inform each other via learned interaction graph:        │
│    Hypertension ──→ Stroke risk (amplifies)                      │
│    Hypertension ──→ CVD risk (amplifies)                         │
│    Diabetes ──────→ CKD risk (amplifies)                         │
│    CKD ───────────→ CVD risk (amplifies)                         │
│    Smoking ───────→ COPD + CVD + Stroke (multi-target)           │
│                                                                   │
│  Graph Neural Network models the disease interaction topology    │
│  Output: cascade-adjusted scores (not independent predictions)   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           LAYER 4: ADAPTIVE META-LEARNER (NOVEL)                 │
│                                                                   │
│  Weights each expert based on:                                   │
│    - Data completeness (more data → trust ML more)               │
│    - Data freshness (stale data → reduce confidence)             │
│    - Population fit (model trained on similar demographics?)     │
│    - Historical accuracy (how well did this model do before?)    │
│                                                                   │
│  High data → trust expert models                                 │
│  Low data → fall back to clinical standards (Framingham, etc.)   │
│  Learns optimal weighting per population (adapts globally)       │
│                                                                   │
│  Output: final 0-100 score + confidence interval + quality flag  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│           LAYER 5: EXPLAINABILITY + CLINICAL SILENCE             │
│                                                                   │
│  SHAP explanations per disease (which features drove the score)  │
│  Confidence-aware alert behavior:                                │
│    High confidence + high risk → ALERT IMMEDIATELY               │
│    High confidence + low risk → SILENT                           │
│    Low confidence + any risk → INFORM with uncertainty            │
│    Model disagreement → FLAG for human review                    │
│                                                                   │
│  LLM interprets results in natural language (never predicts)     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Patent Candidate 1: Disease Cascade Network

**Claim:** A system and method for multi-disease risk prediction where individual disease risk models are connected via a learned interaction graph, such that the output of one disease model influences the input of related disease models, reflecting known clinical disease cascades.

**Why novel:**
- Existing systems predict each disease independently
- Clinical reality: diseases cascade (hypertension → stroke, diabetes → CKD → CVD)
- No published ML system models this cascade as a graph neural network
- The cascade weights are LEARNED from data, not hardcoded

**Implementation:**
- Graph Neural Network (GNN) with diseases as nodes
- Edges represent known clinical relationships
- Edge weights learned from patient outcome data
- Cascade propagation: risk score from one disease becomes a feature for connected diseases

---

## Patent Candidate 2: Adaptive Confidence-Weighted Ensemble

**Claim:** A method for clinical risk prediction that dynamically adjusts the weighting of multiple machine learning models based on per-patient data completeness, feature freshness, and historical model accuracy, such that predictions gracefully degrade from ML-driven to clinical-standard-driven as data becomes sparse.

**Why novel:**
- Existing ensembles use fixed weights (same for all patients)
- Our system adapts weights PER PATIENT based on their specific data availability
- Graceful degradation: full data → ML prediction; sparse data → clinical standard; no data → population prior
- No published system combines adaptive weighting with clinical standard fallback

**Implementation:**
- Data completeness score (0-1) per patient per disease
- Feature freshness score (exponential decay based on measurement age)
- Model confidence calibration (Platt scaling + isotonic regression)
- Blending function: final_score = α * ML_score + (1-α) * clinical_standard_score where α = f(data_completeness, freshness, calibration)

---

## Patent Candidate 3: Population-Adaptive Bayesian Prior Transfer

**Claim:** A method for transferring clinical risk prediction models across populations using Bayesian prior updating, where a model trained on one population adapts to a new population through incremental Bayesian updates as local data accumulates, without requiring the new population to reach a minimum dataset size before predictions begin.

**Why novel:**
- Existing systems require large local datasets before they work (cold-start problem)
- Our system starts with global priors and adapts incrementally
- No data sharing between tenants (privacy-preserving)
- Works from day 1 with zero local data (uses population priors)
- Gets better over time as local data accumulates

**Implementation:**
- Prior: trained on public datasets (MIMIC-IV, UK Biobank, Framingham)
- Likelihood: local patient outcomes as they accumulate
- Posterior: updated model that blends global knowledge with local patterns
- Per-tenant model personalization without sharing raw data

---

## Patent Candidate 4: Retrieval-Augmented Clinical Prediction

**Claim:** A method for augmenting clinical risk predictions by retrieving similar patient trajectories from a de-identified population database, where similarity is computed over temporal health trajectories (not just static features), and retrieved outcomes are used to inform predictions for patients with rare or unusual presentations.

**Why novel:**
- Ram-EHR and EHR-RAG retrieve text/knowledge to augment LLMs
- Our system retrieves PATIENT TRAJECTORIES (temporal sequences of measurements and outcomes)
- Similarity is computed over the trajectory shape, not just current feature values
- Particularly valuable for rare presentations where the model has limited training data

**Implementation:**
- Encode patient trajectories into embedding space (temporal autoencoder)
- Approximate nearest neighbor search over de-identified trajectory database
- Retrieved outcomes weighted by trajectory similarity
- Augments expert model predictions for rare/unusual cases

---

## Patent Candidate 5: Counterfactual Cascade Explanations

**Claim:** A method for generating actionable clinical explanations by computing counterfactual scenarios that propagate through a disease interaction graph, showing clinicians how a single intervention (e.g., reducing blood pressure) cascades through multiple disease risk scores simultaneously.

**Why novel:**
- Existing counterfactual explanations show single-variable, single-outcome changes
- Our system propagates counterfactuals through the Disease Cascade Network
- Shows multi-disease impact: "Lower BP by 20 → stroke risk drops 15 points → CVD risk drops 8 points → CKD stabilizes"
- Provides actionable, prioritized intervention recommendations

**Implementation:**
- Perturb input feature (e.g., systolic_bp -= 20)
- Re-run Layer 2 expert models with perturbed input
- Propagate through Layer 3 cascade network (GNN forward pass)
- Compare original vs. counterfactual scores across all diseases
- Rank interventions by total cascade impact

---

## Patent Candidate 6: Self-Supervised EHR Foundation Model with Missingness Encoding

**Claim:** A method for pre-training clinical prediction models using self-supervised learning on electronic health records, where the pattern of missing data is explicitly encoded as a predictive feature, treating the absence of measurements as clinically informative signal rather than noise to be imputed.

**Why novel:**
- ETHOS/ARES pre-train on available data, treating missing values as gaps to fill
- Our system encodes WHAT IS MISSING as a feature (a patient not tested for HbA1c in 2 years is different from one tested last week — the absence itself is information)
- Missingness patterns correlate with clinical behavior (healthy patients get tested less)
- No published foundation model explicitly uses missingness topology as a predictive signal

**Implementation:**
- Binary missingness mask per feature per time step
- Missingness pattern embedding (learned representation of which tests are missing)
- Self-supervised pre-training objective: predict next measurement AND predict which measurements will be ordered next
- Fine-tune for disease prediction with missingness-aware attention

---

## Patent Candidate 7: Confidence-Calibrated Clinical Silence

**Claim:** A method for clinical decision support systems that determines when NOT to generate alerts, using calibrated model confidence scores and inter-model agreement metrics to suppress notifications when prediction uncertainty exceeds clinically-defined thresholds, thereby reducing alert fatigue while maintaining safety.

**Why novel:**
- CURA (2026) does uncertainty alignment for LLMs in clinical settings
- Existing CDS systems alert whenever a threshold is crossed (binary)
- Our system has a formal "silence" mechanism: if models disagree or confidence is low, it stays quiet
- Reduces alert fatigue (a major clinical problem — 90%+ of alerts are overridden)
- Safety-preserving: high-confidence critical alerts always fire

**Implementation:**
- Compute prediction confidence per expert model (calibrated via Platt scaling)
- Compute inter-model agreement (variance across expert predictions)
- Alert decision matrix: confidence × risk level × model agreement → alert/inform/silent
- Clinician-configurable thresholds per disease and per role
- Audit trail: every silence decision is logged with reasoning

---

## Patent Candidate 8: Temporal Decay-Weighted Feature Importance

**Claim:** A method for weighting clinical features in risk prediction models using learned, disease-specific temporal decay functions, where the influence of each measurement decreases over time at a rate that is specific to both the feature type and the target disease, reflecting the clinical reality that different measurements have different relevance half-lives for different conditions.

**Why novel:**
- TALE-EHR handles irregular time intervals with time-aware attention
- Standard approaches use fixed time windows (e.g., "last 12 months of data")
- Our system learns that: BP from yesterday matters more for stroke than BP from 6 months ago, BUT HbA1c from 3 months ago is still highly relevant for diabetes
- Decay rates are LEARNED per (feature, disease) pair, not hardcoded

**Implementation:**
- Exponential decay function: weight = exp(-λ_{f,d} × Δt) where λ is learned per feature f and disease d
- λ values learned during training via backpropagation
- Clinically interpretable: can report "your last BP reading (3 days ago) has 95% relevance for stroke prediction, but only 60% relevance for CKD prediction"
- Handles irregular measurement intervals naturally

---

## Disease-Specific Expert Model Selection

| Disease | Primary Model | Why This Model |
|---------|--------------|----------------|
| Stroke | TabNet | Attention mechanism identifies which features matter most for THIS patient |
| CVD | XGBoost | Best-in-class for structured tabular risk factors, handles interactions |
| Diabetes | CatBoost | Natively handles categorical features (smoking status, ethnicity) + missing values |
| CKD | LightGBM | Fast training, handles eGFR trajectory data efficiently |
| Hypertensive Crisis | Neural Network | Captures non-linear BP patterns, real-time threshold detection |
| COPD | Temporal Fusion Transformer | Time-series native — handles spirometry trends over time |

**Why different models per disease (not one model for all):**
- Each disease has different data characteristics
- Stroke depends heavily on a few key features (BP, cholesterol) → attention-based model
- Diabetes has many categorical risk factors → CatBoost excels here
- COPD is inherently temporal (lung function decline over time) → TFT
- This specialization outperforms a single generic model

---

## Confidence-Aware Clinical Silence

| Confidence | Risk Level | Action |
|-----------|-----------|--------|
| High (>0.8) | Critical (75-100) | ALERT IMMEDIATELY — interrupt workflow |
| High (>0.8) | High (50-74) | NOTIFY — show in dashboard, don't interrupt |
| High (>0.8) | Low-Moderate (0-49) | SILENT — no action needed |
| Low (<0.5) | Any | INFORM — "Insufficient data, consider ordering [tests]" |
| Models disagree | Any | FLAG — "Expert models disagree, human review recommended" |

---

## Training Data Strategy (Global, Not Region-Locked)

| Phase | Data Source | Purpose |
|-------|------------|---------|
| Pre-training | MIMIC-IV (US ICU), UK Biobank, Framingham | Global baseline priors |
| Fine-tuning | Synthetic data (generated from clinical guidelines) | Fill gaps in real data |
| Adaptation | Per-tenant real patient data (as it accumulates) | Local population fit |
| Validation | Held-out patient outcomes (did prediction come true?) | Continuous accuracy monitoring |

---

## Research Needed (Next Steps)

1. ~~Academic publications on disease cascade modeling in clinical ML~~ — DONE (found 6 papers, none do causal cascade propagation)
2. ~~Graph Neural Networks for multi-morbidity prediction~~ — DONE (found GVA+GNN, Laplacian GNN, none combine with adaptive weighting)
3. ~~Bayesian transfer learning for clinical models across populations~~ — DONE (no prior art for NCD-specific cold-start)
4. ~~Confidence calibration methods for clinical decision support~~ — DONE (CURA 2026 is closest, but for LLMs not ensembles)
5. ~~Temporal Fusion Transformers for longitudinal health data~~ — DONE (TALE-EHR, TFCAM exist but don't learn per-disease decay)
6. ~~Federated learning for multi-site clinical model training~~ — DONE (TrustFed 2026, but doesn't do Bayesian prior transfer)
7. ~~Novel opportunities we haven't considered yet~~ — DONE (identified 8 total claims)

### Remaining Research
- Detailed implementation specifications for each patent claim
- Formal mathematical notation for the provisional patent specification
- Identify potential clinical co-author for paper credibility
- Begin PhysioNet credentialing and UK Biobank application

---

## Document History

| Date | Change |
|------|--------|
| 2026-05-28 | Initial architecture design with 3 patent candidates |
| 2026-05-31 | Added patent candidates 4-8 (Retrieval-Augmented, Counterfactual Cascade, Missingness Encoding, Clinical Silence, Temporal Decay) |
| 2026-05-31 | Paper title finalized: "An Adaptive AI Framework for Multi-Disease Risk Analytics: Confidence-Weighted Ensemble Learning with Disease Cascade Modeling" |
| 2026-05-31 | Full paper plan created (PAPER_PLAN.md) with structure, 30 references, validation strategy, timeline |
| 2026-05-31 | Research landscape analysis complete — confirmed novelty of all 8 claims against 2024-2026 literature |
