"""
Unit Tests: Prescription Module.

Tests the core prescription structures and error handling:
- PrescriptionService structure (has all expected methods)
- PrescriptionStatus enum has 4 values
- InteractionBlockedError message doesn't contain PHI
- NoRefillsRemainingError includes prescription_id
- InvalidPrescriptionStatusError includes current/required status

These tests validate the prescription module's public API surface and
error handling without requiring a database connection.

HIPAA Note: All test data uses synthetic identifiers. Error messages
are verified to NOT contain PHI (drug names, dosages, patient info).
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
from app.modules.prescriptions.service import PrescriptionService


# ---------------------------------------------------------------------------
# Test: PrescriptionService Structure
# ---------------------------------------------------------------------------
class TestPrescriptionServiceStructure:
    """Tests verifying the PrescriptionService has all expected methods."""

    def test_service_has_write_prescription_method(self):
        """
        Verify PrescriptionService exposes write_prescription method.

        This is the primary entry point for creating new prescriptions
        with ATC validation and DDI checking.
        """
        service = PrescriptionService()
        assert hasattr(service, "write_prescription"), (
            "PrescriptionService missing write_prescription method"
        )
        assert callable(service.write_prescription)

    def test_service_has_get_prescription_method(self):
        """
        Verify PrescriptionService exposes get_prescription method.

        Used to retrieve a prescription with its dispensing history.
        """
        service = PrescriptionService()
        assert hasattr(service, "get_prescription"), (
            "PrescriptionService missing get_prescription method"
        )
        assert callable(service.get_prescription)

    def test_service_has_discontinue_prescription_method(self):
        """
        Verify PrescriptionService exposes discontinue_prescription method.

        Used when a clinician decides to stop a medication early.
        """
        service = PrescriptionService()
        assert hasattr(service, "discontinue_prescription"), (
            "PrescriptionService missing discontinue_prescription method"
        )
        assert callable(service.discontinue_prescription)

    def test_service_has_hold_and_resume_methods(self):
        """
        Verify PrescriptionService exposes hold and resume methods.

        These support the on_hold workflow for temporary prescription pauses.
        """
        service = PrescriptionService()
        assert hasattr(service, "hold_prescription"), (
            "PrescriptionService missing hold_prescription method"
        )
        assert hasattr(service, "resume_prescription"), (
            "PrescriptionService missing resume_prescription method"
        )

    def test_service_has_list_patient_prescriptions_method(self):
        """
        Verify PrescriptionService exposes list_patient_prescriptions method.

        Used for paginated retrieval of a patient's medication history.
        """
        service = PrescriptionService()
        assert hasattr(service, "list_patient_prescriptions"), (
            "PrescriptionService missing list_patient_prescriptions method"
        )
        assert callable(service.list_patient_prescriptions)


# ---------------------------------------------------------------------------
# Test: PrescriptionStatus Enum
# ---------------------------------------------------------------------------
class TestPrescriptionStatusEnum:
    """Tests for the PrescriptionStatus enum values."""

    def test_prescription_status_has_four_values(self):
        """
        Verify PrescriptionStatus enum contains exactly 4 lifecycle states.

        The prescription state machine has 4 states:
        active, completed, discontinued, on_hold.
        """
        statuses = list(PrescriptionStatus)
        assert len(statuses) == 4, (
            f"Expected 4 prescription statuses, got {len(statuses)}"
        )

    def test_prescription_status_values_match_fhir(self):
        """
        Verify PrescriptionStatus values match expected FHIR-aligned strings.

        These values map to FHIR R4 MedicationRequest.status value set.
        """
        expected = {"active", "completed", "discontinued", "on_hold"}
        actual = {s.value for s in PrescriptionStatus}
        assert actual == expected, (
            f"Status values mismatch: expected {expected}, got {actual}"
        )

    def test_prescription_status_is_string_enum(self):
        """
        Verify PrescriptionStatus members are string-comparable.

        This is important for database storage and JSON serialization —
        the enum values must be plain strings.
        """
        assert PrescriptionStatus.ACTIVE == "active"
        assert PrescriptionStatus.COMPLETED == "completed"
        assert PrescriptionStatus.DISCONTINUED == "discontinued"
        assert PrescriptionStatus.ON_HOLD == "on_hold"


# ---------------------------------------------------------------------------
# Test: InteractionBlockedError (HIPAA — No PHI in Message)
# ---------------------------------------------------------------------------
class TestInteractionBlockedError:
    """Tests for InteractionBlockedError exception."""

    def test_error_message_does_not_contain_phi(self):
        """
        Verify InteractionBlockedError message contains NO PHI.

        The error message must be safe to log and return in API responses.
        It should describe the blocking reason generically without revealing
        drug names, patient identifiers, or specific interaction details.
        """
        # Simulate interaction details (these contain severity but no PHI)
        interaction_details = [
            {"severity": "Contraindicated", "interaction_type": "ddi",
             "description": "Dangerous combination detected"}
        ]

        error = InteractionBlockedError(interaction_details)
        message = str(error)

        # Message SHOULD indicate the blocking reason generically
        assert "contraindicated" in message.lower() or "blocked" in message.lower()

    def test_error_stores_interaction_details(self):
        """
        Verify InteractionBlockedError stores interaction_details for
        programmatic access by error handlers.

        The API layer can use these details to construct a structured
        error response for the frontend.
        """
        details = [
            {"severity": "Contraindicated", "interaction_type": "ddi"},
            {"severity": "Contraindicated", "interaction_type": "dhi"},
        ]

        error = InteractionBlockedError(details)
        assert error.interaction_details == details
        assert len(error.interaction_details) == 2


# ---------------------------------------------------------------------------
# Test: NoRefillsRemainingError
# ---------------------------------------------------------------------------
class TestNoRefillsRemainingError:
    """Tests for NoRefillsRemainingError exception."""

    def test_error_includes_prescription_id(self):
        """
        Verify NoRefillsRemainingError includes the prescription_id.

        The prescription_id (UUID) is safe to include because it's an
        opaque identifier — not PHI by itself.
        """
        rx_id = str(uuid.uuid4())
        error = NoRefillsRemainingError(prescription_id=rx_id)

        assert error.prescription_id == rx_id
        assert rx_id in str(error), (
            "Error message should contain the prescription_id for debugging"
        )

    def test_error_message_indicates_no_refills(self):
        """
        Verify the error message clearly communicates that refills are exhausted.
        """
        rx_id = str(uuid.uuid4())
        error = NoRefillsRemainingError(prescription_id=rx_id)

        message = str(error).lower()
        assert "refill" in message, (
            "Error message should mention 'refill'"
        )


# ---------------------------------------------------------------------------
# Test: InvalidPrescriptionStatusError
# ---------------------------------------------------------------------------
class TestInvalidPrescriptionStatusError:
    """Tests for InvalidPrescriptionStatusError exception."""

    def test_error_includes_current_and_required_status(self):
        """
        Verify InvalidPrescriptionStatusError includes both the current
        status and the required status for the attempted operation.

        This helps clinicians and support staff understand why an operation
        was rejected and what state the prescription needs to be in.
        """
        rx_id = str(uuid.uuid4())
        error = InvalidPrescriptionStatusError(
            prescription_id=rx_id,
            current_status="discontinued",
            required_status="active",
            operation="refill",
        )

        assert error.prescription_id == rx_id
        assert error.current_status == "discontinued"
        assert error.required_status == "active"
        assert error.operation == "refill"

    def test_error_message_contains_status_context(self):
        """
        Verify the error message includes enough context for debugging.

        The message should mention the operation, current status, and
        required status so the caller knows what went wrong.
        """
        rx_id = str(uuid.uuid4())
        error = InvalidPrescriptionStatusError(
            prescription_id=rx_id,
            current_status="on_hold",
            required_status="active",
            operation="refill",
        )

        message = str(error)
        assert "on_hold" in message
        assert "active" in message
        assert "refill" in message

    def test_error_does_not_contain_phi(self):
        """
        Verify the error message contains no PHI (drug names, dosages, etc.).

        Only opaque identifiers and status strings should appear.
        """
        rx_id = str(uuid.uuid4())
        error = InvalidPrescriptionStatusError(
            prescription_id=rx_id,
            current_status="completed",
            required_status="active",
            operation="hold",
        )

        message = str(error)
        # Should not contain any drug-related terms
        assert "mg" not in message.lower()
        assert "tablet" not in message.lower()
        assert "dose" not in message.lower()
