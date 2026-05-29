"""
RLS Isolation tests — one test per tenant-scoped table.

For each tenant-scoped table:
  1. Insert a row as tenant A (using postgres superuser to bypass setup RLS).
  2. SET LOCAL ROLE test (non-superuser, RLS enforced).
  3. SET LOCAL app.current_tenant = '<tenant_B_uuid>'.
  4. SELECT must return zero rows.

Each test wraps in a transaction and rolls back, so the DB is clean.

Per AGENTS.md the 10 tables in scope:
  patients, measurements, encounters, soap_notes, diagnoses, procedures,
  prescriptions, dispensings, lab_orders, lab_results
"""

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"

TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")
TENANT_B = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
async def conn():
    """Raw asyncpg connection with auto-rollback."""
    connection = await asyncpg.connect(DSN)
    tx = connection.transaction()
    await tx.start()
    yield connection
    await tx.rollback()
    await connection.close()


async def _seed_patient(conn, tenant_id: uuid.UUID, mrn: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a patient as superuser and return (patient_id, user_id)."""
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, $2, $3, 'Test', 'Alpha', '1990-01-01', 'Male', $4)""",
        patient_id, tenant_id, mrn, user_id,
    )
    return patient_id, user_id


async def _seed_encounter(conn, tenant_id: uuid.UUID, patient_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    encounter_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO encounters (id, tenant_id, patient_id, clinician_id,
           status, encounter_class, reason_for_visit)
           VALUES ($1, $2, $3, $4, 'in_progress', 'ambulatory', 'Test visit')""",
        encounter_id, tenant_id, patient_id, user_id,
    )
    return encounter_id


async def _seed_prescription(conn, tenant_id: uuid.UUID, patient_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    prescription_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO prescriptions (id, tenant_id, patient_id, drug_name, atc_code,
           dosage, frequency, route, prescribed_by, refills_allowed, refills_remaining)
           VALUES ($1, $2, $3, 'TestDrug', 'A01AA01', '10mg', 'bid', 'oral', $4, 0, 0)""",
        prescription_id, tenant_id, patient_id, user_id,
    )
    return prescription_id


async def _seed_lab_order(conn, tenant_id: uuid.UUID, patient_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    lab_order_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO lab_orders (id, tenant_id, patient_id, test_name, loinc_code,
           priority, status, ordered_by)
           VALUES ($1, $2, $3, 'Glucose Fasting', '1558-6', 'routine', 'ordered', $4)""",
        lab_order_id, tenant_id, patient_id, user_id,
    )
    return lab_order_id


async def _switch_to_test_role(conn, tenant_id: uuid.UUID):
    """Switch to non-superuser role with tenant_B set as current tenant."""
    await conn.execute("SET LOCAL ROLE test")
    await conn.execute(f"SET LOCAL app.current_tenant = '{tenant_id}'")


# ---------------------------------------------------------------------------
# 1. patients
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_patients(conn):
    patient_id, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-PAT-001")
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM patients WHERE id = $1", patient_id)
    assert row is None, "RLS failed on patients: tenant B can see tenant A's row"


# ---------------------------------------------------------------------------
# 2. measurements
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_measurements(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-MEAS-001")
    meas_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO measurements (id, tenant_id, patient_id, measurement_type,
           value, unit, recorded_at, recorded_by, source)
           VALUES ($1, $2, $3, 'systolic_bp', 120.0, 'mmHg', $4, $5, 'manual')""",
        meas_id, TENANT_A, patient_id,
        datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc), user_id,
    )
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM measurements WHERE id = $1", meas_id)
    assert row is None, "RLS failed on measurements"


# ---------------------------------------------------------------------------
# 3. encounters
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_encounters(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-ENC-001")
    enc_id = await _seed_encounter(conn, TENANT_A, patient_id, user_id)
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM encounters WHERE id = $1", enc_id)
    assert row is None, "RLS failed on encounters"


# ---------------------------------------------------------------------------
# 4. soap_notes
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_soap_notes(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-SOAP-001")
    enc_id = await _seed_encounter(conn, TENANT_A, patient_id, user_id)
    soap_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO soap_notes (id, tenant_id, encounter_id, subjective,
           objective, assessment, plan, recorded_by)
           VALUES ($1, $2, $3, 'S', 'O', 'A', 'P', $4)""",
        soap_id, TENANT_A, enc_id, user_id,
    )
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM soap_notes WHERE id = $1", soap_id)
    assert row is None, "RLS failed on soap_notes"


# ---------------------------------------------------------------------------
# 5. diagnoses
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_diagnoses(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-DX-001")
    enc_id = await _seed_encounter(conn, TENANT_A, patient_id, user_id)
    dx_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO diagnoses (id, tenant_id, encounter_id, patient_id,
           icd10_code, display_name, is_chronic, is_primary, recorded_by)
           VALUES ($1, $2, $3, $4, 'E11.9', 'Type 2 diabetes', true, true, $5)""",
        dx_id, TENANT_A, enc_id, patient_id, user_id,
    )
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM diagnoses WHERE id = $1", dx_id)
    assert row is None, "RLS failed on diagnoses"


# ---------------------------------------------------------------------------
# 6. procedures
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_procedures(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-PROC-001")
    enc_id = await _seed_encounter(conn, TENANT_A, patient_id, user_id)
    proc_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO procedures (id, tenant_id, encounter_id, patient_id,
           code, description, performed_by, performed_at)
           VALUES ($1, $2, $3, $4, '99213', 'Office visit', $5, $6)""",
        proc_id, TENANT_A, enc_id, patient_id, user_id,
        datetime.now(timezone.utc),
    )
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM procedures WHERE id = $1", proc_id)
    assert row is None, "RLS failed on procedures"


# ---------------------------------------------------------------------------
# 7. prescriptions
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_prescriptions(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-RX-001")
    rx_id = await _seed_prescription(conn, TENANT_A, patient_id, user_id)
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM prescriptions WHERE id = $1", rx_id)
    assert row is None, "RLS failed on prescriptions"


# ---------------------------------------------------------------------------
# 8. dispensings
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_dispensings(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-DISP-001")
    rx_id = await _seed_prescription(conn, TENANT_A, patient_id, user_id)
    disp_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO dispensings (id, tenant_id, prescription_id,
           dispensed_quantity, dispensed_by, dispensed_at)
           VALUES ($1, $2, $3, '30 tabs', $4, $5)""",
        disp_id, TENANT_A, rx_id, user_id, datetime.now(timezone.utc),
    )
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM dispensings WHERE id = $1", disp_id)
    assert row is None, "RLS failed on dispensings"


# ---------------------------------------------------------------------------
# 9. lab_orders
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_lab_orders(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-LO-001")
    lo_id = await _seed_lab_order(conn, TENANT_A, patient_id, user_id)
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM lab_orders WHERE id = $1", lo_id)
    assert row is None, "RLS failed on lab_orders"


# ---------------------------------------------------------------------------
# 10. lab_results
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_lab_results(conn):
    patient_id, user_id = await _seed_patient(conn, TENANT_A, "MRN-RLS-LR-001")
    lo_id = await _seed_lab_order(conn, TENANT_A, patient_id, user_id)
    lr_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO lab_results (id, tenant_id, lab_order_id, value, unit,
           is_abnormal, resulted_at, resulted_by)
           VALUES ($1, $2, $3, '95', 'mg/dL', false, $4, $5)""",
        lr_id, TENANT_A, lo_id, datetime.now(timezone.utc), user_id,
    )
    await _switch_to_test_role(conn, TENANT_B)
    row = await conn.fetchrow("SELECT id FROM lab_results WHERE id = $1", lr_id)
    assert row is None, "RLS failed on lab_results"
