"""
PrescpHealth Backend — Lab Order Pydantic Schemas.

Input validation schemas for lab order management API endpoints:
- LabOrderCreate: Create a new lab order (validates LOINC)
- LabOrderStatusUpdate: Update lab order status
- LabResultCreate: Record a lab result

HIPAA Compliance:
- Schemas contain PHI fields (test_name, clinical_indication, values)
- Protected by RBAC at the router level + Cache-Control headers
- Never expose PHI in validation error messages
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.modules.lab_orders.enums import LabPriority


# ---------------------------------------------------------------------------
# Lab Order Create — Place a new lab order
# ---------------------------------------------------------------------------
class LabOrderCreate(BaseModel):
    """
    Input schema for creating a new lab order.

    Triggers LOINC code validation against the code catalog.
    Invalid or inactive LOINC codes are rejected.
    """

    patient_id: uuid.UUID = Field(
        ..., description="Patient this lab order is for"
    )
    encounter_id: Optional[uuid.UUID] = Field(
        None, description="Originating encounter (nullable)"
    )
    test_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="PHI: Human-readable lab test name",
    )
    loinc_code: str = Field(
        ...,
        min_length=3,
        max_length=20,
        description="LOINC code (validated against code catalog)",
    )
    priority: str = Field(
        default=LabPriority.ROUTINE.value,
        description="Processing urgency: routine, urgent, stat",
        pattern="^(routine|urgent|stat)$",
    )
    clinical_indication: Optional[str] = Field(
        None,
        max_length=2000,
        description="PHI: Clinical reason for ordering this test",
    )


# ---------------------------------------------------------------------------
# Lab Order Status Update
# ---------------------------------------------------------------------------
class LabOrderStatusUpdate(BaseModel):
    """Input schema for updating lab order status."""

    status: str = Field(
        ...,
        description="New status: specimen_collected, in_progress, cancelled",
        pattern="^(specimen_collected|in_progress|cancelled)$",
    )


# ---------------------------------------------------------------------------
# Lab Result Create — Record a lab result
# ---------------------------------------------------------------------------
class LabResultCreate(BaseModel):
    """
    Input schema for recording a lab result.

    The is_abnormal flag is computed automatically by comparing
    numeric_value against the reference range.
    """

    value: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="PHI: Result value as string (e.g., '5.2', 'Positive')",
    )
    numeric_value: Optional[float] = Field(
        None, description="PHI: Parsed numeric value (NULL for qualitative)"
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unit of measurement (e.g., mg/dL, mmol/L)",
    )
    reference_range_low: Optional[float] = Field(
        None, description="Lower bound of normal reference range"
    )
    reference_range_high: Optional[float] = Field(
        None, description="Upper bound of normal reference range"
    )
    resulted_at: datetime = Field(
        ..., description="When the result was produced by the lab (UTC)"
    )
