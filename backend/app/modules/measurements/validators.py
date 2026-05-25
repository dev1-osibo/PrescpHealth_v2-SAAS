"""
PrescpHealth Backend — Measurement Physiological Range Validators.

Validates clinical measurement values against physiologically plausible
ranges before they are stored. This is a patient safety gate: values
outside these ranges are physically impossible and indicate data entry
errors, device malfunctions, or unit conversion mistakes.

Clinical Context:
    These ranges represent the absolute physiological boundaries of human
    biology. Values outside these ranges are NOT "unusual" — they are
    IMPOSSIBLE. For example, a systolic BP of 400 mmHg cannot exist in a
    living patient. Rejecting these at the gate prevents garbage data from
    contaminating risk predictions.

    The ranges are intentionally wide to accommodate extreme but real
    clinical scenarios (e.g., malignant hypertension at 280 mmHg systolic,
    severe bradycardia at 25 bpm). Narrower "normal" ranges are handled
    separately by the deviation flagging system.

HIPAA Compliance:
    - Error messages NEVER include the actual submitted value (PHI)
    - Error messages describe the acceptable range and the violation type
    - Only measurement_type is referenced in errors (safe to log)

Dependencies:
    - app.core.exceptions.ValidationError
    - app.modules.measurements.models.MeasurementType

Usage:
    from app.modules.measurements.validators import (
        validate_measurement,
        check_deviation,
    )

    # Validate a measurement before saving
    validate_measurement(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg")

    # Check if a value deviates from patient baseline
    is_flagged, sigma, reason = check_deviation(180.0, 125.0, 10.0)
"""

from dataclasses import dataclass

from app.core.exceptions import ValidationError
from app.modules.measurements.models import MeasurementType


# ---------------------------------------------------------------------------
# Physiological Range Definition
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PhysiologicalRange:
    """
    Defines the absolute physiological boundaries for a measurement type.

    These are NOT normal/healthy ranges — they are the boundaries of
    what is physically possible in a living human. Values outside these
    ranges indicate data entry errors, not clinical abnormalities.

    Attributes:
        min_value: Absolute minimum (below this is physiologically impossible)
        max_value: Absolute maximum (above this is physiologically impossible)
        unit: Expected unit for this measurement type
        description: Brief clinical context for the range
    """

    min_value: float
    max_value: float
    unit: str
    description: str


# ---------------------------------------------------------------------------
# Physiological Range Registry
#
# Each entry maps a MeasurementType to its absolute physiological bounds.
# These ranges are intentionally wide — they represent the limits of
# human biology, not the limits of "normal" values.
#
# Sources for range selection:
# - Clinical literature on extreme recorded values
# - WHO guidelines for measurement device calibration ranges
# - Emergency medicine references for critical care thresholds
# ---------------------------------------------------------------------------
PHYSIOLOGICAL_RANGES: dict[MeasurementType, PhysiologicalRange] = {
    # -----------------------------------------------------------------------
    # CARDIOVASCULAR MEASUREMENTS
    # -----------------------------------------------------------------------

    # Systolic Blood Pressure (mmHg)
    # Lowest survivable: ~40 mmHg (severe cardiogenic shock)
    # Highest recorded: ~300 mmHg (malignant hypertensive emergency)
    # Normal range: 90–120 mmHg (for reference, not used for validation)
    MeasurementType.SYSTOLIC_BP: PhysiologicalRange(
        min_value=40.0,
        max_value=300.0,
        unit="mmHg",
        description="Systolic blood pressure — peak arterial pressure during cardiac contraction",
    ),

    # Diastolic Blood Pressure (mmHg)
    # Lowest survivable: ~20 mmHg (severe shock states)
    # Highest recorded: ~200 mmHg (hypertensive emergency)
    # Normal range: 60–80 mmHg (for reference)
    MeasurementType.DIASTOLIC_BP: PhysiologicalRange(
        min_value=20.0,
        max_value=200.0,
        unit="mmHg",
        description="Diastolic blood pressure — minimum arterial pressure during cardiac relaxation",
    ),

    # Heart Rate (beats per minute)
    # Lowest survivable: ~20 bpm (extreme bradycardia, pacemaker patients)
    # Highest recorded: ~300 bpm (supraventricular tachycardia)
    # Normal resting: 60–100 bpm (for reference)
    MeasurementType.HEART_RATE: PhysiologicalRange(
        min_value=20.0,
        max_value=300.0,
        unit="bpm",
        description="Heart rate — number of cardiac contractions per minute",
    ),

    # -----------------------------------------------------------------------
    # METABOLIC MEASUREMENTS
    # -----------------------------------------------------------------------

    # Body Mass Index (kg/m²)
    # Lowest survivable: ~5 kg/m² (severe wasting, near-death)
    # Highest recorded: ~100+ kg/m² (extreme morbid obesity)
    # Normal range: 18.5–24.9 kg/m² (WHO classification)
    MeasurementType.BMI: PhysiologicalRange(
        min_value=5.0,
        max_value=100.0,
        unit="kg/m²",
        description="Body Mass Index — weight relative to height squared",
    ),

    # Fasting Blood Glucose (mg/dL)
    # Lowest survivable: ~20 mg/dL (severe hypoglycemia, coma threshold)
    # Highest recorded: ~800+ mg/dL (diabetic ketoacidosis / HHS)
    # Normal fasting: 70–100 mg/dL (for reference)
    MeasurementType.BLOOD_GLUCOSE_FASTING: PhysiologicalRange(
        min_value=20.0,
        max_value=800.0,
        unit="mg/dL",
        description="Fasting blood glucose — plasma glucose after 8+ hours without food",
    ),

    # Random Blood Glucose (mg/dL)
    # Wider range than fasting because postprandial spikes can be extreme
    # Lowest: ~20 mg/dL (severe hypoglycemia)
    # Highest: ~1000 mg/dL (extreme hyperglycemic crisis)
    MeasurementType.BLOOD_GLUCOSE_RANDOM: PhysiologicalRange(
        min_value=20.0,
        max_value=1000.0,
        unit="mg/dL",
        description="Random blood glucose — plasma glucose at any time regardless of meals",
    ),

    # HbA1c (%)
    # Lowest possible: ~2% (lab artifact or severe anemia affecting assay)
    # Highest recorded: ~20% (extremely uncontrolled diabetes)
    # Normal: 4.0–5.6% (for reference)
    # Diabetes diagnosis threshold: ≥6.5%
    MeasurementType.HBA1C: PhysiologicalRange(
        min_value=2.0,
        max_value=20.0,
        unit="%",
        description="Glycated haemoglobin — average blood glucose over 2-3 months",
    ),

    # -----------------------------------------------------------------------
    # LIPID PANEL MEASUREMENTS
    # -----------------------------------------------------------------------

    # Total Cholesterol (mg/dL)
    # Lowest: ~50 mg/dL (severe malnutrition, liver failure)
    # Highest: ~500 mg/dL (familial hypercholesterolemia)
    # Desirable: <200 mg/dL (for reference)
    MeasurementType.TOTAL_CHOLESTEROL: PhysiologicalRange(
        min_value=50.0,
        max_value=500.0,
        unit="mg/dL",
        description="Total cholesterol — sum of all cholesterol fractions in blood",
    ),

    # HDL Cholesterol (mg/dL)
    # Lowest: ~5 mg/dL (Tangier disease, severe deficiency)
    # Highest: ~150 mg/dL (genetic hyperalphalipoproteinemia)
    # Desirable: >40 mg/dL men, >50 mg/dL women (for reference)
    MeasurementType.HDL_CHOLESTEROL: PhysiologicalRange(
        min_value=5.0,
        max_value=150.0,
        unit="mg/dL",
        description="HDL cholesterol — 'good' cholesterol, protective against CVD",
    ),

    # LDL Cholesterol (mg/dL)
    # Lowest: ~10 mg/dL (hypobetalipoproteinemia)
    # Highest: ~400 mg/dL (familial hypercholesterolemia)
    # Optimal: <100 mg/dL (for reference)
    MeasurementType.LDL_CHOLESTEROL: PhysiologicalRange(
        min_value=10.0,
        max_value=400.0,
        unit="mg/dL",
        description="LDL cholesterol — 'bad' cholesterol, primary CVD risk driver",
    ),

    # Triglycerides (mg/dL)
    # Lowest: ~20 mg/dL (abetalipoproteinemia)
    # Highest: ~2000+ mg/dL (severe hypertriglyceridemia, pancreatitis risk)
    # Normal: <150 mg/dL (for reference)
    MeasurementType.TRIGLYCERIDES: PhysiologicalRange(
        min_value=20.0,
        max_value=2000.0,
        unit="mg/dL",
        description="Triglycerides — blood fat level, elevated increases pancreatitis and CVD risk",
    ),

    # -----------------------------------------------------------------------
    # RENAL FUNCTION MEASUREMENTS
    # -----------------------------------------------------------------------

    # Serum Creatinine (mg/dL)
    # Lowest: ~0.1 mg/dL (very low muscle mass, pediatric)
    # Highest: ~30 mg/dL (end-stage renal disease before dialysis)
    # Normal: 0.6–1.2 mg/dL men, 0.5–1.1 mg/dL women (for reference)
    MeasurementType.CREATININE: PhysiologicalRange(
        min_value=0.1,
        max_value=30.0,
        unit="mg/dL",
        description="Serum creatinine — waste product filtered by kidneys, marker of renal function",
    ),

    # Estimated Glomerular Filtration Rate (mL/min/1.73m²)
    # Lowest: ~1 mL/min (near-complete renal failure, pre-dialysis)
    # Highest: ~200 mL/min (hyperfiltration in early diabetes, pregnancy)
    # Normal: >90 mL/min (for reference)
    # CKD Stage 5 (kidney failure): <15 mL/min
    MeasurementType.EGFR: PhysiologicalRange(
        min_value=1.0,
        max_value=200.0,
        unit="mL/min/1.73m²",
        description="Estimated GFR — kidney filtration rate, primary CKD staging marker",
    ),

    # Urine Albumin (mg/L)
    # Lowest: 0 mg/L (normal — no albumin in urine)
    # Highest: ~5000 mg/L (nephrotic syndrome, severe proteinuria)
    # Normal: <20 mg/L (for reference)
    # Microalbuminuria: 20–200 mg/L (early kidney damage)
    MeasurementType.URINE_ALBUMIN: PhysiologicalRange(
        min_value=0.0,
        max_value=5000.0,
        unit="mg/L",
        description="Urine albumin — protein leakage indicating kidney damage",
    ),

    # -----------------------------------------------------------------------
    # RESPIRATORY MEASUREMENTS
    # -----------------------------------------------------------------------

    # FEV1 — Forced Expiratory Volume in 1 second (Liters)
    # Lowest: ~0.1 L (severe COPD/restrictive disease)
    # Highest: ~8 L (large, athletic males)
    # Normal varies by age/sex/height — typically 2.5–5.0 L
    MeasurementType.FEV1: PhysiologicalRange(
        min_value=0.1,
        max_value=8.0,
        unit="L",
        description="FEV1 — volume exhaled in first second of forced expiration (COPD marker)",
    ),

    # FVC — Forced Vital Capacity (Liters)
    # Lowest: ~0.1 L (severe restrictive disease)
    # Highest: ~10 L (very large, athletic males)
    # Normal varies by age/sex/height — typically 3.0–6.0 L
    MeasurementType.FVC: PhysiologicalRange(
        min_value=0.1,
        max_value=10.0,
        unit="L",
        description="FVC — total volume exhaled during forced expiration (lung capacity marker)",
    ),

    # SpO2 — Peripheral Oxygen Saturation (%)
    # Lowest survivable: ~50% (severe hypoxemia, imminent cardiac arrest)
    # Highest: 100% (fully saturated, supplemental O2)
    # Normal: 95–100% (for reference)
    # Below 90%: clinical hypoxemia requiring intervention
    MeasurementType.SPO2: PhysiologicalRange(
        min_value=50.0,
        max_value=100.0,
        unit="%",
        description="SpO2 — peripheral oxygen saturation measured by pulse oximetry",
    ),

    # Respiratory Rate (breaths per minute)
    # Lowest: ~4 breaths/min (severe CNS depression, opioid overdose)
    # Highest: ~60 breaths/min (severe respiratory distress, neonates)
    # Normal adult: 12–20 breaths/min (for reference)
    MeasurementType.RESPIRATORY_RATE: PhysiologicalRange(
        min_value=4.0,
        max_value=60.0,
        unit="breaths/min",
        description="Respiratory rate — number of breaths per minute",
    ),

    # -----------------------------------------------------------------------
    # ANTHROPOMETRIC MEASUREMENTS
    # -----------------------------------------------------------------------

    # Weight (kg)
    # Lowest: ~0.5 kg (premature neonate — included for completeness)
    # Highest: ~500 kg (extreme obesity, recorded cases exist)
    # Normal adult: 40–120 kg (for reference)
    MeasurementType.WEIGHT: PhysiologicalRange(
        min_value=0.5,
        max_value=500.0,
        unit="kg",
        description="Body weight — total mass in kilograms",
    ),

    # Height (cm)
    # Lowest: ~20 cm (premature neonate)
    # Highest: ~280 cm (extreme gigantism, tallest recorded humans ~272 cm)
    # Normal adult: 140–200 cm (for reference)
    MeasurementType.HEIGHT: PhysiologicalRange(
        min_value=20.0,
        max_value=280.0,
        unit="cm",
        description="Body height — standing height in centimeters",
    ),

    # Waist Circumference (cm)
    # Lowest: ~20 cm (pediatric/neonate)
    # Highest: ~250 cm (extreme obesity)
    # Normal adult: 60–100 cm (for reference)
    # Metabolic risk threshold: >102 cm men, >88 cm women
    MeasurementType.WAIST_CIRCUMFERENCE: PhysiologicalRange(
        min_value=20.0,
        max_value=250.0,
        unit="cm",
        description="Waist circumference — abdominal obesity marker for metabolic risk",
    ),

    # -----------------------------------------------------------------------
    # LIFESTYLE FACTORS
    # -----------------------------------------------------------------------

    # Smoking Status (encoded categorical)
    # 0 = never smoked
    # 1 = former smoker (quit >12 months ago)
    # 2 = light current smoker (<10 cigarettes/day)
    # 3 = moderate current smoker (10–20 cigarettes/day)
    # 4 = heavy current smoker (>20 cigarettes/day)
    MeasurementType.SMOKING_STATUS: PhysiologicalRange(
        min_value=0.0,
        max_value=4.0,
        unit="encoded",
        description="Smoking status — categorical encoding: 0=never, 1=former, 2=light, 3=moderate, 4=heavy",
    ),
}


# ---------------------------------------------------------------------------
# Validation Function
# ---------------------------------------------------------------------------
def validate_measurement(
    measurement_type: MeasurementType,
    value: float,
    unit: str,
) -> bool:
    """
    Validate a measurement value against its physiological range.

    This is the primary safety gate for incoming measurement data.
    It rejects values that are physically impossible for the given
    measurement type, preventing garbage data from entering the system
    and contaminating risk predictions.

    Args:
        measurement_type: The type of clinical measurement being validated.
        value: The numeric value to validate.
        unit: The unit of measurement provided (must match expected unit).

    Returns:
        True if the value is within the physiological range and the unit
        matches the expected unit for this measurement type.

    Raises:
        ValidationError: If the value is outside the physiological range
            or the unit doesn't match. Error messages describe the issue
            without including the actual value (HIPAA compliance — the
            value is PHI and must not appear in logs or error responses).

    Examples:
        >>> validate_measurement(MeasurementType.SYSTOLIC_BP, 120.0, "mmHg")
        True

        >>> validate_measurement(MeasurementType.SYSTOLIC_BP, 500.0, "mmHg")
        ValidationError: "Value exceeds maximum physiological limit for systolic_bp..."

    Clinical Safety Note:
        These ranges are intentionally wide. A value that passes this
        validation may still be clinically abnormal — that's handled by
        the deviation flagging system (check_deviation), not here.
        This function only rejects IMPOSSIBLE values.
    """
    # Look up the physiological range for this measurement type
    physiological_range = PHYSIOLOGICAL_RANGES.get(measurement_type)

    if physiological_range is None:
        # Unknown measurement type — reject at the gate
        raise ValidationError(
            message=f"Unknown measurement type: '{measurement_type.value}'. Cannot validate.",
            details=[{
                "field": "measurement_type",
                "reason": "unsupported_type",
                "measurement_type": measurement_type.value,
            }],
        )

    # Validate unit matches expected unit for this measurement type
    # Unit mismatch often indicates a conversion error (e.g., submitting
    # mmol/L when mg/dL is expected) which would make the value meaningless
    if unit != physiological_range.unit:
        raise ValidationError(
            message=(
                f"Unit mismatch for {measurement_type.value}: "
                f"expected '{physiological_range.unit}', received '{unit}'. "
                f"Please convert the value to the expected unit before submitting."
            ),
            details=[{
                "field": "unit",
                "reason": "unit_mismatch",
                "measurement_type": measurement_type.value,
                "expected_unit": physiological_range.unit,
                "received_unit": unit,
            }],
        )

    # Validate value is within physiological range
    # Note: we do NOT include the actual value in the error message (PHI)
    if value < physiological_range.min_value:
        raise ValidationError(
            message=(
                f"Value below minimum physiological limit for {measurement_type.value}. "
                f"Acceptable range: {physiological_range.min_value}–{physiological_range.max_value} "
                f"{physiological_range.unit}. "
                f"The submitted value is below {physiological_range.min_value} {physiological_range.unit} "
                f"which is physiologically impossible."
            ),
            details=[{
                "field": "value",
                "reason": "below_minimum",
                "measurement_type": measurement_type.value,
                "min_value": physiological_range.min_value,
                "max_value": physiological_range.max_value,
                "unit": physiological_range.unit,
            }],
        )

    if value > physiological_range.max_value:
        raise ValidationError(
            message=(
                f"Value exceeds maximum physiological limit for {measurement_type.value}. "
                f"Acceptable range: {physiological_range.min_value}–{physiological_range.max_value} "
                f"{physiological_range.unit}. "
                f"The submitted value exceeds {physiological_range.max_value} {physiological_range.unit} "
                f"which is physiologically impossible."
            ),
            details=[{
                "field": "value",
                "reason": "above_maximum",
                "measurement_type": measurement_type.value,
                "min_value": physiological_range.min_value,
                "max_value": physiological_range.max_value,
                "unit": physiological_range.unit,
            }],
        )

    return True


# ---------------------------------------------------------------------------
# Deviation Detection
# ---------------------------------------------------------------------------
def check_deviation(
    value: float,
    baseline_mean: float,
    baseline_std: float,
) -> tuple[bool, float, str | None]:
    """
    Check if a measurement value deviates significantly from a patient's
    personal baseline, indicating a potential clinical change that warrants
    clinician review.

    A deviation of >2 standard deviations from the patient's historical
    mean triggers a flag. This catches sudden changes that may indicate:
    - Medication non-compliance
    - Acute illness onset
    - Device malfunction (if the reading is real but unexpected)
    - Disease progression requiring intervention

    Args:
        value: The new measurement value to check against baseline.
        baseline_mean: The patient's historical mean for this measurement type.
            Computed from their validated measurement history.
        baseline_std: The patient's historical standard deviation for this
            measurement type. Represents their normal variability.

    Returns:
        A tuple of (is_flagged, sigma_deviation, flag_reason):
        - is_flagged: True if |value - mean| > 2 * std (requires review)
        - sigma_deviation: How many standard deviations from the mean
            (always positive, represents magnitude of deviation)
        - flag_reason: Human-readable explanation if flagged, None otherwise.
            Does NOT include the actual value (PHI compliance).

    Edge Cases:
        - If baseline_std is 0 (only one prior measurement or all identical),
          any deviation from the mean is flagged as it cannot be assessed
          statistically. The sigma_deviation is reported as infinity-like
          (999.0) to indicate indeterminate variability.
        - If baseline_std is negative (should never happen, but defensive),
          treated as 0.

    Examples:
        >>> check_deviation(180.0, 125.0, 10.0)
        (True, 5.5, "Measurement deviates 5.5σ from patient baseline (>2σ threshold)")

        >>> check_deviation(130.0, 125.0, 10.0)
        (False, 0.5, None)

    Clinical Context:
        The 2σ threshold means roughly 5% of normal readings will be flagged
        (assuming normal distribution). This is intentionally sensitive —
        it's better to flag a few false positives than miss a genuine
        clinical deterioration. Clinicians can quickly dismiss false flags.
    """
    # Handle edge case: zero or negative standard deviation
    # This occurs when a patient has only one prior measurement (std=0)
    # or when all prior measurements are identical
    if baseline_std <= 0:
        # Cannot compute meaningful sigma deviation without variability data
        # Any difference from the single known value gets flagged because
        # we have no statistical basis to assess whether it's normal
        if value != baseline_mean:
            return (
                True,
                999.0,  # Sentinel value indicating indeterminate deviation
                "Measurement differs from baseline but insufficient history "
                "to assess statistical significance (baseline std=0)",
            )
        # Value exactly matches the only known baseline — no flag
        return (False, 0.0, None)

    # Compute the absolute deviation in units of standard deviation
    # |value - mean| / std gives us how many σ away from the mean
    sigma_deviation = abs(value - baseline_mean) / baseline_std

    # Flag if deviation exceeds 2σ threshold
    # This corresponds to ~95% confidence that the value is outside
    # the patient's normal range (assuming approximately normal distribution)
    if sigma_deviation > 2.0:
        # Round to 1 decimal place for readability in clinical context
        sigma_rounded = round(sigma_deviation, 1)
        flag_reason = (
            f"Measurement deviates {sigma_rounded}\u03c3 from patient baseline "
            f"(>{2}\u03c3 threshold)"
        )
        return (True, sigma_deviation, flag_reason)

    # Value is within normal variability for this patient — no flag
    return (False, sigma_deviation, None)
