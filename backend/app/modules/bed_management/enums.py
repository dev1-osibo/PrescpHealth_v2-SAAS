"""
PrescpHealth Backend — Bed Management Enums.

All enumerations used by the bed management module.
str-Enum for clean JSON serialization.
"""

from enum import Enum


class BedStatus(str, Enum):
    """Current occupancy/availability state of a hospital bed."""

    AVAILABLE = "available"
    OCCUPIED = "occupied"
    MAINTENANCE = "maintenance"  # Under repair or cleaning
    RESERVED = "reserved"        # Pre-reserved for incoming admission


class BedType(str, Enum):
    """Clinical classification of a bed's care level."""

    STANDARD = "standard"
    ICU = "icu"
    ISOLATION = "isolation"
    PEDIATRIC = "pediatric"
    MATERNITY = "maternity"


class AdmissionStatus(str, Enum):
    """
    Lifecycle state of a patient admission.

    active     → Patient currently admitted to the bed.
    discharged → Patient has left; bed returned to available.
    transferred → Patient moved to another bed within or outside facility.
    """

    ACTIVE = "active"
    DISCHARGED = "discharged"
    TRANSFERRED = "transferred"


class DischargeType(str, Enum):
    """
    Clinical classification of how the patient was discharged.

    Used to populate the discharge plan and for quality metrics.
    """

    ROUTINE = "routine"
    AGAINST_MEDICAL_ADVICE = "against_medical_advice"
    TRANSFER = "transfer"
    DECEASED = "deceased"


class NoteType(str, Enum):
    """
    Type of nursing note for categorisation and filtering.

    Assessment   → Initial / shift assessment note.
    Intervention → Procedure or treatment carried out.
    Evaluation   → Response to intervention.
    Handoff      → Shift handover documentation.
    General      → Uncategorised nursing comment.
    """

    ASSESSMENT = "assessment"
    INTERVENTION = "intervention"
    EVALUATION = "evaluation"
    HANDOFF = "handoff"
    GENERAL = "general"
