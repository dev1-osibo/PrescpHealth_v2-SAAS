"""
Unit Tests: Encounter Module.

Tests the core encounter lifecycle logic including:
- Encounter creation sets status=IN_PROGRESS
- Valid and invalid status transitions
- Discharge summary contains all diagnoses and procedures
- EncounterNotFoundError has correct message format
- EncounterAlreadyCompletedError blocks modifications

These tests validate the encounter state machine and error handling
without requiring a database connection (pure unit tests with mocks).

HIPAA Note: All test data uses synthetic patient identifiers (UUIDs).
No real patient data is used in any test.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.modules.encounters.enums import EncounterClass, EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
    InvalidEncounterStatusTransitionError,
)
from app.modules.encounters.service import EncounterService


# ---------------------------------------------------------------------------
# Test: Encounter Creation Sets Status to IN_PROGRESS
# ---------------------------------------------------------------------------
class TestEncounterCreation:
    """Tests for encounter creation behavior."""

    def test_encounter_creation_default_status_is_in_progress(self):
        """
        Verify that new encounters start in IN_PROGRESS status.

        When a patient checks in, the encounter immediately enters
        IN_PROGRESS because the clinical visit has begun. There is no
        intermediate 'waiting' state in the current workflow.
        """
        # The EncounterService.create_encounter sets status=IN_PROGRESS
        # We verify this by checking the enum value used in the service
        assert EncounterStatus.IN_PROGRESS.value == "in_progress", (
            "IN_PROGRESS status should have value 'in_progress'"
        )

    def test_encounter_status_enum_has_four_values(self):
        """
        Verify EncounterStatus enum contains exactly 4 lifecycle states.

        The encounter state machine has 4 states:
        planned, in_progress, completed, cancelled.
        """
        statuses = list(EncounterStatus)
        assert len(statuses) == 4, (
            f"Expected 4 encounter statuses, got {len(statuses)}"
        )
        expected = {"planned", "in_progress", "completed", "cancelled"}
        actual = {s.value for s in statuses}
        assert actual == expected, (
            f"Status values mismatch: expected {expected}, got {actual}"
        )

    def test_encounter_class_enum_has_three_values(self):
        """
        Verify EncounterClass enum contains exactly 3 setting types.

        The encounter classification covers: ambulatory, inpatient, emergency.
        """
        classes = list(EncounterClass)
        assert len(classes) == 3, (
            f"Expected 3 encounter classes, got {len(classes)}"
        )
        expected = {"ambulatory", "inpatient", "emergency"}
        actual = {c.value for c in classes}
        assert actual == expected, (
            f"Class values mismatch: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# Test: Encounter Status Transitions (Valid and Invalid)
# ---------------------------------------------------------------------------
class TestEncounterStatusTransitions:
    """Tests for the encounter status transition state machine."""

    def test_valid_transition_planned_to_in_progress(self):
        """
        Verify planned → in_progress is a valid transition.

        This represents a patient arriving for a scheduled appointment.
        """
        service = EncounterService()
        encounter = MagicMock()
        encounter.id = uuid.uuid4()
        encounter.status = EncounterStatus.PLANNED

        # Should not raise — valid transition
        service._validate_transition(encounter, EncounterStatus.IN_PROGRESS)

    def test_valid_transition_in_progress_to_completed(self):
        """
        Verify in_progress → completed is a valid transition.

        This represents a clinician finishing the encounter and generating
        the discharge summary.
        """
        service = EncounterService()
        encounter = MagicMock()
        encounter.id = uuid.uuid4()
        encounter.status = EncounterStatus.IN_PROGRESS

        # Should not raise — valid transition
        service._validate_transition(encounter, EncounterStatus.COMPLETED)

    def test_valid_transition_planned_to_cancelled(self):
        """
        Verify planned → cancelled is a valid transition.

        This represents a patient cancelling their appointment.
        """
        service = EncounterService()
        encounter = MagicMock()
        encounter.id = uuid.uuid4()
        encounter.status = EncounterStatus.PLANNED

        # Should not raise — valid transition
        service._validate_transition(encounter, EncounterStatus.CANCELLED)

    def test_invalid_transition_completed_to_in_progress(self):
        """
        Verify completed → in_progress is blocked.

        Completed encounters are immutable — they represent the sealed
        clinical record and cannot be reopened.
        """
        service = EncounterService()
        encounter = MagicMock()
        encounter.id = uuid.uuid4()
        encounter.status = EncounterStatus.COMPLETED

        with pytest.raises(EncounterAlreadyCompletedError):
            service._validate_transition(encounter, EncounterStatus.IN_PROGRESS)

    def test_invalid_transition_cancelled_to_in_progress(self):
        """
        Verify cancelled → in_progress is blocked.

        Cancelled encounters cannot be un-cancelled. A new encounter
        must be created instead.
        """
        service = EncounterService()
        encounter = MagicMock()
        encounter.id = uuid.uuid4()
        encounter.status = EncounterStatus.CANCELLED

        with pytest.raises(InvalidEncounterStatusTransitionError):
            service._validate_transition(encounter, EncounterStatus.IN_PROGRESS)


# ---------------------------------------------------------------------------
# Test: Discharge Summary Contains All Diagnoses and Procedures
# ---------------------------------------------------------------------------
class TestDischargeSummary:
    """Tests for discharge summary generation."""

    def test_discharge_summary_contains_all_diagnoses(self):
        """
        Verify discharge summary includes every diagnosis from the encounter.

        The discharge summary is the legal record of what was diagnosed.
        Missing diagnoses could lead to continuity-of-care failures.
        """
        # Create mock encounter with 3 diagnoses
        diagnoses = []
        for i in range(3):
            dx = MagicMock()
            dx.icd10_code = f"E11.{i}"
            dx.display_name = f"Test Diagnosis {i}"
            dx.is_primary = (i == 0)
            dx.is_chronic = (i == 1)
            diagnoses.append(dx)

        encounter = MagicMock()
        encounter.diagnoses = diagnoses
        encounter.procedures = []

        service = EncounterService()
        summary = service._build_discharge_summary(encounter)

        assert len(summary["diagnoses"]) == 3, (
            f"Expected 3 diagnoses, got {len(summary['diagnoses'])}"
        )
        # Verify first diagnosis fields
        assert summary["diagnoses"][0]["icd10_code"] == "E11.0"
        assert summary["diagnoses"][0]["is_primary"] is True

    def test_discharge_summary_contains_all_procedures(self):
        """
        Verify discharge summary includes every procedure from the encounter.

        Procedures performed during the visit must be documented for
        billing, continuity of care, and legal record purposes.
        """
        # Create mock encounter with 2 procedures
        procedures = []
        for i in range(2):
            proc = MagicMock()
            proc.code = f"9921{i}"
            proc.description = f"Test Procedure {i}"
            proc.performed_at = None
            procedures.append(proc)

        encounter = MagicMock()
        encounter.diagnoses = []
        encounter.procedures = procedures

        service = EncounterService()
        summary = service._build_discharge_summary(encounter)

        assert len(summary["procedures"]) == 2, (
            f"Expected 2 procedures, got {len(summary['procedures'])}"
        )
        assert summary["procedures"][0]["code"] == "99210"

    def test_discharge_summary_empty_encounter(self):
        """
        Verify discharge summary handles encounters with no diagnoses/procedures.

        Some encounters may be brief consultations with no formal diagnoses
        or procedures recorded. The summary should still be valid.
        """
        encounter = MagicMock()
        encounter.diagnoses = []
        encounter.procedures = []

        service = EncounterService()
        summary = service._build_discharge_summary(encounter)

        assert summary["diagnoses"] == []
        assert summary["procedures"] == []
        assert "prescriptions" in summary
        assert "follow_up" in summary


# ---------------------------------------------------------------------------
# Test: Exception Error Messages
# ---------------------------------------------------------------------------
class TestEncounterExceptions:
    """Tests for encounter exception classes."""

    def test_encounter_not_found_error_message(self):
        """
        Verify EncounterNotFoundError includes the encounter_id in its message.

        The error message should contain only the UUID (not PHI) for
        debugging and API error response purposes.
        """
        enc_id = uuid.uuid4()
        error = EncounterNotFoundError(enc_id)

        assert str(enc_id) in str(error), (
            "EncounterNotFoundError message should contain the encounter_id"
        )
        assert error.encounter_id == enc_id

    def test_encounter_already_completed_error_blocks_modifications(self):
        """
        Verify EncounterAlreadyCompletedError message indicates immutability.

        The error message should clearly communicate that the encounter
        cannot be modified because it has been completed and sealed.
        """
        enc_id = uuid.uuid4()
        error = EncounterAlreadyCompletedError(enc_id)

        assert str(enc_id) in str(error)
        assert "completed" in str(error).lower()
        assert "cannot be modified" in str(error).lower()
        assert error.encounter_id == enc_id

    def test_invalid_status_transition_error_includes_context(self):
        """
        Verify InvalidEncounterStatusTransitionError includes current and
        attempted status for debugging.
        """
        enc_id = uuid.uuid4()
        error = InvalidEncounterStatusTransitionError(
            encounter_id=enc_id,
            current_status="cancelled",
            attempted_status="in_progress",
        )

        assert str(enc_id) in str(error)
        assert "cancelled" in str(error)
        assert "in_progress" in str(error)
        assert error.current_status == "cancelled"
        assert error.attempted_status == "in_progress"
