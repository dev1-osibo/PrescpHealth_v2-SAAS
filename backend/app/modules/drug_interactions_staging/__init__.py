"""
PrescpHealth Backend — Drug Interaction Safety Engine Module (Staging).

Detects and manages drug-drug interactions (DDI) and drug-health interactions (DHI).

Module Responsibility:
    - Detect DDI when medications are added/changed
    - Detect DHI when medication conflicts with patient's health conditions
    - Consider patient factors: age, renal function (eGFR), sex
    - Enable clinician overrides with mandatory justification
    - Re-evaluate interactions when patient health changes
    - Provide safety summary (Safe/Caution/Action Required)

Key Components:
    - models.py: SQLAlchemy models (MedicationRecord, InteractionResult, DrugInteractionsDB)
    - engine.py: DDI/DHI matching logic
    - service.py: DrugInteractionService (add med, check safety, override)
    - router.py: FastAPI endpoints with RBAC
    - schemas.py: Pydantic request/response models

Dependencies:
    - Requires Task 7 (Measurement module) for patient health data (eGFR, labs)
    - Requires Task 5 (Patient module) for patient demographics
    - Requires RxNorm/ATC drug codes (reference data)
    - Requires core services: audit, events, pagination

HIPAA Compliance:
    - Medication records are PHI — encrypted at rest
    - Interaction assessments are PHI — never log raw data
    - All interactions audited for compliance
"""

from app.modules.drug_interactions_staging.service import DrugInteractionService
from app.modules.drug_interactions_staging.router import router

__all__ = ["DrugInteractionService", "router"]
