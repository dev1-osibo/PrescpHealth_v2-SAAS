"""
PrescpHealth Backend — Report Module Schemas.

Pydantic v2 models for request validation and response serialization.
All schema fields follow the standard envelope pattern:
  {"success": true, "data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}

PHI note: patient_id fields carry UUIDs only; no names or clinical
values appear in request or response schemas.
"""
import uuid
from typing import Annotated

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    """
    Request body for generating a clinical summary PDF.

    Args:
        patient_id: UUID of the patient whose report is requested.
        include_sections: Ordered list of clinical sections to render.
            Defaults to the four standard clinical sections.
    """

    patient_id: uuid.UUID
    include_sections: list[str] = Field(
        default=["demographics", "medications", "risk_scores", "alerts"],
        description="Clinical sections to include in the generated PDF.",
    )


class ReferralRequest(BaseModel):
    """
    Request body for generating a referral letter PDF.

    Args:
        patient_id: UUID of the patient being referred.
        referring_physician: Name or identifier of the referring clinician.
        referral_reason: Clinical reason for the referral (max 1000 chars).
    """

    patient_id: uuid.UUID
    referring_physician: str = Field(
        ...,
        min_length=1,
        description="Name or ID of the referring physician.",
    )
    referral_reason: Annotated[str, Field(max_length=1000)] = Field(
        ...,
        description="Clinical reason for the referral (stored in PDF; not PHI in the same sense).",
    )


class ReportTaskResponse(BaseModel):
    """
    Standard 202 Accepted response for asynchronous report generation.

    Args:
        success: Always True on accepted response.
        data: Contains task_id and estimated_seconds until completion.
        meta: Standard envelope metadata (request_id, timestamp).
    """

    success: bool = True
    data: dict
    meta: dict


class CSVExportMeta(BaseModel):
    """
    Response model for synchronous CSV export operations.

    Used when the full row count is known before streaming begins
    (population exports where counts are pre-computed).

    Args:
        success: Always True on successful export.
        meta: Contains row_count and exported_at timestamp.
    """

    success: bool = True
    meta: dict
