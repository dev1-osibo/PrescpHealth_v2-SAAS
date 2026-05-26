"""
PrescpHealth Backend — Prescription Models (Re-export Hub).

This file re-exports all prescription-related models and enums from their
individual modules for clean imports. All imports of the form:

    from app.modules.prescriptions.models import Prescription, Dispensing
    from app.modules.prescriptions.models import PrescriptionStatus

work via this hub.

The actual implementations live in:
- enums.py — PrescriptionStatus
- prescription_model.py — Prescription class
- dispensing_model.py — Dispensing class

This split complies with the ~150 lines of logic per file rule.
"""

# ---------------------------------------------------------------------------
# Re-export enums
# ---------------------------------------------------------------------------
from app.modules.prescriptions.enums import PrescriptionStatus  # noqa: F401

# ---------------------------------------------------------------------------
# Re-export models
# ---------------------------------------------------------------------------
from app.modules.prescriptions.prescription_model import Prescription  # noqa: F401
from app.modules.prescriptions.dispensing_model import Dispensing  # noqa: F401

# ---------------------------------------------------------------------------
# Public API — everything importable from this module
# ---------------------------------------------------------------------------
__all__ = [
    "Prescription",
    "Dispensing",
    "PrescriptionStatus",
]
