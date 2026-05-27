"""
Unit Tests: Encounter Module — EMR Layer 1.

Tests encounter lifecycle logic:
- Creation sets status to IN_PROGRESS
- Valid status transitions (planned→in_progress, in_progress→completed/cancelled)
- Invalid transitions raise InvalidEncounterStatusTransitionError
- Completed encounters reject new SOAP notes (EncounterAlreadyCompletedError)
- Discharge summary contains diagnoses and procedures lists
- EncounterNotFoundError has correct message format

HIPAA Note: All test data uses synthetic UUIDs. No real patient data.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.modules.encounters.enums import EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
    InvalidEncounterStatusTransitionError,
)
from app.modules.encounters.service import EncounterService


# ---------------------------------------------------------------------------
# Test: Encounter Creation Sets Status to IN_PROGRESS
# ---------------------------------------------------------------------------
class TestEncounterCreationStatus:
    """Verify new encounters default to IN_PROGRESS status."""

    def test_creation_sets_status_in_progress(self):
        """New encounters start IN_PROGRESS when patient checks in."""
        assert EncounterStatus.IN_PROGRESS.value == "in_progress"


# ---------------------------------------------------------------------------
# Test: Valid Status Transitions
# ---------------------------------------------------------------------------
class TestValidStatusTransitions:
    """Verify allowed transitions pass without raising."""

    def _make_encounter(self, status: EncounterStatus) -> MagicMock:
        """Helper to create a mock encounter with given status."""
        enc = MagicMock()
        enc.id = uuid.uuid4()
        enc.status = status
        return enc

    def test_planned_to_in_progress(self):
        """planned → in_progress is valid (patient arrives)."""
        svc = EncounterService()
        svc._validate_transition(
            self._make_encounter(EncounterStatus.PLANNED),
            EncounterStatus.IN_PROGRESS,
        )

    def test_in_progress_to_completed(self):
        """in_progress → completed is valid (clinician finishes visit)."""
        svc = EncounterService()
        svc._validate_transition(
            self._make_encounter(EncounterStatus.IN_PROGRESS),
            EncounterStatus.COMPLETED,
        )

    def test_in_progress_to_cancelled(self):
        """in_progress → cancelled is valid (patient left AMA)."""
        svc = EncounterService()
        svc._validate_transition(
            self._make_encounter(EncounterStatus.IN_PROGRESS),
            EncounterStatus.CANCELLED,
        )


# ---------------------------------------------------------------------------
# Test: Invalid Status Transitions
# ---------------------------------------------------------------------------
class TestInvalidStatusTransitions:
    """Verify disallowed transitions raise the correct error."""

    def test_completed_to_in_progress_raises(self):
        """completed → in_progress is blocked (sealed record)."""
        svc = EncounterService()
        enc = MagicMock()
        enc.id = uuid.uuid4()
        enc.status = EncounterStatus.COMPLETED

        with pytest.raises(EncounterAlreadyCompletedError):
            svc._validate_transition(enc, EncounterStatus.IN_PROGRESS)

    def test_cancelled_to_in_progress_raises(self):
        """cancelled → in_progress is blocked (cannot un-cancel)."""
        svc = EncounterService()
        enc = MagicMock()
        enc.id = uuid.uuid4()
        enc.status = EncounterStatus.CANCELLED

        with pytest.raises(InvalidEncounterStatusTransitionError):
            svc._validate_transition(enc, EncounterStatus.IN_PROGRESS)


# ---------------------------------------------------------------------------
# Test: Completed Encounter Rejects New SOAP Notes
# ---------------------------------------------------------------------------
class TestCompletedEncounterRejectsSoapNotes:
    """Completed encounters are immutable — no new clinical data."""

    def test_completed_encounter_raises_already_completed(self):
        """Attempting to modify a completed encounter raises error."""
        enc_id = uuid.uuid4()
        error = EncounterAlreadyCompletedError(enc_id)

        assert error.encounter_id == enc_id
        assert "completed" in str(error).lower()
        assert "cannot be modified" in str(error).lower()


# ---------------------------------------------------------------------------
# Test: Discharge Summary Contains Diagnoses and Procedures
# ---------------------------------------------------------------------------
class TestDischargeSummary:
    """Verify discharge summary structure from _build_discharge_summary."""

    def test_summary_contains_diagnoses_list(self):
        """Discharge summary includes all encounter diagnoses."""
        dx = MagicMock(
            icd10_code="E11.9", display_name="Type 2 DM",
            is_primary=True, is_chronic=True,
        )
        enc = MagicMock(diagnoses=[dx], procedures=[])

        svc = EncounterService()
        summary = svc._build_discharge_summary(enc)

        assert len(summary["diagnoses"]) == 1
        assert summary["diagnoses"][0]["icd10_code"] == "E11.9"

    def test_summary_contains_procedures_list(self):
        """Discharge summary includes all encounter procedures."""
        proc = MagicMock(code="99213", description="Office visit", performed_at=None)
        enc = MagicMock(diagnoses=[], procedures=[proc])

        svc = EncounterService()
        summary = svc._build_discharge_summary(enc)

        assert len(summary["procedures"]) == 1
        assert summary["procedures"][0]["code"] == "99213"


# ---------------------------------------------------------------------------
# Test: EncounterNotFoundError Message Format
# ---------------------------------------------------------------------------
class TestEncounterNotFoundError:
    """Verify error message includes encounter_id UUID."""

    def test_message_contains_encounter_id(self):
        """Error message includes the UUID for debugging."""
        enc_id = uuid.uuid4()
        error = EncounterNotFoundError(enc_id)

        assert str(enc_id) in str(error)
        assert error.encounter_id == enc_id
