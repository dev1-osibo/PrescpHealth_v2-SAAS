"""
PrescpHealth Backend — FHIR API Pydantic Schemas.

Request and response schemas for the FHIR R4 API endpoints.
FHIR resources are passed as raw dicts (Any) since they have complex,
resource-type-specific schemas. Pydantic validates the wrapper structure.
"""

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class FHIRResourceIn(BaseModel):
    """
    Generic FHIR R4 resource input wrapper.

    The actual resource JSON is in `resource` — validated by the
    FHIR validator (not by Pydantic since FHIR schemas are dynamic).
    """

    resource: dict[str, Any] = Field(
        ..., description="FHIR R4 resource JSON (resourceType required)"
    )


class FHIRBundleOut(BaseModel):
    """
    FHIR R4 Bundle response for search results.

    Wraps a list of matching resources in a FHIR Bundle.
    """

    resourceType: str = "Bundle"
    type: str = "searchset"
    total: int
    entry: list[dict[str, Any]] = []


class BulkExportRequest(BaseModel):
    """
    Body for GET /fhir/r4/$export bulk data export.

    _type: Comma-separated FHIR resource types to export.
    _since: Export only resources modified after this datetime.
    """

    _type: Optional[str] = Field(None, description="Comma-separated FHIR resource types")
    _since: Optional[str] = Field(None, description="ISO 8601 datetime for incremental export")
    output_format: str = Field(
        default="application/fhir+ndjson",
        description="Export file format (NDJSON per Bulk Data spec)",
    )


class SubscriptionIn(BaseModel):
    """
    FHIR R4 Subscription resource input.

    Validates the outer structure; detailed criteria validation
    happens in the SubscriptionManager.
    """

    resourceType: str = Field("Subscription", const=True)
    criteria: str = Field(
        ..., description="FHIR search criteria string (e.g., 'Encounter?status=finished')"
    )
    channel: dict[str, Any] = Field(
        ..., description="Channel config (type, endpoint, payload, header)"
    )
    reason: Optional[str] = Field(
        None, description="Human-readable description of why this subscription exists"
    )
    status: str = Field(default="requested")


class FHIRTaskOut(BaseModel):
    """Response for async operations (bulk export, etc.)."""

    task_id: uuid.UUID
    status: str = "accepted"
    status_url: Optional[str] = None
    message: str = ""
