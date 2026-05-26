"""
PrescpHealth Backend — Prescription SQLAlchemy Model.

Defines the core Prescription database model representing a medication
order written by a Doctor for a patient. Each prescription captures the
drug, dosage, frequency, route, and tracks refills and discontinuation.

FHIR R4 Mapping:
    Internal Prescription → FHIR R4 MedicationRequest resource
    - status → MedicationRequest.status
    - drug_name + atc_code → MedicationRequest.medicationCodeableConcept
    - dosage + frequency + route → MedicationRequest.dosageInstruction
    - patient_id → MedicationRequest.subject (Reference)
    - prescribed_by → MedicationRequest.requester (Reference)
    - refills_allowed → MedicationRequest.dispenseRequest.numberOfRepeatsAllowed
    - fhir_json stores the pre-computed FHIR R4 representation

PHI Fields:
    - drug_name, dosage, frequency, route: Medication details (PHI)
    - discontinuation_reason: Clinical rationale (PHI)
    - interaction_justification: Override reasoning (PHI)
    - fhir_json: Contains full clinical context (PHI)

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.prescriptions.enums import PrescriptionStatus

if TYPE_CHECKING:
    from app.modules.prescriptions.dispensing_model import Dispensing


# ---------------------------------------------------------------------------
# Prescription Model
# ---------------------------------------------------------------------------
class Prescription(TenantMixin, Base):
    """
    Medication prescription model.

    Represents a single medication order written by a Doctor. Tracks the
    full lifecycle from active through completion or discontinuation,
    including refill management and drug interaction acknowledgment.

    RLS: Tenant-scoped — prescriptions only visible within their tenant.
    FHIR: fhir_json column stores pre-computed FHIR R4 MedicationRequest.

    HIPAA Compliance:
    - Drug name, dosage, and frequency are PHI
    - Never log medication details (only log prescription id)
    - Soft delete via status change, data retained 7+ years
    - Discontinuation reason is clinical rationale (PHI)
    """

    __tablename__ = "prescriptions"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable prescription identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Foreign Keys — links to patient and encounter
    # -----------------------------------------------------------------------
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Patient receiving the medication — FK to patients.id",
    )
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="SET NULL"),
        nullable=True,
        comment="Originating encounter — nullable for standalone prescriptions",
    )

    # -----------------------------------------------------------------------
    # Medication Details — PHI
    # -----------------------------------------------------------------------
    drug_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="PHI: Medication name (e.g., Metformin, Lisinopril)",
    )
    atc_code: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="ATC classification code — validated against code_catalogs",
    )
    dosage: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: Dosage amount (e.g., '500mg', '10mg/5ml')",
    )
    frequency: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: Dosing frequency (e.g., 'twice daily', 'every 8 hours')",
    )
    duration_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Duration in days — NULL for ongoing/chronic medications",
    )
    route: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Route of administration (e.g., oral, IV, topical, inhaled)",
    )

    # -----------------------------------------------------------------------
    # Status and Lifecycle
    # -----------------------------------------------------------------------
    status: Mapped[PrescriptionStatus] = mapped_column(
        String(20),
        nullable=False,
        default=PrescriptionStatus.ACTIVE,
        comment="Lifecycle: active, completed, discontinued, on_hold",
    )

    # -----------------------------------------------------------------------
    # Refill Management
    # -----------------------------------------------------------------------
    refills_allowed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total number of refills permitted by prescribing doctor",
    )
    refills_remaining: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Remaining refills available — decremented on each dispensing",
    )

    # -----------------------------------------------------------------------
    # Prescribing Clinician
    # -----------------------------------------------------------------------
    prescribed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the Doctor who wrote this prescription",
    )

    # -----------------------------------------------------------------------
    # Discontinuation Tracking
    # -----------------------------------------------------------------------
    discontinued_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        default=None,
        comment="UUID of the clinician who discontinued this prescription",
    )
    discontinued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="When the prescription was discontinued (NULL if active)",
    )
    discontinuation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Clinical reason for discontinuation",
    )

    # -----------------------------------------------------------------------
    # Drug Interaction Override
    # -----------------------------------------------------------------------
    interaction_acknowledged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if Doctor acknowledged a drug interaction warning",
    )
    interaction_justification: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Doctor's justification for overriding interaction warning",
    )

    # -----------------------------------------------------------------------
    # FHIR R4 Representation — pre-computed for interoperability
    # -----------------------------------------------------------------------
    fhir_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="PHI: Pre-computed FHIR R4 MedicationRequest resource JSON",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    dispensings: Mapped[list["Dispensing"]] = relationship(
        "Dispensing",
        back_populates="prescription",
        cascade="all, delete-orphan",
        order_by="Dispensing.dispensed_at.desc()",
    )
