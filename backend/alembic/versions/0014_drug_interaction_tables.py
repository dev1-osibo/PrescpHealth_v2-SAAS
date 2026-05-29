"""Drug interaction tables: medication_records, interaction_results, drug_interactions_db.

Revision ID: 0014_drug_interaction_tables
Revises: 0013_ai_assistant_tables
Create Date: 2026-05-28 21:15:00.000000

This migration creates the database tables for the Drug Interaction module:

1. medication_records (tenant-scoped)
   - Medications prescribed to patient
   - Tracks active status, start/end dates, prescribed clinician

2. interaction_results (tenant-scoped)
   - Detected DDI or DHI with severity assessment
   - Tracks clinical overrides with justification
   - Immutable audit trail

3. drug_interactions_db (non-tenant-scoped, shared reference data)
   - Known interactions from FDA, UpToDate, etc.
   - NOT tenant-scoped (shared platform data)
   - Used for checking patient's medications

RLS Policies:
    - medication_records: tenant_id isolation
    - interaction_results: tenant_id isolation
    - drug_interactions_db: NO RLS (shared reference data)

HIPAA Compliance:
    - Medication names and codes are PHI
    - Interaction assessments are PHI
    - Both tables encrypted at rest
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0014_drug_interaction_tables'
down_revision = '0013_ai_assistant_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create medication_records, interaction_results, drug_interactions_db tables."""

    # =========================================================================
    # 1. Create medication_records table (tenant-scoped)
    # =========================================================================
    op.create_table(
        'medication_records',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Tenant UUID for RLS'),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Patient UUID'),
        sa.Column('drug_name', sa.String(200), nullable=False, comment='PHI: Drug name'),
        sa.Column('drug_code', sa.String(20), nullable=False, comment='PHI: RxNorm/ATC code'),
        sa.Column('dosage', sa.String(100), nullable=False, comment='PHI: Dosage'),
        sa.Column('frequency', sa.String(100), nullable=False, comment='PHI: Frequency'),
        sa.Column('route', sa.String(50), nullable=False, comment='Route (oral, IV, etc)'),
        sa.Column('start_date', sa.Date(), nullable=False, comment='When prescribed'),
        sa.Column('end_date', sa.Date(), nullable=True, comment='When stopped (null = ongoing)'),
        sa.Column('prescribed_by', postgresql.UUID(as_uuid=True), nullable=False, comment='Clinician UUID'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='true if active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['prescribed_by'], ['users.id'], ondelete='RESTRICT'),
    )

    # Index for "active meds" lookup
    op.create_index('ix_medication_patient_active', 'medication_records', ['patient_id', 'is_active'])

    # Enable RLS on medication_records
    op.execute("""
        ALTER TABLE medication_records ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON medication_records
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # =========================================================================
    # 2. Create interaction_results table (tenant-scoped)
    # =========================================================================
    op.create_table(
        'interaction_results',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Tenant UUID for RLS'),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Patient UUID'),
        sa.Column('interaction_type', sa.String(10), nullable=False, comment="'DDI' or 'DHI'"),
        sa.Column('medication_a_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Primary medication'),
        sa.Column('medication_b_id', postgresql.UUID(as_uuid=True), nullable=True, comment='Secondary medication (null for DHI)'),
        sa.Column('health_condition', sa.String(100), nullable=True, comment='PHI: Health condition (for DHI)'),
        sa.Column('severity', sa.String(20), nullable=False, comment="'Contraindicated', 'Major', 'Moderate', 'Minor'"),
        sa.Column('mechanism', sa.Text(), nullable=False, comment='How interaction occurs'),
        sa.Column('adverse_outcome', sa.Text(), nullable=False, comment='Clinical consequences'),
        sa.Column('recommended_action', sa.Text(), nullable=False, comment='Management strategy'),
        sa.Column('is_overridden', sa.Boolean(), nullable=False, server_default='false', comment='true if overridden'),
        sa.Column('override_justification', sa.Text(), nullable=True, comment='PHI: Override justification'),
        sa.Column('overridden_by', postgresql.UUID(as_uuid=True), nullable=True, comment='Clinician who overrode'),
        sa.Column('overridden_at', sa.DateTime(timezone=True), nullable=True, comment='When overridden'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['medication_a_id'], ['medication_records.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['medication_b_id'], ['medication_records.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['overridden_by'], ['users.id'], ondelete='SET NULL'),
    )

    # Index for "critical issues" lookup
    op.create_index('ix_interaction_patient_severity', 'interaction_results', ['patient_id', 'severity'])

    # Enable RLS on interaction_results
    op.execute("""
        ALTER TABLE interaction_results ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON interaction_results
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # =========================================================================
    # 3. Create drug_interactions_db table (non-tenant-scoped, shared)
    # =========================================================================
    op.create_table(
        'drug_interactions_db',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('drug_a_code', sa.String(20), nullable=False, comment='RxNorm/ATC code'),
        sa.Column('drug_a_name', sa.String(200), nullable=False, comment='Drug name'),
        sa.Column('drug_b_code', sa.String(20), nullable=True, comment='RxNorm/ATC code (null for DHI)'),
        sa.Column('drug_b_name', sa.String(200), nullable=True, comment='Drug name (null for DHI)'),
        sa.Column('health_condition', sa.String(100), nullable=True, comment='Health condition (for DHI)'),
        sa.Column('interaction_type', sa.String(10), nullable=False, comment="'DDI' or 'DHI'"),
        sa.Column('severity', sa.String(20), nullable=False, comment="'Contraindicated', 'Major', 'Moderate', 'Minor'"),
        sa.Column('mechanism', sa.Text(), nullable=False, comment='How interaction occurs'),
        sa.Column('adverse_outcome', sa.Text(), nullable=False, comment='Clinical consequences'),
        sa.Column('recommended_action', sa.Text(), nullable=False, comment='Management strategy'),
        sa.Column('evidence_level', sa.String(20), nullable=False, comment="'High', 'Moderate', 'Low'"),
        sa.Column('source', sa.String(100), nullable=False, comment="Source: 'FDA', 'UpToDate', etc"),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='true if used for checking'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
    )

    # Index for fast lookup by drug codes
    op.create_index('ix_drug_interaction_codes', 'drug_interactions_db', ['drug_a_code', 'drug_b_code', 'is_active'])


def downgrade() -> None:
    """Reverse migration: drop tables."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON interaction_results;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON medication_records;")
    op.drop_table('drug_interactions_db')
    op.drop_table('interaction_results')
    op.drop_table('medication_records')
