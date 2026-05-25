"""
PrescpHealth Backend — Data Sufficiency Check.

Determines whether a patient has enough validated measurement data to
run each of the 6 disease risk models. The Risk Engine (Task 9) calls
this before attempting computation to avoid running models on incomplete
data that would produce unreliable predictions.

Disease Model Requirements:
    Each disease model has a minimum set of measurement types it needs.
    If any required type is missing, the model cannot produce a valid score.
    Some models accept OR-alternatives (e.g., creatinine OR egfr for CKD).

Quality Levels:
    - "full_data": All required features present and validated
    - "sparse_data": Some required features present (partial computation possible)
    - "insufficient": Critical features missing (cannot compute)

HIPAA Compliance:
    - Never logs measurement values (only type names and counts)
    - Only queries validated measurements (Patient_User unvalidated excluded)
    - Returns structural metadata, not PHI values
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.measurements.models import Measurement

# ---------------------------------------------------------------------------
# Module logger — logs sufficiency metadata without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Disease Model Feature Requirements
# ---------------------------------------------------------------------------
# Each disease maps to a list of required feature groups.
# A group is a set of alternatives — at least one must be present.
# Example: ["creatinine", "egfr"] means creatinine OR egfr suffices.
DISEASE_REQUIREMENTS: dict[str, list[list[str]]] = {
    "stroke": [
        ["systolic_bp"],
        ["diastolic_bp"],
        ["heart_rate"],
        # age derived from patient DOB — not a measurement type
        # smoking_status is a measurement type in our system
        ["smoking_status"],
    ],
    "cvd": [
        ["systolic_bp"],
        ["total_cholesterol"],
        ["hdl_cholesterol"],
        ["smoking_status"],
        # age derived from patient DOB — not a measurement type
    ],
    "type_2_diabetes": [
        ["blood_glucose_fasting", "hba1c"],  # Either one suffices
        ["bmi"],
        ["waist_circumference"],
    ],
    "ckd": [
        ["creatinine", "egfr"],  # Either one suffices
        ["urine_albumin"],
        ["systolic_bp"],
    ],
    "hypertensive_crisis": [
        ["systolic_bp"],
        ["diastolic_bp"],
        ["heart_rate"],
    ],
    "copd": [
        ["fev1"],
        ["fvc"],
        ["smoking_status"],
        ["respiratory_rate"],
    ],
}


# ---------------------------------------------------------------------------
# Result Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class DiseaseDataStatus:
    """Status of data availability for a single disease model."""

    disease: str
    is_sufficient: bool
    available_features: list[str] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)
    # "full_data", "sparse_data", or "insufficient"
    data_quality: str = "insufficient"
    # Days since the oldest measurement used (None if no data)
    oldest_measurement_days: int | None = None


@dataclass
class DataSufficiencyResult:
    """Overall data sufficiency assessment for a patient across all diseases."""

    patient_id: uuid.UUID
    diseases: dict[str, DiseaseDataStatus] = field(default_factory=dict)
    # "full_data" if all sufficient, "sparse_data" if some, "insufficient" if none
    overall_quality: str = "insufficient"
    measurement_types_available: list[str] = field(default_factory=list)
    measurement_types_missing: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main Function: Check Data Sufficiency
# ---------------------------------------------------------------------------
async def check_data_sufficiency(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> DataSufficiencyResult:
    """
    Check whether a patient has sufficient data for each disease model.

    Queries only validated measurements (Patient_User unvalidated entries
    are excluded per Requirement 5.4). For each of the 6 disease models,
    determines if the minimum required measurement types are present.

    Args:
        db: Database session (tenant-scoped via RLS).
        patient_id: UUID of the patient to check.

    Returns:
        DataSufficiencyResult with per-disease status and overall quality.
    """
    # Step 1: Query distinct validated measurement types for this patient
    available_types, type_ages = await _get_validated_types(db, patient_id)

    # Step 2: Evaluate each disease model against available data
    diseases: dict[str, DiseaseDataStatus] = {}
    all_missing: set[str] = set()

    for disease_name, requirements in DISEASE_REQUIREMENTS.items():
        status = _evaluate_disease(
            disease_name, requirements, available_types, type_ages
        )
        diseases[disease_name] = status
        all_missing.update(status.missing_features)

    # Step 3: Compute overall quality
    sufficient_count = sum(1 for d in diseases.values() if d.is_sufficient)
    total_count = len(diseases)

    if sufficient_count == total_count:
        overall_quality = "full_data"
    elif sufficient_count > 0:
        overall_quality = "sparse_data"
    else:
        overall_quality = "insufficient"

    result = DataSufficiencyResult(
        patient_id=patient_id,
        diseases=diseases,
        overall_quality=overall_quality,
        measurement_types_available=sorted(available_types),
        measurement_types_missing=sorted(all_missing - available_types),
    )

    logger.info(
        "data_sufficiency_checked",
        patient_id=str(patient_id),
        overall_quality=overall_quality,
        sufficient_diseases=sufficient_count,
        total_diseases=total_count,
    )

    return result


# ---------------------------------------------------------------------------
# Private: Query validated measurement types
# ---------------------------------------------------------------------------
async def _get_validated_types(
    db: AsyncSession,
    patient_id: uuid.UUID,
) -> tuple[set[str], dict[str, int]]:
    """
    Get the set of measurement types with validated data for a patient.

    Also computes the age in days of the oldest measurement per type,
    which is used to report data freshness in the sufficiency result.

    Returns:
        Tuple of (set of type strings, dict of type -> oldest age in days).
    """
    # Query distinct types and their oldest recorded_at (for age calculation)
    query = (
        select(
            Measurement.measurement_type,
            Measurement.recorded_at,
        )
        .where(
            and_(
                Measurement.patient_id == patient_id,
                # Only validated measurements count for risk computation
                Measurement.is_validated == True,  # noqa: E712
            )
        )
    )

    result = await db.execute(query)
    rows = result.all()

    now = datetime.now(timezone.utc)
    available_types: set[str] = set()
    # Track the oldest measurement per type (worst-case freshness)
    type_ages: dict[str, int] = {}

    for row in rows:
        mtype = row.measurement_type
        recorded_at = row.recorded_at
        available_types.add(mtype)

        # Compute age in days
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - recorded_at).days)

        # Keep the oldest (max age) for each type
        if mtype not in type_ages or age_days > type_ages[mtype]:
            type_ages[mtype] = age_days

    return available_types, type_ages


# ---------------------------------------------------------------------------
# Private: Evaluate a single disease model
# ---------------------------------------------------------------------------
def _evaluate_disease(
    disease_name: str,
    requirements: list[list[str]],
    available_types: set[str],
    type_ages: dict[str, int],
) -> DiseaseDataStatus:
    """
    Evaluate data sufficiency for a single disease model.

    Each requirement group is a list of alternatives (OR logic).
    A group is satisfied if ANY type in the group is available.
    The disease is sufficient only if ALL groups are satisfied.
    """
    available_features: list[str] = []
    missing_features: list[str] = []
    oldest_age: int | None = None

    for group in requirements:
        # Check if any alternative in this group is available
        matched = [t for t in group if t in available_types]
        if matched:
            # Use the first available alternative as the "feature"
            feature = matched[0]
            available_features.append(feature)
            # Track oldest measurement age across all matched features
            if feature in type_ages:
                age = type_ages[feature]
                if oldest_age is None or age > oldest_age:
                    oldest_age = age
        else:
            # None of the alternatives are available — report all as missing
            # Use first item as representative for the missing feature label
            missing_features.append(group[0])

    # Determine quality level
    is_sufficient = len(missing_features) == 0
    total_groups = len(requirements)
    satisfied_groups = total_groups - len(missing_features)

    if is_sufficient:
        data_quality = "full_data"
    elif satisfied_groups > 0:
        data_quality = "sparse_data"
    else:
        data_quality = "insufficient"

    return DiseaseDataStatus(
        disease=disease_name,
        is_sufficient=is_sufficient,
        available_features=available_features,
        missing_features=missing_features,
        data_quality=data_quality,
        oldest_measurement_days=oldest_age,
    )
