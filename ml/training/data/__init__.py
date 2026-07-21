"""
PrescpHealth ML Training — Data extraction subpackage.

Turns raw MIMIC-IV tables into a labelled training cohort. Kept deliberately
small and composable:

    paths.py          — env-driven resolution of the MIMIC-IV data root
    disease_labels.py — ICD-10 → 6-disease label assignment
    mimic_cohort.py   — cohort selection + label join → training frame

Design intent: every step is independently unit-testable against tiny synthetic
frames (no real PHI, no dependency on the AWS data box), so the pipeline can be
verified for correctness BEFORE it is ever run against the 364k-patient dataset.
This directly answers the statistical-discipline rule in
docs/ml/dataset-roles-and-validation.md — verify at every step, don't rush to
trained artifacts.
"""
