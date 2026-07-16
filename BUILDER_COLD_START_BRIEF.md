# Builder Brief — Deployment-Level Cold-Start (Population Prior Transfer)

**Date:** 2026-07-09
**Author:** Research-side agent (handing off to the build agent working in this `PrescpHealth` workspace)
**Status:** Product feature brief. Read fully before touching `ml/risk_engine/population_transfer.py`.
**Scope:** Risk engine (and, by extension, forecast engine) cold-start behaviour for new deployments.

---

## 1. Why this exists (the product rationale — this is NOT a patent play)

**Important framing first:** the academic paper and patent this capability was originally conceived under (it was "Patent Claim 3" in the sister research project) have both been **discontinued** — see `PrescpHealth ML Design Patent and Academic Research Project/PATENT_PAPER_TEARDOWN.md` (decision D018). Prior-art review found the claim was not novel enough to pursue, and the paper/analysis track was shut down after a rigour incident. **Do not build this toward a patent or paper.** The module docstrings still say "Patent Claim 3" — treat that as legacy internal naming, not a live objective.

This feature is justified **purely on product grounds**, from PrescpHealth's two sales motions:

| Sale | What the buyer already has | Cold-start needed? |
|------|----------------------------|--------------------|
| **Full product** (EMR + prediction) sold to a hospital standing up a fresh records system | Little/no historical structured data on day 1 | **Yes** — the whole tenant starts empty; the risk/forecast engine has nothing local to calibrate on |
| **Predictive module only** sold to a hospital that already runs an EMR | Existing accumulated patient records | **No** (at the tenant level) — they arrive with data the engine can calibrate on |

So cold-start is the capability that lets the **full-EMR greenfield deployment** produce calibrated, non-embarrassing risk output from day 1, then improve as the hospital accumulates real patients.

---

## 2. What already exists (do not rebuild from scratch — extend it)

A first-draft implementation is already in the repo:

- **`ml/risk_engine/population_transfer.py`** — `PopulationTransfer` class. Beta-Bernoulli conjugate Bayesian updating: starts from published epidemiological priors per disease per population region (`POPULATION_PRIORS`), exposes `get_mean_risk()`, `update_posterior(outcomes)`, and `get_confidence_interval()`. This is the core cold-start mechanism.
- **`ml/risk_engine/data_assessment.py`** — `DataAssessor` produces a per-patient, per-disease **sufficiency score**. This is the natural signal for *how much weight* to put on the cold-start prior vs. a trained local model: low sufficiency → lean on the population prior; high sufficiency → lean on the ML prediction.
- **Spec already mandates the per-patient version:** `prescphealth-saas-rebuild` requirements **6.7** (risk engine uses population-level Bayesian priors for missing features and flags them in SHAP) and **8.5 / 8.6** (forecast engine uses priors when a patient has ≤1 measurement, and reduces reliance as data arrives).

**Conclusion:** the *per-patient sparse-data* prior is already speced and partially built. What is NOT yet handled is the *whole-tenant greenfield* case — that's the actual gap below.

---

## 3. The gap to build (deployment-level cold-start ≠ per-patient priors)

The existing `PopulationTransfer` stores posteriors in an **in-memory instance attribute (`_posteriors`) with no `tenant_id` scoping and no persistence**. (I read `population_transfer.py` and `data_assessment.py` directly; I did NOT trace how the orchestrator instantiates `PopulationTransfer`, so treat the cross-tenant claim below as a risk to verify, not a confirmed defect.) Concrete work items:

### 3.1 (HIGH / correctness + tenant isolation) Make posteriors per-tenant and persisted
- **Verified:** there is no `tenant_id` anywhere in the posterior store, and updates live only in process memory (lost on restart, not shared across worker processes).
- **Risk to verify:** if a single `PopulationTransfer` instance is shared process-wide (common for a stateless service singleton), then **Hospital A's observed outcomes would update the prior Hospital B sees** — a cross-tenant data-contamination bug and a tenant-isolation concern under `.kiro/steering/security-hipaa.md` (aggregate outcome counts derived from one tenant's PHI must not influence another tenant's output). Confirm the instantiation pattern before assuming severity.
- **Required end state regardless of the above:** posteriors scoped by `tenant_id` and persisted (Postgres table with RLS, same pattern as every other module). The published `POPULATION_PRIORS` values are the **shared, non-tenant starting prior**; each tenant's posterior forks from that and is updated only by *that tenant's* local outcomes.

### 3.2 (MEDIUM) Wire cold-start to deployment mode, not just per-patient data
- Add a tenant-level notion of "still in cold-start" (e.g., local outcome count for a disease below a threshold) so the engine knows when it is relying on population priors vs. locally-calibrated models.
- Full-EMR greenfield tenant → starts fully in cold-start. Module-only buyer with imported history → may start already past it. Don't hardcode; derive it from how much local outcome data the tenant actually has.

### 3.3 (MEDIUM) Blend, using the sufficiency score that already exists
- Use `DataAssessor` sufficiency (Layer 1) + tenant cold-start state to weight the population-prior baseline vs. trained-model output. Low data → prior dominates; as data accrues → model dominates. Requirement 8.6 already describes this "reduce reliance proportionally" behaviour for forecasting — mirror it for risk. Before changing the `PopulationTransfer` interface, check whether `meta_learner.py` and `orchestrator.py` consume it (I did not read those two files).

### 3.4 (HONESTY — do not oversell) Be precise about what a cold-start prediction *is*
A day-1 cold-start output is essentially **"the population base rate for a patient with these demographics"** — a prior, not a personalised prediction. It personalises as the patient (and the tenant) accumulate data. This is exactly how Framingham/QRISK-style tools work, so it's legitimate — but the UI/SHAP/report layer must label it honestly (the spec's Req 6.7 "indicate which features were imputed" is the hook). Do not present a cold-start prior as if it were a data-driven personalised risk score.

---

## 4. The epidemiological prior numbers need sourcing before they ship

`POPULATION_PRIORS` in `population_transfer.py` contains Beta(α, β) values per disease per region (e.g. stroke west_african = Beta(4, 96) ≈ 4%). The docstring cites "WHO Global Health Estimates, Lancet population studies" **in general**, but there is no per-value citation, and the numbers read as reasonable-but-illustrative defaults.

For a clinical product these drive real day-1 output, so before launch each value needs either (a) a specific sourced citation, or (b) a clear in-product label that these are rough population defaults pending calibration. **Do not let these ship looking authoritative if they are not individually sourced.** (This caution is deliberate: the sister research project was reset precisely because numbers that looked authoritative turned out not to be — see that project's `DECISION_LOG.md`. Same discipline applies here.)

---

## 5. Guardrails from this workspace's steering (apply as normal)

- **Tenant isolation (`security-hipaa.md`):** per §3.1 — posteriors are per-tenant, RLS-enforced, never a shared global.
- **No PHI in logs (`logging-observability.md`):** `update_posterior` currently logs disease/population and Beta parameters — that's aggregate, not PHI, which is fine, but keep patient-level outcomes out of logs when wiring the batch update path.
- **Testing (`testing-conventions.md`):** add a property test for the core invariant — *a tenant's posterior mean always moves monotonically toward that tenant's observed local event rate as outcomes accumulate, and is never influenced by another tenant's outcomes.* That single property covers both the Bayesian correctness and the isolation fix.
- **Modularity / commenting (`code-style.md`):** the existing file is well-commented and ~150 lines; keep the persistence/tenant-scoping in a separate module rather than bloating it.
- **Change-impact (`change-impact-analysis.md`):** verify which modules import `PopulationTransfer` (candidates: `meta_learner.py`, `orchestrator.py`, the risk-engine backend task in spec tasks 9/13) before altering its interface.

---

## 6. Suggested sequencing

Cold-start is a layer *on top of* the trained per-disease models. It has genuine standalone value (the greenfield tenant needs it), but the blend in §3.3 only matters once real models exist. Reasonable order:
1. §3.1 first — per-tenant persisted posteriors (a correctness/isolation fix worth doing regardless of the rest).
2. §3.2 + §3.4 — tenant cold-start state + honest labelling.
3. §3.3 — blend with trained models, once the risk-engine model layer (spec tasks 9 and 13) is built.
4. §4 — sourcing/calibration of the prior table before any real deployment.

---

*Handoff written after reading: both specs' requirements/tasks (`prescphealth-saas-rebuild`, `emr-hospital-system`), the ML engine layout (`ml/risk_engine/`, `ml/forecast_engine/`), `population_transfer.py` and `data_assessment.py` in full, and the sister research project's teardown. Not read in full: `meta_learner.py`, `orchestrator.py`, the two specs' design.md files. Questions on the product rationale / two sales motions → ask the human; questions on the discontinued patent/paper context → see that project's `PATENT_PAPER_TEARDOWN.md` and `DECISION_LOG.md`.*
