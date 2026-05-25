"""
PrescpHealth Backend — Patient Search Service Delegation.

Contains the search_patients() delegation logic extracted from
PatientService. Wraps the search module for the service interface.

Extracted from service.py to comply with the ~150 lines of logic per
file rule. The PatientService orchestrator delegates to this module.

Note: The actual search query construction lives in search.py.
This module provides the service-layer interface that coordinates
with the search module.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResponse, PaginationParams
from app.modules.patients.search import (
    PatientSearchFilters,
    search_patients as _search_patients,
)


async def search_patients(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    filters: PatientSearchFilters,
    pagination: PaginationParams,
) -> PaginatedResponse:
    """
    Search patients with filters and cursor-based pagination.

    Delegates to the search module for query construction.
    See app.modules.patients.search for filter details.

    Args:
        db: Database session (tenant-scoped via RLS).
        tenant_id: Tenant UUID for explicit filtering.
        filters: Search criteria (name, MRN, status, date range).
        pagination: Page size and cursor.

    Returns:
        PaginatedResponse with patient items and pagination metadata.
    """
    return await _search_patients(db, tenant_id, filters, pagination)
