"""
PrescpHealth Backend — Encounter Models (Re-export Hub).

This file re-exports all encounter-related models and enums from their
individual modules for convenient imports. All imports of the form:

    from app.modules.encounters.models import Encounter, SOAPNote
    from app.modules.encounters.models import EncounterStatus, EncounterClass

continue to work unchanged.

The actual implementations live in:
- enums.py — EncounterStatus, EncounterClass
- encounter_model.py — Encounter class
- soap_note_model.py — SOAPNote class
- diagnosis_model.py — Diagnosis class
- procedure_model.py — Procedure class

This split was done to comply with the ~150 lines of logic per file rule.
"""

# ---------------------------------------------------------------------------
# Re-export enums
# ---------------------------------------------------------------------------
from app.modules.encounters.enums import (  # noqa: F401
    EncounterClass,
    EncounterStatus,
)

# ---------------------------------------------------------------------------
# Re-export models
# ---------------------------------------------------------------------------
from app.modules.encounters.encounter_model import Encounter  # noqa: F401
from app.modules.encounters.soap_note_model import SOAPNote  # noqa: F401
from app.modules.encounters.diagnosis_model import Diagnosis  # noqa: F401
from app.modules.encounters.procedure_model import Procedure  # noqa: F401

# ---------------------------------------------------------------------------
# Public API — everything importable from this module
# ---------------------------------------------------------------------------
__all__ = [
    "Encounter",
    "SOAPNote",
    "Diagnosis",
    "Procedure",
    "EncounterStatus",
    "EncounterClass",
]
