"""
PrescpHealth Backend — Diagnosis SQLAlchemy Model.

Defines the Diagnosis model for recording coded clinical diagnoses
linked to patient encounters. Each diagnosis uses ICD-10 coding
validated against the code_catalogs table.

FHIR R4 Mapping:
    Internal Diagnosis → FHIR R4 Condition resource
    - icd10_code → Condition.code (CodeableConcept)
    - patient_id → Condition.subject (Reference)
    - encounter_id → Condition.encounter (Reference)
    - is_chronic → Condition.clinicalStatus (active vs resolved)
    - created_at → Condition.recordedDate
    - fhir_json stores the pre-computed FHIR R4 representation

PHI Fields:
    - display_name: Reveals patient health condition (PHI)
    - icd10_code: Combined with patient_id constitutes PHI
    - fhir_json: Contains full clinical context (PHI)

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin

if TYPE_CHECKING:
    from app.modules.encounters.encounter_model import Encounter


# ---------------------------------------------------------------------------
# Diagnosis Model
# ---------------------------------------------------------------------------
class Diagnosis(TenantMixin, Base):
    """
    Coded clinical diagnosis recorded during an encounter.

    Each diagnosis links an ICD-10 code to a patient via an encounter.
    The is_chronic flag determines whether the diagnosis should be synced
    to the patient's chronic_conditions JSONB field.

    Validation:
    - icd10_code is validated against code_catalogs (catalog_type='icd10')
    - Invalid codes are rejected at the service layer before persistence

    HIPAA Compliance:
    - Diagnosis data is PHI — never log code + patient together
    - Encrypted at rest, access restricted to Doctor role
    - Retained for minimum 7 years per HIPAA policy

    FHIR Mapping:
    - Maps to FHIR R4 Condition resource
    - fhir_json column stores pre-computed representation
    """

    __tablename__ = "diagnoses"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable diagnosis identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Foreign Keys
    # -----------------------------------------------------------------------
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent encounter — FK to encounters.id",
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Patient this diagnosis belongs to — FK to patients.id",
    )

    # -----------------------------------------------------------------------
    # Diagnosis Coding — validated against code_catalogs
    # -----------------------------------------------------------------------
    icd10_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="ICD-10 code (validated against code_catalogs table)",
    )
    display_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="PHI: Human-readable diagnosis name (from code catalog)",
    )

    # -----------------------------------------------------------------------
    # Classification Flags
    # -----------------------------------------------------------------------
    is_chronic: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this is a chronic condition (syncs to patient record)",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this is the primary diagnosis for the encounter",
    )

    # -----------------------------------------------------------------------
    # Authorship
    # -----------------------------------------------------------------------
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Clinician who recorded this diagnosis (FK to users table)",
    )

    # -----------------------------------------------------------------------
    # FHIR R4 Representation
    # -----------------------------------------------------------------------
    fhir_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="PHI: Pre-computed FHIR R4 Condition resource JSON",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="diagnoses",
    )
