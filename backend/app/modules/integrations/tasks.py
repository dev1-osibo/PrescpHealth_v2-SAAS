"""
PrescpHealth Backend — Integrations Celery Tasks.

Provides async task execution for data sync operations.
Tasks are designed to be idempotent and safely retryable.

Celery Tasks:
    run_sync_task(connector_id)        — Execute a single connector sync
    scheduled_sync_check()             — Periodic task: check which connectors are due for sync

STUB NOTE:
    These tasks use Celery's @app.task decorator pattern.
    In production, the Celery app instance would be imported from app.core.celery.
    This stub defines the task signatures and logic without the decorator
    to avoid circular imports in the staging module.

PHI:
    No PHI in task arguments, logs, or results.
    Only connector_id (UUID) and sync metadata appear.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def run_sync_task_logic(
    connector_id_str: str,
    tenant_id_str: str,
    triggered_by_str: str,
) -> dict[str, Any]:
    """
    Core logic for the run_sync_task Celery task.

    Extracted as a pure async function for testability.
    The Celery task wrapper calls this via asyncio.run().

    Args:
        connector_id_str: ConnectorConfig UUID as string.
        tenant_id_str: Tenant UUID as string.
        triggered_by_str: User UUID that triggered the sync (or "scheduler").

    Returns:
        Dict with sync_log_id, status, and counters.
    """
    from app.core.database import get_session_factory, set_tenant_context
    from app.modules.integrations.sync_engine import SyncEngine

    connector_id = uuid.UUID(connector_id_str)
    tenant_id = uuid.UUID(tenant_id_str)

    # Use a system user ID for scheduler-triggered syncs
    if triggered_by_str == "scheduler":
        user_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    else:
        user_id = uuid.UUID(triggered_by_str)

    logger.info(
        "sync_task_started",
        connector_id=connector_id_str,
        tenant_id=tenant_id_str,
        triggered_by=triggered_by_str,
    )

    engine = SyncEngine()
    factory = get_session_factory()

    async with factory() as db:
        await set_tenant_context(db, tenant_id_str)
        sync_log = await engine.execute_sync(
            db=db,
            connector_id=connector_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await db.commit()

    result = {
        "sync_log_id": str(sync_log.id),
        "connector_id": connector_id_str,
        "status": sync_log.status.value if hasattr(sync_log.status, "value") else sync_log.status,
        "records_processed": sync_log.records_processed,
        "records_succeeded": sync_log.records_succeeded,
        "records_failed": sync_log.records_failed,
        "duration_ms": sync_log.duration_ms,
    }

    logger.info("sync_task_completed", **result)
    return result


async def scheduled_sync_check_logic() -> dict[str, Any]:
    """
    Periodic task logic: identify connectors due for sync and enqueue tasks.

    Checks all active connectors with a sync_schedule against their
    last_sync_at timestamp to determine if they're due for sync.

    Returns:
        Dict with count of connectors checked and tasks enqueued.
    """
    from app.core.database import get_session_factory
    from sqlalchemy import select, text

    logger.info("scheduled_sync_check_started", checked_at=datetime.now(timezone.utc).isoformat())

    # STUB: In production, this would:
    # 1. Query all active connectors with non-null sync_schedule
    # 2. Parse their cron expressions using croniter
    # 3. Check if next_run_time <= now()
    # 4. Enqueue run_sync_task.delay(connector_id) for due connectors

    logger.info("scheduled_sync_check_stub", message="No connectors checked — stub mode")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "connectors_checked": 0,
        "tasks_enqueued": 0,
        "stub": True,
    }


def get_celery_task_stub() -> dict[str, str]:
    """
    Return stub task signatures for documentation purposes.

    In production, these would be Celery @app.task decorated functions.
    The actual Celery app is configured in app.core.celery.

    Returns:
        Dict mapping task names to their queue/routing info.
    """
    return {
        "run_sync_task": {
            "queue": "integrations",
            "max_retries": 5,
            "description": "Execute a single connector sync with retry backoff",
        },
        "scheduled_sync_check": {
            "queue": "scheduled",
            "schedule": "every 5 minutes",
            "description": "Check which connectors are due for automatic sync",
        },
    }
