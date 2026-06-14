"""
PrescpHealth Backend — Alert Escalation Service.

Manages the escalation chain for unacknowledged critical/high alerts.
Runs as a periodic Celery beat task (every 5 minutes) to detect alerts
that have exceeded their acknowledgment timeout.

Escalation chain:
  Level 0 (initial) → Level 1: Nurse did not acknowledge within 15 minutes → Doctor
  Level 1 (escalated) → Level 2: Doctor did not acknowledge within 30 minutes → Clinic_Admin
  Level 2: Maximum escalation — alert logged and resolved as unacknowledged

HIPAA: Only alert_id and user UUIDs appear in logs. No clinical values, patient names,
       or alert content.
"""
import uuid
import structlog
from datetime import datetime, timezone, timedelta
from typing import Any
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.alerts.enums import AlertSeverity, AlertStatus
from app.modules.alerts.exceptions import EscalationError
from app.modules.alerts.models import Alert, EscalationRecord

logger = structlog.get_logger(__name__)

# Maximum escalation level — beyond this, alert is marked resolved/unacknowledged
MAX_ESCALATION_LEVEL = 2


class EscalationService:
    """
    Scans for overdue unacknowledged alerts and escalates them through the clinical chain.
    Instantiated per-run with an injected DB session and audit service.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: Any,
        tenant_id: uuid.UUID,
    ) -> None:
        """
        Args:
            db: Async SQLAlchemy session for querying and updating alerts.
            audit_service: AuditService for logging escalation mutations.
            tenant_id: Tenant scope; all queries are filtered to this tenant.
        """
        self.db = db
        self.audit_service = audit_service
        self.tenant_id = tenant_id

    def _get_escalation_timeout(self, level: int) -> timedelta:
        """
        Return the acknowledgment timeout for a given escalation level.

        Args:
            level: Current escalation level of the alert.

        Returns:
            timedelta after which an unacknowledged alert at this level is escalated.
        """
        if level == 0:
            # Level 0: Nurse has 15 minutes before escalation to Doctor
            return timedelta(minutes=15)
        elif level == 1:
            # Level 1: Doctor has 30 minutes before escalation to Clinic_Admin
            return timedelta(minutes=30)
        else:
            # Levels >= 2 are handled by check_and_escalate as max-escalation
            return timedelta(minutes=30)

    async def check_and_escalate(self) -> None:
        """
        Scan for all unacknowledged critical/high alerts that have exceeded their
        timeout at their current escalation level, and escalate each one.

        Operates at all escalation levels — both level 0 and level 1 alerts
        are evaluated in a single pass.
        """
        now = datetime.now(timezone.utc)

        for level in range(MAX_ESCALATION_LEVEL):
            cutoff = now - self._get_escalation_timeout(level)

            # Query: active or escalated, high/critical severity, at this level,
            # created before cutoff, not yet acknowledged
            stmt = select(Alert).where(
                and_(
                    Alert.tenant_id == self.tenant_id,
                    Alert.acknowledged_at.is_(None),
                    Alert.escalation_level == level,
                    or_(
                        Alert.status == AlertStatus.ACTIVE.value,
                        Alert.status == AlertStatus.ESCALATED.value,
                    ),
                    or_(
                        Alert.severity == AlertSeverity.CRITICAL.value,
                        Alert.severity == AlertSeverity.HIGH.value,
                    ),
                    Alert.created_at < cutoff,
                )
            )
            overdue_alerts = list((await self.db.scalars(stmt)).all())

            logger.info(
                "escalation_scan_complete",
                level=level,
                overdue_count=len(overdue_alerts),
                tenant_id=str(self.tenant_id),
            )

            for alert in overdue_alerts:
                # Determine escalation target based on new level
                # In a full implementation, target_user_id would be resolved via
                # a role-based user lookup (e.g. find the on-call doctor for this tenant).
                # For now, use a sentinel UUID — real resolution is future work.
                target_user_id = uuid.UUID(int=0)  # TODO: resolve via role lookup

                await self.escalate_alert(
                    alert_id=alert.id,
                    target_user_id=target_user_id,
                )

        # Handle max-escalation alerts (level == MAX_ESCALATION_LEVEL)
        cutoff = now - self._get_escalation_timeout(MAX_ESCALATION_LEVEL)
        stmt = select(Alert).where(
            and_(
                Alert.tenant_id == self.tenant_id,
                Alert.acknowledged_at.is_(None),
                Alert.escalation_level == MAX_ESCALATION_LEVEL,
                or_(
                    Alert.severity == AlertSeverity.CRITICAL.value,
                    Alert.severity == AlertSeverity.HIGH.value,
                ),
                Alert.created_at < cutoff,
            )
        )
        max_level_alerts = list((await self.db.scalars(stmt)).all())

        for alert in max_level_alerts:
            logger.warning(
                "alert_max_escalation_reached",
                alert_id=str(alert.id),
                tenant_id=str(self.tenant_id),
            )
            # Resolve as unacknowledged — no further escalation is possible
            alert.status = AlertStatus.RESOLVED.value
            alert.resolved_at = datetime.now(timezone.utc)

            await self.audit_service.log_audit(
                action="alert_resolved_unacknowledged",
                resource_type="alert",
                resource_id=str(alert.id),
                changes={"status": AlertStatus.RESOLVED.value, "reason": "max_escalation_reached"},
            )

        if max_level_alerts:
            await self.db.commit()

    async def escalate_alert(
        self,
        alert_id: uuid.UUID,
        target_user_id: uuid.UUID,
    ) -> Alert:
        """
        Escalate a single alert to the next level in the chain.

        Creates an immutable EscalationRecord audit entry and updates the
        alert's escalation_level and status.

        Args:
            alert_id: Alert to escalate.
            target_user_id: User who should now own this alert.

        Returns:
            Updated Alert record.

        Raises:
            EscalationError: If alert is not found or already at max level.
        """
        stmt = select(Alert).where(
            and_(Alert.id == alert_id, Alert.tenant_id == self.tenant_id)
        )
        alert = (await self.db.scalars(stmt)).first()

        if not alert:
            raise EscalationError(str(alert_id), "alert not found")

        if alert.escalation_level >= MAX_ESCALATION_LEVEL:
            raise EscalationError(str(alert_id), "already at maximum escalation level")

        from_level = alert.escalation_level
        to_level = from_level + 1
        now = datetime.now(timezone.utc)

        # Create immutable escalation audit record
        record = EscalationRecord(
            tenant_id=self.tenant_id,
            alert_id=alert_id,
            from_level=from_level,
            to_level=to_level,
            escalated_at=now,
            target_user_id=target_user_id,
            reason="unacknowledged_timeout",
        )
        self.db.add(record)

        # Update alert state
        alert.escalation_level = to_level
        alert.status = AlertStatus.ESCALATED.value
        alert.escalated_at = now

        await self.audit_service.log_audit(
            action="alert_escalated",
            resource_type="alert",
            resource_id=str(alert.id),
            changes={
                "from_level": from_level,
                "to_level": to_level,
                "target_user_id": str(target_user_id),
            },
        )

        logger.info(
            "alert_escalated",
            alert_id=str(alert.id),
            from_level=from_level,
            to_level=to_level,
            tenant_id=str(self.tenant_id),
        )

        await self.db.commit()
        await self.db.refresh(alert)
        return alert
