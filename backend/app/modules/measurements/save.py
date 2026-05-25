"""
PrescpHealth Backend — Save Measurement Logic.

Handles the complete flow for saving a single clinical measurement:
1. Validate value against physiological range
2. Check idempotency (return existing if duplicate)
3. Check deviation from patient baseline (flag if >2σ)
4. Persist to database
5. Publish MeasurementSaved domain event
6. Create audit log entry

This module is called by MeasurementService.save_measurement() and
by the bulk import module for each valid row.

HIPAA Compliance:
    - Never logs measurement values (only measurement_id and type)
    - Audit log records action metadata, not PHI
    - Domain event contains only measurement_id and type (no value)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import MeasurementSaved, event_bus
from app.core.request_context import get_request_id
from app.modules.audit.service import AuditService
from app.modules.measurements.baseline import compute_baseline
from app.modules.measurements.models import Measurement, MeasurementType
from app.modules.measurements.validators import check_deviation, validate_measurement

# ---------------------------------------------------------------------------
# Module logger — logs save operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Save Measurement
# ---------------------------------------------------------------------------
async def save_measurement(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    user_id: uuid.UUID,
    data: dict[str, Any],
    audit_service: AuditService,
) -> Measurement:
    """
    Save a clinical measurement with full validation and event publishing.

    Complete flow:
    1. Validate the value against physiological range for the type
    2. Check idempotency — if duplicate exists, return it (no error)
    3. Compute patient baseline and check for deviation (>2σ flag)
    4. Create and persist the Measurement record
    5. Publish MeasurementSaved domain event for downstream processing
    6. Create audit log entry for HIPAA compliance

    Args:
        db: Database session (tenant-scoped via RLS).
        tenant_id: Tenant UUID for the measurement.
        patient_id: UUID of the patient this measurement belongs to.
        user_id: UUID of the user recording the measurement.
        data: Measurement data dict with keys:
            - measurement_type (str): Type key (e.g., "systolic_bp")
            - value (float): The numeric measurement value
            - unit (str): Unit of measurement (e.g., "mmHg")
            - recorded_at (datetime): When the measurement was taken
            - source (str): Data source (manual, device, import, patient_portal)
            - notes (str, optional): Clinician notes
        audit_service: AuditService instance for logging.

    Returns:
        The saved (or existing duplicate) Measurement model instance.

    Raises:
        ValidationError: If value is outside physiological range or unit mismatch.
    """
    measurement_type_str = data["measurement_type"]
    value = data["value"]
    unit = data["unit"]
    recorded_at = data["recorded_at"]
    source = data.get("source", "manual")
    notes = data.get("notes")

    # --- Step 1: Validate physiological range ---
    # Raises ValidationError if value is impossible for this type
    measurement_type_enum = MeasurementType(measurement_type_str)
    validate_measurement(measurement_type_enum, value, unit)

    # --- Step 2: Idempotency check ---
    # If this exact measurement already exists, return it (no duplicate creation)
    existing = await _check_idempotency(
        db, patient_id, measurement_type_str, recorded_at, value
    )
    if existing:
        logger.info(
            "measurement_duplicate_skipped",
            measurement_id=str(existing.id),
            measurement_type=measurement_type_str,
        )
        return existing

    # --- Step 3: Deviation detection ---
    is_flagged, flag_reason = await _check_baseline_deviation(
        db, patient_id, measurement_type_str, value
    )

    # --- Step 4: Create and persist ---
    # Patient_User submissions start as unvalidated (require clinician approval)
    is_validated = source != "patient_portal"

    measurement = Measurement(
        tenant_id=tenant_id,
        patient_id=patient_id,
        measurement_type=measurement_type_str,
        value=value,
        unit=unit,
        recorded_at=recorded_at,
        recorded_by=user_id,
        source=source,
        is_validated=is_validated,
        is_flagged=is_flagged,
        flag_reason=flag_reason,
        notes=notes,
    )

    try:
        # Use a savepoint (nested transaction) so that an IntegrityError
        # only rolls back this insert — not the entire session. This is
        # critical for bulk import where multiple rows share one session.
        async with db.begin_nested():
            db.add(measurement)
            await db.flush()
    except IntegrityError:
        # Race condition: another request created the same measurement
        # between our idempotency check and insert. The savepoint was
        # rolled back automatically, but the outer session remains usable.
        existing = await _check_idempotency(
            db, patient_id, measurement_type_str, recorded_at, value
        )
        if existing:
            return existing
        raise  # Unexpected integrity error — re-raise

    # --- Step 5: Publish domain event ---
    # Forward-compatibility: include flagging and validation status so
    # downstream consumers (Risk Engine, Alert Service) can react without
    # re-querying the database for these fields.
    await event_bus.publish(
        MeasurementSaved(
            correlation_id=get_request_id() or str(uuid.uuid4()),
            tenant_id=tenant_id,
            patient_id=patient_id,
            measurement_type=measurement_type_str,
            measurement_id=measurement.id,
            is_flagged=is_flagged,
            flag_reason=flag_reason,
            is_validated=is_validated,
        )
    )

    # --- Step 6: Audit log ---
    await audit_service.log(
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="measurement.create",
        resource_type="measurement",
        resource_id=measurement.id,
        metadata={"measurement_type": measurement_type_str},
    )

    logger.info(
        "measurement_saved",
        measurement_id=str(measurement.id),
        measurement_type=measurement_type_str,
        patient_id=str(patient_id),
    )

    return measurement


# ---------------------------------------------------------------------------
# Idempotency Check (private helper)
# ---------------------------------------------------------------------------
async def _check_idempotency(
    db: AsyncSession,
    patient_id: uuid.UUID,
    measurement_type: str,
    recorded_at: datetime,
    value: float,
) -> Measurement | None:
    """
    Check if an identical measurement already exists.

    Idempotency key: (patient_id, measurement_type, recorded_at, value).
    This prevents duplicate entries from retries, bulk import re-runs,
    or concurrent submissions.

    Returns:
        The existing Measurement if found, None otherwise.
    """
    query = select(Measurement).where(
        and_(
            Measurement.patient_id == patient_id,
            Measurement.measurement_type == measurement_type,
            Measurement.recorded_at == recorded_at,
            Measurement.value == value,
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Baseline Deviation Check (private helper)
# ---------------------------------------------------------------------------
async def _check_baseline_deviation(
    db: AsyncSession,
    patient_id: uuid.UUID,
    measurement_type: str,
    value: float,
) -> tuple[bool, str | None]:
    """
    Check if the new value deviates >2σ from the patient's baseline.

    If the patient has sufficient measurement history, computes the
    baseline and checks deviation. If insufficient history, no flag.

    Returns:
        Tuple of (is_flagged, flag_reason). flag_reason is None if not flagged.
    """
    baseline = await compute_baseline(db, patient_id, measurement_type)

    if baseline is None or not baseline.has_sufficient_data:
        # Not enough history to assess deviation — don't flag
        return (False, None)

    is_flagged, _sigma, flag_reason = check_deviation(
        value, baseline.mean, baseline.std
    )

    return (is_flagged, flag_reason)
