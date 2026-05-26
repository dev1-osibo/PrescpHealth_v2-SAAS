"""
PrescpHealth Backend — Lab Order Enums.

Defines the enumeration types used across the lab_orders module:
- LabOrderStatus: Lifecycle states of a laboratory order
- LabPriority: Urgency level for lab test processing

These enums map to FHIR R4 value sets:
- LabOrderStatus → FHIR ServiceRequest.status
- LabPriority → FHIR ServiceRequest.priority

Usage:
    from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Lab Order Status Enum
# ---------------------------------------------------------------------------
class LabOrderStatus(str, Enum):
    """
    Lab order lifecycle status.

    Maps to FHIR R4 ServiceRequest.status value set:
    - ordered: Test has been requested by a clinician
    - specimen_collected: Specimen obtained from patient
    - in_progress: Lab is processing the specimen
    - resulted: Results are available
    - cancelled: Order was cancelled before completion

    State transitions:
        ordered → specimen_collected → in_progress → resulted
        ordered → cancelled
        specimen_collected → cancelled (rare, e.g., specimen compromised)
    """

    ORDERED = "ordered"
    SPECIMEN_COLLECTED = "specimen_collected"
    IN_PROGRESS = "in_progress"
    RESULTED = "resulted"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Lab Priority Enum
# ---------------------------------------------------------------------------
class LabPriority(str, Enum):
    """
    Priority level for lab test processing.

    Maps to FHIR R4 ServiceRequest.priority:
    - routine: Standard processing time (24-72 hours typical)
    - urgent: Expedited processing (4-12 hours typical)
    - stat: Immediate processing required (< 1 hour)

    Priority affects:
    - Lab processing queue order
    - Alert escalation on delayed results
    - Clinician notification urgency
    """

    ROUTINE = "routine"
    URGENT = "urgent"
    STAT = "stat"
