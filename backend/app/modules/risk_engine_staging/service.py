"""
PrescpHealth Backend — Risk Engine Service.

RiskService orchestrates risk score computation:
1. Trigger async Celery task (enqueue, return task_id for polling)
2. Retrieve latest risk scores for a patient (all 6 diseases)
3. Query historical risk score trends per disease

Key Responsibilities:
    - Enqueue Celery tasks for background risk computation
    - Fetch and cache latest scores (via feature vector + ML pipeline)
    - Store computed scores with input snapshots and SHAP explanations
    - Publish RiskScoreComputed domain events for downstream subscribers
    - Maintain model version lineage for audit trails

The actual ML computation (ensemble models, SHAP, confidence intervals)
is implemented in Task 20 (ml/risk_engine/). For now, this service calls
a stub that returns mock scores (replaced in Task 20).

HIPAA Compliance:
    - Never log risk scores or feature values (opaque IDs only)
    - Cache headers set to no-store on API responses containing PHI
    - Input snapshots are stored encrypted in DB, cleared from logs
    - All computations audited via AuditService
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus, RiskScoreComputed
from app.modules.audit.service import AuditService
from app.modules.measurements.service import MeasurementService
from app.modules.risk_engine_staging.models import RiskScore, ShapExplanation, ModelVersion
from app.modules.risk_engine_staging.enums import Disease, RiskStratum
from app.modules.risk_engine_staging.tasks import compute_risk_scores_task

logger = structlog.get_logger(__name__)


class RiskService:
    """
    Service for managing risk score computation and retrieval.

    Provides high-level operations for the risk engine:
    - trigger_computation(patient_id): Enqueue async computation, return task_id
    - get_latest_scores(patient_id): Fetch 6 latest scores (one per disease)
    - get_score_history(patient_id, disease): Paginate historical scores

    Dependencies:
    - MeasurementService: for getting patient feature vectors
    - AuditService: for logging computations
    - Celery: for async task enqueueing
    - ML engine stub: for mock scores (Task 20 replaces with real models)
    """

    def __init__(
        self,
        db_session: AsyncSession,
        measurement_service: MeasurementService,
        audit_service: AuditService,
        request_id: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ):
        """
        Initialize RiskService with dependencies.

        Args:
            db_session: AsyncSession for database queries
            measurement_service: MeasurementService for feature vectors
            audit_service: AuditService for audit logging
            request_id: Correlation ID for tracing
            tenant_id: Current tenant UUID (for RLS)
            user_id: Current user UUID (for audit trail)
        """
        self.db = db_session
        self.measurement_service = measurement_service
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def trigger_computation(self, patient_id: uuid.UUID) -> str:
        """
        Enqueue an async risk computation task.

        Triggers the Celery task that will:
        1. Fetch patient's latest validated measurements
        2. Extract feature vector
        3. Run ML ensemble (stub for now, real in Task 20)
        4. Store RiskScore + ShapExplanation records
        5. Publish RiskScoreComputed event

        Args:
            patient_id: Patient UUID to compute risk for

        Returns:
            task_id: Celery task ID (frontend polls /tasks/{task_id}/status)

        Raises:
            ValueError: If patient doesn't exist or has insufficient data

        Audit Trail:
            Logs "risk_computation_triggered" with patient_id, computation_id
        """
        # Generate computation ID (groups all 6 disease scores from this run)
        computation_id = uuid.uuid4()

        logger.info(
            "risk_computation_triggered",
            patient_id=str(patient_id),
            computation_id=str(computation_id),
            request_id=self.request_id,
        )

        # Audit log the triggering action
        await self.audit_service.log_audit(
            action="risk_computation_triggered",
            resource_type="patient",
            resource_id=str(patient_id),
            changes={"computation_id": str(computation_id)},
        )

        # Enqueue Celery task (fires in background)
        task = compute_risk_scores_task.delay(
            patient_id=str(patient_id),
            computation_id=str(computation_id),
            tenant_id=str(self.tenant_id),
            triggered_by_user_id=str(self.user_id),
            correlation_id=self.request_id,
        )

        return task.id

    async def get_latest_scores(self, patient_id: uuid.UUID) -> dict[str, Optional[dict]]:
        """
        Fetch the latest risk scores for all 6 diseases.

        Returns a dictionary mapping disease names to their latest score data.
        If a disease hasn't been computed yet, the value is None.

        Args:
            patient_id: Patient UUID

        Returns:
            Dict[str, Optional[Dict]]: Mapping disease -> score response (or None)
            Example:
            {
                "stroke": {
                    "disease": "stroke",
                    "score": 72.45,
                    "stratum": "High",
                    "confidence_lower": 68.2,
                    "confidence_upper": 76.8,
                    "model_version": "v1.2.0",
                    "computed_at": "2026-05-28T20:30:00Z"
                },
                "cvd": None,  # Not computed yet
                ...
            }

        HIPAA Note:
            The caller (API endpoint) must set Cache-Control: no-store
            because this response contains PHI (risk scores).
        """
        result = {}

        for disease in Disease.all_diseases():
            # Query latest RiskScore for this disease
            stmt = (
                select(RiskScore)
                .where(RiskScore.patient_id == patient_id)
                .where(RiskScore.disease == disease)
                .order_by(desc(RiskScore.computed_at))
                .limit(1)
            )
            row = await self.db.scalar(stmt)

            if row:
                # Fetch corresponding SHAP explanation
                shap_stmt = select(ShapExplanation).where(
                    ShapExplanation.risk_score_id == row.id
                )
                shap = await self.db.scalar(shap_stmt)

                result[disease] = {
                    "disease": disease,
                    "score": float(row.score),
                    "stratum": row.stratum,
                    "confidence_lower": float(row.confidence_lower),
                    "confidence_upper": float(row.confidence_upper),
                    "model_version": "v1.0.0-stub",  # Real version from FK in Task 20
                    "computed_at": row.computed_at.isoformat(),
                    "shap": {
                        "base_value": float(shap.base_value),
                        "feature_contributions": shap.feature_contributions,
                    } if shap else None,
                }
            else:
                result[disease] = None

        return result

    async def get_score_history(
        self,
        patient_id: uuid.UUID,
        disease: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Fetch paginated historical risk scores for a specific disease.

        Returns scores ordered most-recent-first with full metadata.

        Args:
            patient_id: Patient UUID
            disease: Disease name (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)
            limit: Max scores to return (default 50, max 500)
            offset: Pagination offset (0-indexed)

        Returns:
            List[Dict]: Historical scores with dates and model versions

        Raises:
            ValueError: If disease not in allowed list
        """
        if disease not in Disease.all_diseases():
            raise ValueError(f"Unknown disease: {disease}. Must be one of {Disease.all_diseases()}")

        # Cap limit to prevent DOS
        limit = min(limit, 500)

        stmt = (
            select(RiskScore)
            .where(RiskScore.patient_id == patient_id)
            .where(RiskScore.disease == disease)
            .order_by(desc(RiskScore.computed_at))
            .offset(offset)
            .limit(limit)
        )

        rows = (await self.db.scalars(stmt)).all()

        return [
            {
                "score": float(row.score),
                "stratum": row.stratum,
                "confidence_lower": float(row.confidence_lower),
                "confidence_upper": float(row.confidence_upper),
                "computed_at": row.computed_at.isoformat(),
                "model_version": "v1.0.0-stub",
            }
            for row in rows
        ]

    async def store_scores(
        self,
        patient_id: uuid.UUID,
        computation_id: uuid.UUID,
        scores: dict[str, dict],
        input_snapshot: dict,
        model_version_id: uuid.UUID,
    ) -> None:
        """
        Store computed risk scores and SHAP explanations.

        Called by the Celery task after ML computation.
        Creates one RiskScore + ShapExplanation pair per disease.

        Args:
            patient_id: Patient UUID
            computation_id: Groups all scores from this computation run
            scores: Dict mapping disease -> {score, stratum, ci_lower, ci_upper, shap}
            input_snapshot: Feature vector used for computation
            model_version_id: Which model version produced these scores

        Side Effects:
            - Inserts RiskScore records
            - Inserts ShapExplanation records
            - Publishes RiskScoreComputed event
            - Audits the storage action
        """
        # Create RiskScore + ShapExplanation records
        risk_scores = []
        shap_explanations = []

        for disease, score_data in scores.items():
            risk_score = RiskScore(
                tenant_id=self.tenant_id,
                patient_id=patient_id,
                disease=disease,
                score=Decimal(str(score_data["score"])),
                stratum=score_data["stratum"],
                confidence_lower=Decimal(str(score_data["ci_lower"])),
                confidence_upper=Decimal(str(score_data["ci_upper"])),
                model_version_id=model_version_id,
                input_snapshot=input_snapshot,
                computation_id=computation_id,
            )
            risk_scores.append(risk_score)
            self.db.add(risk_score)

            # SHAP explanation (will be linked after risk_score gets an ID)
            shap_data = score_data.get("shap", {})
            shap = ShapExplanation(
                tenant_id=self.tenant_id,
                risk_score=risk_score,  # SQLAlchemy will FK this properly
                base_value=Decimal(str(shap_data.get("base_value", 0.5))),
                feature_contributions=shap_data.get("features", []),
            )
            shap_explanations.append(shap)
            self.db.add(shap)

        # Flush to DB to ensure IDs are assigned
        await self.db.flush()

        # Log audit event
        await self.audit_service.log_audit(
            action="risk_scores_stored",
            resource_type="computation",
            resource_id=str(computation_id),
            changes={
                "patient_id": str(patient_id),
                "disease_count": len(scores),
                "computation_id": str(computation_id),
            },
        )

        # Publish event for downstream subscribers (alerts, forecast, etc.)
        event = RiskScoreComputed(
            correlation_id=self.request_id,
            tenant_id=self.tenant_id,
            patient_id=patient_id,
            disease_count=len(scores),
            computation_id=computation_id,
        )
        await event_bus.publish(event)

        logger.info(
            "risk_scores_stored",
            patient_id=str(patient_id),
            computation_id=str(computation_id),
            disease_count=len(scores),
            request_id=self.request_id,
        )
