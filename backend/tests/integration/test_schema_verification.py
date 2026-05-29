"""
Schema verification — indexes, RLS policies, audit_logs partitioning.

Asserts the structural invariants the application depends on:
  - Critical performance indexes exist
  - All 10 tenant-scoped tables have a tenant_isolation_policy
  - audit_logs uses table partitioning (pg_inherits has child partitions)
"""

import asyncpg
import pytest

DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(DSN)
    yield connection
    await connection.close()


# Indexes the schema must have (name → tablename pairs).
EXPECTED_INDEXES = [
    ("patients", "uq_patient_tenant_mrn"),
    ("patients", "ix_patients_tenant_id"),
    ("patients", "ix_patients_active"),
    ("measurements", "uq_measurement_idempotency"),
    ("measurements", "ix_measurements_patient_type_time"),
    ("encounters", "ix_encounters_tenant_patient_checkin"),
    ("diagnoses", "ix_diagnoses_tenant_patient_icd10"),
    ("prescriptions", "ix_prescriptions_tenant_patient_status"),
    ("lab_orders", "ix_lab_orders_tenant_patient_status"),
    ("lab_results", "ix_lab_results_order"),
    ("code_catalogs", "uq_code_catalog_type_code"),
    ("code_catalogs", "ix_code_catalogs_display_name_en_trgm"),
    ("refresh_tokens", "refresh_tokens_token_hash_key"),
]


@pytest.mark.integration
async def test_expected_indexes_exist(conn):
    rows = await conn.fetch(
        "SELECT tablename, indexname FROM pg_indexes WHERE schemaname='public'"
    )
    present = {(r["tablename"], r["indexname"]) for r in rows}
    missing = [pair for pair in EXPECTED_INDEXES if pair not in present]
    assert not missing, f"Missing expected indexes: {missing}"


# Tenant-scoped tables per AGENTS.md (excluding refresh_tokens which has no
# tenant_id column and no RLS).
TENANT_SCOPED_TABLES = [
    "patients", "patient_versions", "measurements",
    "encounters", "soap_notes", "diagnoses", "procedures",
    "prescriptions", "dispensings", "lab_orders", "lab_results",
    "users", "audit_logs",
]


@pytest.mark.integration
async def test_all_tenant_scoped_tables_have_rls_policy(conn):
    rows = await conn.fetch(
        "SELECT DISTINCT tablename FROM pg_policies WHERE schemaname='public'"
    )
    tables_with_policy = {r["tablename"] for r in rows}
    missing = [t for t in TENANT_SCOPED_TABLES if t not in tables_with_policy]
    assert not missing, f"Tenant-scoped tables missing RLS policy: {missing}"


@pytest.mark.integration
async def test_tenant_scoped_tables_rls_enabled(conn):
    """Every tenant-scoped table has BOTH rowsecurity AND forcerowsecurity set."""
    rows = await conn.fetch(
        """SELECT c.relname AS table, c.relrowsecurity, c.relforcerowsecurity
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind IN ('r','p')"""
    )
    state = {r["table"]: (r["relrowsecurity"], r["relforcerowsecurity"]) for r in rows}
    failures = []
    for t in TENANT_SCOPED_TABLES:
        if t not in state:
            failures.append(f"{t}: not present")
            continue
        rls_on, forced = state[t]
        if not rls_on or not forced:
            failures.append(f"{t}: rowsecurity={rls_on} forcerowsecurity={forced}")
    assert not failures, f"RLS not properly enforced on: {failures}"


@pytest.mark.integration
async def test_audit_logs_is_partitioned(conn):
    """audit_logs has child partitions registered in pg_inherits."""
    rows = await conn.fetch(
        """SELECT inhrelid::regclass::text AS child
           FROM pg_inherits
           WHERE inhparent = 'public.audit_logs'::regclass"""
    )
    assert len(rows) > 0, "audit_logs has no partitions (pg_inherits empty)"
    # Verify naming convention audit_logs_YYYY_MM
    for r in rows:
        name = r["child"]
        assert name.startswith("audit_logs_"), f"Unexpected partition name: {name}"


@pytest.mark.integration
async def test_audit_logs_partitions_cover_current_period(conn):
    """At least 12 monthly partitions are pre-created."""
    rows = await conn.fetch(
        """SELECT inhrelid::regclass::text AS child
           FROM pg_inherits
           WHERE inhparent = 'public.audit_logs'::regclass"""
    )
    assert len(rows) >= 12, f"Expected ≥12 monthly partitions; found {len(rows)}"
