"""
PrescpHealth Backend — Measurement Bulk Import.

Handles CSV-style bulk import of multiple measurements for a patient.
Each row is validated independently — valid rows succeed, invalid rows
are reported with line numbers and reasons.

Key Behaviors:
- Each row validated independently (one bad row doesn't block others)
- Duplicates are SKIPPED (not errors) — idempotent by design
- Valid rows are committed; invalid rows reported in the error summary
- Transaction boundary: valid rows persist even if some rows fail validation

Import Summary Response:
    {
        "created": 5,           # New measurements saved
        "skipped_duplicates": 2, # Existing duplicates (idempotent skip)
        "errors": [             # Rows that failed validation
            {"line": 3, "reason": "Value below minimum for systolic_bp"},
            {"line": 7, "reason": "Unknown measurement type: 'invalid_type'"},
        ]
    }

HIPAA Compliance:
    - Error reasons describe the issue without including the actual value
    - Audit log records bulk import metadata (count, not values)
    - Source is set to "import" for all bulk-imported measurements
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.modules.audit.service import AuditService
from app.modules.measurements.models import Measurement
from app.modules.measurements.save import save_measurement

# ---------------------------------------------------------------------------
# Module logger — logs bulk import operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Bulk Import Result
# ---------------------------------------------------------------------------
@dataclass
class BulkImportResult:
    """
    Summary of a bulk import operation.

    Attributes:
        created: Number of new measurements successfully saved.
        skipped_duplicates: Number of rows skipped because they already exist.
        errors: List of dicts with 'line' and 'reason' for failed rows.
    """

    created: int = 0
    skipped_duplicates: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to API response format."""
        return {
            "created": self.created,
            "skipped_duplicates": self.skipped_duplicates,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Bulk Import
# ---------------------------------------------------------------------------
async def bulk_import(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    patient_id: uuid.UUID,
    user_id: uuid.UUID,
    measurements_list: list[dict[str, Any]],
    audit_service: AuditService,
) -> BulkImportResult:
    """
    Import multiple measurements for a patient with per-row validation.

    Each row is processed independently:
    - Valid rows are saved (via save_measurement which handles idempotency)
    - Duplicate rows are skipped (counted in skipped_duplicates)
    - Invalid rows are reported with line number and reason

    The source is automatically set to "import" for all rows.

    Args:
        db: Database session (tenant-scoped via RLS).
        tenant_id: Tenant UUID for all measurements.
        patient_id: UUID of the patient these measurements belong to.
        user_id: UUID of the user performing the import.
        measurements_list: List of measurement data dicts. Each dict should
            contain: measurement_type, value, unit, recorded_at.
            Line numbers are 1-indexed based on list position.
        audit_service: AuditService instance for logging.

    Returns:
        BulkImportResult with counts of created, skipped, and errored rows.
    """
    result = BulkImportResult()

    for index, row_data in enumerate(measurements_list):
        # Line numbers are 1-indexed for user-facing error messages
        line_number = index + 1

        try:
            # Force source to "import" for bulk-imported measurements
            row_data["source"] = "import"

            measurement = await save_measurement(
                db=db,
                tenant_id=tenant_id,
                patient_id=patient_id,
                user_id=user_id,
                data=row_data,
                audit_service=audit_service,
            )

            # Determine if this was a new creation or a duplicate skip
            # save_measurement returns existing record for duplicates
            if _is_duplicate_return(measurement):
                result.skipped_duplicates += 1
            else:
                result.created += 1

        except ValidationError as exc:
            # Validation failure — record the error with line number
            # Error message is already PHI-safe (validators don't include values)
            result.errors.append({
                "line": line_number,
                "reason": exc.message,
            })

        except Exception as exc:
            # Unexpected error — log internally, report generic message to user
            logger.error(
                "bulk_import_row_error",
                line=line_number,
                error_type=type(exc).__name__,
                patient_id=str(patient_id),
            )
            result.errors.append({
                "line": line_number,
                "reason": "Unexpected error processing this row",
            })

    # Commit all valid rows in a single transaction
    await db.commit()

    # Audit log for the bulk import operation (metadata only, no PHI)
    await audit_service.log(
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
        action="measurement.bulk_import",
        resource_type="measurement",
        metadata={
            "patient_id": str(patient_id),
            "total_rows": len(measurements_list),
            "created": result.created,
            "skipped_duplicates": result.skipped_duplicates,
            "error_count": len(result.errors),
        },
    )

    logger.info(
        "bulk_import_completed",
        patient_id=str(patient_id),
        total_rows=len(measurements_list),
        created=result.created,
        skipped=result.skipped_duplicates,
        errors=len(result.errors),
    )

    return result


def _is_duplicate_return(measurement: Measurement) -> bool:
    """
    Determine if save_measurement returned an existing duplicate.

    When save_measurement finds an idempotent duplicate, it returns the
    existing record without adding it to the session as "new". We detect
    this by checking the SQLAlchemy instance state: if the object is
    "pending" (new, not yet committed), it was just created. If it's
    "persistent" (already in DB), it was returned as a duplicate.

    Returns:
        True if the measurement was a pre-existing duplicate, False if new.
    """
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(measurement)
    # Pending = just added to session (new creation)
    # Persistent + not pending = already existed in DB (duplicate)
    return not state.pending
