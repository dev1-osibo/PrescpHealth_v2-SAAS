"""
PrescpHealth Backend — Risk Engine Module (Staging).

The Risk Engine module computes disease risk scores for patients using
an ensemble of ML models (XGBoost, LightGBM, Random Forest, Neural Network).

Module Responsibility:
    - Expose API endpoints for triggering and retrieving risk computations
    - Manage async Celery tasks for background score computation
    - Store risk scores, confidence intervals, and SHAP explanations
    - Track ML model versions for audit and rollback
    - Publish RiskScoreComputed domain events for downstream subscribers

Key Components:
    - models.py: SQLAlchemy models (RiskScore, ShapExplanation, ModelVersion)
    - service.py: RiskService (trigger, retrieve, store)
    - tasks.py: Celery task for async risk computation
    - router.py: FastAPI endpoints with RBAC
    - schemas.py: Pydantic request/response models
    - enums.py: Disease and stratum enums

Dependencies:
    - Requires Task 7 (Measurement module) for feature vector extraction
    - Requires Task 5 (Patient module) for patient data
    - Requires core services: audit, events, pagination
    - Requires ML pipeline (Task 20) — currently stubbed

HIPAA Compliance:
    - Risk scores are PHI when tied to patient_id — never log values
    - Feature snapshots are PHI — encrypted at rest, cleared in logs
    - All responses include Cache-Control: no-store
    - All computation audited via AuditService
"""

from app.modules.risk_engine.service import RiskService
from app.modules.risk_engine.router import router

__all__ = ["RiskService", "router"]
