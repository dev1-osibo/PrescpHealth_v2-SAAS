"""
PrescpHealth Backend — Measurement Module Exceptions.

Custom exceptions specific to the clinical measurement module.
These provide clear, PHI-safe error messages for measurement operations.

HIPAA Compliance:
    - Error messages NEVER include measurement values (PHI)
    - Only measurement_id (UUID) and measurement_type are referenced
    - Generic messages with request_id for support correlation
"""

from app.core.exceptions import ForbiddenError, NotFoundError


class MeasurementNotFoundError(NotFoundError):
    """
    Raised when a measurement record cannot be found.

    Could mean: wrong ID, wrong tenant (RLS hides it), or soft-deleted.
    Always returns 404 regardless of reason (prevents tenant enumeration).
    """

    def __init__(self, measurement_id) -> None:
        """
        Args:
            measurement_id: UUID of the measurement that was not found.
        """
        super().__init__(
            message="Measurement not found",
            details={"measurement_id": str(measurement_id)},
        )


class MeasurementValidationForbiddenError(ForbiddenError):
    """
    Raised when a non-clinician attempts to validate a measurement.

    Only clinician roles (Doctor, Nurse, Clinic_Admin) can validate
    measurements. Patient_User submissions require clinician approval.
    """

    def __init__(self) -> None:
        super().__init__(
            message="Only clinicians can validate measurements",
            details={"reason": "insufficient_role"},
        )
