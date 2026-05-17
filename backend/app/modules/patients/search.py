"""
PrescpHealth Backend — Patient Search Service.

Provides search and filtering capabilities for patient records with
cursor-based pagination. Supports:
- Partial name matching (ILIKE for case-insensitive search)
- MRN exact/partial match
- Status filtering (Active, Inactive, etc.)
- Date range filtering (created_at)
- Cursor-based pagination (consistent results, O(1) performance)

Performance:
- Uses ILIKE with indexed columns for name search
- Cursor pagination avoids offset performance degradation
- Filters applied at database level (not in Python)

HIPAA Compliance:
- Search results are tenant-scoped via RLS (automatic)
- Only patient_id logged in search operations — never search terms
- Soft-deleted patients excluded from search by default
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import (
    PaginatedResponse,
    PaginationParams,
    decode_cursor,
    encode_cursor,
)
from app.modules.patients.models import Patient, PatientStatus

# ---------------------------------------------------------------------------
# Module logger — logs search operations without PHI or search terms
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


@dataclass
class PatientSearchFilters:
    """
    Search filters for patient list queries.

    All filters are optional — omitting a filter means "no restriction"
    on that dimension. Filters are combined with AND logic.

    Attributes:
        name_query: Partial name match (searches first_name OR last_name).
        mrn_query: Partial MRN match.
        status: Filter by patient status (Active, Inactive, etc.).
        created_after: Only patients created after this datetime.
        created_before: Only patients created before this datetime.
        include_deleted: Whether to include soft-deleted patients (default False).
    """

    name_query: str | None = None
    mrn_query: str | None = None
    status: PatientStatus | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    include_deleted: bool = False


async def search_patients(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: PatientSearchFilters,
    pagination: PaginationParams,
) -> PaginatedResponse:
    """
    Search patients with filters and cursor-based pagination.

    Builds a dynamic query based on provided filters, applies cursor
    pagination, and returns results with pagination metadata.

    Sort order: created_at DESC (newest first) — consistent with cursor.

    Args:
        db: Database session (tenant-scoped via RLS).
        tenant_id: Tenant UUID (used for explicit filter alongside RLS).
        filters: Search criteria (all optional).
        pagination: Page size and cursor from client.

    Returns:
        PaginatedResponse with items, cursor, and has_more flag.
    """
    # Start with base query — RLS handles tenant isolation, but we also
    # filter explicitly for defense-in-depth
    query = select(Patient).where(Patient.tenant_id == tenant_id)

    # Apply filters
    query = _apply_filters(query, filters)

    # Apply cursor-based pagination
    query = _apply_cursor(query, pagination.cursor)

    # Sort by created_at DESC for consistent cursor ordering
    query = query.order_by(Patient.created_at.desc())

    # Fetch one extra row to determine if there are more results
    query = query.limit(pagination.page_size + 1)

    result = await db.execute(query)
    patients = list(result.scalars().all())

    # Determine if there are more results beyond this page
    has_more = len(patients) > pagination.page_size
    if has_more:
        # Remove the extra row — it's only for has_more detection
        patients = patients[:pagination.page_size]

    # Build cursor for next page (based on last item's created_at)
    next_cursor = None
    if has_more and patients:
        last_patient = patients[-1]
        next_cursor = encode_cursor(
            sort_field="created_at",
            sort_value=last_patient.created_at.isoformat(),
            direction="desc",
        )

    logger.info(
        "patient_search_completed",
        tenant_id=str(tenant_id),
        result_count=len(patients),
        has_more=has_more,
    )

    return PaginatedResponse(
        items=patients,
        cursor=next_cursor,
        has_more=has_more,
    )


def _apply_filters(query, filters: PatientSearchFilters):
    """
    Apply search filters to the patient query.

    Each filter is optional — only non-None filters are applied.
    All filters combine with AND logic.

    Args:
        query: The base SQLAlchemy select query.
        filters: The search filters to apply.

    Returns:
        Modified query with filters applied.
    """
    # Exclude soft-deleted patients unless explicitly requested
    if not filters.include_deleted:
        query = query.where(Patient.deleted_at.is_(None))

    # Name search — case-insensitive partial match on first OR last name
    if filters.name_query:
        name_pattern = f"%{filters.name_query}%"
        query = query.where(
            or_(
                Patient.first_name.ilike(name_pattern),
                Patient.last_name.ilike(name_pattern),
            )
        )

    # MRN search — case-insensitive partial match
    if filters.mrn_query:
        mrn_pattern = f"%{filters.mrn_query}%"
        query = query.where(Patient.medical_record_number.ilike(mrn_pattern))

    # Status filter — exact match
    if filters.status:
        query = query.where(Patient.status == filters.status.value)

    # Date range filters
    if filters.created_after:
        query = query.where(Patient.created_at >= filters.created_after)
    if filters.created_before:
        query = query.where(Patient.created_at <= filters.created_before)

    return query


def _apply_cursor(query, cursor: str | None):
    """
    Apply cursor-based pagination to the query.

    Decodes the cursor to get the last item's sort value, then
    filters to only return items after that position.

    For DESC ordering: items with created_at < cursor value.

    Args:
        query: The SQLAlchemy select query.
        cursor: Opaque cursor string from client (None for first page).

    Returns:
        Modified query with cursor filter applied.
    """
    if cursor is None:
        return query

    cursor_data = decode_cursor(cursor)
    if cursor_data is None:
        # Invalid cursor — treat as first page (don't error out)
        return query

    # For DESC ordering, we want items BEFORE the cursor position
    if cursor_data["dir"] == "desc":
        cursor_value = datetime.fromisoformat(cursor_data["value"])
        query = query.where(Patient.created_at < cursor_value)

    return query
