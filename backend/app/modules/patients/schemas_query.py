"""
PrescpHealth Backend — Patient Query Parameter Schema.

Defines the PatientSearchParams schema for validating and parsing
query parameters from the patient search/filter URL.

Extracted from schemas.py to comply with the ~150 lines of logic per
file rule. Re-exported from schemas.py for backward compatibility.

All fields are optional — omitting a field means no filter on that
dimension. Multiple filters combine with AND logic.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.modules.patients.enums import PatientStatus


# ---------------------------------------------------------------------------
# PatientSearchParams — Query parameter validation
# ---------------------------------------------------------------------------
class PatientSearchParams(BaseModel):
    """
    Query parameters for patient search/filter.

    All fields are optional — omitting a field means no filter on that
    dimension. Multiple filters combine with AND logic.

    Used to validate and parse query parameters from the URL before
    converting to PatientSearchFilters for the service layer.
    """

    name: Optional[str] = Field(
        None,
        description="Partial name match (searches first_name OR last_name)",
    )
    mrn: Optional[str] = Field(
        None,
        description="Partial MRN match",
    )
    status: Optional[PatientStatus] = Field(
        None,
        description="Filter by patient status (Active, Inactive, etc.)",
    )
    created_after: Optional[datetime] = Field(
        None,
        description="Only patients created after this datetime (UTC)",
    )
    created_before: Optional[datetime] = Field(
        None,
        description="Only patients created before this datetime (UTC)",
    )
    include_deleted: bool = Field(
        default=False,
        description="Whether to include soft-deleted patients",
    )
