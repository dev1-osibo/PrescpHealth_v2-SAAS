"""
PrescpHealth Backend — Prescription Enums.

Defines the enumeration types used across the prescriptions module:
- PrescriptionStatus: Lifecycle states of a medication prescription

These enums map directly to FHIR R4 MedicationRequest resource value sets:
- PrescriptionStatus → MedicationRequest.status

Usage:
    from app.modules.prescriptions.enums import PrescriptionStatus
    # OR (via re-export):
    from app.modules.prescriptions.models import PrescriptionStatus
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Prescription Status Enum
# ---------------------------------------------------------------------------
class PrescriptionStatus(str, Enum):
    """
    Prescription lifecycle status.

    Maps to FHIR R4 MedicationRequest.status value set:
    - active: Prescription is currently in effect, patient should be taking
    - completed: Full course finished (duration elapsed or refills exhausted)
    - discontinued: Clinician stopped the prescription early (reason recorded)
    - on_hold: Temporarily paused (e.g., pending interaction review)

    State transitions:
        active → completed (duration elapsed or refills exhausted)
        active → discontinued (clinician decision, reason required)
        active → on_hold (temporary pause)
        on_hold → active (resumed)
        on_hold → discontinued (decided to stop permanently)
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    DISCONTINUED = "discontinued"
    ON_HOLD = "on_hold"
