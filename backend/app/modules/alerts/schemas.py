"""
PrescpHealth Backend — Alert System Pydantic Schemas.

Request/response models for alert API endpoints.
Follows the same validation and envelope conventions used in risk_engine/schemas.py.

HIPAA: Responses with PHI must be served with Cache-Control: no-store.
       The `payload` field in AlertResponse contains clinical PHI — do not cache.
"""
import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from app.modules.alerts.enums import (
    AlertSeverity,
    AlertStatus,
    AlertType,
    ThresholdCondition,
    DispatchChannel,
)


class AlertResponse(BaseModel):
    """
    Full alert representation with all lifecycle fields.
    Returned by GET /api/v1/alerts and GET /api/v1/patients/{patient_id}/alerts.
    Contains PHI — must be served with Cache-Control: no-store.
    """
    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    alert_type: str
    severity: str
    title: str
    message: str
    payload: dict[str, Any]           # Clinical context; contains PHI
    status: str
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[uuid.UUID] = None   # User UUID who acknowledged; no names
    acknowledgment_notes: Optional[str] = None
    escalation_level: int
    escalated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    channels_dispatched: list[str]
    dispatch_status: dict[str, str]

    model_config = {"from_attributes": True}


class AlertListResponse(BaseModel):
    """Standard envelope for paginated alert list."""
    success: bool = True
    data: list[AlertResponse]
    meta: dict[str, Any]


class AcknowledgeAlertRequest(BaseModel):
    """Request body for acknowledging an alert."""
    notes: Optional[str] = Field(
        None,
        max_length=1000,
        description="Optional clinical notes on acknowledgment",
    )


class ConfigureThresholdRequest(BaseModel):
    """
    Request body to create or update an alert threshold.
    Either measurement_type (for measurement-based) or disease (for risk-score-based)
    should be provided — not both. The rules engine handles the routing.
    """
    patient_id: Optional[uuid.UUID] = Field(
        None,
        description="NULL = tenant-wide default; otherwise patient-specific override",
    )
    measurement_type: Optional[str] = Field(None, max_length=100)
    disease: Optional[str] = Field(None, max_length=100)
    condition: ThresholdCondition
    threshold_value: Optional[float] = None
    target_stratum: Optional[str] = Field(
        None,
        max_length=30,
        description="Required when condition=enters_stratum",
    )
    severity: AlertSeverity


class ThresholdResponse(BaseModel):
    """
    Configured threshold representation.
    Returned by POST and GET /api/v1/patients/{patient_id}/alert-thresholds.
    """
    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: Optional[uuid.UUID]
    measurement_type: Optional[str]
    disease: Optional[str]
    condition: str
    threshold_value: Optional[float]
    target_stratum: Optional[str]
    severity: str
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ThresholdListResponse(BaseModel):
    """Standard envelope for threshold list."""
    success: bool = True
    data: list[ThresholdResponse]
    meta: dict[str, Any]


class SingleAlertResponse(BaseModel):
    """Standard envelope for single alert (acknowledge, get by id)."""
    success: bool = True
    data: AlertResponse
    meta: dict[str, Any]
