"""Create encounters, soap_notes, diagnoses, procedures tables with RLS.

Revision ID: 0007
Revises: 0006_code_catalogs
Create Date: 2025-06-01

Creates the core clinical encounter tables:
- encounters: Patient visit records with status, class, timing
- soap_notes: Structured clinical notes (Subjective, Objective, Assessment, Plan)
- diagnoses: ICD-10 coded diagnoses linked to encounters and patients
- procedures: SNOMED CT coded procedures performed during encounters

Design Decisions:
- All 4 tables are tenant-scoped with RLS policies for data isolation
- encounters.patient_id FK to patients.id (RESTRICT on delete — never orphan)
- soap_notes and procedures CASCADE on encounter delete (logically grouped)
- diagnoses CASCADE on encounter delete but also FK to patients for direct lookup
- JSONB columns (discharge_summary, fhir_json) store structured clinical data
- Composite indexes optimized for common query patterns:
  - (tenant_id, patient_id, check_in_time DESC) — patient encounter history
  - (tenant_id, clinician_id, status) — clinician workload view
  - (tenant_id, patient_id, icd10_code) — patient diagnosis lookup

HIPAA Compliance:
- All tables contain PHI (clinical notes, diagnoses, procedures)
- RLS enforces tenant isolation at database level
- Soft delete via encounter status (cancelled), data retained 7+ years
- PHI fields documented in column comments for encryption awareness

FHIR R4 Mapping:
- encounters.fhir_json → FHIR R4 Encounter resource
- diagnoses.fhir_json → FHIR R4 Condition resource
- Pre-computed on write for zero-cost FHIR API serving
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Revision identifiers
revision: str = "0007_encounter_tables"
down_revision: Union[str, None] = "0006_code_catalogs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create encounter-related tables with RLS policies and indexes.

    Steps:
    1. Create encounters table
    2. Create soap_notes table
    3. Create diagnoses table
    4. Create procedures table
    5. Enable RLS on all 4 tables
    6. Create composite indexes for query performance
    """

    # --- Step 1: Create encounters table ---
    op.create_table(
        "encounters",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable encounter identifier (UUID)",
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Patient being seen — FK to patients.id",
        ),
        sa.Column(
            "clinician_id",
            UUID(as_uuid=True),
            nullable=False,
            comment="Assigned clinician UUID (FK to users table)",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="in_progress",
            comment="Encounter lifecycle: planned, in_progress, completed, cancelled",
        ),
        sa.Column(
            "encounter_class",
            sa.String(20),
            nullable=False,
            server_default="ambulatory",
            comment="Setting: ambulatory, inpatient, emergency (FHIR ActEncounterCode)",
        ),
        sa.Column(
            "reason_for_visit",
            sa.Text,
            nullable=False,
            comment="PHI: Chief complaint / reason for visit",
        ),
        sa.Column(
            "check_in_time",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="When patient arrived / encounter started (UTC)",
        ),
        sa.Column(
            "check_out_time",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When encounter ended (NULL if still in progress)",
        ),
        sa.Column(
            "discharge_summary",
            JSONB,
            nullable=True,
            comment="PHI: Generated discharge summary {diagnoses, procedures, rx, follow_up}",
        ),
        sa.Column(
            "fhir_json",
            JSONB,
            nullable=True,
            comment="PHI: Pre-computed FHIR R4 Encounter resource JSON",
        ),
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

    # --- Step 2: Create soap_notes table ---
    op.create_table(
        "soap_notes",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable SOAP note identifier (UUID)",
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),
        sa.Column(
            "encounter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent encounter — FK to encounters.id",
        ),
        sa.Column(
            "subjective",
            sa.Text,
            nullable=True,
            comment="PHI: Patient-reported symptoms, history, concerns",
        ),
        sa.Column(
            "objective",
            sa.Text,
            nullable=True,
            comment="PHI: Clinician observations, exam findings, vitals",
        ),
        sa.Column(
            "assessment",
            sa.Text,
            nullable=True,
            comment="PHI: Clinical assessment, differential diagnoses",
        ),
        sa.Column(
            "plan",
            sa.Text,
            nullable=True,
            comment="PHI: Treatment plan, medications, follow-up instructions",
        ),
        sa.Column(
            "recorded_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="Clinician who authored this note (FK to users table)",
        ),
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

    # --- Step 3: Create diagnoses table ---
    op.create_table(
        "diagnoses",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable diagnosis identifier (UUID)",
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),
        sa.Column(
            "encounter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent encounter — FK to encounters.id",
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Patient this diagnosis belongs to — FK to patients.id",
        ),
        sa.Column(
            "icd10_code",
            sa.String(10),
            nullable=False,
            comment="ICD-10 code (validated against code_catalogs table)",
        ),
        sa.Column(
            "display_name",
            sa.String(500),
            nullable=False,
            comment="PHI: Human-readable diagnosis name (from code catalog)",
        ),
        sa.Column(
            "is_chronic",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether this is a chronic condition (syncs to patient record)",
        ),
        sa.Column(
            "is_primary",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether this is the primary diagnosis for the encounter",
        ),
        sa.Column(
            "recorded_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="Clinician who recorded this diagnosis (FK to users table)",
        ),
        sa.Column(
            "fhir_json",
            JSONB,
            nullable=True,
            comment="PHI: Pre-computed FHIR R4 Condition resource JSON",
        ),
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

    # --- Step 4: Create procedures table ---
    op.create_table(
        "procedures",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
            comment="Immutable procedure identifier (UUID)",
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            nullable=False,
            index=True,
            comment="Tenant UUID for RLS isolation",
        ),
        sa.Column(
            "encounter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("encounters.id", ondelete="CASCADE"),
            nullable=False,
            comment="Parent encounter — FK to encounters.id",
        ),
        sa.Column(
            "patient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("patients.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Patient this procedure was performed on — FK to patients.id",
        ),
        sa.Column(
            "code",
            sa.String(20),
            nullable=False,
            comment="SNOMED CT procedure code (e.g., 80146002)",
        ),
        sa.Column(
            "description",
            sa.Text,
            nullable=False,
            comment="PHI: Human-readable procedure description",
        ),
        sa.Column(
            "performed_by",
            UUID(as_uuid=True),
            nullable=False,
            comment="Clinician who performed the procedure (FK to users table)",
        ),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="When the procedure was performed (UTC)",
        ),
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

    # --- Step 5: Enable RLS on all 4 tables ---
    # Row-Level Security ensures tenant isolation at the database level.
    # Even if application code forgets to filter by tenant_id, the database
    # will enforce isolation automatically via the session variable.
    op.execute("""
        -- RLS on encounters table
        ALTER TABLE encounters ENABLE ROW LEVEL SECURITY;
        ALTER TABLE encounters FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON encounters
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);

        -- RLS on soap_notes table
        ALTER TABLE soap_notes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE soap_notes FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON soap_notes
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);

        -- RLS on diagnoses table
        ALTER TABLE diagnoses ENABLE ROW LEVEL SECURITY;
        ALTER TABLE diagnoses FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON diagnoses
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);

        -- RLS on procedures table
        ALTER TABLE procedures ENABLE ROW LEVEL SECURITY;
        ALTER TABLE procedures FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON procedures
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # --- Step 6: Create composite indexes for query performance ---
    op.execute("""
        -- Index: Patient encounter history (newest first)
        -- Used by: GET /patients/{id}/encounters — shows visit timeline
        CREATE INDEX ix_encounters_tenant_patient_checkin
            ON encounters (tenant_id, patient_id, check_in_time DESC);

        -- Index: Clinician workload by status
        -- Used by: GET /encounters?clinician_id=X&status=in_progress
        CREATE INDEX ix_encounters_tenant_clinician_status
            ON encounters (tenant_id, clinician_id, status);

        -- Index: SOAP notes by encounter (for eager loading)
        CREATE INDEX ix_soap_notes_encounter
            ON soap_notes (encounter_id);

        -- Index: Patient diagnosis lookup by ICD-10 code
        -- Used by: checking if patient already has a chronic condition
        CREATE INDEX ix_diagnoses_tenant_patient_icd10
            ON diagnoses (tenant_id, patient_id, icd10_code);

        -- Index: Diagnoses by encounter (for eager loading)
        CREATE INDEX ix_diagnoses_encounter
            ON diagnoses (encounter_id);

        -- Index: Procedures by encounter (for eager loading)
        CREATE INDEX ix_procedures_encounter
            ON procedures (encounter_id);

        -- Index: Procedures by patient (for patient procedure history)
        CREATE INDEX ix_procedures_tenant_patient
            ON procedures (tenant_id, patient_id);
    """)


def downgrade() -> None:
    """
    Drop encounter-related tables and RLS policies.

    WARNING: This permanently deletes all encounter, SOAP note,
    diagnosis, and procedure data. Only use in development.
    """
    # Drop RLS policies (must drop before disabling RLS)
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON procedures;"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON diagnoses;"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON soap_notes;"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_policy ON encounters;"
    )

    # Disable RLS
    op.execute("ALTER TABLE procedures DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE diagnoses DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE soap_notes DISABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE encounters DISABLE ROW LEVEL SECURITY;")

    # Drop tables in dependency order (children first)
    op.drop_table("procedures")
    op.drop_table("diagnoses")
    op.drop_table("soap_notes")
    op.drop_table("encounters")
