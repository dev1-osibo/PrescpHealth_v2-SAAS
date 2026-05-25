"""
PrescpHealth Backend — Feature Vector Extraction.

Transforms raw Measurement objects into a structured feature dictionary
suitable for consumption by the Risk Engine (Task 9) and Forecast Engine
(Task 10). Each measurement type becomes a feature with metadata about
freshness, validation status, and staleness.

Why a separate module:
- The Risk Engine needs a consistent, well-typed input format
- Staleness detection prevents stale data from silently affecting predictions
- Centralizing feature extraction avoids duplicating transformation logic
  across multiple ML model adapters

Output Format:
    {
        "systolic_bp": {
            "value": 120.0,
            "unit": "mmHg",
            "recorded_at": "2025-01-15T10:30:00+00:00",
            "age_days": 3,
            "is_validated": True,
            "is_stale": False,
        },
        ...
    }

HIPAA Compliance:
    - Never logs measurement values (only patient_id and type counts)
    - The returned dict contains PHI (values) — caller must handle securely
    - No caching of feature vectors in browser-accessible storage
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.measurements.history import get_latest_measurements

# ---------------------------------------------------------------------------
# Module logger — logs extraction metadata without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Default threshold: measurements older than 90 days are marked stale.
# Risk Engine may choose to down-weight or exclude stale features.
DEFAULT_STALENESS_THRESHOLD_DAYS = 90


# ---------------------------------------------------------------------------
# Feature Vector Extraction
# ---------------------------------------------------------------------------
async def get_feature_vector(
    db: AsyncSession,
    patient_id: uuid.UUID,
    staleness_threshold_days: int = DEFAULT_STALENESS_THRESHOLD_DAYS,
) -> dict[str, dict]:
    """
    Extract a structured feature vector from a patient's latest measurements.

    Fetches the most recent measurement of each type and transforms them
    into a dict keyed by measurement_type with metadata useful for ML models.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient to extract features for.
        staleness_threshold_days: Measurements older than this many days
            are marked is_stale=True. Default is 90 days.

    Returns:
        Dict keyed by measurement_type string. Each value is a dict with:
        - value (float): The measurement reading
        - unit (str): Unit of measurement
        - recorded_at (str): ISO-8601 timestamp of when it was taken
        - age_days (int): Days since the measurement was recorded
        - is_validated (bool): Whether a clinician validated this reading
        - is_stale (bool): True if age_days > staleness_threshold_days

        Measurement types with no data are simply absent from the dict.
        Returns empty dict if patient has no measurements at all.
    """
    # Fetch the latest measurement of each type for this patient
    measurements = await get_latest_measurements(db=db, patient_id=patient_id)

    if not measurements:
        logger.debug(
            "feature_vector_empty",
            patient_id=str(patient_id),
        )
        return {}

    now = datetime.now(timezone.utc)
    feature_vector: dict[str, dict] = {}

    for measurement in measurements:
        # Compute age in days since the measurement was recorded
        age_days = _compute_age_days(measurement.recorded_at, now)

        # A measurement is stale if it's older than the threshold —
        # the Risk Engine should treat stale features with caution
        is_stale = age_days > staleness_threshold_days

        feature_vector[measurement.measurement_type] = {
            "value": measurement.value,
            "unit": measurement.unit,
            "recorded_at": measurement.recorded_at.isoformat(),
            "age_days": age_days,
            "is_validated": measurement.is_validated,
            "is_stale": is_stale,
        }

    logger.debug(
        "feature_vector_extracted",
        patient_id=str(patient_id),
        feature_count=len(feature_vector),
        stale_count=sum(
            1 for f in feature_vector.values() if f["is_stale"]
        ),
    )

    return feature_vector


# ---------------------------------------------------------------------------
# Helper: Compute age in days
# ---------------------------------------------------------------------------
def _compute_age_days(recorded_at: datetime, now: datetime) -> int:
    """
    Compute the number of whole days between recorded_at and now.

    Handles timezone-aware and naive datetimes by normalizing to UTC.
    Returns 0 if recorded_at is in the future (clock skew protection).
    """
    # Ensure both are timezone-aware for safe subtraction
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)

    delta = now - recorded_at
    # Protect against negative age (future timestamps from clock skew)
    return max(0, delta.days)
