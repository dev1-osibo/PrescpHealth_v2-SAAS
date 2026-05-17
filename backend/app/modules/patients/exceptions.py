"""
PrescpHealth Backend — Patient Module Exceptions.

Patient-specific exceptions that extend the core exception hierarchy.
These provide clear, descriptive error messages for patient operations
without ever exposing PHI in error details.

Usage:
    from app.modules.patients.exceptions import PatientNotFoundError

    raise PatientNotFoundError(patient_id=patient_id)
"""

import uuid

from app.core.exceptions import ConflictError, NotFoundError, ValidationError


class PatientNotFoundError(NotFoundError):
    """
    Raised when a patient record cannot be found.

    This covers both truly missing patients AND soft-deleted patients
    (from the caller's perspective, they're the same — inaccessible).
    Never reveals whether the patient exists in another tenant.
    """

    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(
            message="Patient not found",
            details={"patient_id": str(patient_id)},
        )


class PatientAlreadyDeletedError(ConflictError):
    """
    Raised when attempting to soft-delete a patient that's already deleted.

    Prevents double-deletion which would overwrite the original deleted_at
    timestamp and corrupt the audit trail.
    """

    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(
            message="Patient is already deleted",
            details={"patient_id": str(patient_id)},
        )


class PatientNotDeletedError(ConflictError):
    """
    Raised when attempting to restore a patient that isn't deleted.

    Restoring an active patient is a no-op error — the caller likely
    has stale state and should refresh.
    """

    def __init__(self, patient_id: uuid.UUID) -> None:
        super().__init__(
            message="Patient is not deleted and cannot be restored",
            details={"patient_id": str(patient_id)},
        )


class DuplicateMRNError(ConflictError):
    """
    Raised when a medical record number already exists for this tenant.

    MRN is unique per tenant (different clinics can reuse MRN schemes).
    """

    def __init__(self, mrn: str) -> None:
        super().__init__(
            message="A patient with this medical record number already exists",
            details={"field": "medical_record_number"},
        )


class PatientVersionNotFoundError(NotFoundError):
    """
    Raised when a specific version number doesn't exist for a patient.

    Used in point-in-time recovery when requesting a version that
    hasn't been created yet (e.g., version 99 when only 3 exist).
    """

    def __init__(self, patient_id: uuid.UUID, version_number: int) -> None:
        super().__init__(
            message=f"Version {version_number} not found for this patient",
            details={
                "patient_id": str(patient_id),
                "version_number": version_number,
            },
        )
