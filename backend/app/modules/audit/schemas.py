"""
PrescpHealth Backend — Audit Log Pydantic Schemas.

Request/response schemas for the audit log read-only API.
These schemas enforce consistent response formatting and provide
query parameter validation for filtering audit entries.

Schema Design:
- Response schemas structure outgoing data (consistent envelope format)
- Filter schemas validate query parameters for list endpoints
- No write schemas — audit entries are created by the service only
- No PHI in any schema field — only opaque UUIDs and action metadata

Per API design steering rule:
- All responses use the standard envelope format
- Pagination uses cursor-based approach
- Timestamps are ISO-8601 UTC

Requirements Satisfied:
- 18.4: Audit entries readable by authorized roles
- 18.5: No write/delete schemas exposed (append-only enforcement)
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------
class AuditLogResponse(BaseModel):
    """
    Single audit log entry response.

    Represents one immutable audit record. Contains only non-PHI
    metadata about an action that was performed in the system.

    Fields mirror the AuditLog SQLAlchemy model but use Pydantic
    types for serialization and OpenAPI documentation.
    """

    id: int = Field(
        ...,
        description="Auto-incrementing audit entry ID",
    )
    tenant_id: uuid.UUID = Field(
        ...,
        description="Tenant UUID for the action context",
    )
    user_id: uuid.UUID = Field(
        ...,
        description="UUID of the user who performed the action",
    )
    action: str = Field(
        ...,
        description="Action performed (e.g., 'patient.create', 'auth.login')",
        examples=["patient.create", "measurement.update", "auth.login"],
    )
    resource_type: str = Field(
        ...,
        description="Type of resource affected (e.g., 'patient', 'measurement')",
        examples=["patient", "measurement", "user"],
    )
    resource_id: uuid.UUID | None = Field(
        None,
        description="UUID of the affected resource (NULL for non-resource actions)",
    )
    changes: dict[str, Any] | None = Field(
        None,
        description="Change details: {field: {old, new}} — NO PHI values",
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Request context: {ip, user_agent, correlation_id}",
    )
    created_at: datetime = Field(
        ...,
        description="When the action occurred (UTC ISO-8601)",
    )

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    """
    Paginated list of audit log entries.

    Wraps a list of AuditLogResponse items with pagination metadata.
    Used by the GET /api/v1/audit endpoint.

    Per API design steering rule:
    - Uses cursor-based pagination
    - Includes has_more flag for client-side pagination control
    """

    items: list[AuditLogResponse] = Field(
        ...,
        description="List of audit log entries for the current page",
    )
    cursor: str | None = Field(
        None,
        description="Cursor for the next page (None if no more pages)",
    )
    has_more: bool = Field(
        ...,
        description="Whether there are more entries after this page",
    )


# ---------------------------------------------------------------------------
# Filter/Query Schemas
# ---------------------------------------------------------------------------
class AuditLogFilter(BaseModel):
    """
    Query parameters for filtering audit log entries.

    All fields are optional — omitting a field means "no filter on this field".
    Multiple filters are combined with AND logic.

    Used as a dependency in the list endpoint to validate and parse
    query parameters from the URL.
    """

    user_id: uuid.UUID | None = Field(
        None,
        description="Filter by acting user UUID",
    )
    action: str | None = Field(
        None,
        description="Filter by action type (exact match, e.g., 'patient.create')",
    )
    resource_type: str | None = Field(
        None,
        description="Filter by resource type (e.g., 'patient', 'measurement')",
    )
    resource_id: uuid.UUID | None = Field(
        None,
        description="Filter by specific resource UUID",
    )
    start_date: datetime | None = Field(
        None,
        description="Filter entries created on or after this timestamp (UTC)",
    )
    end_date: datetime | None = Field(
        None,
        description="Filter entries created on or before this timestamp (UTC)",
    )
