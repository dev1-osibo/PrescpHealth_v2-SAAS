"""Forecast engine tables: forecasts, intervention_simulations.

Revision ID: 0012_forecast_engine_tables
Revises: 0011_risk_engine_tables
Create Date: 2026-05-28 20:55:00.000000

This migration creates the database tables for the Forecast Engine module:

1. forecasts (tenant-scoped)
   - Disease trajectory predictions at 3/6/12 month horizons
   - Stores ensemble weights for explainability (TFT, LSTM, Prophet)
   - Data quality indicator warns if forecast is based on limited data
   - One row per target per horizon

2. intervention_simulations (tenant-scoped)
   - Counterfactual "what-if" analysis for clinical interventions
   - References baseline forecast for comparison
   - Immutable audit records

RLS Policies:
    - forecasts: tenant_id isolation
    - intervention_simulations: tenant_id isolation

HIPAA Compliance:
    - Forecasts and simulations are PHI (sensitive clinical data)
    - Both tables encrypted at rest (TDE or column-level encryption)
    - Append-only audit trail (no soft-delete)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0012_forecast_engine_tables'
down_revision = '0011_risk_engine_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create forecasts, intervention_simulations tables."""

    # =========================================================================
    # 1. Create forecasts table (tenant-scoped)
    # =========================================================================
    op.create_table(
        'forecasts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Tenant UUID for RLS'),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Patient UUID'),
        sa.Column('forecast_type', sa.String(50), nullable=False, comment="Type: 'metric' or 'risk_trajectory'"),
        sa.Column('target', sa.String(100), nullable=False, comment='PHI: What we forecast (e.g., systolic_bp, stroke)'),
        sa.Column('horizon_months', sa.Integer(), nullable=False, comment='3, 6, or 12 months'),
        sa.Column('point_estimate', sa.Numeric(10, 4), nullable=False, comment='PHI: Best prediction'),
        sa.Column('confidence_lower', sa.Numeric(10, 4), nullable=False, comment='PHI: 95% CI lower'),
        sa.Column('confidence_upper', sa.Numeric(10, 4), nullable=False, comment='PHI: 95% CI upper'),
        sa.Column('data_quality', sa.String(20), nullable=False, server_default='full_data', comment="'full_data', 'sparse_data', or 'prior_only'"),
        sa.Column('model_ensemble_weights', postgresql.JSONB(), nullable=False, server_default='{"tft": 0.4, "lstm": 0.35, "prophet": 0.25}', comment='Model weights {tft, lstm, prophet}'),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When computed'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('patient_id', 'target', 'horizon_months', 'computed_at', name='uq_forecast_patient_target_horizon_time'),
    )

    # Index for fast "latest forecast" lookup
    op.create_index('ix_forecast_patient_target_computed', 'forecasts', ['patient_id', 'target', sa.desc('computed_at')])

    # Enable RLS on forecasts
    op.execute("""
        ALTER TABLE forecasts ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON forecasts
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)

    # =========================================================================
    # 2. Create intervention_simulations table (tenant-scoped)
    # =========================================================================
    op.create_table(
        'intervention_simulations',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Tenant UUID for RLS'),
        sa.Column('patient_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Patient UUID'),
        sa.Column('intervention_type', sa.String(50), nullable=False, comment="'weight_loss', 'smoking_cessation', 'medication_addition', 'exercise_increase'"),
        sa.Column('parameters', postgresql.JSONB(), nullable=False, server_default='{}', comment='Intervention params (e.g., target_weight_kg)'),
        sa.Column('baseline_forecast_id', postgresql.UUID(as_uuid=True), nullable=False, comment='Reference forecast'),
        sa.Column('simulated_results', postgresql.JSONB(), nullable=False, server_default='[]', comment='PHI: [{horizon, metric, baseline_value, simulated_value, delta}]'),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='When computed'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['baseline_forecast_id'], ['forecasts.id'], ondelete='RESTRICT'),
    )

    # Index for fast lookup by intervention type
    op.create_index('ix_simulation_patient_intervention_computed', 'intervention_simulations', ['patient_id', 'intervention_type', sa.desc('computed_at')])

    # Enable RLS on intervention_simulations
    op.execute("""
        ALTER TABLE intervention_simulations ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation_policy ON intervention_simulations
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid);
    """)


def downgrade() -> None:
    """Reverse migration: drop tables."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON intervention_simulations;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation_policy ON forecasts;")
    op.drop_table('intervention_simulations')
    op.drop_table('forecasts')
