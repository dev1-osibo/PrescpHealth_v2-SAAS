# PrescpHealth — ML Architecture: Novel Ensemble Design

## Status: RESEARCH IN PROGRESS — Patent Candidate

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

1. Academic publications on disease cascade modeling in clinical ML
2. Graph Neural Networks for multi-morbidity prediction
3. Bayesian transfer learning for clinical models across populations
4. Confidence calibration methods for clinical decision support
5. Temporal Fusion Transformers for longitudinal health data
6. Federated learning for multi-site clinical model training
7. Novel opportunities we haven't considered yet

---

## Document History

| Date | Change |
|------|--------|
| 2026-05-28 | Initial architecture design with 3 patent candidates |
