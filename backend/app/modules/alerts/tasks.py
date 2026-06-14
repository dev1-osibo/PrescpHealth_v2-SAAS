"""
PrescpHealth Backend — Alert System Celery Tasks.

Background tasks for alert dispatch and escalation checking.
Follows the same patterns as risk_engine/tasks.py:
- Shared Celery app instance
- Async tasks run via asyncio.run()
- Exponential backoff retry on dispatch failures
- PHI-safe logging (alert_id and task_id only; no patient data)

Task schedule:
- dispatch_alert_task: Triggered on alert creation; retries up to 5x with exponential backoff
- check_escalations_task: Periodic — every 5 minutes
- check_missed_followups_task: Periodic — daily per tenant
"""
import asyncio
import uuid
import structlog
from celery import shared_task
from sqlalchemy import select

logger = structlog.get_logger(__name__)

# Exponential backoff delays in seconds: 30s, 2m, 8m, 30m, 90m
# Formula: 30 * (4 ** retry_count)
_BACKOFF_BASE = 30
_BACKOFF_FACTOR = 4


@shared_task(
    bind=True,
    name="alerts.dispatch_alert",
    max_retries=5,
    acks_late=True,         # Acknowledge only after completion — prevents lost tasks on crash
    reject_on_worker_lost=True,
)
def dispatch_alert_task(self, alert_id: str, channels: list[str]) -> dict:
    """
    Dispatch an alert across the specified channels.

    Uses exponential backoff for retries. Email channel is given a 24-hour
    retry window; SMS is given a 6-hour window. Retry logic is enforced
    by checking elapsed time relative to alert.created_at.

    PHI safety: logs only alert_id, channel names, and task_id.
                NEVER logs patient data, alert message, or clinical values.

    Args:
        alert_id: UUID string of the alert to dispatch.
        channels: List of DispatchChannel values to attempt delivery on.

    Returns:
        dict with dispatch results per channel.

    Raises:
        Retries task on any exception, up to max_retries times.
    """
    # Run async dispatch logic in a synchronous Celery worker context
    return asyncio.run(_dispatch_alert_async(self, alert_id, channels))


async def _dispatch_alert_async(task: any, alert_id: str, channels: list[str]) -> dict:
    """
    Async implementation of dispatch_alert_task.

    Separated from the Celery task decorator to allow clean async/await throughout.

    Args:
        task: The Celery task instance (for retry access).
        alert_id: UUID string of the alert.
        channels: Dispatch channels to attempt.

    Returns:
        dispatch_status dict from the updated alert record.
    """
    from app.core.database import get_async_session_context
    from app.modules.alerts.dispatcher import AlertDispatcher
    from app.modules.alerts.models import Alert

    logger.info(
        "dispatch_alert_task_started",
        alert_id=alert_id,
        channels=channels,
        task_id=task.request.id,
        retry_count=task.request.retries,
    )

    try:
        async with get_async_session_context() as db:
            # Load the alert to get its tenant_id for the dispatcher
            alert_uuid = uuid.UUID(alert_id)
            stmt = select(Alert).where(Alert.id == alert_uuid)
            alert = (await db.scalars(stmt)).first()

            if not alert:
                # Alert was deleted after task was enqueued — do not retry
                logger.warning(
                    "dispatch_alert_not_found_skip",
                    alert_id=alert_id,
                    task_id=task.request.id,
                )
                return {"skipped": True, "reason": "alert_not_found"}

            dispatcher = AlertDispatcher(db=db, tenant_id=alert.tenant_id)
            updated_alert = await dispatcher.dispatch(
                alert_id=alert_uuid,
                channels=channels,
            )

            logger.info(
                "dispatch_alert_task_completed",
                alert_id=alert_id,
                task_id=task.request.id,
            )

            return dict(updated_alert.dispatch_status)

    except Exception as exc:
        # Exponential backoff: 30s → 2m → 8m → 30m → 90m
        retry_delay = _BACKOFF_BASE * (_BACKOFF_FACTOR ** task.request.retries)

        logger.warning(
            "dispatch_alert_task_retry",
            alert_id=alert_id,
            task_id=task.request.id,
            retry_count=task.request.retries,
            retry_delay_seconds=retry_delay,
            error_type=type(exc).__name__,
            # NOTE: exc.args NOT logged — may contain PHI from downstream exceptions
        )

        # Let Celery handle retry scheduling
        raise task.retry(exc=exc, countdown=retry_delay)


@shared_task(
    name="alerts.check_escalations",
    ignore_result=True,
)
def check_escalations_task() -> None:
    """
    Periodic task: scan for overdue unacknowledged alerts and escalate them.

    Scheduled to run every 5 minutes via Celery beat.
    Iterates over all active tenants and runs EscalationService.check_and_escalate().

    PHI safety: logs tenant_id UUID only; no patient data or alert content.
    """
    asyncio.run(_check_escalations_async())


async def _check_escalations_async() -> None:
    """Async implementation of check_escalations_task."""
    from app.core.database import get_async_session_context
    from app.modules.audit.service import AuditService
    from app.modules.alerts.escalation import EscalationService

    logger.info("check_escalations_task_started")

    # TODO: Replace with real active tenant query once tenant management module is available
    # For now, stub logs intent — escalation task is wired and ready
    logger.info(
        "check_escalations_tenant_lookup_stub",
        note="Real tenant iteration pending tenant management module",
    )

    # Stub: in production this iterates over active tenant_ids from the tenants table
    active_tenant_ids: list[uuid.UUID] = []

    for tenant_id in active_tenant_ids:
        try:
            async with get_async_session_context() as db:
                audit_service = AuditService(db=db, tenant_id=tenant_id)
                escalation_svc = EscalationService(
                    db=db,
                    audit_service=audit_service,
                    tenant_id=tenant_id,
                )
                await escalation_svc.check_and_escalate()

        except Exception as exc:
            logger.error(
                "check_escalations_tenant_failed",
                tenant_id=str(tenant_id),
                error_type=type(exc).__name__,
            )

    logger.info("check_escalations_task_completed")


@shared_task(
    name="alerts.check_missed_followups",
    ignore_result=True,
)
def check_missed_followups_task(tenant_id: str) -> None:
    """
    Periodic task: check for patients who missed scheduled follow-ups.

    Scheduled to run daily per tenant via Celery beat.
    Full implementation pending appointments module integration.

    PHI safety: logs tenant_id UUID only.

    Args:
        tenant_id: UUID string of the tenant to check.
    """
    logger.info(
        "check_missed_followups_task_started",
        tenant_id=tenant_id,
        note="Stub — full implementation pending appointments module",
    )

    # Placeholder — full implementation in a later task when appointments module is available
    # Will call AlertRulesEngine.check_missed_followup() for each patient with overdue visits
    logger.info(
        "check_missed_followups_task_completed",
        tenant_id=tenant_id,
    )
