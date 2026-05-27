"""
PrescpHealth Backend — Encounter Pydantic Schemas.

Input validation schemas for encounter management API endpoints:
- EncounterCreate: New encounter (check-in)
- EncounterUpdate: Update encounter fields
- SOAPNoteCreate: Add SOAP note to encounter
- DiagnosisCreate: Record diagnosis for encounter
- ProcedureCreate: Record procedure for encounter
- DischargeRequest: Complete encounter with discharge summary

HIPAA Compliance:
- Schemas contain PHI fields (reason, SOAP content, diagnoses)
- Protected by RBAC at the router level + Cache-Control headers
- Never expose PHI in validation error messages
"""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.modules.encounters.enums import EncounterClass


# ---------------------------------------------------------------------------
# Encounter Create — Input for starting a new encounter
# ---------------------------------------------------------------------------
class EncounterCreate(BaseModel):
    """Input schema for creating a new encounter (patient check-in)."""

    patient_id: uuid.UUID = Field(
        ..., description="Patient UUID being seen"
    )
    reason_for_visit: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="PHI: Chief complaint / reason for visit",
    )
    encounter_class: EncounterClass = Field(
        default=EncounterClass.AMBULATORY,
        description="Setting: ambulatory, inpatient, emergency",
    )


# ---------------------------------------------------------------------------
# Encounter Update — Partial update of mutable fields
# ---------------------------------------------------------------------------
class EncounterUpdate(BaseModel):
    """Input schema for updating an active encounter."""

    clinician_id: Optional[uuid.UUID] = Field(
        None, description="Reassign to different clinician"
    )
    encounter_class: Optional[EncounterClass] = Field(
        None, description="Change encounter setting"
    )


# ---------------------------------------------------------------------------
# SOAP Note Create — Add clinical note to encounter
# ---------------------------------------------------------------------------
class SOAPNoteCreate(BaseModel):
    """Input schema for adding a SOAP note to an encounter."""

    subjective: Optional[str] = Field(
        None, max_length=10000, description="PHI: Patient-reported symptoms"
    )
    objective: Optional[str] = Field(
        None, max_length=10000, description="PHI: Clinician observations"
    )
    assessment: Optional[str] = Field(
        None, max_length=10000, description="PHI: Clinical assessment"
    )
    plan: Optional[str] = Field(
        None, max_length=10000, description="PHI: Treatment plan"
    )


# ---------------------------------------------------------------------------
# Diagnosis Create — Record coded diagnosis
# ---------------------------------------------------------------------------
class DiagnosisCreate(BaseModel):
    """Input schema for recording a diagnosis on an encounter."""

    icd10_code: str = Field(
        ...,
        min_length=3,
        max_length=10,
        description="ICD-10 code (validated against code catalog)",
    )
    is_chronic: bool = Field(
        default=False,
        description="Whether this is a chronic condition",
    )
    is_primary: bool = Field(
        default=False,
        description="Whether this is the primary diagnosis",
    )


# ---------------------------------------------------------------------------
# Procedure Create — Record clinical procedure
# ---------------------------------------------------------------------------
class ProcedureCreate(BaseModel):
    """Input schema for recording a procedure on an encounter."""

    code: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="SNOMED CT procedure code",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="PHI: Human-readable procedure description",
    )
    performed_at: datetime = Field(
        ..., description="When the procedure was performed (UTC)"
    )


# ---------------------------------------------------------------------------
# Discharge Request — Complete encounter
# ---------------------------------------------------------------------------
class DischargeRequest(BaseModel):
    """Input schema for completing/discharging an encounter."""

    follow_up_instructions: Optional[str] = Field(
        None,
        max_length=5000,
        description="PHI: Follow-up instructions for patient",
    )
