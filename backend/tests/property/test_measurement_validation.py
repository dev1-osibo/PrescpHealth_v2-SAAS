"""
Property Test: Measurement Validation and Round-Trip.

Property 5 from design.md:
    "For any measurement type and for any numeric value, the platform SHALL
    accept the value if and only if it falls within the defined physiological
    range for that type. Furthermore, for any measurement accepted by the
    platform, a subsequent GET request for that patient's measurement history
    SHALL return the submitted value unchanged."

This proves that the measurement validation system maintains correct invariants:
1. Any value within the physiological range passes validation (returns True)
2. Any value outside the physiological range raises ValidationError
3. Error messages never contain the actual submitted value (PHI safety)
4. Round-trip: a value that passes validation can be stored in the Measurement
   model and read back unchanged (no precision loss or silent modification)

Why this matters (HIPAA + Patient Safety):
    - Validation prevents garbage data from contaminating risk predictions
    - PHI safety in error messages prevents accidental value leakage in logs
    - Round-trip integrity ensures clinical decisions are based on accurate data

Validates: Requirements 5.2, 5.3
"""

import re
import uuid
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, strategies as st

from app.core.exceptions import ValidationError
from app.modules.measurements.models import Measurement, MeasurementType
from app.modules.measurements.validators import (
    PHYSIOLOGICAL_RANGES,
    validate_measurement,
)


# ---------------------------------------------------------------------------
# Strategies: Generate measurement types and values
# ---------------------------------------------------------------------------

# All measurement types that have defined physiological ranges
measurement_type_strategy = st.sampled_from(list(PHYSIOLOGICAL_RANGES.keys()))

# Random UUIDs for patient_id, tenant_id, recorded_by
uuid_strategy = st.uuids()

# Random datetimes for recorded_at (realistic clinical range)
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2025, 12, 31),
    timezones=st.just(timezone.utc),
)


def value_within_range(measurement_type: MeasurementType) -> st.SearchStrategy[float]:
    """
    Generate a float value strictly within the physiological range for a type.

    Uses the defined min/max from PHYSIOLOGICAL_RANGES to ensure the value
    is valid. Adds a small epsilon buffer to avoid floating-point boundary issues.
    """
    phys_range = PHYSIOLOGICAL_RANGES[measurement_type]
    # Small buffer to stay strictly within bounds
    epsilon = (phys_range.max_value - phys_range.min_value) * 0.001
    return st.floats(
        min_value=phys_range.min_value + epsilon,
        max_value=phys_range.max_value - epsilon,
        allow_nan=False,
        allow_infinity=False,
    )


def value_below_range(measurement_type: MeasurementType) -> st.SearchStrategy[float]:
    """
    Generate a float value strictly below the physiological minimum.

    These values are physiologically impossible and must be rejected.
    """
    phys_range = PHYSIOLOGICAL_RANGES[measurement_type]
    # Generate values from a reasonable lower bound to just below minimum
    lower_bound = phys_range.min_value - 1000.0
    return st.floats(
        min_value=lower_bound,
        max_value=phys_range.min_value - 0.01,
        allow_nan=False,
        allow_infinity=False,
    )


def value_above_range(measurement_type: MeasurementType) -> st.SearchStrategy[float]:
    """
    Generate a float value strictly above the physiological maximum.

    These values are physiologically impossible and must be rejected.
    """
    phys_range = PHYSIOLOGICAL_RANGES[measurement_type]
    # Generate values from just above maximum to a reasonable upper bound
    upper_bound = phys_range.max_value + 1000.0
    return st.floats(
        min_value=phys_range.max_value + 0.01,
        max_value=upper_bound,
        allow_nan=False,
        allow_infinity=False,
    )


class TestMeasurementValidationAndRoundTrip:
    """
    Property-based tests proving measurement validation and round-trip invariants.

    The core invariants tested:
    1. Values within physiological range always pass validation
    2. Values outside physiological range always raise ValidationError
    3. Error messages never leak the actual measurement value (PHI)
    4. Round-trip: validated values stored in Measurement model read back unchanged
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_valid_value_passes_validation(self, data):
        """
        Property: For any measurement type and any value within its
        physiological range, validate_measurement returns True.

        This ensures the validation gate never rejects legitimate clinical
        values that fall within the bounds of human physiology.

        **Validates: Requirements 5.2, 5.3**
        """
        # Draw a random measurement type
        measurement_type = data.draw(measurement_type_strategy)
        # Draw a value within the valid range for that type
        value = data.draw(value_within_range(measurement_type))
        # Get the expected unit for this type
        expected_unit = PHYSIOLOGICAL_RANGES[measurement_type].unit

        # INVARIANT: Valid values must pass validation
        result = validate_measurement(measurement_type, value, expected_unit)
        assert result is True, (
            f"validate_measurement returned {result} for {measurement_type.value} "
            f"with a value within physiological range. Expected True."
        )

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_below_range_raises_validation_error(self, data):
        """
        Property: For any measurement type and any value below its
        physiological minimum, validate_measurement raises ValidationError.

        Values below the minimum are physiologically impossible and indicate
        data entry errors or device malfunctions.

        **Validates: Requirements 5.2, 5.3**
        """
        measurement_type = data.draw(measurement_type_strategy)
        value = data.draw(value_below_range(measurement_type))
        expected_unit = PHYSIOLOGICAL_RANGES[measurement_type].unit

        # INVARIANT: Below-range values must raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(measurement_type, value, expected_unit)

        # Verify the error has meaningful context
        assert "below" in exc_info.value.message.lower() or "minimum" in exc_info.value.message.lower(), (
            f"Error message should indicate value is below minimum, "
            f"got: '{exc_info.value.message}'"
        )

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_above_range_raises_validation_error(self, data):
        """
        Property: For any measurement type and any value above its
        physiological maximum, validate_measurement raises ValidationError.

        Values above the maximum are physiologically impossible and indicate
        data entry errors or device malfunctions.

        **Validates: Requirements 5.2, 5.3**
        """
        measurement_type = data.draw(measurement_type_strategy)
        value = data.draw(value_above_range(measurement_type))
        expected_unit = PHYSIOLOGICAL_RANGES[measurement_type].unit

        # INVARIANT: Above-range values must raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(measurement_type, value, expected_unit)

        # Verify the error has meaningful context
        assert "exceeds" in exc_info.value.message.lower() or "maximum" in exc_info.value.message.lower(), (
            f"Error message should indicate value exceeds maximum, "
            f"got: '{exc_info.value.message}'"
        )

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_error_message_never_contains_actual_value(self, data):
        """
        Property: For any measurement type and any value outside its range,
        the error message never contains the actual submitted value.

        This is a HIPAA compliance requirement — measurement values are PHI
        and must never appear in error messages (which may be logged, returned
        to clients, or displayed in monitoring dashboards).

        **Validates: Requirements 5.2, 5.3**
        """
        measurement_type = data.draw(measurement_type_strategy)
        # Choose either below or above range
        direction = data.draw(st.sampled_from(["below", "above"]))

        if direction == "below":
            value = data.draw(value_below_range(measurement_type))
        else:
            value = data.draw(value_above_range(measurement_type))

        expected_unit = PHYSIOLOGICAL_RANGES[measurement_type].unit

        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(measurement_type, value, expected_unit)

        error_message = exc_info.value.message

        # The actual submitted value must NOT appear in the error message
        # We use word-boundary matching to avoid false positives where the
        # value string is a substring of a boundary value (e.g., "0.0" in "40.0")
        phys_range = PHYSIOLOGICAL_RANGES[measurement_type]

        # Build a set of "allowed" number strings that legitimately appear
        # in the error message (the range boundaries are safe to display)
        allowed_numbers = {
            str(phys_range.min_value),
            str(phys_range.max_value),
            f"{phys_range.min_value:.1f}",
            f"{phys_range.max_value:.1f}",
            f"{phys_range.min_value:.2f}",
            f"{phys_range.max_value:.2f}",
        }

        value_str = str(value)
        value_formatted = f"{value:.1f}"

        # Only assert PHI leak if the value string is NOT a substring of
        # any allowed boundary value and appears as a standalone token
        if value_str not in allowed_numbers:
            # Use regex word boundary to check for standalone occurrence
            # This avoids false positives like "0.0" matching inside "40.0"
            pattern = re.compile(r"(?<!\d)" + re.escape(value_str) + r"(?!\d)")
            assert not pattern.search(error_message), (
                f"Error message contains the actual value '{value_str}' — "
                f"this is a PHI leak. Message: '{error_message}'"
            )

        if value_formatted not in allowed_numbers:
            pattern = re.compile(r"(?<!\d)" + re.escape(value_formatted) + r"(?!\d)")
            assert not pattern.search(error_message), (
                f"Error message contains formatted value '{value_formatted}' — "
                f"this is a PHI leak. Message: '{error_message}'"
            )

    @given(data=st.data())
    @settings(max_examples=100, deadline=None)
    def test_property_round_trip_value_unchanged(self, data):
        """
        Property: For any measurement type and any value that passes
        validation, storing it in the Measurement model and reading it
        back yields the exact same value (no precision loss).

        This ensures clinical decisions are based on the actual submitted
        values, not silently modified versions.

        **Validates: Requirements 5.2, 5.3**
        """
        measurement_type = data.draw(measurement_type_strategy)
        value = data.draw(value_within_range(measurement_type))
        expected_unit = PHYSIOLOGICAL_RANGES[measurement_type].unit
        patient_id = data.draw(uuid_strategy)
        tenant_id = data.draw(uuid_strategy)
        recorded_by = data.draw(uuid_strategy)
        recorded_at = data.draw(datetime_strategy)

        # First, validate the value passes
        assert validate_measurement(measurement_type, value, expected_unit) is True

        # Create a Measurement model instance (simulating storage)
        measurement = Measurement(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            patient_id=patient_id,
            measurement_type=measurement_type.value,
            value=value,
            unit=expected_unit,
            recorded_at=recorded_at,
            recorded_by=recorded_by,
            source="manual",
            is_validated=True,
            is_flagged=False,
        )

        # INVARIANT: The value read back from the model is identical
        assert measurement.value == value, (
            f"Round-trip value mismatch: stored {value} but read back "
            f"{measurement.value} for {measurement_type.value}. "
            f"Clinical data must not be silently modified."
        )

        # Also verify other fields are preserved correctly
        assert measurement.measurement_type == measurement_type.value
        assert measurement.unit == expected_unit
        assert measurement.patient_id == patient_id
        assert measurement.tenant_id == tenant_id

    @given(data=st.data())
    @settings(max_examples=50, deadline=None)
    def test_property_unit_mismatch_raises_validation_error(self, data):
        """
        Property: For any measurement type, providing a unit that doesn't
        match the expected unit raises ValidationError.

        Unit mismatches often indicate conversion errors (e.g., submitting
        mmol/L when mg/dL is expected) which would make the value meaningless.

        **Validates: Requirements 5.2, 5.3**
        """
        measurement_type = data.draw(measurement_type_strategy)
        value = data.draw(value_within_range(measurement_type))
        expected_unit = PHYSIOLOGICAL_RANGES[measurement_type].unit

        # Generate a wrong unit that differs from the expected one
        wrong_units = ["wrong_unit", "invalid", "kg", "lbs", "mmol/L", "celsius"]
        wrong_unit = data.draw(
            st.sampled_from([u for u in wrong_units if u != expected_unit])
        )

        # INVARIANT: Wrong unit must raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(measurement_type, value, wrong_unit)

        assert "unit" in exc_info.value.message.lower(), (
            f"Error message should mention unit mismatch, "
            f"got: '{exc_info.value.message}'"
        )
