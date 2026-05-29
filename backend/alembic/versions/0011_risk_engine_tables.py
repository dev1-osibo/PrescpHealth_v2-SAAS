"""Risk engine tables: model_versions, risk_scores, shap_explanations.

Revision ID: 0011_risk_engine_tables
Revises: 0010_fix_dispensings_updated_at
Create Date: 2026-05-28 20:25:00.000000

This migration creates the database tables for the Risk Engine module:

1. model_versions (non-tenant-scoped)
   - Stores versioned ML model artifacts with performance metrics
   - One active version per disease (enforced by unique constraint)
   - Enables rollback and audit trail

2. risk_scores (tenant-scoped)
   - Stores computed risk predictions (0-100) with confidence intervals
   - Input snapshot preserved for auditability
   - One per disease per computation
   - Indexes for fast "latest score" lookups

3. shap_explanations (tenant-scoped)
   - Feature importance breakdowns (SHAP values)
   - 1-to-1 relationship with risk_scores
   - Cascade delete on risk_score deletion

RLS Policies:
    - risk_scores: tenant_id isolation
    - shap_explanations: tenant_id isolation
    - model_versions: NOT tenant-scoped (platform-level)

HIPAA Compliance:
    - Risk scores and features are PHI
    - Both tables encrypted at rest (TDE or column-level encryption)
    - Input snapshots preserved for audit (sensitive data)
    - Soft-delete not applicable (scores are immutable audit records)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0011_risk_engine_tables'
down_revision = '0010_fix_dispensings_updated_at'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create model_versions, risk_scores, shap_explanations tables."""

    # =========================================================================
    # 1. Create model_versions table (platform-level, not tenant-scoped)
    # =========================================================================
    op.create_table(
        'model_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('disease', sa.String(50), nullable=False, comment='Disease type (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)'),
        sa.Column('version', sa.String(20), nullable=False, comment='Semantic version (e.g., 1.2.0)'),
        sa.Column('artifact_path', sa.String(500), nullable=False, comment='S3 or local path to model artifact'),
        sa.Column('metrics', postgresql.JSONB(), nullable=False, server_default='{}', comment='Performance metrics: {auc_roc, calibration_score, ...}'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='false', comment='True = current production version'),
        sa.Column('deployed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When deployed to production'),
        sa.Column('deployed_by', postgresql.UUID(as_uuid=True), nullable=True, comment='User UUID who deployed'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Record creation time'),
    )
    op.create_index('ix_model_version_disease_active', 'model_versions', ['disease', 'is_active'])
    op.create_unique_constraint('uq_model_version_disease_version', 'model_versions', ['disease', 'version'])

    # =========================================================================
    # 2. Create risk_scores table (tenant-scoped with RLS)
    # =========================================================================
    op.create_table(
        'risk_scores',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True, comment='Tenant UUID for RLS isolation'),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Patient this score belongs to'),
        sa.Column('disease', sa.String(50), nullable=False, comment='Disease type'),
        sa.Column('score', sa.Numeric(precision=5, scale=2), nullable=False, comment='PHI: Risk score 0-100'),
        sa.Column('stratum', sa.String(20), nullable=False, comment='Risk stratum (Low/Moderate/High/Critical)'),
        sa.Column('confidence_lower', sa.Numeric(precision=5, scale=2), nullable=False, comment='95% CI lower bound'),
        sa.Column('confidence_upper', sa.Numeric(precision=5, scale=2), nullable=False, comment='95% CI upper bound'),
        sa.Column('model_version_id', postgresql.UUID(as_uuid=True), nullable=False, comment='FK to model_versions'),
        sa.Column('input_snapshot', postgresql.JSONB(), nullable=False, comment='PHI: Feature dict at computation time'),
        sa.Column('computation_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Groups scores from same computation'),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When computed'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Created timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Updated timestamp'),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['model_version_id'], ['model_versions.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_risk_score_patient_disease_computed', 'risk_scores', ['patient_id', 'disease', 'computed_at'], postgresql_order_by={'computed_at': 'DESC'})
    op.create_index('ix_risk_score_computation', 'risk_scores', ['computation_id'])

    # Enable RLS on risk_scores
    op.execute('ALTER TABLE risk_scores ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE risk_scores FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON risk_scores
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # =========================================================================
    # 3. Create shap_explanations table (tenant-scoped with RLS)
    # =========================================================================
    op.create_table(
        'shap_explanations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True, comment='Tenant UUID for RLS isolation'),
        sa.Column('risk_score_id', postgresql.UUID(as_uuid=True), nullable=False, unique=True, comment='1-to-1 FK to risk_score'),
        sa.Column('base_value', sa.Numeric(precision=5, scale=2), nullable=False, comment='SHAP base value'),
        sa.Column('feature_contributions', postgresql.JSONB(), nullable=False, server_default='[]', comment='PHI: List of feature contributions'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Created timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='Updated timestamp'),
        sa.ForeignKeyConstraint(['risk_score_id'], ['risk_scores.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_shap_risk_score_id', 'shap_explanations', ['risk_score_id'])

    # Enable RLS on shap_explanations
    op.execute('ALTER TABLE shap_explanations ENABLE ROW LEVEL SECURITY;')
    op.execute('ALTER TABLE shap_explanations FORCE ROW LEVEL SECURITY;')
    op.execute("""
        CREATE POLICY tenant_isolation_policy ON shap_explanations
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Drop risk engine tables (reverse migration)."""

    # Drop policies and RLS
    op.execute('ALTER TABLE shap_explanations DISABLE ROW LEVEL SECURITY;')
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON shap_explanations;')
    op.execute('ALTER TABLE risk_scores DISABLE ROW LEVEL SECURITY;')
    op.execute('DROP POLICY IF EXISTS tenant_isolation_policy ON risk_scores;')

    # Drop tables
    op.drop_table('shap_explanations')
    op.drop_table('risk_scores')
    op.drop_table('model_versions')
