"""
PrescpHealth Backend — TaskStatusService.

Business logic layer for querying background task status.
Follows the AlertService constructor pattern: injected DB, audit service,
request_id, tenant_id, and user_id.

PHI safety: result content is never logged — only task_id, task_type, status.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.task_status.exceptions import TaskNotFoundError
from app.modules.task_status.models import BackgroundTask

logger = structlog.get_logger(__name__)


class TaskStatusService:
    """
    Read-only service for background task status queries.

    Instantiated per-request with injected dependencies; all queries
    are scoped to the current tenant_id.
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
            audit_service: Injected AuditService (reserved for future mutations).
            request_id: Correlation ID from the HTTP request.
            tenant_id: Current tenant scope enforced on all queries.
            user_id: Authenticated user performing the request.
        """
        self.db = db
        self.audit_service = audit_service
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id

    async def get_task_status(self, task_id: uuid.UUID) -> dict[str, Any]:
        """
        Return status information for a single background task.

        PHI: result content is never written to logs.

        Args:
            task_id: UUID of the task to retrieve.

        Returns:
            Dict of task fields suitable for serialisation.

        Raises:
            TaskNotFoundError: If the task does not exist in the current tenant.
        """
        stmt = select(BackgroundTask).where(
            BackgroundTask.id == task_id,
            BackgroundTask.tenant_id == self.tenant_id,
        )
        task = (await self.db.scalars(stmt)).first()

        if task is None:
            logger.warning(
                "task_status_not_found",
                task_id=str(task_id),
                tenant_id=str(self.tenant_id),
                request_id=self.request_id,
            )
            raise TaskNotFoundError(str(task_id))

        logger.info(
            "task_status_retrieved",
            task_id=str(task.id),
            task_type=task.task_type,
            status=task.status,
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )
        return task  # type: ignore[return-value]  # router converts via schema

    async def list_tenant_tasks(
        self,
        status_filter: str | None,
        limit: int = 50,
    ) -> list[Any]:
        """
        List background tasks for the current tenant with optional status filter.

        Args:
            status_filter: If provided, return only tasks with this status string.
            limit: Maximum number of records to return (default 50).

        Returns:
            List of BackgroundTask ORM objects ordered by created_at descending.
        """
        conditions = [BackgroundTask.tenant_id == self.tenant_id]
        if status_filter:
            conditions.append(BackgroundTask.status == status_filter)

        stmt = (
            select(BackgroundTask)
            .where(*conditions)
            .order_by(BackgroundTask.created_at.desc())
            .limit(limit)
        )
        tasks = list((await self.db.scalars(stmt)).all())

        logger.info(
            "tenant_tasks_listed",
            count=len(tasks),
            status_filter=status_filter,
            tenant_id=str(self.tenant_id),
            request_id=self.request_id,
        )
        return tasks
