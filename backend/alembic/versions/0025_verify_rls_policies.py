"""
Alembic Migration 0025 — Verify RLS Policies on All Tenant-Scoped Tables.

This migration acts as a SAFETY NET: it verifies that Row-Level Security
policies exist on every tenant-scoped table. If any table is missing its
RLS policy (due to a migration bug or manual intervention), this migration
creates the missing policy automatically.

Why verification instead of creation:
    Each table's migration (0004–0024) already creates its own RLS policy.
    This migration provides defense-in-depth by ensuring nothing was missed.
    Think of it as a database-level assertion that tenant isolation is complete.

Tables verified (all 41 tenant-scoped tables):
    patients, patient_versions, measurements, risk_scores, shap_explanations,
    model_versions, forecasts, intervention_simulations, conversations,
    messages, medication_records, interaction_results, encounters, soap_notes,
    diagnoses, procedures, prescriptions, dispensings, lab_orders, lab_results,
    alerts, alert_thresholds, escalation_records, appointments, waitlist,
    referrals, documents, consents, identity_verifications, invoices,
    invoice_line_items, payments, insurance_claims, wards, beds, admissions,
    nursing_notes, connector_configs, sync_logs, cached_population_metrics,
    background_tasks

HIPAA NOTE:
    RLS is the PRIMARY security boundary for multi-tenancy. Without it,
    cross-tenant data leakage is possible. This migration guarantees
    that boundary is intact across the entire schema.

down_revision: 0024_integrations_tables
"""

from alembic import op

# ---------------------------------------------------------------------------
# Migration metadata
# ---------------------------------------------------------------------------
revision = "0025_verify_rls_policies"
down_revision = "0024_integrations_tables"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# All tenant-scoped tables that MUST have RLS enabled
# ---------------------------------------------------------------------------
TENANT_SCOPED_TABLES: list[str] = [
    "patients",
    "patient_versions",
    "measurements",
    "risk_scores",
    "shap_explanations",
    "model_versions",
    "forecasts",
    "intervention_simulations",
    "conversations",
    "messages",
    "medication_records",
    "interaction_results",
    "encounters",
    "soap_notes",
    "diagnoses",
    "procedures",
    "prescriptions",
    "dispensings",
    "lab_orders",
    "lab_results",
    "alerts",
    "alert_thresholds",
    "escalation_records",
    "appointments",
    "waitlist",
    "referrals",
    "documents",
    "consents",
    "identity_verifications",
    "invoices",
    "invoice_line_items",
    "payments",
    "insurance_claims",
    "wards",
    "beds",
    "admissions",
    "nursing_notes",
    "connector_configs",
    "sync_logs",
    "cached_population_metrics",
    "background_tasks",
]


def upgrade() -> None:
    """
    Verify RLS policies exist on all tenant-scoped tables.

    For each table in TENANT_SCOPED_TABLES:
    1. Check pg_policies to see if a policy exists
    2. If missing, enable RLS and create the standard tenant isolation policy
    3. Log which tables needed remediation (via RAISE NOTICE)

    The standard policy pattern:
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """
    tables_array = ", ".join(f"'{t}'" for t in TENANT_SCOPED_TABLES)

    op.execute(f"""
        DO $$
        DECLARE
            tbl TEXT;
            tables TEXT[] := ARRAY[{tables_array}];
            policy_exists BOOLEAN;
        BEGIN
            FOREACH tbl IN ARRAY tables
            LOOP
                SELECT EXISTS(
                    SELECT 1 FROM pg_policies
                    WHERE tablename = tbl
                      AND policyname = 'tenant_isolation_policy'
                ) INTO policy_exists;

                IF NOT policy_exists THEN
                    RAISE NOTICE 'RLS policy missing on %, creating...', tbl;
                    EXECUTE format(
                        'ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl
                    );
                    EXECUTE format(
                        'ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl
                    );
                    EXECUTE format(
                        'CREATE POLICY tenant_isolation_policy ON %I '
                        'USING (tenant_id = current_setting(''app.current_tenant'')::uuid) '
                        'WITH CHECK (tenant_id = current_setting(''app.current_tenant'')::uuid)',
                        tbl
                    );
                END IF;
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    """
    No-op downgrade — verification migrations don't need reversal.

    We don't remove RLS policies on downgrade because:
    1. They were originally created by their own table migrations
    2. Removing them would break tenant isolation
    3. This migration only ADDS missing policies as a safety net
    """
    pass
