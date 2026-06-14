"""
PrescpHealth Backend — BackgroundTaskTracker.

Lightweight data-access helper for creating and updating background task records.
Designed to be called from Celery tasks, FastAPI routes, or service layers.

PHI safety rule: never log params or result content — only task_id, task_type, status.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.task_status.models import BackgroundTask

logger = structlog.get_logger(__name__)


class BackgroundTaskTracker:
    """
    Create and track background task records in the database.

    Instantiated per-request or per-task with an injected async DB session
    and the current tenant scope.  All queries are tenant-filtered.
    """

    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        """
        Args:
            db: Async SQLAlchemy session (request-scoped or task-scoped).
            tenant_id: Tenant UUID used to scope all task records.
        """
        self.db = db
        self.tenant_id = tenant_id

    async def create_task(self, task_type: str, params: dict[str, Any]) -> str:
        """
        Persist a new background task in ``pending`` status.

        PHI: params may contain clinical data — logged only as task_type, never content.

        Args:
            task_type: Logical label for the task (e.g. ``"risk_score_batch"``).
            params: Arbitrary input parameters stored in JSONB (may contain PHI).

        Returns:
            Newly created task UUID as a plain string.
        """
        task = BackgroundTask(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            task_type=task_type,
            status="pending",
            params=params,
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(task)

        logger.info(
            "background_task_created",
            task_id=str(task.id),
            task_type=task_type,
            tenant_id=str(self.tenant_id),
        )
        return str(task.id)

    async def update_status(
        self,
        task_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """
        Update the status (and optionally result/error) of an existing task.

        Sets ``started_at`` when transitioning to ``running``, and
        ``completed_at`` when transitioning to ``completed`` or ``failed``.

        PHI: result content is never logged — only task_id and status.

        Args:
            task_id: UUID string of the task to update.
            status: New status string (pending/running/completed/failed/retrying).
            result: Optional result payload (may contain PHI — stored only).
            error: Optional error message string (must not contain PHI).
        """
        task = await self._get_task(task_id)
        if task is None:
            logger.warning("update_status_task_not_found", task_id=task_id)
            return

        task.status = status
        now = datetime.now(timezone.utc)

        if status == "running" and task.started_at is None:
            task.started_at = now
        if status in ("completed", "failed"):
            task.completed_at = now
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error

        await self.db.commit()

        logger.info(
            "background_task_status_updated",
            task_id=task_id,
            status=status,
            tenant_id=str(self.tenant_id),
        )

    async def get_status(self, task_id: str) -> dict[str, Any] | None:
        """
        Retrieve current status information for a task.

        PHI: result is included in returned dict but never logged here.

        Args:
            task_id: UUID string of the task to look up.

        Returns:
            Dict with task fields, or ``None`` if not found in this tenant.
        """
        task = await self._get_task(task_id)
        if task is None:
            return None

        return {
            "task_id": str(task.id),
            "task_type": task.task_type,
            "status": task.status,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "celery_task_id": task.celery_task_id,
            "error": task.error,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "created_at": task.created_at,
        }

    async def mark_retry(self, task_id: str) -> None:
        """
        Increment ``retry_count`` and set status to ``retrying``.

        Called by Celery retry hooks before re-queuing the task.

        Args:
            task_id: UUID string of the task to mark for retry.
        """
        task = await self._get_task(task_id)
        if task is None:
            logger.warning("mark_retry_task_not_found", task_id=task_id)
            return

        task.retry_count += 1
        task.status = "retrying"
        await self.db.commit()

        logger.info(
            "background_task_marked_retry",
            task_id=task_id,
            retry_count=task.retry_count,
            tenant_id=str(self.tenant_id),
        )

    async def _get_task(self, task_id: str) -> BackgroundTask | None:
        """
        Internal helper: fetch a task by UUID string within the current tenant scope.

        Args:
            task_id: UUID string of the task.

        Returns:
            BackgroundTask ORM object or ``None``.
        """
        try:
            task_uuid = uuid.UUID(task_id)
        except ValueError:
            logger.warning("invalid_task_id_format", task_id=task_id)
            return None

        stmt = select(BackgroundTask).where(
            BackgroundTask.id == task_uuid,
            BackgroundTask.tenant_id == self.tenant_id,
        )
        return (await self.db.scalars(stmt)).first()
