"""
PrescpHealth Backend — Measurement Pydantic Schemas.

Request/response schemas for the clinical measurement API.
These schemas enforce input validation at the API boundary and
structure outgoing data in a consistent format.

Schema Design:
- MeasurementCreate: Validates input for recording a single measurement
- MeasurementResponse: Full measurement output (serialized from model)
- MeasurementListResponse: Paginated list with cursor metadata
- BulkImportRequest: List of measurement data dicts for batch import
- BulkImportResponse: Summary of bulk import results
- MeasurementHistoryParams: Query parameter validation for history endpoint

HIPAA Compliance:
- Schemas contain PHI fields (measurement values, notes) — protected
  by RBAC at the router level and Cache-Control headers
- Never expose PHI in error messages (Pydantic validation errors
  are sanitized before returning to client)
- All responses include request_id for correlation without PHI

Per API design steering rule:
- All responses use the standard envelope format
- Cursor-based pagination for list endpoints
- Timestamps are ISO-8601 UTC
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.modules.measurements.models import MeasurementSource, MeasurementType


# ---------------------------------------------------------------------------
# Request Schemas — Input Validation
# ---------------------------------------------------------------------------
class MeasurementCreate(BaseModel):
    """
    Input schema for recording a single clinical measurement.

    Validates required fields at the API boundary. Physiological range
    validation is performed in the service layer (type-specific ranges).

    Fields:
    - measurement_type: Which vital sign / lab result / lifestyle factor
    - value: Numeric reading (broad range here; service validates per-type)
    - unit: Unit of measurement (e.g., mmHg, mg/dL, kg)
    - recorded_at: When the measurement was actually taken (UTC)
    - source: Provenance (manual, device, import, patient_portal)
    - notes: Optional clinician notes (PHI — encrypted at rest)
    """

    measurement_type: MeasurementType = Field(
        ...,
        description="Clinical measurement type (e.g., systolic_bp, hba1c, bmi)",
        examples=["systolic_bp"],
    )
    value: float = Field(
        ...,
        ge=0,
        le=10000,
        description="Numeric measurement value (physiological range validated in service)",
        examples=[120.0],
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement (e.g., mmHg, mg/dL, kg, %)",
        examples=["mmHg"],
    )
    recorded_at: datetime = Field(
        ...,
        description="When the measurement was taken (ISO-8601 UTC)",
        examples=["2025-01-15T10:30:00Z"],
    )
    source: MeasurementSource = Field(
        ...,
        description="Data source: manual, device, import, patient_portal",
        examples=["manual"],
    )
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional clinician notes about this measurement (PHI)",
    )


class BulkImportItem(BaseModel):
    """
    Single row in a bulk import request.

    Same fields as MeasurementCreate but source is optional (defaults
    to 'import' in the service layer).
    """

    measurement_type: MeasurementType = Field(
        ...,
        description="Clinical measurement type",
    )
    value: float = Field(
        ...,
        ge=0,
        le=10000,
        description="Numeric measurement value",
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement",
    )
    recorded_at: datetime = Field(
        ...,
        description="When the measurement was taken (ISO-8601 UTC)",
    )
    notes: Optional[str] = Field(
        None,
        max_length=2000,
        description="Optional notes (PHI)",
    )


class BulkImportRequest(BaseModel):
    """
    Request body for bulk measurement import.

    Contains a list of measurement data items to import for a patient.
    Each row is validated independently — valid rows succeed, invalid
    rows are reported in the error summary.

    Limits:
    - Maximum 500 rows per request (prevents timeout on large imports)
    """

    measurements: list[BulkImportItem] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="List of measurements to import (max 500 per request)",
    )


# ---------------------------------------------------------------------------
# Response Schemas — Output Formatting
# ---------------------------------------------------------------------------
class MeasurementResponse(BaseModel):
    """
    Single measurement response schema.

    Serializes a Measurement model instance for API output.
    Includes all fields that the requesting role is authorized to see.

    PHI fields (value, notes) are included because RBAC is enforced
    at the router level — if you can call the endpoint, you're
    authorized to see the data.
    """

    id: uuid.UUID = Field(..., description="Measurement UUID (immutable)")
    tenant_id: uuid.UUID = Field(..., description="Tenant UUID")
    patient_id: uuid.UUID = Field(..., description="Patient UUID")
    measurement_type: str = Field(..., description="Measurement type key")
    value: float = Field(..., description="Numeric measurement value (PHI)")
    unit: str = Field(..., description="Unit of measurement")
    recorded_at: datetime = Field(..., description="When measurement was taken (UTC)")
    recorded_by: uuid.UUID = Field(..., description="User who recorded this")
    source: str = Field(..., description="Data source (manual, device, import, patient_portal)")
    is_validated: bool = Field(..., description="Whether clinician has validated")
    validated_by: Optional[uuid.UUID] = Field(None, description="Validating clinician UUID")
    validated_at: Optional[datetime] = Field(None, description="Validation timestamp")
    is_flagged: bool = Field(..., description="Whether value deviates >2σ from baseline")
    flag_reason: Optional[str] = Field(None, description="Reason for flagging")
    notes: Optional[str] = Field(None, description="Clinician notes (PHI)")
    created_at: Optional[datetime] = Field(None, description="Record creation time")
    updated_at: Optional[datetime] = Field(None, description="Last update time")

    model_config = {"from_attributes": True}


class MeasurementListResponse(BaseModel):
    """
    Paginated list of measurements with cursor metadata.

    Used by the GET /patients/{id}/measurements endpoint.
    Wraps a list of MeasurementResponse items with pagination state.
    """

    items: list[MeasurementResponse] = Field(
        ...,
        description="List of measurement records for the current page",
    )
    cursor: Optional[str] = Field(
        None,
        description="Cursor for the next page (None if no more pages)",
    )
    has_more: bool = Field(
        ...,
        description="Whether there are more measurements after this page",
    )


class BulkImportResponse(BaseModel):
    """
    Response schema for bulk import operations.

    Reports how many rows were created, how many were skipped as
    duplicates (idempotent), and which rows had validation errors.
    """

    created: int = Field(..., description="Number of new measurements saved")
    skipped_duplicates: int = Field(
        ...,
        description="Number of rows skipped (already exist — idempotent)",
    )
    errors: list[dict[str, Any]] = Field(
        ...,
        description="List of {line, reason} for rows that failed validation",
    )


# ---------------------------------------------------------------------------
# Query Parameter Schema
# ---------------------------------------------------------------------------
class MeasurementHistoryParams(BaseModel):
    """
    Query parameters for measurement history/list endpoint.

    All fields are optional — omitting a field means no filter on that
    dimension. Multiple filters combine with AND logic.

    Used to validate and parse query parameters from the URL before
    converting to HistoryFilters for the service layer.
    """

    measurement_type: Optional[MeasurementType] = Field(
        None,
        description="Filter by measurement type (e.g., systolic_bp)",
    )
    date_from: Optional[datetime] = Field(
        None,
        description="Only measurements recorded on or after this datetime (UTC)",
    )
    date_to: Optional[datetime] = Field(
        None,
        description="Only measurements recorded on or before this datetime (UTC)",
    )
    validated_only: bool = Field(
        default=False,
        description="If true, only return clinician-validated measurements",
    )
    flagged_only: bool = Field(
        default=False,
        description="If true, only return flagged measurements (>2σ deviation)",
    )
