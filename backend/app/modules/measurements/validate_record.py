"""
PrescpHealth Backend — Measurement Validation (Clinician Approval).

Handles the workflow where a clinician validates (approves) a measurement
that was submitted by a Patient_User via the patient portal.

Business Rule:
    Patient_User measurements start with is_validated=False and are excluded
    from risk computation until a clinician reviews and validates them.
    This prevents unreliable self-reported data from affecting clinical
    risk scores without professional oversight.

Who Can Validate:
    - Doctor (any clinician role)
    - Nurse
    - Clinic_Admin
    - Super_Admin
    NOT: Patient_User (cannot validate their own submissions)

HIPAA Compliance:
    - Audit log records who validated and when (not the measurement value)
    - Only measurement_id and type are logged
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.measurements.exceptions import (
    MeasurementNotFoundError,
    MeasurementValidationForbiddenError,
)
from app.modules.measurements.models import Measurement

# ---------------------------------------------------------------------------
# Module logger — logs validation operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Roles that are allowed to validate measurements
# Patient_User is explicitly excluded — they cannot validate their own data
CLINICIAN_ROLES = {"Doctor", "Nurse", "Clinic_Admin", "Super_Admin"}


# ---------------------------------------------------------------------------
# Validate Measurement Record
# ---------------------------------------------------------------------------
async def validate_measurement_record(
    db: AsyncSession,
    measurement_id: uuid.UUID,
    user_id: uuid.UUID,
    user_role: str,
    audit_service: AuditService,
) -> Measurement:
    """
    Mark a measurement as validated by a clinician.

    Sets is_validated=True, records who validated it and when.
    Only clinician roles can perform this action.

    Args:
        db: Database session (tenant-scoped via RLS).
        measurement_id: UUID of the measurement to validate.
        user_id: UUID of the clinician performing validation.
        user_role: Role string of the user (e.g., "Doctor", "Patient_User").
        audit_service: AuditService instance for logging.

    Returns:
        The updated Measurement model instance with validation fields set.

    Raises:
        MeasurementNotFoundError: If measurement doesn't exist or wrong tenant.
        MeasurementValidationForbiddenError: If user is not a clinician.
    """
    # --- Permission check: only clinicians can validate ---
    if user_role not in CLINICIAN_ROLES:
        raise MeasurementValidationForbiddenError()

    # --- Load the measurement ---
    result = await db.execute(
        select(Measurement).where(Measurement.id == measurement_id)
    )
    measurement = result.scalar_one_or_none()

    if measurement is None:
        raise MeasurementNotFoundError(measurement_id)

    # --- Apply validation ---
    # Idempotent: if already validated, update the validator info
    measurement.is_validated = True
    measurement.validated_by = user_id
    measurement.validated_at = datetime.now(timezone.utc)

    await db.flush()

    # --- Audit log ---
    await audit_service.log(
        db=db,
        tenant_id=measurement.tenant_id,
        user_id=user_id,
        action="measurement.validate",
        resource_type="measurement",
        resource_id=measurement.id,
        metadata={"measurement_type": measurement.measurement_type},
    )

    logger.info(
        "measurement_validated",
        measurement_id=str(measurement_id),
        measurement_type=measurement.measurement_type,
        validated_by=str(user_id),
    )

    return measurement
