"""
PrescpHealth Backend — Drug Interaction Module Exceptions.

Custom exceptions for drug interaction safety engine.
"""


class DrugInteractionError(Exception):
    """Base exception for drug interaction module."""

    def __init__(self, message: str, error_code: str = "DRUG_INTERACTION_ERROR"):
        """
        Initialize exception.

        Args:
            message: Human-readable error message (no PHI)
            error_code: Machine-readable error code
        """
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class InteractionCheckFailedError(DrugInteractionError):
    """Raised when DDI/DHI check encounters error."""

    def __init__(self, message: str):
        super().__init__(
            message=message,
            error_code="INTERACTION_CHECK_FAILED",
        )


class MedicationNotFoundError(DrugInteractionError):
    """Raised when medication record not found."""

    def __init__(self, medication_id: str):
        super().__init__(
            message=f"Medication {medication_id} not found",
            error_code="MEDICATION_NOT_FOUND",
        )


class InteractionNotFoundError(DrugInteractionError):
    """Raised when interaction result not found."""

    def __init__(self, interaction_id: str):
        super().__init__(
            message=f"Interaction {interaction_id} not found",
            error_code="INTERACTION_NOT_FOUND",
        )


class InvalidOverrideJustificationError(DrugInteractionError):
    """Raised when override justification is insufficient."""

    def __init__(self, message: str = "Justification too short or missing"):
        super().__init__(
            message=message,
            error_code="INVALID_OVERRIDE_JUSTIFICATION",
        )


class DrugCodeNotFoundError(DrugInteractionError):
    """Raised when RxNorm/ATC code not found in database."""

    def __init__(self, drug_code: str):
        super().__init__(
            message=f"Drug code {drug_code} not found in interaction database",
            error_code="DRUG_CODE_NOT_FOUND",
        )
