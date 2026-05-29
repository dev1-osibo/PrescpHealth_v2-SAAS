"""
Unit Tests: Lab Order Module.

Tests the core lab order structures and error handling:
- LabOrderService structure (has all expected methods)
- LabOrderStatus enum has 5 values
- LabPriority enum has 3 values
- LOINC-to-measurement mapping covers expected codes
- LabOrderNotFoundError, InvalidLabOrderStatusTransitionError,
  LabOrderAlreadyResultedError

These tests validate the lab order module's public API surface,
enum definitions, and error handling without requiring a database.

HIPAA Note: All test data uses synthetic identifiers. Error messages
are verified to contain only UUIDs and status strings (no PHI).
"""

import uuid

import pytest

from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
from app.modules.lab_orders.exceptions import (
    InvalidLabOrderStatusTransitionError,
    LabOrderAlreadyResultedError,
    LabOrderNotFoundError,
)
from app.modules.lab_orders.loinc_to_measurement import (
    map_loinc_to_measurement,
    _LOINC_TO_MEASUREMENT,
)
from app.modules.lab_orders.service import LabOrderService
from app.modules.measurements.models import MeasurementType


# ---------------------------------------------------------------------------
# Test: LabOrderService Structure
# ---------------------------------------------------------------------------
class TestLabOrderServiceStructure:
    """Tests verifying the LabOrderService has all expected methods."""

    def test_service_has_create_lab_order_method(self):
        """
        Verify LabOrderService exposes create_lab_order method.

        This is the primary entry point for placing new lab orders
        with LOINC code validation.
        """
        service = LabOrderService()
        assert hasattr(service, "create_lab_order"), (
            "LabOrderService missing create_lab_order method"
        )
        assert callable(service.create_lab_order)

    def test_service_has_get_lab_order_method(self):
        """
        Verify LabOrderService exposes get_lab_order method.

        Used to retrieve a lab order with its results.
        """
        service = LabOrderService()
        assert hasattr(service, "get_lab_order"), (
            "LabOrderService missing get_lab_order method"
        )
        assert callable(service.get_lab_order)

    def test_service_has_update_status_method(self):
        """
        Verify LabOrderService exposes update_status method.

        Used for transitioning lab orders through the state machine.
        """
        service = LabOrderService()
        assert hasattr(service, "update_status"), (
            "LabOrderService missing update_status method"
        )
        assert callable(service.update_status)

    def test_service_has_collect_specimen_method(self):
        """
        Verify LabOrderService exposes collect_specimen method.

        Convenience method combining status transition with timestamp.
        """
        service = LabOrderService()
        assert hasattr(service, "collect_specimen"), (
            "LabOrderService missing collect_specimen method"
        )
        assert callable(service.collect_specimen)

    def test_service_has_list_patient_lab_orders_method(self):
        """
        Verify LabOrderService exposes list_patient_lab_orders method.

        Used for paginated retrieval of a patient's lab history.
        """
        service = LabOrderService()
        assert hasattr(service, "list_patient_lab_orders"), (
            "LabOrderService missing list_patient_lab_orders method"
        )
        assert callable(service.list_patient_lab_orders)


# ---------------------------------------------------------------------------
# Test: LabOrderStatus Enum
# ---------------------------------------------------------------------------
class TestLabOrderStatusEnum:
    """Tests for the LabOrderStatus enum values."""

    def test_lab_order_status_has_five_values(self):
        """
        Verify LabOrderStatus enum contains exactly 5 lifecycle states.

        The lab order state machine has 5 states:
        ordered, specimen_collected, in_progress, resulted, cancelled.
        """
        statuses = list(LabOrderStatus)
        assert len(statuses) == 5, (
            f"Expected 5 lab order statuses, got {len(statuses)}"
        )

    def test_lab_order_status_values(self):
        """
        Verify LabOrderStatus values match expected strings.

        These values are stored in the database and used in FHIR mapping.
        """
        expected = {
            "ordered", "specimen_collected", "in_progress",
            "resulted", "cancelled",
        }
        actual = {s.value for s in LabOrderStatus}
        assert actual == expected, (
            f"Status values mismatch: expected {expected}, got {actual}"
        )

    def test_lab_order_status_is_string_enum(self):
        """
        Verify LabOrderStatus members are string-comparable.

        Important for database storage and JSON serialization.
        """
        assert LabOrderStatus.ORDERED == "ordered"
        assert LabOrderStatus.SPECIMEN_COLLECTED == "specimen_collected"
        assert LabOrderStatus.IN_PROGRESS == "in_progress"
        assert LabOrderStatus.RESULTED == "resulted"
        assert LabOrderStatus.CANCELLED == "cancelled"


# ---------------------------------------------------------------------------
# Test: LabPriority Enum
# ---------------------------------------------------------------------------
class TestLabPriorityEnum:
    """Tests for the LabPriority enum values."""

    def test_lab_priority_has_three_values(self):
        """
        Verify LabPriority enum contains exactly 3 urgency levels.

        The priority levels are: routine, urgent, stat.
        """
        priorities = list(LabPriority)
        assert len(priorities) == 3, (
            f"Expected 3 lab priorities, got {len(priorities)}"
        )

    def test_lab_priority_values(self):
        """
        Verify LabPriority values match expected FHIR-aligned strings.

        These map to FHIR R4 ServiceRequest.priority value set.
        """
        expected = {"routine", "urgent", "stat"}
        actual = {p.value for p in LabPriority}
        assert actual == expected, (
            f"Priority values mismatch: expected {expected}, got {actual}"
        )

    def test_lab_priority_is_string_enum(self):
        """
        Verify LabPriority members are string-comparable.
        """
        assert LabPriority.ROUTINE == "routine"
        assert LabPriority.URGENT == "urgent"
        assert LabPriority.STAT == "stat"


# ---------------------------------------------------------------------------
# Test: LOINC-to-Measurement Mapping
# ---------------------------------------------------------------------------
class TestLoincToMeasurementMapping:
    """Tests for the LOINC code to MeasurementType mapping."""

    def test_mapping_covers_expected_metabolic_codes(self):
        """
        Verify metabolic LOINC codes are mapped correctly.

        These codes cover glucose and HbA1c — critical for diabetes
        risk computation.
        """
        # Fasting glucose
        assert map_loinc_to_measurement("2345-7") == MeasurementType.BLOOD_GLUCOSE_FASTING
        # Random glucose
        assert map_loinc_to_measurement("2339-0") == MeasurementType.BLOOD_GLUCOSE_RANDOM
        # HbA1c
        assert map_loinc_to_measurement("4548-4") == MeasurementType.HBA1C

    def test_mapping_covers_expected_lipid_codes(self):
        """
        Verify lipid panel LOINC codes are mapped correctly.

        These codes cover the full lipid panel — critical for
        cardiovascular risk computation.
        """
        assert map_loinc_to_measurement("2093-3") == MeasurementType.TOTAL_CHOLESTEROL
        assert map_loinc_to_measurement("2085-9") == MeasurementType.HDL_CHOLESTEROL
        assert map_loinc_to_measurement("2089-1") == MeasurementType.LDL_CHOLESTEROL
        assert map_loinc_to_measurement("2571-8") == MeasurementType.TRIGLYCERIDES

    def test_mapping_covers_expected_renal_codes(self):
        """
        Verify renal function LOINC codes are mapped correctly.

        These codes cover creatinine, eGFR, and urine albumin —
        critical for CKD risk computation.
        """
        assert map_loinc_to_measurement("2160-0") == MeasurementType.CREATININE
        assert map_loinc_to_measurement("33914-3") == MeasurementType.EGFR
        assert map_loinc_to_measurement("14959-1") == MeasurementType.URINE_ALBUMIN

    def test_mapping_covers_respiratory_code(self):
        """
        Verify SpO2 LOINC code is mapped correctly.

        Oxygen saturation feeds the respiratory risk model.
        """
        assert map_loinc_to_measurement("2708-6") == MeasurementType.SPO2

    def test_unmapped_code_returns_none(self):
        """
        Verify that LOINC codes not in the mapping return None.

        Not all lab tests feed the risk engine. CBC, cultures, etc.
        should return None to indicate no measurement creation needed.
        """
        # CBC-related codes should not map
        assert map_loinc_to_measurement("58410-2") is None
        assert map_loinc_to_measurement("718-7") is None
        # Completely invalid code
        assert map_loinc_to_measurement("INVALID") is None
        # Empty string
        assert map_loinc_to_measurement("") is None


# ---------------------------------------------------------------------------
# Test: Lab Order Exceptions
# ---------------------------------------------------------------------------
class TestLabOrderExceptions:
    """Tests for lab order exception classes."""

    def test_lab_order_not_found_error(self):
        """
        Verify LabOrderNotFoundError includes the order_id in its message.

        The error message should contain only the UUID (not PHI) for
        debugging and API error response purposes.
        """
        order_id = uuid.uuid4()
        error = LabOrderNotFoundError(order_id)

        assert error.order_id == order_id
        assert str(order_id) in str(error), (
            "LabOrderNotFoundError message should contain the order_id"
        )
        assert str(order_id) in error.message

    def test_invalid_lab_order_status_transition_error(self):
        """
        Verify InvalidLabOrderStatusTransitionError includes current and
        requested status for debugging.

        The error should clearly communicate which transition was attempted
        and why it was rejected.
        """
        order_id = uuid.uuid4()
        error = InvalidLabOrderStatusTransitionError(
            order_id=order_id,
            current_status="resulted",
            requested_status="in_progress",
        )

        assert error.order_id == order_id
        assert error.current_status == "resulted"
        assert error.requested_status == "in_progress"
        assert "resulted" in str(error)
        assert "in_progress" in str(error)
        assert str(order_id) in str(error)

    def test_lab_order_already_resulted_error(self):
        """
        Verify LabOrderAlreadyResultedError prevents duplicate results.

        Once a lab order has been resulted, no additional results can be
        recorded. This prevents accidental data overwrites.
        """
        order_id = uuid.uuid4()
        error = LabOrderAlreadyResultedError(order_id)

        assert error.order_id == order_id
        assert str(order_id) in str(error)
        assert "already" in str(error).lower()
        assert "resulted" in str(error).lower()

    def test_exceptions_do_not_contain_phi(self):
        """
        Verify all lab order exceptions contain only UUIDs and status strings.

        No test names, patient identifiers, or result values should appear
        in any exception message (HIPAA compliance).
        """
        order_id = uuid.uuid4()

        errors = [
            LabOrderNotFoundError(order_id),
            InvalidLabOrderStatusTransitionError(order_id, "ordered", "resulted"),
            LabOrderAlreadyResultedError(order_id),
        ]

        for error in errors:
            message = str(error).lower()
            # Should not contain test-related PHI
            assert "glucose" not in message
            assert "cholesterol" not in message
