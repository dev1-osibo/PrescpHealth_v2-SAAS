"""
PrescpHealth Backend — Procedure SQLAlchemy Model.

Defines the Procedure model for recording clinical procedures
performed during patient encounters. Each procedure uses SNOMED CT
coding for standardized procedure identification.

FHIR R4 Mapping:
    Internal Procedure → FHIR R4 Procedure resource
    - code → Procedure.code (CodeableConcept, SNOMED CT)
    - patient_id → Procedure.subject (Reference)
    - encounter_id → Procedure.encounter (Reference)
    - performed_by → Procedure.performer (Reference)
    - performed_at → Procedure.performedDateTime

PHI Fields:
    - description: Reveals clinical procedure performed (PHI)
    - code: Combined with patient_id constitutes PHI

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin

if TYPE_CHECKING:
    from app.modules.encounters.encounter_model import Encounter


# ---------------------------------------------------------------------------
# Procedure Model
# ---------------------------------------------------------------------------
class Procedure(TenantMixin, Base):
    """
    Clinical procedure recorded during an encounter.

    Captures procedures performed on a patient with SNOMED CT coding
    for standardized identification and interoperability.

    Note: Unlike Diagnosis, Procedure does NOT have updated_at from
    TenantMixin's TimestampMixin — it only uses created_at. The
    performed_at field captures when the procedure actually happened
    (which may differ from when it was recorded).

    HIPAA Compliance:
    - Procedure data is PHI — never log code + patient together
    - Encrypted at rest, access restricted to Doctor role
    - Retained for minimum 7 years per HIPAA policy
    """

    __tablename__ = "procedures"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable procedure identifier (UUID)",
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
        comment="Patient this procedure was performed on — FK to patients.id",
    )

    # -----------------------------------------------------------------------
    # Procedure Coding — SNOMED CT
    # -----------------------------------------------------------------------
    code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="SNOMED CT procedure code (e.g., 80146002)",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="PHI: Human-readable procedure description",
    )

    # -----------------------------------------------------------------------
    # Performer and Timing
    # -----------------------------------------------------------------------
    performed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Clinician who performed the procedure (FK to users table)",
    )
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the procedure was performed (UTC)",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="procedures",
    )
