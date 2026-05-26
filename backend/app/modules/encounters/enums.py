"""
PrescpHealth Backend — Encounter Enums.

Defines the enumeration types used across the encounters module:
- EncounterStatus: Lifecycle states of a patient encounter
- EncounterClass: Classification of the encounter setting

These enums map directly to FHIR R4 Encounter resource value sets:
- EncounterStatus → FHIR Encounter.status
- EncounterClass → FHIR Encounter.class (ActEncounterCode)

Usage:
    from app.modules.encounters.enums import EncounterStatus, EncounterClass
    # OR (via re-export):
    from app.modules.encounters.models import EncounterStatus, EncounterClass
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Encounter Status Enum
# ---------------------------------------------------------------------------
class EncounterStatus(str, Enum):
    """
    Encounter lifecycle status.

    Maps to FHIR R4 Encounter.status value set:
    - planned: Encounter is scheduled but patient has not arrived
    - in_progress: Patient has checked in, encounter is active
    - completed: Encounter finished, discharge summary generated
    - cancelled: Encounter was cancelled before completion

    State transitions:
        planned → in_progress → completed
        planned → cancelled
        in_progress → cancelled (rare, e.g., patient left AMA)
    """

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Encounter Class Enum
# ---------------------------------------------------------------------------
class EncounterClass(str, Enum):
    """
    Classification of the encounter setting/context.

    Maps to FHIR R4 Encounter.class (ActEncounterCode value set):
    - ambulatory: Outpatient visit (most common in clinic settings)
    - inpatient: Patient admitted to hospital/ward
    - emergency: Emergency department visit

    This determines workflow expectations:
    - Ambulatory: short visit, SOAP note, discharge same day
    - Inpatient: linked to bed management, nursing notes, multi-day
    - Emergency: urgent triage, may convert to inpatient
    """

    AMBULATORY = "ambulatory"
    INPATIENT = "inpatient"
    EMERGENCY = "emergency"
