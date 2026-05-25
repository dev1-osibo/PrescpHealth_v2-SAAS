"""
PrescpHealth Backend — Clinical Measurement Module.

This module handles recording, validating, and querying clinical
measurements (vital signs, lab results, lifestyle factors) for patients.
Measurements are the primary input data for the Risk Engine and
Forecasting Engine.

Key Responsibilities:
- Record clinical measurements with source tracking and validation status
- Validate physiological ranges per measurement type (reject impossible values)
- Flag deviations from patient baseline (>2σ triggers clinician review)
- Support bulk CSV import with per-row validation and error reporting
- Provide time-series history queries for charting and ML feature extraction
- Enforce idempotency via (patient_id, measurement_type, recorded_at, value)

PHI Warning:
    Measurement values are Protected Health Information (PHI). They must:
    - Never be logged (only log measurement_id UUID and type)
    - Never be cached in browser-accessible storage
    - Be encrypted at rest (column-level or TDE)
    - Be soft-deleted only (7-year HIPAA retention minimum)

Dependencies:
    - app.core.base_model (Base, TenantMixin)
    - app.modules.patients.models (Patient — FK reference)

Data Flow:
    Measurement submitted → Validate range → Check idempotency →
    Flag deviation if >2σ → Save → Publish MeasurementSaved event →
    Risk Engine recomputes scores asynchronously
"""

from app.modules.measurements.models import Measurement, MeasurementType

__all__ = ["Measurement", "MeasurementType"]
