"""
PrescpHealth Backend — Measurement Baseline Computation.

Computes a patient's personal baseline (mean and standard deviation)
for a specific measurement type. The baseline is used by the deviation
detection system to flag measurements that deviate >2σ from the patient's
normal range.

Algorithm:
    1. Query validated measurements for the patient + type
    2. Use the LARGER of: last 90 days OR last 10 readings
       (ensures enough data points for statistical significance)
    3. Compute mean and standard deviation from the selected set
    4. Return (mean, std, sample_count) for use by check_deviation()

Why "larger of 90 days or 10 readings":
    - A patient with daily readings has ~90 data points in 90 days (plenty)
    - A patient with quarterly readings has ~1 in 90 days (not enough)
    - Using "last 10 readings" for sparse data ensures we always have
      enough points for a meaningful standard deviation
    - Using "last 90 days" for frequent data keeps the baseline current

HIPAA Compliance:
    - Never logs measurement values (only patient_id and type)
    - Returns only statistical aggregates (mean, std) — not raw values
"""

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.measurements.models import Measurement

# ---------------------------------------------------------------------------
# Module logger — logs baseline computation metadata without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Baseline Result
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BaselineResult:
    """
    Result of a baseline computation for a patient's measurement type.

    Attributes:
        mean: Average value from the baseline sample.
        std: Standard deviation from the baseline sample.
        sample_count: Number of measurements used in computation.
        has_sufficient_data: True if sample_count >= 3 (minimum for
            meaningful standard deviation).
    """

    mean: float
    std: float
    sample_count: int
    has_sufficient_data: bool


# ---------------------------------------------------------------------------
# Baseline Computation
# ---------------------------------------------------------------------------
async def compute_baseline(
    db: AsyncSession,
    patient_id: uuid.UUID,
    measurement_type: str,
) -> BaselineResult | None:
    """
    Compute the baseline (mean, std) for a patient's measurement type.

    Uses validated measurements only — unvalidated Patient_User submissions
    are excluded to prevent unreliable data from skewing the baseline.

    Selection logic:
    - Fetch measurements from the last 90 days
    - If fewer than 10 readings in 90 days, fetch the last 10 readings
      regardless of date (ensures statistical significance)
    - Use whichever set is LARGER

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient.
        measurement_type: The measurement type string (e.g., "systolic_bp").

    Returns:
        BaselineResult with mean, std, and sample count.
        Returns None if no validated measurements exist for this patient/type.

    Note:
        Does NOT log measurement values (PHI). Only logs patient_id and type.
    """
    # --- Strategy 1: Last 90 days of validated measurements ---
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)

    time_based_query = (
        select(Measurement.value)
        .where(
            and_(
                Measurement.patient_id == patient_id,
                Measurement.measurement_type == measurement_type,
                Measurement.is_validated == True,  # noqa: E712
                Measurement.recorded_at >= ninety_days_ago,
            )
        )
        .order_by(Measurement.recorded_at.desc())
    )

    time_result = await db.execute(time_based_query)
    time_values = [row[0] for row in time_result.fetchall()]

    # --- Strategy 2: Last 10 validated readings (regardless of date) ---
    count_based_query = (
        select(Measurement.value)
        .where(
            and_(
                Measurement.patient_id == patient_id,
                Measurement.measurement_type == measurement_type,
                Measurement.is_validated == True,  # noqa: E712
            )
        )
        .order_by(Measurement.recorded_at.desc())
        .limit(10)
    )

    count_result = await db.execute(count_based_query)
    count_values = [row[0] for row in count_result.fetchall()]

    # --- Use whichever set is LARGER ---
    values = time_values if len(time_values) >= len(count_values) else count_values

    if not values:
        # No validated measurements exist — cannot compute baseline
        return None

    # Compute mean and standard deviation
    sample_count = len(values)
    mean = sum(values) / sample_count

    if sample_count < 2:
        # Cannot compute std with fewer than 2 data points
        return BaselineResult(
            mean=mean,
            std=0.0,
            sample_count=sample_count,
            has_sufficient_data=False,
        )

    # Population std (not sample std) — we have the full recent history
    variance = sum((v - mean) ** 2 for v in values) / sample_count
    std = math.sqrt(variance)

    logger.debug(
        "baseline_computed",
        patient_id=str(patient_id),
        measurement_type=measurement_type,
        sample_count=sample_count,
    )

    return BaselineResult(
        mean=mean,
        std=std,
        sample_count=sample_count,
        # Need at least 3 readings for a meaningful standard deviation
        has_sufficient_data=sample_count >= 3,
    )
