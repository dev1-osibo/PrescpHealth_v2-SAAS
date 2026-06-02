"""
PrescpHealth Backend — Task Status Pydantic Schemas.

Defines the serialisation layer for background task status responses.
All schemas use Pydantic v2 with ``from_attributes=True`` for ORM compatibility.

PHI note: result may contain clinical data; the API layer sets
Cache-Control: no-store on all responses containing task data.
"""
import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class TaskStatusResponse(BaseModel):
    """
    Serialised view of a single BackgroundTask record.

    Fields are a safe subset of the ORM model — params (PHI) is excluded.
    result is included but the endpoint sets Cache-Control: no-store.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    tenant_id: uuid.UUID
    task_type: str
    status: str
    retry_count: int
    max_retries: int
    celery_task_id: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class TaskStatusEnvelope(BaseModel):
    """
    Standard response envelope wrapping a single TaskStatusResponse.

    Conforms to the project-wide envelope:
        {"success": true, "data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}
    """

    success: bool = True
    data: TaskStatusResponse
    meta: dict[str, Any]
