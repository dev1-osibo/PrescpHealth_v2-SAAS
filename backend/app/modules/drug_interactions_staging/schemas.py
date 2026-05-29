"""
PrescpHealth Backend — Drug Interaction Pydantic Schemas.

Request/response models for drug interaction API endpoints.
"""

from datetime import date
from typing import Optional, List, Any
import uuid

from pydantic import BaseModel, Field


# ============================================================================
# Request Models
# ============================================================================

class AddMedicationRequest(BaseModel):
    """Request to add a medication."""

    drug_name: str = Field(..., min_length=1, max_length=200, description="Drug name")
    drug_code: str = Field(..., min_length=1, max_length=20, description="RxNorm/ATC code")
    dosage: str = Field(..., min_length=1, max_length=100, description="Dosage")
    frequency: str = Field(..., min_length=1, max_length=100, description="Frequency")
    route: str = Field(..., min_length=1, max_length=50, description="Route (oral, IV, etc)")
    start_date: date = Field(..., description="When prescribed")


class OverrideInteractionRequest(BaseModel):
    """Request to override an interaction."""

    justification: str = Field(
        ...,
        min_length=20,
        max_length=1000,
        description="Mandatory clinical justification (min 20 chars)",
    )


# ============================================================================
# Response Models
# ============================================================================

class CriticalInteractionItem(BaseModel):
    """One critical interaction."""

    type: str = Field(..., description="'DDI' or 'DHI'")
    severity: str = Field(..., description="'Contraindicated', 'Major', 'Moderate', 'Minor'")
    action: str = Field(..., description="Recommended clinical action")


class AddMedicationResponse(BaseModel):
    """Response to add medication endpoint."""

    success: bool = Field(True, description="Always true on success")
    data: dict = Field(
        ...,
        description="{medication_id, ddi_count, dhi_count, safety_status, critical_interactions}",
    )
    meta: dict = Field(default_factory=dict, description="Metadata {request_id, ...}")


class SafetySummaryItem(BaseModel):
    """One safety recommendation."""

    interaction_id: str = Field(..., description="InteractionResult UUID")
    type: str = Field(..., description="'DDI' or 'DHI'")
    severity: str = Field(..., description="Severity level")
    action: str = Field(..., description="Recommended action")


class SafetySummaryResponse(BaseModel):
    """Response to get safety summary endpoint."""

    success: bool = Field(True, description="Always true")
    data: dict = Field(
        ...,
        description="{overall_status, critical_issue_count, moderate_issue_count, active_medication_count, recommendations}",
    )
    meta: dict = Field(default_factory=dict, description="Metadata")


class OverrideInteractionResponse(BaseModel):
    """Response to override interaction endpoint."""

    success: bool = Field(True, description="Always true on success")
    data: dict = Field(..., description="{message: '...'}")
    meta: dict = Field(default_factory=dict, description="Metadata")


class MedicationItem(BaseModel):
    """Active medication in list."""

    id: str = Field(..., description="Medication UUID")
    drug_name: str = Field(..., description="PHI: Drug name")
    drug_code: str = Field(..., description="PHI: RxNorm/ATC code")
    dosage: str = Field(..., description="PHI: Dosage")
    frequency: str = Field(..., description="PHI: Frequency")
    route: str = Field(..., description="Route")
    start_date: str = Field(..., description="Start date (ISO)")
    end_date: Optional[str] = Field(None, description="End date (ISO) if stopped")


class ActiveMedicationsResponse(BaseModel):
    """Response to get active medications endpoint."""

    success: bool = Field(True, description="Always true")
    data: List[MedicationItem] = Field(..., description="List of active medications")
    meta: dict = Field(default_factory=dict, description="Metadata")


# ============================================================================
# Standard Envelope (used by router)
# ============================================================================

class StandardResponse(BaseModel):
    """Standard response envelope for all API endpoints."""

    success: bool = Field(..., description="true for 2xx, false for errors")
    data: Optional[Any] = Field(None, description="Response payload")
    meta: dict = Field(default_factory=dict, description="Metadata {request_id, ...}")
