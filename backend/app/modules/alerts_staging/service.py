"""
PrescpHealth Backend — Alert Service.

Core business logic layer for the alert system. Handles alert creation,
acknowledgment, threshold configuration, and alert retrieval.

Follows the same structural patterns as risk_engine/service.py:
- Injected DB session + AuditService
- PHI-safe logging (UUIDs only, never patient data or measurements)
- Standard response envelope via schemas
- Full async/await throughout
"""
import uuid
import structlog
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts_staging.enums import AlertStatus, AlertType, AlertSeverity, DispatchChannel
from app.modules.alerts_staging.exceptions import AlertNotFoundError, ThresholdConfigurationError
from app.modules.alerts_staging.models import Alert, AlertThreshold
from app.modules.alerts_staging.schemas import ConfigureThresholdRequest

logger = structlog.get_logger(__name__)


class AlertService:
    """
    Orchestrates alert lifecycle: creation, acknowledgment, retrieval, and threshold management.
    Instantiated per-request with injected DB session and audit service.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: Any,
        request_id: str,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """
        Args:
            db: Async SQLAlchemy session (request-scoped).
            audit_service: Injected AuditService for mutation logging.
            request_id: Correlation ID from HTTP request; included in all log entries.
            tenant_id: Current tenant scope enforced on all queries.
            user_id: Authenticated user; used as actor in audit records.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def evaluate_thresholds(
        self,
        patient_id: uuid.UUID,
        event: dict[str, Any],
    ) -> list[Alert]:
        """
        Check an incoming domain event against configured thresholds.
        Delegates to rules_engine; this entry point allows service-layer callers to trigger evaluation.

        Args:
            patient_id: Patient whose thresholds are evaluated.
            event: Domain event payload (measurement_saved, risk_score_computed, etc.).

        Returns:
            List of Alert records created from threshold breaches.
        """
        # Import here to avoid circular dependency with rules_engine
        from app.modules.alerts_staging.rules_engine import AlertRulesEngine

        rules = AlertRulesEngine(db=self.db, tenant_id=self.tenant_id, alert_service=self)

        # Route event to the appropriate evaluator based on its type
        event_type = event.get("event_type", "")
        created_alerts: list[Alert] = []

        if event_type == "measurement_saved":
            await rules.evaluate_measurement(
                patient_id=patient_id,
                measurement_type=event.get("measurement_type", ""),
                value=event.get("value", 0.0),
            )
        elif event_type == "risk_score_computed":
            await rules.evaluate_risk_score(
                patient_id=patient_id,
                disease=event.get("disease", ""),
                score=event.get("score", 0.0),
                stratum=event.get("stratum", ""),
            )

        return created_alerts

    async def create_alert(
        self,
        alert_type: AlertType,
        severity: AlertSeverity,
        patient_id: uuid.UUID,
        title: str,
        message: str,
        payload: dict[str, Any],
    ) -> Alert:
        """
        Persist a new alert record and enqueue multi-channel dispatch.

        PHI safety: logs only alert_id, severity, alert_type — never message content or payload values.

        Args:
            alert_type: Classification of alert trigger.
            severity: Clinical urgency level.
            patient_id: Patient the alert concerns.
            title: Short human-readable alert title.
            message: Full alert description (contains PHI; not logged).
            payload: Structured clinical data (contains PHI; not logged).

        Returns:
            Newly persisted Alert record.
        """
        from app.modules.alerts_staging.tasks import dispatch_alert_task

        # Build alert with all channels queued for dispatch
        alert = Alert(
            tenant_id=self.tenant_id,
            patient_id=patient_id,
            alert_type=alert_type.value,
            severity=severity.value,
            title=title,
            message=message,
            payload=payload,
            status=AlertStatus.ACTIVE.value,
            escalation_level=0,
            channels_dispatched=[],
            dispatch_status={},
        )
        self.db.add(alert)
        await self.db.flush()   # Obtain PK before committing so we can pass alert_id to task

        # Audit log — only structural metadata, never PHI
        await self.audit_service.log_audit(
            action="alert_created",
            resource_type="alert",
            resource_id=str(alert.id),
            changes={"severity": alert.severity, "alert_type": alert.alert_type},
        )

        # PHI-safe log — alert_id and severity only
        logger.info(
            "alert_created",
            alert_id=str(alert.id),
            severity=alert.severity,
            alert_type=alert.alert_type,
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        await self.db.commit()
        await self.db.refresh(alert)

        # Enqueue dispatch asynchronously so HTTP response is not blocked
        dispatch_alert_task.delay(str(alert.id), [c.value for c in DispatchChannel])

        return alert

    async def acknowledge(
        self,
        alert_id: uuid.UUID,
        user_id: uuid.UUID,
        notes: Optional[str],
    ) -> Alert:
        """
        Acknowledge an alert — marks it reviewed and stops escalation.

        Args:
            alert_id: Alert to acknowledge.
            user_id: Clinician acknowledging the alert.
            notes: Optional clinical notes (stored; not logged).

        Raises:
            AlertNotFoundError: If alert not found in current tenant scope.
        """
        # Tenant-scoped lookup — RLS double-enforced at DB layer
        stmt = select(Alert).where(
            and_(Alert.id == alert_id, Alert.tenant_id == self.tenant_id)
        )
        alert = (await self.db.scalars(stmt)).first()

        if not alert:
            raise AlertNotFoundError(str(alert_id))

        # Transition state; preserve original timestamps
        alert.status = AlertStatus.ACKNOWLEDGED.value
        alert.acknowledged_at = datetime.now(timezone.utc)
        alert.acknowledged_by = user_id
        alert.acknowledgment_notes = notes

        await self.audit_service.log_audit(
            action="alert_acknowledged",
            resource_type="alert",
            resource_id=str(alert.id),
            changes={"status": AlertStatus.ACKNOWLEDGED.value, "acknowledged_by": str(user_id)},
        )

        logger.info(
            "alert_acknowledged",
            alert_id=str(alert.id),
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        await self.db.commit()
        await self.db.refresh(alert)
        return alert

    async def get_patient_alerts(
        self,
        patient_id: uuid.UUID,
        status_filter: Optional[str],
        limit: int,
        offset: int,
    ) -> list[Alert]:
        """
        Retrieve paginated alert history for a patient.

        Args:
            patient_id: Patient whose alerts to retrieve.
            status_filter: Optional AlertStatus string to filter by.
            limit: Page size (max enforced at router layer).
            offset: Pagination offset.

        Returns:
            List of Alert records ordered by created_at descending.
        """
        conditions = [
            Alert.tenant_id == self.tenant_id,
            Alert.patient_id == patient_id,
        ]
        if status_filter:
            conditions.append(Alert.status == status_filter)

        stmt = (
            select(Alert)
            .where(and_(*conditions))
            .order_by(Alert.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.db.scalars(stmt)).all())

    async def get_unacknowledged(self) -> list[Alert]:
        """
        Retrieve all active/escalated alerts that have not been acknowledged.
        Used by the clinical dashboard to surface urgent items.

        Returns:
            List of unacknowledged alerts, most severe and oldest first.
        """
        stmt = (
            select(Alert)
            .where(
                and_(
                    Alert.tenant_id == self.tenant_id,
                    Alert.acknowledged_at.is_(None),
                    or_(
                        Alert.status == AlertStatus.ACTIVE.value,
                        Alert.status == AlertStatus.ESCALATED.value,
                    ),
                )
            )
            .order_by(Alert.severity.asc(), Alert.created_at.asc())
        )
        return list((await self.db.scalars(stmt)).all())

    async def configure_threshold(
        self,
        data: ConfigureThresholdRequest,
        created_by: uuid.UUID,
    ) -> AlertThreshold:
        """
        Create a new alert threshold configuration.

        Args:
            data: Validated threshold configuration from the request body.
            created_by: Clinician creating the threshold; stored for audit.

        Returns:
            Persisted AlertThreshold record.
        """
        # Validate that either measurement_type or disease is provided (not neither)
        if not data.measurement_type and not data.disease:
            raise ThresholdConfigurationError("Either measurement_type or disease must be specified")

        threshold = AlertThreshold(
            tenant_id=self.tenant_id,
            patient_id=data.patient_id,
            measurement_type=data.measurement_type,
            disease=data.disease,
            condition=data.condition.value,
            threshold_value=data.threshold_value,
            target_stratum=data.target_stratum,
            severity=data.severity.value,
            is_active=True,
            created_by=created_by,
        )
        self.db.add(threshold)
        await self.db.flush()

        await self.audit_service.log_audit(
            action="threshold_configured",
            resource_type="alert_threshold",
            resource_id=str(threshold.id),
            changes={
                "severity": threshold.severity,
                "condition": threshold.condition,
                "is_active": True,
            },
        )

        logger.info(
            "threshold_configured",
            threshold_id=str(threshold.id),
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )

        await self.db.commit()
        await self.db.refresh(threshold)
        return threshold
