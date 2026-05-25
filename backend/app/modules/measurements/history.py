"""
PrescpHealth Backend — Measurement History & Latest Queries.

Provides time-series history queries and "latest of each type" lookups
for clinical measurements. Used by:
- Frontend charts (time-series visualization)
- Risk engine (feature extraction — latest values as model inputs)
- Clinical review (measurement trends over time)

Query Patterns:
- History: Cursor-based pagination, ordered by recorded_at DESC
- Latest: One row per measurement type (most recent for each)

HIPAA Compliance:
    - Never logs measurement values (only patient_id and type)
    - RLS enforces tenant isolation at the database level
    - Results contain PHI (values) — caller must handle appropriately
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import (
    PaginatedResponse,
    PaginationParams,
    decode_cursor,
    encode_cursor,
)
from app.modules.measurements.models import Measurement

# ---------------------------------------------------------------------------
# Module logger — logs query metadata without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# History Filters
# ---------------------------------------------------------------------------
@dataclass
class HistoryFilters:
    """
    Optional filters for measurement history queries.

    Attributes:
        date_from: Only include measurements recorded on or after this date.
        date_to: Only include measurements recorded on or before this date.
        validated_only: If True, only return validated measurements.
        flagged_only: If True, only return flagged measurements (>2σ deviation).
    """

    date_from: datetime | None = None
    date_to: datetime | None = None
    validated_only: bool = False
    flagged_only: bool = False


# ---------------------------------------------------------------------------
# History Query
# ---------------------------------------------------------------------------
async def get_measurement_history(
    db: AsyncSession,
    patient_id: uuid.UUID,
    measurement_type: str,
    pagination: PaginationParams,
    filters: HistoryFilters | None = None,
) -> PaginatedResponse:
    """
    Retrieve time-series measurement history for a patient and type.

    Returns measurements ordered by recorded_at DESC (newest first)
    with cursor-based pagination for efficient traversal of large histories.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient.
        measurement_type: The measurement type to query (e.g., "systolic_bp").
        pagination: Page size and optional cursor for continuation.
        filters: Optional date range, validated-only, flagged-only filters.

    Returns:
        PaginatedResponse with measurement items, cursor, and has_more flag.
    """
    if filters is None:
        filters = HistoryFilters()

    # Build base query with required filters
    conditions = [
        Measurement.patient_id == patient_id,
        Measurement.measurement_type == measurement_type,
    ]

    # Apply optional filters
    if filters.date_from:
        conditions.append(Measurement.recorded_at >= filters.date_from)
    if filters.date_to:
        conditions.append(Measurement.recorded_at <= filters.date_to)
    if filters.validated_only:
        conditions.append(Measurement.is_validated == True)  # noqa: E712
    if filters.flagged_only:
        conditions.append(Measurement.is_flagged == True)  # noqa: E712

    # Apply cursor-based pagination (cursor encodes the last recorded_at)
    if pagination.cursor:
        cursor_data = decode_cursor(pagination.cursor)
        if cursor_data and cursor_data.get("field") == "recorded_at":
            # Fetch items AFTER the cursor position (older than cursor)
            cursor_time = datetime.fromisoformat(cursor_data["value"])
            conditions.append(Measurement.recorded_at < cursor_time)

    # Execute query with limit + 1 to detect has_more
    query = (
        select(Measurement)
        .where(and_(*conditions))
        .order_by(Measurement.recorded_at.desc())
        .limit(pagination.page_size + 1)
    )

    result = await db.execute(query)
    items = list(result.scalars().all())

    # Determine if there are more pages
    has_more = len(items) > pagination.page_size
    if has_more:
        items = items[: pagination.page_size]

    # Build cursor from the last item's recorded_at
    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_cursor(
            sort_field="recorded_at",
            sort_value=last_item.recorded_at.isoformat(),
            direction="desc",
        )

    return PaginatedResponse(items=items, cursor=next_cursor, has_more=has_more)


# ---------------------------------------------------------------------------
# Latest Measurements (one per type)
# ---------------------------------------------------------------------------
async def get_latest_measurements(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> list[Measurement]:
    """
    Get the most recent measurement of each type for a patient.

    Used by the risk engine for feature extraction — it needs the latest
    value of each measurement type as input features for the ML models.

    Implementation uses a correlated subquery to find the max recorded_at
    per measurement_type, then fetches those specific rows.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient.

    Returns:
        List of Measurement objects — one per measurement type that has data.
        Empty list if the patient has no measurements.
    """
    # Subquery: find the max recorded_at per measurement_type for this patient
    latest_subquery = (
        select(
            Measurement.measurement_type,
            Measurement.recorded_at,
        )
        .where(Measurement.patient_id == patient_id)
        .distinct(Measurement.measurement_type)
        .order_by(
            Measurement.measurement_type,
            Measurement.recorded_at.desc(),
        )
        .subquery()
    )

    # Main query: fetch full measurement rows matching the latest per type
    query = (
        select(Measurement)
        .join(
            latest_subquery,
            and_(
                Measurement.measurement_type == latest_subquery.c.measurement_type,
                Measurement.recorded_at == latest_subquery.c.recorded_at,
                Measurement.patient_id == patient_id,
            ),
        )
    )

    result = await db.execute(query)
    measurements = list(result.scalars().all())

    logger.debug(
        "latest_measurements_fetched",
        patient_id=str(patient_id),
        type_count=len(measurements),
    )

    return measurements
