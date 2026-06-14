"""
PrescpHealth Backend — Admin Module Schemas.

Pydantic v2 request/response models for tenant management,
model lifecycle operations, and tenant settings.
"""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Tenant schemas
# ---------------------------------------------------------------------------

class CreateTenantRequest(BaseModel):
    """Request body for creating a new tenant organisation."""

    name: str = Field(..., max_length=100, description="Unique tenant display name")
    region: str = Field(..., description="Deployment region, e.g. 'us-east-1'")
    settings: dict[str, Any] = Field(default_factory=dict, description="Tenant-level settings")


class TenantResponse(BaseModel):
    """Serialised tenant record returned to callers."""

    id: uuid.UUID
    name: str
    region: str
    settings: dict[str, Any]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TenantListResponse(BaseModel):
    """Paginated list of tenant records."""

    success: bool = True
    data: list[TenantResponse]
    meta: dict[str, Any]


class UpdateTenantRequest(BaseModel):
    """Partial update for tenant settings or activation state."""

    settings: dict[str, Any] | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Model lifecycle schemas
# ---------------------------------------------------------------------------

class DeployModelRequest(BaseModel):
    """Request body for deploying a new model version to production."""

    disease: str = Field(..., description="Disease identifier, e.g. 'diabetes'")
    version: str = Field(..., description="Semantic version string, e.g. '1.2.0'")
    artifact_path: str = Field(..., description="S3 / GCS path to the serialised model artefact")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Evaluation metrics (AUC, F1, …)")


class ModelVersionResponse(BaseModel):
    """Serialised model version record."""

    id: uuid.UUID
    disease: str
    version: str
    artifact_path: str
    metrics: dict[str, Any]
    is_active: bool
    deployed_at: datetime

    model_config = {"from_attributes": True}


class RollbackRequest(BaseModel):
    """Request body for rolling back to a previous model version."""

    disease: str = Field(..., description="Disease whose active model to roll back")
    target_version: str = Field(..., description="Version string to restore as active")


# ---------------------------------------------------------------------------
# Tenant settings schemas
# ---------------------------------------------------------------------------

class TenantSettingsRequest(BaseModel):
    """Partial update for tenant-level operational settings."""

    timezone: str | None = Field(None, description="IANA timezone, e.g. 'America/New_York'")
    language: str | None = Field(None, description="BCP-47 language tag, e.g. 'en-US'")
    notification_channels: list[str] | None = Field(
        None, description="Active notification channels, e.g. ['email', 'sms']"
    )


class TenantSettingsResponse(BaseModel):
    """Current resolved settings for the tenant."""

    tenant_id: uuid.UUID
    settings: dict[str, Any]
    updated_at: datetime
