"""
Unit Tests: Lab Order Module — EMR Layer 1.

Tests lab order structures and error handling:
- LabOrderStatus enum has 5 values
- LabPriority enum has 3 values
- Valid status transitions: ordered→specimen_collected→in_progress→resulted
- ordered→cancelled is valid
- resulted→anything is invalid (terminal state)
- LabOrderNotFoundError message format
- LabOrderAlreadyResultedError message format
- LOINC-to-measurement mapping returns correct types for known codes
- LOINC-to-measurement returns None for unknown codes

HIPAA Note: All test data uses synthetic UUIDs. No real patient data.
"""

import uuid

import pytest

from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
from app.modules.lab_orders.exceptions import (
    InvalidLabOrderStatusTransitionError,
    LabOrderAlreadyResultedError,
    LabOrderNotFoundError,
)
from app.modules.lab_orders.loinc_to_measurement import map_loinc_to_measurement
from app.modules.lab_orders.service import _VALID_TRANSITIONS
from app.modules.measurements.models import MeasurementType


# ---------------------------------------------------------------------------
# Test: LabOrderStatus Enum
# ---------------------------------------------------------------------------
class TestLabOrderStatusEnum:
    """Verify LabOrderStatus has exactly 5 lifecycle states."""

    def test_has_five_values(self):
        """LabOrderStatus: ordered, specimen_collected, in_progress, resulted, cancelled."""
        assert len(list(LabOrderStatus)) == 5

    def test_values_match_expected(self):
        """Enum values match FHIR R4 ServiceRequest.status."""
        expected = {"ordered", "specimen_collected", "in_progress", "resulted", "cancelled"}
        actual = {s.value for s in LabOrderStatus}
        assert actual == expected


# ---------------------------------------------------------------------------
# Test: LabPriority Enum
# ---------------------------------------------------------------------------
class TestLabPriorityEnum:
    """Verify LabPriority has exactly 3 urgency levels."""

    def test_has_three_values(self):
        """LabPriority: routine, urgent, stat."""
        assert len(list(LabPriority)) == 3

    def test_values_match_expected(self):
        """Enum values match FHIR R4 ServiceRequest.priority."""
        expected = {"routine", "urgent", "stat"}
        actual = {p.value for p in LabPriority}
        assert actual == expected


# ---------------------------------------------------------------------------
# Test: Valid Status Transitions
# ---------------------------------------------------------------------------
class TestValidLabOrderTransitions:
    """Verify allowed transitions in the lab order state machine."""

    def test_ordered_to_specimen_collected(self):
        """ordered → specimen_collected is valid (specimen obtained)."""
        allowed = _VALID_TRANSITIONS[LabOrderStatus.ORDERED.value]
        assert LabOrderStatus.SPECIMEN_COLLECTED.value in allowed

    def test_specimen_collected_to_in_progress(self):
        """specimen_collected → in_progress is valid (lab processing)."""
        allowed = _VALID_TRANSITIONS[LabOrderStatus.SPECIMEN_COLLECTED.value]
        assert LabOrderStatus.IN_PROGRESS.value in allowed

    def test_in_progress_to_resulted(self):
        """in_progress → resulted is valid (results available)."""
        allowed = _VALID_TRANSITIONS[LabOrderStatus.IN_PROGRESS.value]
        assert LabOrderStatus.RESULTED.value in allowed

    def test_ordered_to_cancelled(self):
        """ordered → cancelled is valid (order withdrawn)."""
        allowed = _VALID_TRANSITIONS[LabOrderStatus.ORDERED.value]
        assert LabOrderStatus.CANCELLED.value in allowed


# ---------------------------------------------------------------------------
# Test: Invalid Transitions — Resulted is Terminal
# ---------------------------------------------------------------------------
class TestResultedIsTerminal:
    """Verify resulted is a terminal state with no outgoing transitions."""

    def test_resulted_to_anything_is_invalid(self):
        """resulted → any status is blocked (terminal state)."""
        allowed = _VALID_TRANSITIONS[LabOrderStatus.RESULTED.value]
        assert allowed == set(), (
            f"Resulted should be terminal but allows: {allowed}"
        )


# ---------------------------------------------------------------------------
# Test: LabOrderNotFoundError Message Format
# ---------------------------------------------------------------------------
class TestLabOrderNotFoundError:
    """Verify error message includes order_id UUID."""

    def test_message_contains_order_id(self):
        """Error message includes the UUID for debugging."""
        order_id = uuid.uuid4()
        error = LabOrderNotFoundError(order_id)

        assert str(order_id) in str(error)
        assert error.order_id == order_id


# ---------------------------------------------------------------------------
# Test: LabOrderAlreadyResultedError Message Format
# ---------------------------------------------------------------------------
class TestLabOrderAlreadyResultedError:
    """Verify error message indicates order was already resulted."""

    def test_message_contains_order_id_and_resulted(self):
        """Error message includes UUID and 'already' + 'resulted'."""
        order_id = uuid.uuid4()
        error = LabOrderAlreadyResultedError(order_id)

        assert str(order_id) in str(error)
        assert "already" in str(error).lower()
        assert "resulted" in str(error).lower()


# ---------------------------------------------------------------------------
# Test: LOINC-to-Measurement Mapping — Known Codes
# ---------------------------------------------------------------------------
class TestLoincMappingKnownCodes:
    """Verify known LOINC codes return correct MeasurementType."""

    def test_glucose_fasting(self):
        """LOINC 2345-7 maps to BLOOD_GLUCOSE_FASTING."""
        assert map_loinc_to_measurement("2345-7") == MeasurementType.BLOOD_GLUCOSE_FASTING

    def test_hba1c(self):
        """LOINC 4548-4 maps to HBA1C."""
        assert map_loinc_to_measurement("4548-4") == MeasurementType.HBA1C

    def test_total_cholesterol(self):
        """LOINC 2093-3 maps to TOTAL_CHOLESTEROL."""
        assert map_loinc_to_measurement("2093-3") == MeasurementType.TOTAL_CHOLESTEROL

    def test_creatinine(self):
        """LOINC 2160-0 maps to CREATININE."""
        assert map_loinc_to_measurement("2160-0") == MeasurementType.CREATININE


# ---------------------------------------------------------------------------
# Test: LOINC-to-Measurement Mapping — Unknown Codes
# ---------------------------------------------------------------------------
class TestLoincMappingUnknownCodes:
    """Verify unknown LOINC codes return None."""

    def test_unknown_code_returns_none(self):
        """Unmapped LOINC codes return None (not risk-relevant)."""
        assert map_loinc_to_measurement("99999-9") is None

    def test_empty_string_returns_none(self):
        """Empty string returns None gracefully."""
        assert map_loinc_to_measurement("") is None
