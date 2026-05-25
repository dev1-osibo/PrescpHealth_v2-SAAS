"""
PrescpHealth Backend — Patient Models (Re-export Hub).

This file re-exports all patient-related models and enums from their
individual modules for backward compatibility. All existing imports
of the form:

    from app.modules.patients.models import Patient, PatientVersion
    from app.modules.patients.models import PatientGender, PatientStatus

continue to work unchanged.

The actual implementations live in:
- enums.py — PatientGender, PatientStatus, PatientChangeType
- patient_model.py — Patient class
- patient_version_model.py — PatientVersion class

This split was done to comply with the ~150 lines of logic per file rule.
"""

# ---------------------------------------------------------------------------
# Re-export enums
# ---------------------------------------------------------------------------
from app.modules.patients.enums import (  # noqa: F401
    PatientChangeType,
    PatientGender,
    PatientStatus,
)

# ---------------------------------------------------------------------------
# Re-export models
# ---------------------------------------------------------------------------
from app.modules.patients.patient_model import Patient  # noqa: F401
from app.modules.patients.patient_version_model import PatientVersion  # noqa: F401

# ---------------------------------------------------------------------------
# Public API — everything importable from this module
# ---------------------------------------------------------------------------
__all__ = [
    "Patient",
    "PatientVersion",
    "PatientGender",
    "PatientStatus",
    "PatientChangeType",
]
