"""
PrescpHealth Backend — LOINC to MeasurementType Mapping.

Maps common LOINC codes to the internal MeasurementType enum values.
This mapping determines which lab results feed into the risk computation
pipeline. Not all lab tests map to a measurement type — only those that
the risk engine uses for disease prediction.

Why this mapping exists:
    Lab results are recorded with LOINC codes (e.g., "2345-7" for Glucose).
    The risk engine operates on MeasurementType values (e.g., "blood_glucose_fasting").
    This module bridges the two systems so lab results automatically flow
    into the risk pipeline without manual intervention.

Coverage:
    - Cardiovascular markers (cholesterol panel)
    - Metabolic markers (glucose, HbA1c)
    - Renal function (creatinine, eGFR)
    - Respiratory (SpO2)
    - Returns None for LOINC codes that don't map to a risk-relevant type

HIPAA Note:
    This module handles ONLY code mappings (public reference data).
    No PHI is processed or logged here.

Usage:
    from app.modules.lab_orders.loinc_to_measurement import map_loinc_to_measurement

    measurement_type = map_loinc_to_measurement("2345-7")
    # Returns MeasurementType.BLOOD_GLUCOSE_FASTING
"""

from app.modules.measurements.models import MeasurementType


# ---------------------------------------------------------------------------
# LOINC → MeasurementType Mapping Table
# ---------------------------------------------------------------------------
# Maps commonly ordered LOINC codes to their corresponding MeasurementType.
# Only codes relevant to the six-disease risk prediction engine are included.
# Labs that don't feed the risk engine (e.g., CBC, urinalysis) return None.
_LOINC_TO_MEASUREMENT: dict[str, MeasurementType] = {
    # --- Metabolic ---
    "2345-7": MeasurementType.BLOOD_GLUCOSE_FASTING,   # Glucose [Mass/Vol] in Serum/Plasma
    "2339-0": MeasurementType.BLOOD_GLUCOSE_RANDOM,    # Glucose [Mass/Vol] in Blood
    "4548-4": MeasurementType.HBA1C,                   # Hemoglobin A1c/Total Hb in Blood
    # --- Lipid Panel ---
    "2093-3": MeasurementType.TOTAL_CHOLESTEROL,       # Cholesterol [Mass/Vol] in Serum/Plasma
    "2085-9": MeasurementType.HDL_CHOLESTEROL,         # HDL Cholesterol [Mass/Vol]
    "2089-1": MeasurementType.LDL_CHOLESTEROL,         # LDL Cholesterol [Mass/Vol]
    "2571-8": MeasurementType.TRIGLYCERIDES,           # Triglycerides [Mass/Vol]
    # --- Renal Function ---
    "2160-0": MeasurementType.CREATININE,              # Creatinine [Mass/Vol] in Serum/Plasma
    "33914-3": MeasurementType.EGFR,                   # eGFR by CKD-EPI
    "14959-1": MeasurementType.URINE_ALBUMIN,          # Microalbumin [Mass/Vol] in Urine
    # --- Respiratory ---
    "2708-6": MeasurementType.SPO2,                    # Oxygen saturation in Arterial blood
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def map_loinc_to_measurement(loinc_code: str) -> MeasurementType | None:
    """
    Map a LOINC code to its corresponding MeasurementType.

    Returns the MeasurementType if the LOINC code is relevant to the
    risk computation pipeline. Returns None for codes that don't map
    to a measurement type (e.g., CBC, culture results, pathology).

    This is intentional — not all lab results feed the risk engine.
    Only quantitative results with defined physiological ranges and
    risk model features are mapped.

    Args:
        loinc_code: The LOINC code string (e.g., "2345-7").

    Returns:
        MeasurementType enum value if mapped, None otherwise.

    Examples:
        >>> map_loinc_to_measurement("2345-7")
        MeasurementType.BLOOD_GLUCOSE_FASTING

        >>> map_loinc_to_measurement("58410-2")  # CBC
        None
    """
    return _LOINC_TO_MEASUREMENT.get(loinc_code)
