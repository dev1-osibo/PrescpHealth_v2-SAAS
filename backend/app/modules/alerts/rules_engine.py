"""
PrescpHealth Backend — Alert Rules Engine.

Evaluates incoming domain events against configured AlertThreshold records and
fires alerts when thresholds are breached.

Design:
- Subscribes to domain events via event_bus (measurement_saved, risk_score_computed, forecast_completed)
- Queries tenant-scoped AlertThreshold records for each patient event
- Patient-specific thresholds are evaluated; tenant-wide defaults fill gaps
- All alert creation is delegated to AlertService
"""
import uuid
import structlog
from typing import Any
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.alerts.enums import AlertType, AlertSeverity, ThresholdCondition
from app.modules.alerts.models import AlertThreshold

logger = structlog.get_logger(__name__)


class AlertRulesEngine:
    """
    Evaluates domain events against alert threshold configurations.
    Instantiated per-evaluation with an injected DB session and AlertService.
    """

    def __init__(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        alert_service: Any,
    ) -> None:
        """
        Args:
            db: Async SQLAlchemy session for threshold queries.
            tenant_id: Current tenant scope; all threshold queries are filtered by this.
            alert_service: AlertService instance used to create alerts on breach.
        """
        self.db = db
        self.tenant_id = tenant_id
        self.alert_service = alert_service

    async def _load_thresholds(
        self,
        patient_id: uuid.UUID,
        measurement_type: str | None = None,
        disease: str | None = None,
    ) -> list[AlertThreshold]:
        """
        Load active thresholds for a patient, including tenant-wide defaults.

        Patient-specific thresholds (patient_id matches) and tenant-wide defaults
        (patient_id IS NULL) are both loaded and evaluated.

        Args:
            patient_id: Patient to load thresholds for.
            measurement_type: Filter to measurement-based thresholds if provided.
            disease: Filter to risk-score-based thresholds if provided.

        Returns:
            All matching active AlertThreshold records.
        """
        conditions = [
            AlertThreshold.tenant_id == self.tenant_id,
            AlertThreshold.is_active == True,          # noqa: E712 — SQLAlchemy requires == True
            or_(
                AlertThreshold.patient_id == patient_id,
                AlertThreshold.patient_id.is_(None),   # Tenant-wide defaults
            ),
        ]

        # Only filter by measurement_type or disease when explicitly provided
        if measurement_type:
            conditions.append(AlertThreshold.measurement_type == measurement_type)
        if disease:
            conditions.append(AlertThreshold.disease == disease)

        stmt = select(AlertThreshold).where(and_(*conditions))
        return list((await self.db.scalars(stmt)).all())

    async def evaluate_measurement(
        self,
        patient_id: uuid.UUID,
        measurement_type: str,
        value: float,
    ) -> None:
        """
        Evaluate a patient measurement against configured thresholds.

        Triggers THRESHOLD_BREACH alerts for ABOVE/BELOW conditions.
        PHI-safe: only logs patient_id UUID and measurement_type — never the value.

        Args:
            patient_id: Patient whose measurement was recorded.
            measurement_type: Clinical measurement type (e.g. "blood_glucose").
            value: The measured value used for threshold comparison.
        """
        thresholds = await self._load_thresholds(
            patient_id=patient_id,
            measurement_type=measurement_type,
        )

        for threshold in thresholds:
            breached = False

            if threshold.condition == ThresholdCondition.ABOVE.value:
                # Alert when measured value exceeds configured maximum
                breached = threshold.threshold_value is not None and value > threshold.threshold_value
            elif threshold.condition == ThresholdCondition.BELOW.value:
                # Alert when measured value drops below configured minimum
                breached = threshold.threshold_value is not None and value < threshold.threshold_value

            if breached:
                logger.info(
                    "threshold_breach_detected",
                    patient_id=str(patient_id),
                    measurement_type=measurement_type,
                    condition=threshold.condition,
                    threshold_id=str(threshold.id),
                    tenant_id=str(self.tenant_id),
                    # NOTE: value NOT logged — contains PHI
                )

                await self.alert_service.create_alert(
                    alert_type=AlertType.THRESHOLD_BREACH,
                    severity=AlertSeverity(threshold.severity),
                    patient_id=patient_id,
                    title=f"Threshold breach: {measurement_type}",
                    message=(
                        f"Measurement {measurement_type} {threshold.condition} "
                        f"configured threshold"
                    ),
                    payload={
                        "threshold_id": str(threshold.id),
                        "measurement_type": measurement_type,
                        "condition": threshold.condition,
                        # Storing value in payload for clinical review; never in logs
                        "measured_value": value,
                        "threshold_value": threshold.threshold_value,
                    },
                )

    async def evaluate_risk_score(
        self,
        patient_id: uuid.UUID,
        disease: str,
        score: float,
        stratum: str,
    ) -> None:
        """
        Evaluate a computed risk score against stratum-based thresholds.

        Triggers RISK_CRITICAL alerts when a patient enters a monitored risk stratum.
        PHI-safe: logs patient_id UUID, disease, and stratum name — never numeric score.

        Args:
            patient_id: Patient whose risk score was computed.
            disease: Disease model that generated the score (e.g. "diabetes").
            score: Computed risk score (stored in payload; never logged).
            stratum: Named risk stratum (e.g. "critical", "high").
        """
        thresholds = await self._load_thresholds(patient_id=patient_id, disease=disease)

        for threshold in thresholds:
            # Check enters_stratum condition: patient moved into a monitored risk band
            if (
                threshold.condition == ThresholdCondition.ENTERS_STRATUM.value
                and threshold.target_stratum == stratum
            ):
                logger.info(
                    "risk_stratum_breach",
                    patient_id=str(patient_id),
                    disease=disease,
                    stratum=stratum,
                    threshold_id=str(threshold.id),
                    tenant_id=str(self.tenant_id),
                )

                await self.alert_service.create_alert(
                    alert_type=AlertType.RISK_CRITICAL,
                    severity=AlertSeverity(threshold.severity),
                    patient_id=patient_id,
                    title=f"Risk alert: {disease} entered {stratum} stratum",
                    message=f"Patient risk for {disease} has entered the {stratum} stratum",
                    payload={
                        "disease": disease,
                        "stratum": stratum,
                        "threshold_id": str(threshold.id),
                        "score": score,  # Stored in payload for clinical review; never logged
                    },
                )

    async def evaluate_forecast(
        self,
        patient_id: uuid.UUID,
        forecast_data: dict[str, Any],
    ) -> None:
        """
        Evaluate forecast projections for threshold crossings.

        Checks whether the forecasted trajectory is projected to breach any configured
        threshold within the forecast horizon.

        Args:
            patient_id: Patient whose forecast was completed.
            forecast_data: Forecast payload (projections, horizon, disease context).
        """
        # Extract projected crossings from forecast payload
        projected_crossings = forecast_data.get("projected_crossings", [])

        for crossing in projected_crossings:
            measurement_type = crossing.get("measurement_type", "")
            days_until = crossing.get("days_until", 0)

            logger.info(
                "forecast_threshold_crossing_detected",
                patient_id=str(patient_id),
                measurement_type=measurement_type,
                days_until=days_until,
                tenant_id=str(self.tenant_id),
                # NOTE: projected values NOT logged — contains PHI
            )

            await self.alert_service.create_alert(
                alert_type=AlertType.FORECAST_WARNING,
                severity=AlertSeverity.MODERATE,
                patient_id=patient_id,
                title=f"Forecast warning: {measurement_type} projected to breach threshold",
                message=(
                    f"Forecast projects {measurement_type} threshold breach "
                    f"in approximately {days_until} days"
                ),
                payload={
                    "forecast_id": str(forecast_data.get("forecast_id", "")),
                    "measurement_type": measurement_type,
                    "days_until": days_until,
                    "projected_value": crossing.get("projected_value"),  # PHI; in payload only
                },
            )

    async def check_missed_followup(self, patient_id: uuid.UUID) -> bool:
        """
        Placeholder for missed follow-up detection logic.

        Full implementation will query the appointments/scheduling module for
        overdue follow-ups and generate MISSED_FOLLOWUP alerts.

        TODO (later task): Integrate with appointments module once available.

        Args:
            patient_id: Patient to check for missed follow-ups.

        Returns:
            False — placeholder always returns no missed follow-up detected.
        """
        logger.info(
            "check_missed_followup_placeholder",
            patient_id=str(patient_id),
            tenant_id=str(self.tenant_id),
            note="Full implementation pending appointments module integration",
        )
        # Placeholder — will integrate with appointments module in a later task
        return False

    def register_subscriptions(self) -> None:
        """
        Subscribe the rules engine to domain events from the event bus.

        Each handler creates a fresh DB session so events are processed
        independently of any HTTP request context.

        Subscriptions:
        - measurement_saved → evaluate_measurement
        - risk_score_computed → evaluate_risk_score
        - forecast_completed → evaluate_forecast
        """
        from app.core.database import get_async_session_context
        from app.modules.audit.service import AuditService
        from app.modules.alerts.service import AlertService

        async def on_measurement_saved(event: Any) -> None:
            """Handle measurement_saved domain event."""
            async with get_async_session_context() as db:
                # Build a minimal AlertService for the rules engine to delegate to
                svc = AlertService(
                    db=db,
                    audit_service=AuditService(db=db, tenant_id=event.tenant_id),
                    request_id="event_bus",
                    tenant_id=event.tenant_id,
                    user_id=uuid.UUID(int=0),  # System actor for event-driven alerts
                )
                engine = AlertRulesEngine(db=db, tenant_id=event.tenant_id, alert_service=svc)
                await engine.evaluate_measurement(
                    patient_id=event.patient_id,
                    measurement_type=event.measurement_type,
                    value=getattr(event, "value", 0.0),
                )

        async def on_risk_score_computed(event: Any) -> None:
            """Handle risk_score_computed domain event."""
            async with get_async_session_context() as db:
                svc = AlertService(
                    db=db,
                    audit_service=AuditService(db=db, tenant_id=event.tenant_id),
                    request_id="event_bus",
                    tenant_id=event.tenant_id,
                    user_id=uuid.UUID(int=0),
                )
                engine = AlertRulesEngine(db=db, tenant_id=event.tenant_id, alert_service=svc)
                await engine.evaluate_risk_score(
                    patient_id=event.patient_id,
                    disease=getattr(event, "disease", ""),
                    score=getattr(event, "score", 0.0),
                    stratum=getattr(event, "stratum", ""),
                )

        async def on_forecast_completed(event: Any) -> None:
            """Handle forecast_completed domain event."""
            async with get_async_session_context() as db:
                svc = AlertService(
                    db=db,
                    audit_service=AuditService(db=db, tenant_id=event.tenant_id),
                    request_id="event_bus",
                    tenant_id=event.tenant_id,
                    user_id=uuid.UUID(int=0),
                )
                engine = AlertRulesEngine(db=db, tenant_id=event.tenant_id, alert_service=svc)
                await engine.evaluate_forecast(
                    patient_id=event.patient_id,
                    forecast_data=getattr(event, "forecast_data", {}),
                )

        # Register all event handlers with the central event bus
        event_bus.subscribe("measurement_saved", on_measurement_saved)
        event_bus.subscribe("risk_score_computed", on_risk_score_computed)
        event_bus.subscribe("forecast_completed", on_forecast_completed)

        logger.info("alert_rules_engine_subscriptions_registered")
