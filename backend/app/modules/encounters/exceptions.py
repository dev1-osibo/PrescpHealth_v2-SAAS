"""
PrescpHealth Backend — Encounter Module Exceptions.

Custom exception classes for the encounters module. These provide
clear, specific error types for different failure modes in encounter
workflows. Each exception carries enough context for error handlers
to produce meaningful API responses without exposing PHI.

Usage:
    from app.modules.encounters.exceptions import (
        EncounterNotFoundError,
        EncounterAlreadyCompletedError,
        InvalidEncounterStatusTransitionError,
    )

HIPAA: Exception messages MUST NOT contain PHI (no reason_for_visit,
no diagnosis details, no SOAP note content). Only opaque UUIDs are safe.
"""

import uuid


# ---------------------------------------------------------------------------
# Encounter Not Found
# ---------------------------------------------------------------------------
class EncounterNotFoundError(Exception):
    """
    Raised when an encounter lookup fails (no matching record).

    This can happen when:
    - The encounter_id doesn't exist in the database
    - The encounter exists but belongs to a different tenant (RLS hides it)
    - The encounter was soft-deleted

    The error message includes only the encounter_id (UUID, not PHI).
    """

    def __init__(self, encounter_id: uuid.UUID) -> None:
        self.encounter_id = encounter_id
        super().__init__(f"Encounter not found: {encounter_id}")


# ---------------------------------------------------------------------------
# Encounter Already Completed
# ---------------------------------------------------------------------------
class EncounterAlreadyCompletedError(Exception):
    """
    Raised when attempting to modify a completed encounter.

    Once an encounter reaches 'completed' status, it is immutable.
    No new SOAP notes, diagnoses, or procedures can be added.
    The discharge summary has been generated and the record is sealed.

    This enforces clinical documentation integrity — completed encounters
    represent the final, signed-off clinical record.
    """

    def __init__(self, encounter_id: uuid.UUID) -> None:
        self.encounter_id = encounter_id
        super().__init__(
            f"Encounter {encounter_id} is already completed and cannot be modified"
        )


# ---------------------------------------------------------------------------
# Invalid Status Transition
# ---------------------------------------------------------------------------
class InvalidEncounterStatusTransitionError(Exception):
    """
    Raised when an encounter status change violates allowed transitions.

    Valid transitions:
        planned → in_progress → completed
        planned → cancelled
        in_progress → cancelled (rare, e.g., patient left AMA)

    Invalid examples:
        completed → in_progress (cannot reopen)
        cancelled → in_progress (cannot un-cancel)
        completed → cancelled (already finalized)

    The error includes current and attempted status for debugging,
    but never includes clinical content (PHI-safe).
    """

    def __init__(
        self,
        encounter_id: uuid.UUID,
        current_status: str,
        attempted_status: str,
    ) -> None:
        self.encounter_id = encounter_id
        self.current_status = current_status
        self.attempted_status = attempted_status
        super().__init__(
            f"Invalid status transition for encounter {encounter_id}: "
            f"{current_status} → {attempted_status}"
        )
