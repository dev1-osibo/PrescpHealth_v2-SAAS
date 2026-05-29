"""Create prescriptions and dispensings tables with RLS and indexes.

Revision ID: 0008
Revises: 0006_code_catalogs
Create Date: 2025-06-15

Creates the prescription management tables:
- prescriptions: Medication orders written by Doctors for patients,
  tracking drug details, dosage, refills, and discontinuation.
- dispensings: Individual dispensing events linked to prescriptions,
  recording what was dispensed, by whom, and when.

Design Decisions:
- ATC code validated at application layer against code_catalogs table
  (not a FK — code_catalogs is reference data, not transactional)
- encounter_id is nullable to support standalone prescriptions
  (e.g., chronic medication renewals outside an encounter context)
- refills_allowed and refills_remaining track refill lifecycle;
  refills_remaining is decremented atomically on each dispensing
- interaction_acknowledged + interaction_justification support the
  DDI override workflow (Contraindicated interactions require explicit
  Doctor acknowledgment with documented clinical justification)
- fhir_json stores pre-computed FHIR R4 MedicationRequest for
  interoperability without runtime transformation overhead

Indexes:
- (tenant_id, patient_id, status): Most common query — "active meds for patient"
- (encounter_id): Link prescriptions back to originating encounter

HIPAA Compliance:
- RLS enforces tenant isolation at database level
- Drug names, dosages, and frequencies are PHI — encrypted at rest via TDE
- No hard delete — status transitions preserve full history
- Discontinuation reason is clinical rationale (PHI)
- Audit trail via PrescriptionWritten domain events
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# Revision identifiers
revision: str = "0008_prescription_tables"
down_revision: Union[str, None] = "0007_encounter_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create prescriptions and dispensings tables with RLS and indexes.

    Steps:
    1. Create prescriptions table with all columns and constraints
    2. Create dispensings table with all columns and constraints
    3. Enable RLS on both tables for tenant isolation
    4. Create indexes for common query patterns
    """

    # --- Step 1: Create prescriptions table ---
    op.create_table(
        "prescriptions",
        # Primary key — UUID
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable prescription identifier (UUID)",
        ),
        # Tenant isolation
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="Tenant UUID for RLS isolation",
        ),
        # Patient reference
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Patient receiving the medication — FK to patients.id",
        ),
        # Encounter reference (nullable for standalone prescriptions)
        sa.Column(
            "encounter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="SET NULL"),
            nullable=True,
            comment="Originating encounter — nullable for standalone Rx",
        ),
        # Medication details — PHI
        sa.Column(
            "drug_name",
            sa.String(255),
            nullable=False,
            comment="PHI: Medication name (e.g., Metformin, Lisinopril)",
        ),
        sa.Column(
            "atc_code",
            sa.String(10),
            nullable=False,
            comment="ATC classification code — validated at app layer",
        ),
        sa.Column(
            "dosage",
            sa.String(100),
            nullable=False,
            comment="PHI: Dosage amount (e.g., '500mg', '10mg/5ml')",
        ),
        sa.Column(
            "frequency",
            sa.String(100),
            nullable=False,
            comment="PHI: Dosing frequency (e.g., 'twice daily')",
        ),
        sa.Column(
            "duration_days",
            sa.Integer,
            nullable=True,
            comment="Duration in days — NULL for ongoing/chronic meds",
        ),
        sa.Column(
            "route",
            sa.String(50),
            nullable=False,
            comment="Route of administration (oral, IV, topical, etc.)",
        ),
        # Status
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
            comment="Lifecycle: active, completed, discontinued, on_hold",
        ),
        # Refill management
        sa.Column(
            "refills_allowed",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Total refills permitted by prescribing doctor",
        ),
        sa.Column(
            "refills_remaining",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
            comment="Remaining refills — decremented on each dispensing",
        ),
        # Prescribing clinician
        sa.Column(
            "prescribed_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of the Doctor who wrote this prescription",
        ),
        # Discontinuation tracking
        sa.Column(
            "discontinued_by",
            UUID(as_uuid=True),
            nullable=True,
            comment="UUID of clinician who discontinued this Rx",
        ),
        sa.Column(
            "discontinued_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the prescription was discontinued",
        ),
        sa.Column(
            "discontinuation_reason",
            sa.Text,
            nullable=True,
            comment="PHI: Clinical reason for discontinuation",
        ),
        # Drug interaction override
        sa.Column(
            "interaction_acknowledged",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="True if Doctor acknowledged DDI warning",
        ),
        sa.Column(
            "interaction_justification",
            sa.Text,
            nullable=True,
            comment="PHI: Justification for overriding DDI warning",
        ),
        # FHIR R4 representation
        sa.Column(
            "fhir_json",
            JSONB,
            nullable=True,
            comment="PHI: Pre-computed FHIR R4 MedicationRequest JSON",
        ),
        # Timestamps (from TenantMixin pattern)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Row creation timestamp (UTC)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Last modification timestamp (UTC)",
        ),
    )

    # --- Step 2: Create dispensings table ---
    op.create_table(
        "dispensings",
        # Primary key — UUID
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable dispensing record identifier (UUID)",
        ),
        # Tenant isolation
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="Tenant UUID for RLS isolation",
        ),
        # Prescription reference
        sa.Column(
            "prescription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prescriptions.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Parent prescription — FK to prescriptions.id",
        ),
        # Dispensing details
        sa.Column(
            "dispensed_quantity",
            sa.String(100),
            nullable=False,
            comment="PHI: Quantity dispensed (e.g., '30 tablets')",
        ),
        sa.Column(
            "dispensed_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="UUID of staff who dispensed the medication",
        ),
        sa.Column(
            "dispensed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="When the medication was dispensed (UTC)",
        ),
        # Refill flag
        sa.Column(
            "is_refill",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="True if this is a refill, False for initial fill",
        ),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="Row creation timestamp (UTC)",
        ),
    )

    # --- Step 3: Enable RLS on both tables ---
    op.execute("""
        -- Enable Row-Level Security on prescriptions table
        ALTER TABLE prescriptions ENABLE ROW LEVEL SECURITY;
        ALTER TABLE prescriptions FORCE ROW LEVEL SECURITY;

        -- Policy: users can only see/modify prescriptions for their tenant
        CREATE POLICY tenant_isolation_policy ON prescriptions
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);

        -- Enable Row-Level Security on dispensings table
        ALTER TABLE dispensings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE dispensings FORCE ROW LEVEL SECURITY;

        -- Policy: users can only see/modify dispensings for their tenant
        CREATE POLICY tenant_isolation_policy ON dispensings
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # --- Step 4: Create indexes for common query patterns ---
    op.execute("""
        -- Index: Active medications for a patient within a tenant
        -- Most common query: "show me all active prescriptions for patient X"
        -- Composite index covers tenant isolation + patient filter + status filter
        CREATE INDEX ix_prescriptions_tenant_patient_status
            ON prescriptions (tenant_id, patient_id, status);

        -- Index: Prescriptions linked to a specific encounter
        -- Used when viewing encounter details with associated prescriptions
        CREATE INDEX ix_prescriptions_encounter
            ON prescriptions (encounter_id)
            WHERE encounter_id IS NOT NULL;

        -- Index: Dispensings by tenant for RLS-filtered queries
        CREATE INDEX ix_dispensings_tenant
            ON dispensings (tenant_id);

        -- Index: Dispensings by prescription for refill history
        CREATE INDEX ix_dispensings_prescription
            ON dispensings (prescription_id, dispensed_at DESC);
    """)


def downgrade() -> None:
    """
    Drop prescriptions and dispensings tables with RLS policies.

    WARNING: This permanently deletes all prescription data.
    Only use in development — never in production.
    """
    # Drop RLS policies
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON dispensings;"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON prescriptions;"
    )

    # Disable RLS
    op.execute("ALTER TABLE dispensings DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE prescriptions DISABLE ROW LEVEL SECURITY;")

    # Drop tables (dispensings first due to FK dependency)
    op.drop_table("dispensings")
    op.drop_table("prescriptions")
