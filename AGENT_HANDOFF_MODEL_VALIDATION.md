# Agent Handoff Note: Model Validation Strategy

**From:** Coding session (ML engine build)
**To:** Paper/Patent session
**Date:** June 18, 2026
**Copy this file to:** `PrescpHealth ML Design Patent and Academic Research Project/`

---

## Key Decision Made

We've decided NOT to pre-assign specific algorithms to specific diseases (e.g., "XGBoost for CVD"). Instead, we're taking a **data-driven model selection approach** where we train ALL candidate models on EACH disease and let the validation metrics determine the best performer per disease.

The patent's Layer 2 describes disease-specific expert models. The paper will VALIDATE which model is best per disease through empirical experimentation — making the contribution both architectural AND empirical.

---

## Why This Is Better for the Paper

1. **Scientific credibility** — Reviewers will question "why XGBoost for CVD?" unless you show evidence. This approach provides that evidence.
2. **Stronger contribution** — The paper can include a model selection table showing ALL candidates' performance per disease. This IS a result, not just a design choice.
3. **Honest science** — If CatBoost turns out to beat XGBoost for CVD on MIMIC-IV data, we want to know that and use the better model.
4. **Ablation study** — Comparing per-disease specialists vs. single-model-for-all proves the "specialized expert" hypothesis from the patent.

---

## The Experimental Protocol (add to Methods section)

```
Model Selection Protocol:

For each disease d in {stroke, cvd, diabetes, ckd, hypertensive_crisis, copd}:
    Candidate models M = {XGBoost, LightGBM, CatBoost, NeuralNet, TFT, DeepSurv}
    
    For each model m in M:
        Train m on disease d using 5-fold stratified cross-validation
        Compute metrics: AUROC, AUPRC, Brier score, ECE (Expected Calibration Error)
    
    Selection criterion:
        best_model[d] = argmax_m(AUROC) subject to ECE < 0.05
        (Best discrimination while maintaining acceptable calibration)
    
    Report: Full comparison table + rationale for final selection
```

---

## What Goes in the Paper

### Results section — Table: "Model Selection Results"

| Disease | XGBoost | LightGBM | CatBoost | Neural Net | TFT | DeepSurv | Winner |
|---------|---------|----------|----------|-----------|-----|----------|--------|
| Stroke | AUROC / Brier | ... | ... | ... | ... | ... | TBD |
| CVD | ... | ... | ... | ... | ... | ... | TBD |
| Diabetes | ... | ... | ... | ... | ... | ... | TBD |
| CKD | ... | ... | ... | ... | ... | ... | TBD |
| Hypertensive Crisis | ... | ... | ... | ... | ... | ... | TBD |
| COPD | ... | ... | ... | ... | ... | ... | TBD |

### Discussion point:
"Our initial hypothesis of model-disease pairings (based on clinical data characteristics) was [confirmed/partially revised] by empirical validation."

---

## EDA Component (add to Methods section 5.1)

Before model selection, conduct Exploratory Data Analysis on MIMIC-IV:

1. **Feature distributions** per disease cohort
2. **Missing data patterns** — validates Patent Claim 6 (Missingness Encoding)
3. **Correlation analysis** between features and outcomes
4. **Class imbalance** — event rates per disease
5. **Temporal patterns** — validates Patent Claim 8 (Temporal Decay)
6. **Disease co-occurrence** — validates Patent Claim 1 (Disease Cascade)

### EDA directly informs:
- Feature selection per disease (validates DISEASE_FEATURE_WEIGHTS)
- Decay rate initialization (validates lambda_d values)
- Sufficiency thresholds
- Cascade graph structure (GNN edge initialization)

---

## Patent Connection

| Patent Claim | Paper Validates |
|-------------|----------------|
| Claim 1 (Cascade GNN) | EDA proves disease co-occurrence patterns exist in data |
| Claim 2 (Adaptive Ensemble) | Model selection shows per-disease specialists beat generic model |
| Claim 8 (Temporal Decay) | EDA shows measurement recency correlates with prediction accuracy |
| Claim 6 (Missingness) | EDA shows missingness patterns are non-random (clinical signal) |

The provisional is filed. Even if validation reveals different optimal models, the FRAMEWORK is protected.

---

## Action Items for Paper Session

1. Add "Exploratory Data Analysis" as Methods section 5.1
2. Add "Model Selection Protocol" to Methods section 5.4
3. Add model comparison table to Results section
4. Add reflection on hypothesis vs. empirical results to Discussion
5. Add to Limitations: model selection is dataset-specific
6. Add ablation study: "single model for all" vs. "per-disease specialist"

---

## Data Sources

- **MIMIC-IV**: Primary training + model selection (PhysioNet)
- **UK Biobank**: External validation
- **WHO STEPS**: Population transfer validation
- **Framingham**: Benchmark comparison
