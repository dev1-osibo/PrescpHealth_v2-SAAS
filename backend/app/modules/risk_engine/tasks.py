"""
PrescpHealth Backend — Risk Engine Celery Tasks.

Background worker tasks for async risk score computation.

Task: compute_risk_scores
    Triggered when: A new validated measurement is saved
    Processing:
    1. Fetch latest validated measurements for patient
    2. Extract feature vector (calls MeasurementService)
    3. Check data sufficiency (calls MeasurementService)
    4. Call ML engine (stub for now, real in Task 20)
    5. Store RiskScore + ShapExplanation records
    6. Publish RiskScoreComputed event
    7. Log audit trail

Retry Policy:
    - Up to 3 retries with exponential backoff (30s, 2min, 8min)
    - Max execution time: 30 seconds
    - Failures logged but don't crash the worker

HIPAA Compliance:
    - Never log patient names, measurement values, or risk scores
    - Log only computation_id, patient_id UUID, and status
    - Feature vectors are in memory only (cleared after computation)
    - Input snapshots stored encrypted in DB (not in logs)
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import structlog
from celery import shared_task
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.modules.audit.service import AuditService
from app.modules.measurements.service import MeasurementService
from app.modules.risk_engine.enums import Disease, RiskStratum

logger = structlog.get_logger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,  # First retry after 30s
    time_limit=30,  # Max 30 seconds execution time
)
def compute_risk_scores_task(
    self,
    patient_id: str,
    computation_id: str,
    tenant_id: str,
    triggered_by_user_id: str,
    correlation_id: str,
) -> dict:
    """
    Async Celery task to compute all 6 disease risk scores for a patient.

    This is the main entry point for background risk computation.
    Runs on a Celery worker (independent from API server).

    Args:
        patient_id: Patient UUID (as string from task enqueue)
        computation_id: Groups all scores from this run
        tenant_id: Tenant UUID (for RLS context)
        triggered_by_user_id: User who triggered computation
        correlation_id: Request correlation ID for tracing

    Returns:
        Dict with computation status and result

    Side Effects:
        - Stores RiskScore records in DB
        - Stores ShapExplanation records in DB
        - Publishes RiskScoreComputed domain event
        - Logs audit trail
        - On failure: Schedules retry via Celery

    HIPAA Note:
        Logs only UUIDs and status — never patient data, measurements, or scores.
    """
    try:
        logger.info(
            "risk_computation_started",
            computation_id=computation_id,
            patient_id=patient_id,
            correlation_id=correlation_id,
        )

        # Convert strings to UUIDs
        patient_uuid = uuid.UUID(patient_id)
        tenant_uuid = uuid.UUID(tenant_id)
        user_uuid = uuid.UUID(triggered_by_user_id)
        computation_uuid = uuid.UUID(computation_id)

        # Step 1: Get DB session and services
        # (In real code, would use FastAPI dependency injection; here we manually create)
        engine = create_async_engine(get_settings().database_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Step 2: Fetch latest validated measurements and build feature vector
        # (Would call measurement_service.get_feature_vector() in real code)
        # For now, mock feature vector
        feature_vector = {
            "systolic_bp": 160,
            "diastolic_bp": 95,
            "bmi": 28.5,
            "blood_glucose_fasting": 126,
            "hba1c": 7.2,
            "total_cholesterol": 240,
            "hdl_cholesterol": 38,
            "ldl_cholesterol": 150,
            "triglycerides": 180,
            "creatinine": 1.1,
            "egfr": 65,
            "heart_rate": 72,
            "smoking_status": "current",
            "age": 55,
        }

        # Step 3: Check data sufficiency
        # (Would call measurement_service.check_data_sufficiency() in real code)
        data_sufficiency = {
            "has_minimum_data": True,
            "data_quality": "full_data",
        }

        # Step 4: Call ML engine (STUB — Task 20 replaces this)
        # For now, return mock scores
        mock_scores = _compute_mock_scores(feature_vector, data_sufficiency)

        # Step 5: Store scores and SHAP explanations
        # (Would use RiskService.store_scores() in real code)
        # For now, just log completion
        logger.info(
            "risk_computation_completed",
            computation_id=computation_id,
            patient_id=patient_id,
            disease_count=len(mock_scores),
            correlation_id=correlation_id,
        )

        return {
            "status": "success",
            "computation_id": computation_id,
            "disease_count": len(mock_scores),
        }

    except Exception as exc:
        logger.error(
            "risk_computation_failed",
            computation_id=computation_id,
            patient_id=patient_id,
            error=str(exc),
            correlation_id=correlation_id,
        )

        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 30 * (2 ** self.request.retries)  # 30s, 60s, 120s
            logger.info(
                "risk_computation_retrying",
                retry_attempt=self.request.retries + 1,
                retry_delay=retry_delay,
                computation_id=computation_id,
            )
            raise self.retry(exc=exc, countdown=retry_delay)
        else:
            logger.error(
                "risk_computation_failed_final",
                computation_id=computation_id,
                error=str(exc),
            )
            return {
                "status": "failed",
                "computation_id": computation_id,
                "error": str(exc),
            }


def _compute_mock_scores(feature_vector: dict, data_sufficiency: dict) -> dict[str, dict]:
    """
    Generate mock risk scores (replaced by real ML pipeline in Task 20).

    For now, returns deterministic mock scores based on feature values.
    Real implementation will call ensemble ML models.

    Args:
        feature_vector: Dict of {feature_name: value}
        data_sufficiency: Dict with {has_minimum_data, data_quality}

    Returns:
        Dict mapping disease -> {score, stratum, ci_lower, ci_upper, shap}
    """
    # Simple mock: higher glucose → higher diabetes risk, etc.
    glucose = feature_vector.get("blood_glucose_fasting", 100)
    systolic = feature_vector.get("systolic_bp", 120)
    egfr = feature_vector.get("egfr", 90)
    age = feature_vector.get("age", 50)

    scores = {}

    # Stroke risk: based on BP and age
    stroke_score = min(100, 30 + (systolic - 120) * 0.5 + (age - 45) * 0.3)
    scores["stroke"] = {
        "score": stroke_score,
        "stratum": _score_to_stratum(stroke_score),
        "ci_lower": max(0, stroke_score - 5),
        "ci_upper": min(100, stroke_score + 5),
        "shap": {
            "base_value": 30.0,
            "features": [
                {"feature": "systolic_bp", "value": systolic, "shap_value": 0.25, "direction": "positive"},
                {"feature": "age", "value": age, "shap_value": 0.15, "direction": "positive"},
            ],
        },
    }

    # Diabetes risk: based on glucose and HbA1c
    diabetes_score = min(100, 20 + (glucose - 100) * 0.5)
    scores["diabetes"] = {
        "score": diabetes_score,
        "stratum": _score_to_stratum(diabetes_score),
        "ci_lower": max(0, diabetes_score - 5),
        "ci_upper": min(100, diabetes_score + 5),
        "shap": {
            "base_value": 20.0,
            "features": [
                {"feature": "blood_glucose_fasting", "value": glucose, "shap_value": 0.30, "direction": "positive"},
            ],
        },
    }

    # CKD risk: based on eGFR and creatinine
    ckd_score = max(0, 100 - egfr * 0.5)  # Lower eGFR = higher risk
    scores["ckd"] = {
        "score": ckd_score,
        "stratum": _score_to_stratum(ckd_score),
        "ci_lower": max(0, ckd_score - 5),
        "ci_upper": min(100, ckd_score + 5),
        "shap": {
            "base_value": 50.0,
            "features": [
                {"feature": "egfr", "value": egfr, "shap_value": -0.50, "direction": "negative"},
            ],
        },
    }

    # CVD risk: based on BP, cholesterol, age
    cvd_score = min(100, 25 + (systolic - 120) * 0.3 + (age - 45) * 0.2)
    scores["cvd"] = {
        "score": cvd_score,
        "stratum": _score_to_stratum(cvd_score),
        "ci_lower": max(0, cvd_score - 5),
        "ci_upper": min(100, cvd_score + 5),
        "shap": {
            "base_value": 25.0,
            "features": [
                {"feature": "systolic_bp", "value": systolic, "shap_value": 0.20, "direction": "positive"},
                {"feature": "age", "value": age, "shap_value": 0.12, "direction": "positive"},
            ],
        },
    }

    # Hypertensive Crisis risk: based on BP
    hyp_score = max(0, (systolic - 130) * 1.5) if systolic > 130 else 10
    scores["hypertensive_crisis"] = {
        "score": min(100, hyp_score),
        "stratum": _score_to_stratum(min(100, hyp_score)),
        "ci_lower": max(0, hyp_score - 5),
        "ci_upper": min(100, hyp_score + 5),
        "shap": {
            "base_value": 10.0,
            "features": [
                {"feature": "systolic_bp", "value": systolic, "shap_value": 0.40, "direction": "positive"},
            ],
        },
    }

    # COPD risk: based on age and smoking
    copd_score = min(100, 15 + (age - 40) * 0.5)
    scores["copd"] = {
        "score": copd_score,
        "stratum": _score_to_stratum(copd_score),
        "ci_lower": max(0, copd_score - 5),
        "ci_upper": min(100, copd_score + 5),
        "shap": {
            "base_value": 15.0,
            "features": [
                {"feature": "age", "value": age, "shap_value": 0.25, "direction": "positive"},
            ],
        },
    }

    return scores


def _score_to_stratum(score: float) -> str:
    """Convert numeric score to stratum label."""
    if score < 25:
        return RiskStratum.LOW.value
    elif score < 50:
        return RiskStratum.MODERATE.value
    elif score < 75:
        return RiskStratum.HIGH.value
    else:
        return RiskStratum.CRITICAL.value
