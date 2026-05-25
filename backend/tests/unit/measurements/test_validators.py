"""
Unit tests for measurement physiological range validators.

Tests the validate_measurement() and check_deviation() functions that
form the safety gate for incoming clinical measurement data.

Validates:
- Each measurement type accepts values within its physiological range
- Out-of-range values are rejected with descriptive errors (no PHI)
- Unit mismatches are caught and reported
- Deviation detection correctly flags >2σ deviations
- Edge cases (zero std, boundary values) are handled safely
"""

import pytest

from app.core.exceptions import ValidationError
from app.modules.measurements.models import MeasurementType
from app.modules.measurements.validators import (
    PHYSIOLOGICAL_RANGES,
    check_deviation,
    validate_measurement,
)


# ---------------------------------------------------------------------------
# Test: All measurement types have defined ranges
# ---------------------------------------------------------------------------
class TestPhysiologicalRangeCompleteness:
    """Verify that every MeasurementType has a corresponding range definition."""

    def test_all_measurement_types_have_ranges(self):
        """Every MeasurementType enum member must have a physiological range defined."""
        for measurement_type in MeasurementType:
            assert measurement_type in PHYSIOLOGICAL_RANGES, (
                f"MeasurementType.{measurement_type.name} has no physiological range defined"
            )

    def test_all_ranges_have_valid_bounds(self):
        """Every range must have min < max and a non-empty unit."""
        for measurement_type, range_def in PHYSIOLOGICAL_RANGES.items():
            assert range_def.min_value < range_def.max_value, (
                f"{measurement_type.value}: min ({range_def.min_value}) >= max ({range_def.max_value})"
            )
            assert range_def.unit, f"{measurement_type.value}: unit is empty"
            assert range_def.description, f"{measurement_type.value}: description is empty"


# ---------------------------------------------------------------------------
# Test: validate_measurement — happy path
# ---------------------------------------------------------------------------
class TestValidateMeasurementAccepts:
    """Test that valid measurements within physiological range are accepted."""

    def test_systolic_bp_normal(self):
        """Normal systolic BP (120 mmHg) should be accepted."""
        assert validate_measurement(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg") is True

    def test_systolic_bp_at_minimum(self):
        """Systolic BP at exact minimum boundary (40 mmHg) should be accepted."""
        assert validate_measurement(MeasurementType.SYSTOLIC_BP, 40.0, "mmHg") is True

    def test_systolic_bp_at_maximum(self):
        """Systolic BP at exact maximum boundary (300 mmHg) should be accepted."""
        assert validate_measurement(MeasurementType.SYSTOLIC_BP, 300.0, "mmHg") is True

    def test_heart_rate_bradycardia(self):
        """Extreme bradycardia (25 bpm) is rare but physiologically possible."""
        assert validate_measurement(MeasurementType.HEART_RATE, 25.0, "bpm") is True

    def test_hba1c_diabetic(self):
        """High HbA1c (12%) indicates poorly controlled diabetes but is valid."""
        assert validate_measurement(MeasurementType.HBA1C, 12.0, "%") is True

    def test_egfr_low_ckd(self):
        """Very low eGFR (5 mL/min) indicates CKD stage 5 but is valid."""
        assert validate_measurement(MeasurementType.EGFR, 5.0, "mL/min/1.73m²") is True

    def test_spo2_hypoxemic(self):
        """SpO2 of 70% is dangerously low but physiologically possible."""
        assert validate_measurement(MeasurementType.SPO2, 70.0, "%") is True

    def test_weight_normal(self):
        """Normal adult weight (75 kg) should be accepted."""
        assert validate_measurement(MeasurementType.WEIGHT, 75.0, "kg") is True


# ---------------------------------------------------------------------------
# Test: validate_measurement — rejection (out of range)
# ---------------------------------------------------------------------------
class TestValidateMeasurementRejects:
    """Test that impossible values are rejected with descriptive errors."""

    def test_systolic_bp_too_high(self):
        """Systolic BP of 400 mmHg is physiologically impossible."""
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(MeasurementType.SYSTOLIC_BP, 400.0, "mmHg")
        assert "above_maximum" in str(exc_info.value.details)
        assert exc_info.value.code == "VALIDATION_ERROR"

    def test_systolic_bp_too_low(self):
        """Systolic BP of 10 mmHg is physiologically impossible."""
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(MeasurementType.SYSTOLIC_BP, 10.0, "mmHg")
        assert "below_minimum" in str(exc_info.value.details)

    def test_heart_rate_zero(self):
        """Heart rate of 0 means cardiac arrest — not a valid measurement."""
        with pytest.raises(ValidationError):
            validate_measurement(MeasurementType.HEART_RATE, 0.0, "bpm")

    def test_spo2_above_100(self):
        """SpO2 cannot exceed 100% — it's a percentage of saturation."""
        with pytest.raises(ValidationError):
            validate_measurement(MeasurementType.SPO2, 105.0, "%")

    def test_bmi_negative(self):
        """Negative BMI is physically impossible."""
        with pytest.raises(ValidationError):
            validate_measurement(MeasurementType.BMI, -5.0, "kg/m²")

    def test_creatinine_too_high(self):
        """Creatinine of 50 mg/dL exceeds physiological maximum."""
        with pytest.raises(ValidationError):
            validate_measurement(MeasurementType.CREATININE, 50.0, "mg/dL")

    def test_weight_too_high(self):
        """Weight of 600 kg exceeds physiological maximum."""
        with pytest.raises(ValidationError):
            validate_measurement(MeasurementType.WEIGHT, 600.0, "kg")

    def test_error_does_not_contain_actual_value(self):
        """Error messages must NOT contain the actual submitted value (PHI)."""
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(MeasurementType.SYSTOLIC_BP, 999.0, "mmHg")
        # The value 999.0 should NOT appear in the error message
        assert "999" not in exc_info.value.message


# ---------------------------------------------------------------------------
# Test: validate_measurement — unit mismatch
# ---------------------------------------------------------------------------
class TestValidateMeasurementUnitMismatch:
    """Test that unit mismatches are caught before range validation."""

    def test_wrong_unit_for_bp(self):
        """Submitting BP in kPa instead of mmHg should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(MeasurementType.SYSTOLIC_BP, 120.0, "kPa")
        assert "unit_mismatch" in str(exc_info.value.details)
        assert "mmHg" in exc_info.value.message

    def test_wrong_unit_for_glucose(self):
        """Submitting glucose in mmol/L instead of mg/dL should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(MeasurementType.BLOOD_GLUCOSE_FASTING, 5.5, "mmol/L")
        assert "unit_mismatch" in str(exc_info.value.details)

    def test_wrong_unit_for_weight(self):
        """Submitting weight in lbs instead of kg should be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            validate_measurement(MeasurementType.WEIGHT, 165.0, "lbs")
        assert "unit_mismatch" in str(exc_info.value.details)


# ---------------------------------------------------------------------------
# Test: check_deviation — flagging behavior
# ---------------------------------------------------------------------------
class TestCheckDeviation:
    """Test the statistical deviation detection for baseline comparison."""

    def test_large_deviation_is_flagged(self):
        """A value 5.5σ from baseline should be flagged."""
        is_flagged, sigma, reason = check_deviation(180.0, 125.0, 10.0)
        assert is_flagged is True
        assert sigma == pytest.approx(5.5, rel=1e-2)
        assert reason is not None
        assert "5.5" in reason

    def test_small_deviation_not_flagged(self):
        """A value 0.5σ from baseline should NOT be flagged."""
        is_flagged, sigma, reason = check_deviation(130.0, 125.0, 10.0)
        assert is_flagged is False
        assert sigma == pytest.approx(0.5, rel=1e-2)
        assert reason is None

    def test_exactly_2_sigma_not_flagged(self):
        """A value exactly at 2σ should NOT be flagged (threshold is >2, not >=2)."""
        is_flagged, sigma, reason = check_deviation(145.0, 125.0, 10.0)
        assert is_flagged is False
        assert sigma == pytest.approx(2.0, rel=1e-2)

    def test_just_above_2_sigma_is_flagged(self):
        """A value just above 2σ should be flagged."""
        is_flagged, sigma, reason = check_deviation(145.1, 125.0, 10.0)
        assert is_flagged is True
        assert sigma > 2.0

    def test_negative_deviation_is_flagged(self):
        """A value significantly BELOW baseline should also be flagged."""
        is_flagged, sigma, reason = check_deviation(90.0, 125.0, 10.0)
        assert is_flagged is True
        assert sigma == pytest.approx(3.5, rel=1e-2)

    def test_zero_std_different_value_flagged(self):
        """With std=0, any value different from mean should be flagged."""
        is_flagged, sigma, reason = check_deviation(130.0, 125.0, 0.0)
        assert is_flagged is True
        assert sigma == 999.0  # Sentinel value for indeterminate
        assert "insufficient history" in reason

    def test_zero_std_same_value_not_flagged(self):
        """With std=0, a value equal to the mean should NOT be flagged."""
        is_flagged, sigma, reason = check_deviation(125.0, 125.0, 0.0)
        assert is_flagged is False
        assert sigma == 0.0
        assert reason is None

    def test_negative_std_treated_as_zero(self):
        """Negative std (should never happen) is treated defensively as zero."""
        is_flagged, sigma, reason = check_deviation(130.0, 125.0, -5.0)
        assert is_flagged is True
        assert sigma == 999.0

    def test_flag_reason_does_not_contain_value(self):
        """Flag reason must NOT contain the actual measurement value (PHI)."""
        is_flagged, sigma, reason = check_deviation(200.0, 125.0, 10.0)
        assert is_flagged is True
        # The actual value (200.0) should not appear in the reason
        assert "200" not in reason
