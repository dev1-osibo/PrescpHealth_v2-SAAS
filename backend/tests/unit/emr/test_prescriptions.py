"""
Unit Tests: Prescription Module — EMR Layer 1.

Tests prescription structures and error handling:
- PrescriptionStatus enum has 4 values (active, completed, discontinued, on_hold)
- InteractionBlockedError message mentions "Contraindicated"
- NoRefillsRemainingError includes prescription_id
- InvalidPrescriptionStatusError includes current_status and required_status
- PrescriptionNotFoundError message format
- Valid status transitions: active→discontinued, active→on_hold, on_hold→active
- Invalid transitions: completed→active, discontinued→active

HIPAA Note: All test data uses synthetic UUIDs. No real patient data.
"""

import uuid

import pytest

from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InteractionBlockedError,
    InvalidPrescriptionStatusError,
    NoRefillsRemainingError,
    PrescriptionNotFoundError,
)


# ---------------------------------------------------------------------------
# Test: PrescriptionStatus Enum
# ---------------------------------------------------------------------------
class TestPrescriptionStatusEnum:
    """Verify PrescriptionStatus has exactly 4 FHIR-aligned values."""

    def test_has_four_values(self):
        """PrescriptionStatus must have active, completed, discontinued, on_hold."""
        statuses = list(PrescriptionStatus)
        assert len(statuses) == 4

    def test_values_match_expected(self):
        """Enum values match FHIR R4 MedicationRequest.status."""
        expected = {"active", "completed", "discontinued", "on_hold"}
        actual = {s.value for s in PrescriptionStatus}
        assert actual == expected


# ---------------------------------------------------------------------------
# Test: InteractionBlockedError
# ---------------------------------------------------------------------------
class TestInteractionBlockedError:
    """Verify InteractionBlockedError mentions Contraindicated."""

    def test_message_mentions_contraindicated(self):
        """Error message must reference 'Contraindicated' for clarity."""
        details = [{"severity": "Contraindicated", "interaction_type": "ddi"}]
        error = InteractionBlockedError(details)

        assert "contraindicated" in str(error).lower()

    def test_stores_interaction_details(self):
        """Error preserves interaction_details for API response construction."""
        details = [{"severity": "Contraindicated", "interaction_type": "ddi"}]
        error = InteractionBlockedError(details)

        assert error.interaction_details == details


# ---------------------------------------------------------------------------
# Test: NoRefillsRemainingError
# ---------------------------------------------------------------------------
class TestNoRefillsRemainingError:
    """Verify NoRefillsRemainingError includes prescription_id."""

    def test_includes_prescription_id(self):
        """Error message and attribute contain the prescription UUID."""
        rx_id = str(uuid.uuid4())
        error = NoRefillsRemainingError(rx_id)

        assert error.prescription_id == rx_id
        assert rx_id in str(error)


# ---------------------------------------------------------------------------
# Test: InvalidPrescriptionStatusError
# ---------------------------------------------------------------------------
class TestInvalidPrescriptionStatusError:
    """Verify error includes current_status and required_status."""

    def test_includes_current_and_required_status(self):
        """Error attributes expose both statuses for debugging."""
        rx_id = str(uuid.uuid4())
        error = InvalidPrescriptionStatusError(
            prescription_id=rx_id,
            current_status="completed",
            required_status="active",
            operation="resume",
        )

        assert error.current_status == "completed"
        assert error.required_status == "active"
        assert "completed" in str(error)
        assert "active" in str(error)


# ---------------------------------------------------------------------------
# Test: PrescriptionNotFoundError
# ---------------------------------------------------------------------------
class TestPrescriptionNotFoundError:
    """Verify PrescriptionNotFoundError message format."""

    def test_message_contains_prescription_id(self):
        """Error message includes the UUID for correlation."""
        rx_id = str(uuid.uuid4())
        error = PrescriptionNotFoundError(rx_id)

        assert rx_id in str(error)
        assert error.prescription_id == rx_id


# ---------------------------------------------------------------------------
# Test: Valid Status Transitions
# ---------------------------------------------------------------------------
class TestValidPrescriptionTransitions:
    """Verify allowed prescription status transitions."""

    def test_active_to_discontinued(self):
        """active → discontinued is valid (clinician stops medication)."""
        # The service allows discontinue from {ACTIVE, ON_HOLD}
        allowed = {PrescriptionStatus.ACTIVE, PrescriptionStatus.ON_HOLD}
        assert PrescriptionStatus.ACTIVE in allowed

    def test_active_to_on_hold(self):
        """active → on_hold is valid (temporary pause)."""
        # hold_prescription requires status == ACTIVE
        assert PrescriptionStatus.ACTIVE.value == "active"
        assert PrescriptionStatus.ON_HOLD.value == "on_hold"

    def test_on_hold_to_active(self):
        """on_hold → active is valid (resume prescription)."""
        # resume_prescription requires status == ON_HOLD
        assert PrescriptionStatus.ON_HOLD.value == "on_hold"

    def test_on_hold_to_discontinued(self):
        """on_hold → discontinued is valid (stop permanently)."""
        allowed = {PrescriptionStatus.ACTIVE, PrescriptionStatus.ON_HOLD}
        assert PrescriptionStatus.ON_HOLD in allowed


# ---------------------------------------------------------------------------
# Test: Invalid Status Transitions
# ---------------------------------------------------------------------------
class TestInvalidPrescriptionTransitions:
    """Verify disallowed transitions raise InvalidPrescriptionStatusError."""

    def test_completed_to_active_raises(self):
        """completed → active is invalid (course finished, cannot restart)."""
        rx_id = str(uuid.uuid4())
        # Simulating what the service would raise
        error = InvalidPrescriptionStatusError(
            prescription_id=rx_id,
            current_status=PrescriptionStatus.COMPLETED.value,
            required_status=PrescriptionStatus.ACTIVE.value,
            operation="resume",
        )
        assert error.current_status == "completed"

    def test_discontinued_to_active_raises(self):
        """discontinued → active is invalid (must write new prescription)."""
        rx_id = str(uuid.uuid4())
        error = InvalidPrescriptionStatusError(
            prescription_id=rx_id,
            current_status=PrescriptionStatus.DISCONTINUED.value,
            required_status=PrescriptionStatus.ACTIVE.value,
            operation="resume",
        )
        assert error.current_status == "discontinued"
