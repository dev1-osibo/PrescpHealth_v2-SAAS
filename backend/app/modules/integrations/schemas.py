"""
PrescpHealth Backend — Integrations Pydantic Schemas.

Request/response models for connector management and sync history.

Security:
    ConnectorCreateRequest includes credentials for initial setup.
    Credentials are stored but NEVER returned in responses — use
    ConnectorOut which excludes the credentials field.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.modules.integrations.enums import (
    AuthType,
    ConnectorType,
    SyncDirection,
    SyncStatus,
)


# ---------------------------------------------------------------------------
# Connector Schemas
# ---------------------------------------------------------------------------

class ConnectorCreateRequest(BaseModel):
    """Body for POST /api/v1/integrations/connectors."""

    connector_type: ConnectorType
    name: str = Field(..., min_length=1, max_length=255)
    base_url: str = Field(..., max_length=2048,
                          description="Base URL of the external system (not logged)")
    auth_type: AuthType
    # Credentials are write-only — never returned in responses
    credentials: dict[str, Any] = Field(
        ...,
        description="Auth credentials (api_key, username+password, or oauth2 config). "
                    "Write-only — never returned in API responses.",
    )
    sync_direction: SyncDirection
    sync_schedule: Optional[str] = Field(
        None, max_length=128,
        description="Cron expression for automatic syncs (e.g., '0 2 * * *')",
    )
    is_active: bool = Field(default=True)


class ConnectorUpdateRequest(BaseModel):
    """Body for PUT /api/v1/integrations/connectors/{id}."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    base_url: Optional[str] = Field(None, max_length=2048)
    auth_type: Optional[AuthType] = None
    credentials: Optional[dict[str, Any]] = Field(
        None, description="Update credentials (write-only)"
    )
    sync_direction: Optional[SyncDirection] = None
    sync_schedule: Optional[str] = Field(None, max_length=128)
    is_active: Optional[bool] = None


class ConnectorOut(BaseModel):
    """
    Connector response object.

    SECURITY: credentials field is intentionally EXCLUDED.
    Never expose auth secrets in API responses.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    connector_type: ConnectorType
    name: str
    base_url: str
    auth_type: AuthType
    sync_direction: SyncDirection
    sync_schedule: Optional[str] = None
    is_active: bool
    last_sync_at: Optional[datetime] = None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Sync Log Schemas
# ---------------------------------------------------------------------------

class SyncLogOut(BaseModel):
    """Sync log entry response object."""

    id: uuid.UUID
    connector_id: uuid.UUID
    direction: SyncDirection
    status: SyncStatus
    records_processed: int
    records_succeeded: int
    records_failed: int
    # error_summary is metadata — no PHI
    error_summary: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Sync Trigger
# ---------------------------------------------------------------------------

class SyncTriggerResponse(BaseModel):
    """Response for POST /connectors/{id}/sync."""

    task_id: uuid.UUID
    connector_id: uuid.UUID
    status: str = "queued"
    message: str = "Sync task queued for execution"
