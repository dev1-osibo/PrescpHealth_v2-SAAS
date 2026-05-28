"""
Integration tests for database integrity — RLS, constraints, and migrations.

Runs against a real PostgreSQL instance (prescphealth_test) with all 9 migrations
applied. Uses asyncpg directly (not SQLAlchemy) to test RLS session variables
and raw constraint behavior at the database level.

Each test uses BEGIN/ROLLBACK to keep the database clean between runs.
The 'test' role (non-superuser) is used for RLS tests because the postgres
superuser bypasses RLS regardless of FORCE ROW LEVEL SECURITY.
"""

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

# Connection string for the test database (all 9 migrations pre-applied)
DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"

# All tables expected after 9 migrations are applied
EXPECTED_TABLES = [
    "users", "refresh_tokens", "audit_logs", "patients", "patient_versions",
    "measurements", "code_catalogs", "encounters", "soap_notes", "diagnoses",
    "procedures", "prescriptions", "dispensings", "lab_orders", "lab_results",
]

TENANT_A = str(uuid.UUID("00000000-0000-0000-0000-000000000001"))
TENANT_B = str(uuid.UUID("00000000-0000-0000-0000-000000000002"))


@pytest.fixture
async def conn():
    """Provide a raw asyncpg connection with automatic rollback."""
    connection = await asyncpg.connect(DSN)
    tx = connection.transaction()
    await tx.start()
    yield connection
    await tx.rollback()
    await connection.close()


# ---------------------------------------------------------------------------
# 1. Migrations applied correctly — all expected tables exist
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_all_expected_tables_exist(conn):
    """Verify all 15 tables from 9 migrations are present in the database."""
    rows = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    existing = {r["tablename"] for r in rows}
    for table in EXPECTED_TABLES:
        assert table in existing, f"Table '{table}' missing from database"


# ---------------------------------------------------------------------------
# 2. RLS blocks cross-tenant access
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_blocks_cross_tenant_read(conn):
    """Insert a patient as tenant A, verify tenant B cannot see it via RLS."""
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Insert as superuser (bypasses RLS for setup)
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, $2, 'MRN-RLS', 'Test', 'Alpha', '1990-01-01', 'Male', $3)""",
        patient_id, uuid.UUID(TENANT_A), user_id,
    )

    # Switch to non-superuser role so RLS is enforced
    await conn.execute("SET LOCAL ROLE test")
    await conn.execute(f"SET LOCAL app.current_tenant = '{TENANT_B}'")
    row = await conn.fetchrow("SELECT id FROM patients WHERE id = $1", patient_id)
    assert row is None, "RLS failed: tenant B can see tenant A's patient"


# ---------------------------------------------------------------------------
# 3. Unique constraint rejects duplicate measurements
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_unique_constraint_rejects_duplicate_measurement(conn):
    """Duplicate (patient_id, measurement_type, recorded_at, value) is rejected."""
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()
    recorded_at = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

    # Create a patient first
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, $2, 'MRN-UC', 'Test', 'Unique', '1985-05-05', 'Female', $3)""",
        patient_id, uuid.UUID(TENANT_A), user_id,
    )

    # Insert first measurement
    await conn.execute(
        """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
           value, unit, recorded_at, recorded_by, source)
           VALUES ($1, $2, 'systolic_bp', 120.0, 'mmHg', $3, $4, 'manual')""",
        uuid.UUID(TENANT_A), patient_id, recorded_at, user_id,
    )

    # Duplicate insert should fail
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
               value, unit, recorded_at, recorded_by, source)
               VALUES ($1, $2, 'systolic_bp', 120.0, 'mmHg', $3, $4, 'manual')""",
            uuid.UUID(TENANT_A), patient_id, recorded_at, user_id,
        )


# ---------------------------------------------------------------------------
# 4. Foreign keys enforce integrity
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_fk_rejects_nonexistent_patient(conn):
    """Inserting a measurement with a non-existent patient_id is rejected."""
    fake_patient = uuid.uuid4()
    user_id = uuid.uuid4()

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute(
            """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
               value, unit, recorded_at, recorded_by, source)
               VALUES ($1, $2, 'bmi', 22.5, 'kg/m2', $3, $4, 'manual')""",
            uuid.UUID(TENANT_A), fake_patient,
            datetime.now(timezone.utc), user_id,
        )


# ---------------------------------------------------------------------------
# 5. Code catalog validation — lookup and miss
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_code_catalog_lookup_and_miss(conn):
    """Insert a code, verify lookup works; verify non-existent code returns nothing."""
    code_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO code_catalogs (id, catalog_type, code, display_name_en)
           VALUES ($1, 'icd10', 'E11.9', 'Type 2 diabetes mellitus without complications')""",
        code_id,
    )

    # Lookup existing code
    row = await conn.fetchrow(
        "SELECT display_name_en FROM code_catalogs WHERE catalog_type='icd10' AND code='E11.9'"
    )
    assert row is not None
    assert "diabetes" in row["display_name_en"].lower()

    # Non-existent code returns nothing
    miss = await conn.fetchrow(
        "SELECT id FROM code_catalogs WHERE catalog_type='icd10' AND code='Z99.99'"
    )
    assert miss is None


# ---------------------------------------------------------------------------
# 6. Audit log is append-only — UPDATE blocked by RLS (no UPDATE policy)
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_audit_log_update_rejected(conn):
    """Insert an audit entry as superuser, then verify non-superuser cannot UPDATE."""
    tenant_uuid = uuid.UUID(TENANT_A)
    user_id = uuid.uuid4()

    # Insert as superuser (setup)
    await conn.execute(
        """INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, created_at)
           VALUES ($1, $2, 'patient.create', 'patient', $3)""",
        tenant_uuid, user_id, datetime.now(timezone.utc),
    )

    # Switch to non-superuser role — RLS enforced, no UPDATE policy exists
    await conn.execute("SET LOCAL ROLE test")
    await conn.execute(f"SET LOCAL app.current_tenant = '{TENANT_A}'")

    # Attempt UPDATE — should affect 0 rows (no UPDATE policy on audit_logs)
    result = await conn.execute(
        "UPDATE audit_logs SET action = 'tampered' WHERE user_id = $1", user_id
    )
    rows_affected = int(result.split(" ")[-1])
    assert rows_affected == 0, "Audit log UPDATE should be blocked by RLS"
