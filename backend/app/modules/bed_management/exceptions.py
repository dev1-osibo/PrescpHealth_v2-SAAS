"""
PrescpHealth Backend — Bed Management Exceptions.

All messages reference IDs only — no patient names or PHI.
"""

import uuid


class BedManagementError(Exception):
    """Base class for all bed management errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class WardNotFoundError(BedManagementError):
    """Raised when a ward cannot be located."""

    def __init__(self, ward_id: uuid.UUID) -> None:
        super().__init__(message=f"Ward {ward_id} not found", status_code=404)
        self.ward_id = ward_id


class BedNotFoundError(BedManagementError):
    """Raised when a bed cannot be located."""

    def __init__(self, bed_id: uuid.UUID) -> None:
        super().__init__(message=f"Bed {bed_id} not found", status_code=404)
        self.bed_id = bed_id


class BedNotAvailableError(BedManagementError):
    """Raised when attempting to admit to a non-available bed."""

    def __init__(self, bed_id: uuid.UUID, current_status: str) -> None:
        super().__init__(
            message=f"Bed {bed_id} is not available (current status: {current_status})",
            status_code=409,
        )


class AdmissionNotFoundError(BedManagementError):
    """Raised when an admission record cannot be located."""

    def __init__(self, admission_id: uuid.UUID) -> None:
        super().__init__(message=f"Admission {admission_id} not found", status_code=404)
        self.admission_id = admission_id


class AdmissionAlreadyDischargedError(BedManagementError):
    """Raised when trying to discharge/modify an already-discharged admission."""

    def __init__(self, admission_id: uuid.UUID) -> None:
        super().__init__(
            message=f"Admission {admission_id} is already discharged",
            status_code=409,
        )


class NursingNoteNotFoundError(BedManagementError):
    """Raised when a nursing note cannot be located."""

    def __init__(self, note_id: uuid.UUID) -> None:
        super().__init__(message=f"Nursing note {note_id} not found", status_code=404)
