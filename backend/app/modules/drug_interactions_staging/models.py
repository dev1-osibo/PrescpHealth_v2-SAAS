"""
PrescpHealth Backend — Drug Interaction SQLAlchemy Models.

Models for medication management and interaction detection:
- MedicationRecord: Medications prescribed to patient
- InteractionResult: Detected DDI or DHI with override tracking
- DrugInteractionsDB: Reference data (not tenant-scoped, shared across platform)

Design Principles:
    - MedicationRecord is tenant-scoped (per patient, per tenant)
    - InteractionResult tracks both detection and overrides (audit trail)
    - DrugInteractionsDB is shared reference data (replicated, not tenant-specific)
    - Overrides are immutable (record who, when, why)

RLS and Tenant Isolation:
    - MedicationRecord uses TenantMixin (RLS on tenant_id)
    - InteractionResult uses TenantMixin (RLS on tenant_id)
    - DrugInteractionsDB does NOT use TenantMixin (shared reference data)

HIPAA Compliance:
    - Medication names and codes are PHI — encrypt at rest
    - Interaction assessments are PHI
    - Override justifications are PHI (may contain clinical reasoning)

Indexes:
    - (patient_id, is_active) on medication_records for quick "active meds" lookup
    - (patient_id, severity) on interaction_results for "critical issues" lookup
"""

import uuid
from datetime import datetime, date

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    Boolean,
    Date,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin


class MedicationRecord(TenantMixin, Base):
    """
    Medication currently or previously prescribed to a patient.

    Tracks drug name, code (RxNorm/ATC), dosage, frequency, and active status.

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        patient_id: Patient UUID (FK to patients table)
        drug_name: Drug name (e.g., "lisinopril")
        drug_code: RxNorm or ATC code (e.g., "314076")
        dosage: e.g., "10 mg"
        frequency: e.g., "once daily"
        route: e.g., "oral", "IV"
        start_date: When prescribed
        end_date: When stopped (nullable, null = ongoing)
        prescribed_by: Clinician UUID (FK to users.id)
        is_active: true if currently active, false if historical
        created_at, updated_at: From TenantMixin

    Design Note:
        - is_active flag enables soft-delete (deactivate instead of deleting)
        - end_date captures when medication stopped
        - drug_code enables programmatic lookup in DrugInteractionsDB
        - Immutable records (no updates, only inserts and end_date changes)
    """

    __tablename__ = "medication_records"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient UUID",
    )

    drug_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="PHI: Drug name (e.g., 'lisinopril')",
    )

    drug_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="PHI: RxNorm or ATC code (e.g., '314076')",
    )

    dosage: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: Dosage (e.g., '10 mg')",
    )

    frequency: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: Frequency (e.g., 'once daily')",
    )

    route: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Route: 'oral', 'IV', 'topical', etc.",
    )

    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="When prescribed",
    )

    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=True,
        comment="When stopped (null = ongoing)",
    )

    prescribed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Clinician UUID",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
        comment="true if currently active",
    )

    __table_args__ = (
        Index("ix_medication_patient_active", "patient_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<MedicationRecord patient={self.patient_id} drug={self.drug_name} active={self.is_active}>"


class InteractionResult(TenantMixin, Base):
    """
    Detected drug-drug (DDI) or drug-health (DHI) interaction.

    Tracks detected interaction, severity assessment, and any clinical override.

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        patient_id: Patient UUID
        interaction_type: "DDI" (drug-drug) or "DHI" (drug-health)
        medication_a_id: FK to medication_records (primary drug)
        medication_b_id: FK to medication_records (secondary drug, null for DHI)
        health_condition: For DHI (e.g., "CKD stage 4"), null for DDI
        severity: "Contraindicated", "Major", "Moderate", "Minor"
        mechanism: Why interaction occurs
        adverse_outcome: What could go wrong
        recommended_action: Clinical recommendation
        is_overridden: true if clinician overrode interaction
        override_justification: Mandatory justification for override
        overridden_by: Clinician UUID (user.id) who overrode
        overridden_at: When override occurred
        created_at, updated_at: From TenantMixin

    Design Note:
        - Interactions are immutable (append-only audit trail)
        - Overrides are recorded with who/when/why
        - severity guides clinical importance
        - Both DDI and DHI in same table (interaction_type distinguishes)
    """

    __tablename__ = "interaction_results"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient UUID",
    )

    interaction_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="'DDI' (drug-drug) or 'DHI' (drug-health)",
    )

    medication_a_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("medication_records.id", ondelete="CASCADE"),
        nullable=False,
        comment="Primary medication",
    )

    medication_b_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("medication_records.id", ondelete="SET NULL"),
        nullable=True,
        comment="Secondary medication (null for DHI)",
    )

    health_condition: Mapped[str] = mapped_column(
        String(100),
        nullable=True,
        comment="PHI: Health condition (for DHI, e.g., 'CKD stage 4')",
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'Contraindicated', 'Major', 'Moderate', 'Minor'",
    )

    mechanism: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Why interaction occurs",
    )

    adverse_outcome: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="What could go wrong",
    )

    recommended_action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Clinical recommendation",
    )

    is_overridden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="true if clinician overrode",
    )

    override_justification: Mapped[str] = mapped_column(
        Text,
        nullable=True,
        comment="PHI: Why override was necessary",
    )

    overridden_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Clinician who overrode",
    )

    overridden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When override occurred",
    )

    __table_args__ = (
        Index("ix_interaction_patient_severity", "patient_id", "severity"),
    )

    def __repr__(self) -> str:
        return f"<InteractionResult patient={self.patient_id} type={self.interaction_type} severity={self.severity}>"


class DrugInteractionsDB(Base):
    """
    Reference data: Known interactions between drugs and conditions.

    Non-tenant-scoped (shared across all tenants). Contains evidence-based
    interaction information (e.g., from FDA, medical literature).

    Fields:
        id: UUID primary key
        drug_a_code: RxNorm/ATC code for first drug
        drug_a_name: Drug name
        drug_b_code: RxNorm/ATC code for second drug (null for DHI)
        drug_b_name: Drug name (null for DHI)
        health_condition: For DHI (e.g., "CKD", "hepatic_impairment")
        interaction_type: "DDI" or "DHI"
        severity: "Contraindicated", "Major", "Moderate", "Minor"
        mechanism: How interaction occurs
        adverse_outcome: Clinical consequences
        recommended_action: Management strategy
        evidence_level: "High", "Moderate", "Low"
        source: Where data came from (e.g., "FDA", "UpToDate", "Lexi-Comp")
        is_active: true if currently used for checking, false if deprecated
        created_at: When record was added

    Design Note:
        - NOT tenant-scoped (reference data, same for all tenants)
        - NO RLS policies
        - Shared across entire platform
        - Populated from drug interaction databases (FDA, UpToDate, etc.)
    """

    __tablename__ = "drug_interactions_db"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    drug_a_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="RxNorm/ATC code",
    )

    drug_a_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Drug name",
    )

    drug_b_code: Mapped[str] = mapped_column(
        String(20),
        nullable=True,
        comment="RxNorm/ATC code (null for DHI)",
    )

    drug_b_name: Mapped[str] = mapped_column(
        String(200),
        nullable=True,
        comment="Drug name (null for DHI)",
    )

    health_condition: Mapped[str] = mapped_column(
        String(100),
        nullable=True,
        comment="Health condition (for DHI)",
    )

    interaction_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="'DDI' or 'DHI'",
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'Contraindicated', 'Major', 'Moderate', 'Minor'",
    )

    mechanism: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="How interaction occurs",
    )

    adverse_outcome: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Clinical consequences",
    )

    recommended_action: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Management strategy",
    )

    evidence_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="'High', 'Moderate', 'Low'",
    )

    source: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Source: 'FDA', 'UpToDate', 'Lexi-Comp', etc.",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
        comment="true if used for checking, false if deprecated",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    def __repr__(self) -> str:
        return f"<DrugInteractionsDB {self.drug_a_name} + {self.drug_b_name or self.health_condition}>"
