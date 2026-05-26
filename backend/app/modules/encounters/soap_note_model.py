"""
PrescpHealth Backend — SOAP Note SQLAlchemy Model.

Defines the SOAPNote model for structured clinical documentation.
SOAP (Subjective, Objective, Assessment, Plan) is the standard format
for clinical encounter notes used worldwide.

PHI Fields (ALL fields are PHI):
    - subjective: Patient-reported symptoms and history
    - objective: Clinician observations, exam findings, vitals
    - assessment: Clinical assessment and differential diagnoses
    - plan: Treatment plan, medications, follow-up instructions

    These fields MUST be:
    - Encrypted at rest (column-level or TDE)
    - Never logged (only log soap_note id and encounter_id)
    - Never cached in browser-accessible storage
    - Returned only with proper RBAC authorization (Doctor role)

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin

if TYPE_CHECKING:
    from app.modules.encounters.encounter_model import Encounter


# ---------------------------------------------------------------------------
# SOAP Note Model
# ---------------------------------------------------------------------------
class SOAPNote(TenantMixin, Base):
    """
    Structured clinical note in SOAP format.

    Each encounter can have multiple SOAP notes (e.g., initial assessment
    and follow-up within the same visit). The most recent note represents
    the current clinical state.

    HIPAA Compliance:
    - ALL text fields are PHI — never log content
    - Encrypted at rest, access restricted to Doctor/Nurse roles
    - Retained for minimum 7 years per HIPAA policy

    FHIR Mapping:
    - Maps to FHIR R4 DocumentReference or ClinicalImpression
    - Content included in encounter's fhir_json for completeness
    """

    __tablename__ = "soap_notes"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable SOAP note identifier (UUID)",
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

    # -----------------------------------------------------------------------
    # SOAP Sections — ALL are PHI
    # -----------------------------------------------------------------------
    subjective: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Patient-reported symptoms, history, concerns",
    )
    objective: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Clinician observations, exam findings, vitals",
    )
    assessment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Clinical assessment, differential diagnoses",
    )
    plan: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Treatment plan, medications, follow-up instructions",
    )

    # -----------------------------------------------------------------------
    # Authorship
    # -----------------------------------------------------------------------
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Clinician who authored this note (FK to users table)",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    encounter: Mapped["Encounter"] = relationship(
        "Encounter",
        back_populates="soap_notes",
    )
