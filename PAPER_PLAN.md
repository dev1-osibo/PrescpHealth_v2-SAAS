# Academic Paper Plan — Session Handover Document

## Paper Title

**"An Adaptive AI Framework for Multi-Disease Risk Analytics: Confidence-Weighted Ensemble Learning with Disease Cascade Modeling"**

---

## Filing Strategy (CRITICAL — DO THIS FIRST)

### Order of Operations
1. **File provisional patent** (USPTO) — establishes priority date
2. **Submit paper** — can reference "patent pending"
3. **File non-provisional patent** within 12 months of provisional

### Why This Order
- A provisional patent costs ~$320 (micro entity) and gives you 12 months of protection
- Once you publish the paper, you have only 1 year (US) or 0 days (most other countries) to file
- The provisional does NOT require formal claims — just a specification describing the invention
- Filing first means your publication date doesn't matter for patent purposes

### Provisional Patent Requirements (USPTO)
- Specification (written description of the invention) — your architecture document covers this
- Drawings (architecture diagrams) — the 5-layer diagram qualifies
- Cover sheet (form SB/16)
- Filing fee: $320 (micro entity) / $640 (small entity)
- NO formal claims required (but include informal ones for clarity)
- NO oath/declaration required
- Expires after 12 months — must file non-provisional before then

---

## Target Journals (Ranked by Fit)

| Priority | Journal | Impact Factor | Open Access | Word Limit | Review Time | Notes |
|----------|---------|--------------|-------------|------------|-------------|-------|
| 1 | npj Digital Medicine (Nature) | ~15 | Yes (Gold OA) | No strict limit (~5000-8000 words) | 4-8 weeks | Best fit: AI methods + clinical validation |
| 2 | Journal of Biomedical Informatics | ~8 | Hybrid | 8000 words | 6-10 weeks | Technical depth welcome |
| 3 | Artificial Intelligence in Medicine | ~7 | Hybrid | 10000 words | 8-12 weeks | Pure AI methods focus |
| 4 | IEEE J Biomed Health Inform | ~7 | Hybrid | 8 pages (double column) | 8-16 weeks | Engineering-focused |
| 5 | The Lancet Digital Health | ~30 | Yes (Gold OA) | 4000 words (Article) | 4-6 weeks | Very competitive, high impact |
| 6 | JAMIA | ~7 | Hybrid | 4000 words | 6-12 weeks | Health informatics community |

**Recommendation:** Submit to npj Digital Medicine first. It's Nature-branded (prestige), open access (visibility), accepts technical AI papers with clinical validation, and has reasonable review times.

---

## Paper Structure

### Standard Structure for npj Digital Medicine / AI in Medicine

```
1. Abstract (250 words max)
2. Introduction
3. Results
4. Discussion
5. Methods
6. Data Availability
7. Code Availability
8. References
9. Supplementary Materials
```

Note: npj Digital Medicine puts Methods AFTER Discussion (Nature style). Other journals put Methods before Results.

---

## Detailed Section Plan

### 1. Abstract (250 words)

**Structure:** Background - Problem - Method - Results - Conclusion

Key points to hit:
- NCDs cause 74% of global deaths; existing risk tools predict diseases independently
- We propose a 5-layer adaptive framework that models disease cascades via GNN
- Confidence-weighted ensemble adapts per-patient based on data completeness
- Validated on MIMIC-IV (N=X) and UK Biobank (N=X)
- Results: AUC improvement over Framingham/QRISK3, calibration metrics, cascade detection accuracy
- Conclusion: First framework to model inter-disease cascades with adaptive confidence weighting

### 2. Introduction (800-1000 words)

**Paragraph flow:**
1. NCD burden globally (WHO stats: 41M deaths/year, 74% of all deaths)
2. Current risk prediction tools and their limitations (Framingham, QRISK3, WHO/ISH — all single-disease, static, population-level)
3. ML approaches to date (single-model, single-disease, fixed ensembles)
4. The gap: no system models disease cascades, adapts to data availability, or knows when to stay silent
5. Our contribution: 5-layer architecture with 8 novel components
6. Paper organization

### 3. Results (1500-2000 words)

**Subsections:**
- 3.1 Disease Cascade Detection — GNN correctly identifies cascade pathways (hypertension to stroke, diabetes to CKD to CVD)
- 3.2 Prediction Performance — AUC/AUROC comparison vs. baselines (Framingham, QRISK3, standalone XGBoost, standard ensemble)
- 3.3 Adaptive Weighting Impact — performance improvement when data is sparse vs. complete
- 3.4 Confidence Calibration — reliability diagrams, Brier scores, ECE (Expected Calibration Error)
- 3.5 Clinical Silence Evaluation — false alert reduction, alert fatigue metrics
- 3.6 Population Transfer — cold-start performance on new populations (WHO STEPS countries)
- 3.7 Counterfactual Explanations — clinician evaluation of actionability

**Key metrics to report:**
- AUROC per disease (stroke, CVD, diabetes, CKD, hypertensive crisis, COPD)
- Calibration: Brier score, ECE, reliability diagrams
- Net Reclassification Improvement (NRI) vs. Framingham
- Decision Curve Analysis (clinical utility)
- Alert precision/recall at different confidence thresholds

### 4. Discussion (1000-1500 words)

**Paragraph flow:**
1. Summary of key findings
2. Comparison with existing work (ARES, MetaPred, Ram-EHR, standard GNN approaches)
3. Clinical implications — what this means for clinicians
4. The "clinical silence" contribution — reducing alert fatigue
5. Limitations (retrospective validation, no RCT yet, dataset biases)
6. Future work (prospective validation, federated deployment, RCT)

### 5. Methods (2000-3000 words)

**Subsections:**
- 5.1 Study Design and Data Sources
  - MIMIC-IV: cohort selection, inclusion/exclusion criteria
  - UK Biobank: cohort selection, follow-up period
  - WHO STEPS: countries used for transfer learning validation
- 5.2 Feature Engineering
  - Clinical features (vitals, labs, medications, diagnoses)
  - Temporal features (trends, variability, freshness scores)
  - Data completeness scoring
- 5.3 Layer 1: Data Assessment Module
  - Per-patient completeness scoring algorithm
  - Feature freshness exponential decay
  - Data sufficiency thresholds per disease
- 5.4 Layer 2: Disease-Specific Expert Models
  - Model selection rationale per disease
  - Hyperparameter optimization (Optuna/Bayesian)
  - Training procedure (5-fold stratified CV)
- 5.5 Layer 3: Disease Cascade Network
  - GNN architecture (message passing, edge weight learning)
  - Cascade propagation algorithm
  - Training with known clinical relationships as priors
- 5.6 Layer 4: Adaptive Meta-Learner
  - Confidence-weighted blending function
  - Clinical standard fallback mechanism
  - Per-patient weight computation
- 5.7 Layer 5: Explainability and Clinical Silence
  - SHAP computation per disease
  - Confidence threshold calibration
  - Alert decision logic
- 5.8 Counterfactual Cascade Explanations
  - Intervention simulation methodology
  - Cascade propagation of counterfactuals
- 5.9 Population Transfer (Bayesian Prior)
  - Prior specification from public datasets
  - Incremental Bayesian updating algorithm
  - Cold-start evaluation protocol
- 5.10 Statistical Analysis
  - Performance metrics (AUROC, AUPRC, Brier, ECE, NRI, DCA)
  - Confidence intervals (bootstrap, 1000 iterations)
  - Comparison tests (DeLong test for AUC comparison)

---

## 8 Patent Claims (Novel Contributions)

### Claim 1: Disease Cascade Network
**What:** GNN where disease risk scores propagate through learned interaction edges
**Novel because:** Existing GNNs model disease co-occurrence; ours models causal cascade propagation where one disease's output becomes another's input feature
**Prior art gap:** No published system uses learned cascade weights (not hardcoded) for multi-NCD prediction

### Claim 2: Adaptive Confidence-Weighted Ensemble
**What:** Per-patient model weighting based on data completeness, freshness, and historical accuracy
**Novel because:** Existing ensembles use fixed weights; ours adapts per-patient and gracefully degrades to clinical standards
**Prior art gap:** ARES uses a single foundation model; no system combines multiple specialized models with adaptive weighting + clinical standard fallback

### Claim 3: Population-Adaptive Bayesian Prior Transfer
**What:** Bayesian prior updating for cross-population model adaptation without data sharing
**Novel because:** Federated learning shares model weights; ours transfers priors that adapt incrementally
**Prior art gap:** No system combines Bayesian transfer with NCD-specific cold-start handling

### Claim 4: Retrieval-Augmented Clinical Prediction
**What:** Finding similar patient trajectories to augment prediction for rare/unusual presentations
**Novel because:** Ram-EHR retrieves text/knowledge; ours retrieves similar patient outcome trajectories
**Prior art gap:** No system uses trajectory-based retrieval (not just feature similarity) for NCD risk

### Claim 5: Counterfactual Cascade Explanations
**What:** "What-if" scenarios that propagate through the disease cascade ("lower BP leads to stroke risk drops leads to CVD risk drops")
**Novel because:** Existing counterfactuals show single-variable changes; ours shows multi-disease cascade effects
**Prior art gap:** No published system combines counterfactual explanations with disease cascade propagation

### Claim 6: Self-Supervised EHR Foundation Model with Missingness Encoding
**What:** Pre-training that treats missing data as a signal (patient not tested = information)
**Novel because:** ETHOS/ARES pre-train on available data; ours explicitly encodes WHAT IS MISSING as a feature
**Prior art gap:** No system uses missingness patterns as predictive features in a foundation model context

### Claim 7: Confidence-Calibrated Clinical Silence
**What:** System that decides when NOT to alert based on model confidence and agreement
**Novel because:** CURA does uncertainty for LLMs; ours applies it to ensemble disagreement for alert suppression
**Prior art gap:** No clinical decision support system has a formal "silence" mechanism based on calibrated confidence

### Claim 8: Temporal Decay-Weighted Feature Importance
**What:** Exponential decay weighting where recent measurements matter more, with decay rate learned per-disease
**Novel because:** TALE-EHR handles irregular intervals; ours learns disease-specific decay rates (BP freshness matters differently for stroke vs. CKD)
**Prior art gap:** No system learns per-disease temporal decay rates for feature importance

---

## Validation Datasets

### Primary Datasets (Free Access)

| Dataset | Access Method | Size | What It Provides | Use In Paper |
|---------|-------------|------|-----------------|--------------|
| **MIMIC-IV** | PhysioNet (credentialing required, ~1 week) | 300K+ patients, 500K+ admissions | ICU: vitals, labs, meds, diagnoses, procedures, notes | Primary training + validation |
| **UK Biobank** | Research application (free, ~4-8 weeks approval) | 500K participants | Genetics, lifestyle, clinical, 15+ year outcomes | External validation + NCD outcomes |
| **WHO STEPS** | Public download (immediate) | Multi-country surveys | NCD risk factors across 100+ countries | Population transfer validation |
| **Framingham Heart Study** | BioLINCC (free, application) | 15K participants | CVD risk factors, 70+ year follow-up | Benchmark comparison |
| **MIMIC-IV-Ext-22MCTS** | PhysioNet | 22M temporal events | Extended time-series clinical events | Temporal modeling |
| **eICU** | PhysioNet | 200K+ admissions | Multi-center ICU (208 hospitals) | Multi-site generalization |
| **All of Us** (NIH) | Researcher Workbench (free) | 400K+ participants | Diverse US population, EHR + genomics | Diversity validation |

### How to Access

**PhysioNet (MIMIC-IV, eICU, MIMIC-IV-Ext):**
1. Create account at physionet.org
2. Complete CITI "Data or Specimens Only Research" training (~4 hours)
3. Sign data use agreement
4. Access granted within 1-7 days
5. Download via wget or Google Cloud/AWS

**UK Biobank:**
1. Register as researcher at ukbiobank.ac.uk
2. Submit research application (describe your study)
3. Approval takes 4-8 weeks
4. Access via UK Biobank Research Analysis Platform (RAP)
5. Free for approved academic research

**WHO STEPS:**
1. Visit who.int/teams/noncommunicable-diseases/surveillance/data
2. Download country-specific survey data directly
3. No application needed for aggregate data
4. Individual-level data may require country permission

---

## Key References (Organized by Topic)

### Disease Cascade / Multi-Morbidity GNNs
1. "A Generative Framework for Predictive Modeling of Multiple Chronic Conditions Using Graph Variational Autoencoder and Bandit-Optimized GNN" — IEEE J Biomed Health Inform, 2025
2. "A Laplacian regularized graph neural network for predictive modeling of multiple chronic conditions" — PubMed, Feb 2024
3. "Graph neural networks for clinical risk prediction based on electronic health records" — J Biomed Inform, Mar 2024
4. "Applying precision medicine principles to the management of multimorbidity: comorbidity networks, graph ML, and knowledge graphs" — Frontiers in Medicine, 2023
5. "Clinical Multi-modal Fusion with Heterogeneous Graph and Disease Correlation Learning for Multi-Disease Prediction" — arXiv, Sep 2025
6. "Causal Graph Neural Networks for Healthcare" — arXiv, Nov 2025

### Adaptive/Foundation Models for EHR
7. "Foundation Model of Electronic Medical Records for Adaptive Risk Estimation (ARES)" — arXiv, Feb 2025
8. "MetaPred: Meta-Learning for Clinical Risk Prediction with Limited Patient EHRs" — arXiv, 2019 (updated 2025)
9. "Retrieval-Augmented Prototype-Guided Foundation Model for Electronic Health Records" — arXiv, May 2025
10. "EHR-RAG: Bridging Long-Horizon Structured EHR and LLMs via Enhanced Retrieval-Augmented Generation" — arXiv, Jan 2025
11. "Ram-EHR: Retrieval Augmentation Meets Clinical Predictions on EHRs" — arXiv, Mar 2024
12. "Personalised Federated Learning for Real Large-Scale Healthcare Systems" — arXiv, May 2024

### Confidence Calibration and Uncertainty
13. "CURA: Clinical Uncertainty Risk Alignment for Language Model-Based Risk Prediction" — arXiv, Apr 2026
14. "Bayesian Uncertainty Quantification for Safe Clinical Decision Support" — arXiv, Nov 2025
15. "Calibration, Uncertainty Communication, and Deployment Readiness in CKD Risk Prediction" — arXiv, May 2025
16. "TrustFed: Enabling trustworthy medical AI under data privacy constraints" — arXiv, Mar 2026

### Counterfactual Explanations in Healthcare
17. "Counterfactual Modeling with Fine-Tuned LLMs for Health Intervention Design" — arXiv, Jan 2025
18. "Exploiting Counterfactual Explanations for Medical Research" — arXiv, Jul 2023
19. "Clinical decision making under uncertainty: a bootstrapped counterfactual inference approach" — BMC Med Inform, Sep 2024
20. "Understanding the Effect of Counterfactual Explanations on Trust and Reliance on AI for Clinical Decision Making" — arXiv, Aug 2023

### Temporal Modeling in Clinical Data
21. "TALE-EHR: Time-Aware Attention for Enhanced EHR Modeling" — arXiv, Jul 2025
22. "Temporal-Feature Cross Attention Mechanism (TFCAM)" — arXiv, Mar 2025
23. "LITT: Individual-Level Time Transformation for event-timing-focused attention" — arXiv, Feb 2025
24. "Stable Prediction of Adverse Events in Medical Time-Series Data" — arXiv, Oct 2025

### NCD Risk Prediction Baselines
25. "Prediction of the Risk of Adverse Clinical Outcomes with ML in Patients with NCDs" — PubMed, 2025
26. "Machine learning models for predicting multimorbidity trajectories" — PubMed, 2025
27. "Development and validation of a prediction model for 10-year risk of MACE (NeuralCVD)" — UK Biobank, PubMed 2022
28. "Adaptive weighted stacking model for mortality risk prediction in sepsis" — Springer, Sep 2024

### Data Standards and Infrastructure
29. "MEDS: Medical Event Data Standard — open-source framework for health AI" — Columbia University, May 2026
30. "MIMIC-IV-Ext-22MCTS: A 22 Million-Event Temporal Clinical Time-Series Dataset" — arXiv, May 2025

---

## Experimental Design

### Cohort Selection (MIMIC-IV)
- **Inclusion:** Adults (18+), 2+ hospital admissions, 1+ NCD diagnosis (ICD-10: I10-I15, I20-I25, I60-I69, E10-E14, N18, J40-J47)
- **Exclusion:** Less than 24h total ICU stay, missing more than 80% of core vitals, terminal diagnosis at admission
- **Expected N:** ~80,000-120,000 patients

### Cohort Selection (UK Biobank)
- **Inclusion:** All participants with baseline assessment + 5+ year follow-up
- **Exclusion:** Prevalent NCD at baseline (for incident prediction), withdrawn consent
- **Expected N:** ~350,000-400,000 participants
- **Outcomes:** Incident stroke, CVD event, diabetes diagnosis, CKD stage 3+, COPD diagnosis

### Train/Validation/Test Split
- MIMIC-IV: 70% train / 15% validation / 15% test (temporal split — train on earlier admissions)
- UK Biobank: External validation only (no training on this data)
- WHO STEPS: Population transfer evaluation only

### Baseline Comparisons
1. Framingham Risk Score (CVD)
2. QRISK3 (CVD, UK-specific)
3. WHO/ISH risk charts (global)
4. Standalone XGBoost (single model, all diseases)
5. Standard fixed-weight ensemble (XGBoost + LightGBM + NN, equal weights)
6. ARES (if code available)
7. Individual disease-specific models (no cascade)

### Ablation Studies
1. Full model vs. no cascade (remove Layer 3)
2. Full model vs. fixed weights (remove adaptive weighting)
3. Full model vs. no clinical standard fallback
4. Full model vs. no temporal decay
5. Full model vs. no confidence calibration
6. Full model vs. no counterfactual module

---

## Figures and Tables Plan

### Main Figures (6-8)
1. **Architecture diagram** — 5-layer system overview (already exists in ml-architecture.md)
2. **Disease cascade graph** — GNN topology with learned edge weights
3. **Adaptive weighting visualization** — how weights shift with data completeness (3 patient examples: full data, partial, sparse)
4. **ROC curves** — per-disease comparison vs. baselines (6 panels)
5. **Calibration plots** — reliability diagrams per disease
6. **Clinical silence evaluation** — precision-recall at different confidence thresholds
7. **Counterfactual cascade example** — "lower BP by 20" leads to cascade effect visualization
8. **Population transfer** — performance on new populations over time (cold-start curve)

### Main Tables (4-5)
1. **Dataset characteristics** — demographics, disease prevalence, data completeness
2. **Performance comparison** — AUROC, AUPRC, Brier, NRI per disease per method
3. **Ablation results** — each component's contribution
4. **Clinical silence metrics** — alert reduction, false positive reduction, missed critical events
5. **Computational cost** — inference time, memory, scalability

### Supplementary
- Full hyperparameter tables
- Additional calibration metrics
- Subgroup analyses (age, sex, ethnicity)
- Sensitivity analyses
- Code snippets for key algorithms

---

## Timeline Estimate

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| 1. File provisional patent | 1-2 weeks | USPTO filing with specification + diagrams |
| 2. PhysioNet credentialing | 1 week | MIMIC-IV access |
| 3. UK Biobank application | 4-8 weeks | Access approval |
| 4. Data preprocessing | 2-3 weeks | Clean cohorts, feature engineering |
| 5. Model development | 4-6 weeks | All 5 layers implemented + trained |
| 6. Experiments | 3-4 weeks | All comparisons, ablations, calibration |
| 7. Paper writing | 3-4 weeks | Full manuscript draft |
| 8. Internal review | 1-2 weeks | Co-author review, revisions |
| 9. Submission | 1 day | Submit to npj Digital Medicine |
| 10. Review cycle | 4-8 weeks | Respond to reviewers |

**Total: ~5-7 months from start to submission**

---

## Tools and Libraries Needed

### ML/DL Stack
- PyTorch (GNN, neural networks, TFT)
- PyTorch Geometric (GNN implementation)
- XGBoost, LightGBM, CatBoost (expert models)
- scikit-learn (preprocessing, metrics, calibration)
- SHAP (explainability)
- Optuna (hyperparameter optimization)

### Clinical/Data
- pandas, numpy (data manipulation)
- lifelines (survival analysis)
- pysurvival (survival models)
- tableone (cohort characteristics table)

### Visualization
- matplotlib, seaborn (standard plots)
- networkx (graph visualization)
- plotly (interactive cascade visualization)

### Evaluation
- sklearn.metrics (AUROC, AUPRC, Brier)
- netcal (calibration metrics, ECE)
- dcurves (Decision Curve Analysis)
- scipy.stats (DeLong test, bootstrap CI)

---

## Key Differentiators to Emphasize

When writing, always contrast against existing work:

| Feature | Existing Systems | Our Framework |
|---------|-----------------|---------------|
| Disease modeling | Independent predictions | Cascade propagation via GNN |
| Ensemble weighting | Fixed (same for all patients) | Adaptive per-patient |
| Data sparsity | Fails or degrades silently | Graceful fallback to clinical standards |
| Alerting | Always alert if threshold exceeded | Confidence-aware silence |
| Explanations | "Feature X contributed Y%" | "If you change X, diseases A then B then C all improve" |
| Population transfer | Requires retraining | Bayesian prior updating (works from day 1) |
| Missing data | Imputation or exclusion | Missingness as a signal |
| Temporal handling | Fixed windows or RNNs | Per-disease learned decay rates |

---

## Author Positioning

Since you are coming from data analytics/AI (not medicine):
- Position as "health AI / clinical analytics" researcher
- Emphasize the ENGINEERING novelty (architecture, algorithms, systems)
- Clinical validation proves it works, but the contribution is the AI framework
- Consider a clinical co-author for credibility (a doctor who can validate clinical relevance)
- Affiliation: your institution/company + "Independent Researcher" is fine for solo

---

## Quick Reference: What to Bring to the Paper Session

1. This document (PAPER_PLAN.md)
2. The ML architecture document (.kiro/specs/ml-architecture.md)
3. The product design document (.kiro/specs/product-design.md)
4. Access to the codebase (for implementation details of the 5 layers)
5. PhysioNet account (start credentialing NOW — takes ~1 week)
6. UK Biobank researcher registration (start NOW — takes 4-8 weeks)

---

## Immediate Actions (Do Before Paper Session)

1. **TODAY:** Create PhysioNet account and start CITI training
2. **THIS WEEK:** Submit UK Biobank researcher application
3. **THIS WEEK:** Draft provisional patent specification (use ml-architecture.md as base)
4. **NEXT SESSION:** Begin paper writing with the structure above

---

## Document History

| Date | Change |
|------|--------|
| 2026-05-31 | Initial paper plan created with full structure, 8 patent claims, 30 references, validation strategy |
