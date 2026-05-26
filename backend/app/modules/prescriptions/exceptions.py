"""
PrescpHealth Backend — Prescription Module Exceptions.

Custom exception classes for the prescriptions module. These provide
clear, typed error handling for prescription-related business rule
violations without exposing PHI in error messages.

Exception Hierarchy:
    PrescriptionNotFoundError — Prescription UUID not found in database
    InteractionBlockedError — Contraindicated DDI detected, no acknowledgment
    NoRefillsRemainingError — Refill requested but count is zero
    InvalidPrescriptionStatusError — Operation invalid for current status

HIPAA Compliance:
    - Error messages contain ONLY opaque UUIDs and status strings
    - Never include drug names, dosages, or patient identifiers
    - Safe to log and return in API error responses
"""


# ---------------------------------------------------------------------------
# Base Exception for Prescriptions Module
# ---------------------------------------------------------------------------
class PrescriptionError(Exception):
    """
    Base exception for all prescription module errors.

    All prescription-specific exceptions inherit from this class,
    allowing callers to catch all prescription errors with a single
    except clause when needed.
    """

    pass


# ---------------------------------------------------------------------------
# Prescription Not Found
# ---------------------------------------------------------------------------
class PrescriptionNotFoundError(PrescriptionError):
    """
    Raised when a prescription UUID does not exist in the database.

    This is a 404-equivalent error. The prescription_id is safe to
    include in the message because UUIDs are opaque identifiers (not PHI).
    """

    def __init__(self, prescription_id: str) -> None:
        """
        Args:
            prescription_id: The UUID string that was not found.
        """
        self.prescription_id = prescription_id
        super().__init__(
            f"Prescription not found: {prescription_id}"
        )


# ---------------------------------------------------------------------------
# Drug Interaction Blocked
# ---------------------------------------------------------------------------
class InteractionBlockedError(PrescriptionError):
    """
    Raised when a Contraindicated drug-drug interaction is detected
    and the prescribing Doctor has NOT acknowledged the interaction.

    The prescription cannot proceed until the Doctor either:
    1. Acknowledges the interaction with a documented justification
    2. Chooses a different medication

    HIPAA: interaction_details contains only severity and interaction
    type — never drug names or patient identifiers.
    """

    def __init__(self, interaction_details: list[dict]) -> None:
        """
        Args:
            interaction_details: List of detected interactions with
                severity and type info (no PHI).
        """
        self.interaction_details = interaction_details
        super().__init__(
            "Prescription blocked: Contraindicated drug interaction detected. "
            "Acknowledgment with justification required to proceed."
        )


# ---------------------------------------------------------------------------
# No Refills Remaining
# ---------------------------------------------------------------------------
class NoRefillsRemainingError(PrescriptionError):
    """
    Raised when a refill is requested but refills_remaining is zero.

    The patient must obtain a new prescription from their Doctor
    to continue receiving this medication.
    """

    def __init__(self, prescription_id: str) -> None:
        """
        Args:
            prescription_id: The UUID of the prescription with no refills.
        """
        self.prescription_id = prescription_id
        super().__init__(
            f"No refills remaining for prescription: {prescription_id}"
        )


# ---------------------------------------------------------------------------
# Invalid Prescription Status
# ---------------------------------------------------------------------------
class InvalidPrescriptionStatusError(PrescriptionError):
    """
    Raised when an operation is attempted on a prescription whose
    current status does not allow that operation.

    Examples:
    - Attempting to refill a discontinued prescription
    - Attempting to resume a prescription that is not on_hold
    - Attempting to discontinue an already completed prescription

    HIPAA: Only includes status strings and prescription_id (no PHI).
    """

    def __init__(
        self,
        prescription_id: str,
        current_status: str,
        required_status: str,
        operation: str,
    ) -> None:
        """
        Args:
            prescription_id: The UUID of the prescription.
            current_status: The prescription's current status.
            required_status: The status required for this operation.
            operation: The operation that was attempted.
        """
        self.prescription_id = prescription_id
        self.current_status = current_status
        self.required_status = required_status
        self.operation = operation
        super().__init__(
            f"Cannot {operation} prescription {prescription_id}: "
            f"status is '{current_status}', requires '{required_status}'"
        )
