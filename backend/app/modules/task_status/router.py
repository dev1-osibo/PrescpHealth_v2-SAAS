"""
PrescpHealth Backend — Task Status FastAPI Router.

Exposes a single read endpoint for querying background task status.
Follows alerts/router.py patterns:
- RBAC enforced via require_role dependency
- Cache-Control: no-store on all responses (task results may contain PHI)
- Standard response envelope on all success responses
- HTTPException on all error paths

HIPAA: Cache-Control: no-store is set unconditionally because task result
payloads may contain PHI (clinical computation outputs).
"""
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.core.database import get_db
from app.core.deps import get_current_user, get_request_id
from app.modules.auth.rbac import Role, require_role
from app.modules.task_status.exceptions import TaskNotFoundError
from app.modules.task_status.schemas import TaskStatusEnvelope, TaskStatusResponse
from app.modules.task_status.service import TaskStatusService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["task_status"])

_NO_STORE = "no-store"


def _build_service(
    db: AsyncSession,
    current_user: dict,
    request_id: str,
) -> TaskStatusService:
    """Construct TaskStatusService with injected dependencies."""
    tenant_id = uuid.UUID(current_user["tenant_id"])
    user_id = uuid.UUID(current_user["user_id"])
    audit_service = AuditService(db=db, tenant_id=tenant_id)
    return TaskStatusService(
        db=db,
        audit_service=audit_service,
        request_id=request_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def _meta(request_id: str) -> dict:
    """Build standard response meta block."""
    return {
        "request_id": request_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/api/v1/tasks/{task_id}/status",
    response_model=TaskStatusEnvelope,
    dependencies=[Depends(require_role(Role.NURSE))],
    summary="Get background task status",
)
async def get_task_status(
    task_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    request_id: str = Depends(get_request_id),
) -> TaskStatusEnvelope:
    """
    Return the current status of a background task.

    Accessible to all clinical users (Nurse and above). Result payloads
    may contain PHI, so Cache-Control: no-store is always set.

    Args:
        task_id: UUID of the background task to look up.

    Returns:
        TaskStatusEnvelope with task status details.

    Raises:
        404: If the task is not found in the current tenant.
        500: On unexpected errors.
    """
    response.headers["Cache-Control"] = _NO_STORE

    svc = _build_service(db, current_user, request_id)

    try:
        task = await svc.get_task_status(task_id=task_id)
        return TaskStatusEnvelope(
            data=TaskStatusResponse.model_validate(task),
            meta=_meta(request_id),
        )
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    except Exception as exc:
        logger.error(
            "get_task_status_error",
            task_id=str(task_id),
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve task status",
        )
