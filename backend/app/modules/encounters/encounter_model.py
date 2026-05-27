"""
PrescpHealth Backend — Encounter SQLAlchemy Model.

Defines the core Encounter database model representing a patient visit.
Each encounter captures the clinical context of a single patient-clinician
interaction: check-in, reason for visit, status, and discharge.

FHIR R4 Mapping:
    Internal Encounter → FHIR R4 Encounter resource
    - status → Encounter.status
    - encounter_class → Encounter.class
    - patient_id → Encounter.subject (Reference)
    - clinician_id → Encounter.participant (Reference)
    - check_in_time/check_out_time → Encounter.period
    - reason_for_visit → Encounter.reasonCode
    - fhir_json stores the pre-computed FHIR R4 representation

PHI Fields:
    - reason_for_visit: Contains clinical complaint (PHI)
    - discharge_summary: Contains diagnoses, procedures, plans (PHI)
    - fhir_json: Contains full clinical context (PHI)

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.encounters.enums import EncounterClass, EncounterStatus

if TYPE_CHECKING:
    from app.modules.encounters.soap_note_model import SOAPNote
    from app.modules.encounters.diagnosis_model import Diagnosis
    from app.modules.encounters.procedure_model import Procedure


# ---------------------------------------------------------------------------
# Encounter Model
# ---------------------------------------------------------------------------
class Encounter(TenantMixin, Base):
    """
    Core encounter (patient visit) model.

    Represents a single clinical interaction between a patient and
    a clinician. All clinical activities (SOAP notes, diagnoses,
    procedures, prescriptions, lab orders) are linked to an encounter.

    RLS: Tenant-scoped — encounters only visible within their tenant.
    FHIR: fhir_json column stores pre-computed FHIR R4 Encounter resource.

    HIPAA Compliance:
    - reason_for_visit and discharge_summary are PHI
    - Never log these fields (only log encounter id)
    - Soft delete via encounter status, data retained 7+ years
    """

    __tablename__ = "encounters"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable encounter identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Foreign Keys — links to patient and clinician
    # -----------------------------------------------------------------------
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Patient being seen — FK to patients.id",
    )
    clinician_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Assigned clinician UUID (FK to users table)",
    )

    # -----------------------------------------------------------------------
    # Encounter Classification and Status
    # -----------------------------------------------------------------------
    status: Mapped[EncounterStatus] = mapped_column(
        String(20),
        nullable=False,
        default=EncounterStatus.IN_PROGRESS,
        comment="Encounter lifecycle: planned, in_progress, completed, cancelled",
    )
    encounter_class: Mapped[EncounterClass] = mapped_column(
        String(20),
        nullable=False,
        default=EncounterClass.AMBULATORY,
        comment="Setting: ambulatory, inpatient, emergency (FHIR ActEncounterCode)",
    )

    # -----------------------------------------------------------------------
    # Clinical Context — PHI
    # -----------------------------------------------------------------------
    reason_for_visit: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="PHI: Chief complaint / reason for visit",
    )

    # -----------------------------------------------------------------------
    # Timing
    # -----------------------------------------------------------------------
    check_in_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When patient arrived / encounter started (UTC)",
    )
    check_out_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="When encounter ended (NULL if still in progress)",
    )

    # -----------------------------------------------------------------------
    # Discharge Summary — PHI (generated on completion)
    # -----------------------------------------------------------------------
    discharge_summary: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="PHI: Generated discharge summary {diagnoses, procedures, rx, follow_up}",
    )

    # -----------------------------------------------------------------------
    # FHIR R4 Representation — pre-computed for interoperability
    # -----------------------------------------------------------------------
    fhir_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="PHI: Pre-computed FHIR R4 Encounter resource JSON",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    soap_notes: Mapped[list["SOAPNote"]] = relationship(
        "SOAPNote",
        back_populates="encounter",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    diagnoses: Mapped[list["Diagnosis"]] = relationship(
        "Diagnosis",
        back_populates="encounter",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    procedures: Mapped[list["Procedure"]] = relationship(
        "Procedure",
        back_populates="encounter",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
