"""
Foreign key integrity — one test per FK relationship.

Each test inserts a child row whose parent ID does not exist; asserts the
database raises asyncpg.ForeignKeyViolationError.

FKs derived from pg_constraint where contype='f' (public schema):
  diagnoses.encounter_id  → encounters.id
  diagnoses.patient_id    → patients.id
  dispensings.prescription_id → prescriptions.id
  encounters.patient_id   → patients.id
  lab_orders.encounter_id → encounters.id
  lab_orders.patient_id   → patients.id
  lab_results.lab_order_id → lab_orders.id
  lab_results.measurement_id → measurements.id
  measurements.patient_id → patients.id
  mfa_configs.user_id     → users.id
  patient_versions.patient_id → patients.id
  prescriptions.patient_id → patients.id
  prescriptions.encounter_id → encounters.id
  procedures.encounter_id → encounters.id
  procedures.patient_id   → patients.id
  refresh_tokens.user_id  → users.id
"""

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest

DSN = "postgresql://postgres:2026victory@localhost:5432/prescphealth_test"
TENANT_A = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(DSN)
    tx = connection.transaction()
    await tx.start()
    yield connection
    await tx.rollback()
    await connection.close()


async def _seed_patient(conn, mrn: str) -> tuple[uuid.UUID, uuid.UUID]:
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, $2, $3, 'Test', 'FK', '1990-01-01', 'Male', $4)""",
        patient_id, TENANT_A, mrn, user_id,
    )
    return patient_id, user_id


async def _seed_encounter(conn, patient_id, user_id) -> uuid.UUID:
    enc_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO encounters (id, tenant_id, patient_id, clinician_id,
           status, encounter_class, reason_for_visit)
           VALUES ($1, $2, $3, $4, 'in_progress', 'ambulatory', 'fk test')""",
        enc_id, TENANT_A, patient_id, user_id,
    )
    return enc_id


# ---------------------------------------------------------------------------
async def _expect_fk(conn, sql, *args):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute(sql, *args)


# diagnoses.encounter_id
@pytest.mark.integration
async def test_fk_diagnoses_encounter_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-DX-ENC")
    await _expect_fk(conn,
        """INSERT INTO diagnoses (tenant_id, encounter_id, patient_id,
           icd10_code, display_name, recorded_by)
           VALUES ($1, $2, $3, 'E11.9', 'Diabetes', $4)""",
        TENANT_A, uuid.uuid4(), patient_id, user_id,
    )


# diagnoses.patient_id
@pytest.mark.integration
async def test_fk_diagnoses_patient_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-DX-PAT")
    enc_id = await _seed_encounter(conn, patient_id, user_id)
    await _expect_fk(conn,
        """INSERT INTO diagnoses (tenant_id, encounter_id, patient_id,
           icd10_code, display_name, recorded_by)
           VALUES ($1, $2, $3, 'E11.9', 'Diabetes', $4)""",
        TENANT_A, enc_id, uuid.uuid4(), user_id,
    )


# dispensings.prescription_id
@pytest.mark.integration
async def test_fk_dispensings_prescription_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-DISP")
    await _expect_fk(conn,
        """INSERT INTO dispensings (tenant_id, prescription_id,
           dispensed_quantity, dispensed_by, dispensed_at)
           VALUES ($1, $2, '30 tabs', $3, $4)""",
        TENANT_A, uuid.uuid4(), user_id, datetime.now(timezone.utc),
    )


# encounters.patient_id
@pytest.mark.integration
async def test_fk_encounters_patient_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-ENC-PAT")
    await _expect_fk(conn,
        """INSERT INTO encounters (tenant_id, patient_id, clinician_id,
           status, encounter_class, reason_for_visit)
           VALUES ($1, $2, $3, 'in_progress', 'ambulatory', 'fk test')""",
        TENANT_A, uuid.uuid4(), user_id,
    )


# lab_orders.encounter_id
@pytest.mark.integration
async def test_fk_lab_orders_encounter_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-LO-ENC")
    await _expect_fk(conn,
        """INSERT INTO lab_orders (tenant_id, patient_id, encounter_id,
           test_name, loinc_code, priority, status, ordered_by)
           VALUES ($1, $2, $3, 'Glucose', '1558-6', 'routine', 'ordered', $4)""",
        TENANT_A, patient_id, uuid.uuid4(), user_id,
    )


# lab_orders.patient_id
@pytest.mark.integration
async def test_fk_lab_orders_patient_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-LO-PAT")
    await _expect_fk(conn,
        """INSERT INTO lab_orders (tenant_id, patient_id, test_name,
           loinc_code, priority, status, ordered_by)
           VALUES ($1, $2, 'Glucose', '1558-6', 'routine', 'ordered', $3)""",
        TENANT_A, uuid.uuid4(), user_id,
    )


# lab_results.lab_order_id
@pytest.mark.integration
async def test_fk_lab_results_lab_order_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-LR-LO")
    await _expect_fk(conn,
        """INSERT INTO lab_results (tenant_id, lab_order_id, value, unit,
           is_abnormal, resulted_at, resulted_by)
           VALUES ($1, $2, '95', 'mg/dL', false, $3, $4)""",
        TENANT_A, uuid.uuid4(), datetime.now(timezone.utc), user_id,
    )


# lab_results.measurement_id (nullable FK; insert a row referencing nonexistent measurement)
@pytest.mark.integration
async def test_fk_lab_results_measurement_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-LR-MEAS")
    lo_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO lab_orders (id, tenant_id, patient_id, test_name,
           loinc_code, priority, status, ordered_by)
           VALUES ($1, $2, $3, 'Glucose', '1558-6', 'routine', 'ordered', $4)""",
        lo_id, TENANT_A, patient_id, user_id,
    )
    await _expect_fk(conn,
        """INSERT INTO lab_results (tenant_id, lab_order_id, value, unit,
           is_abnormal, resulted_at, resulted_by, measurement_id)
           VALUES ($1, $2, '95', 'mg/dL', false, $3, $4, $5)""",
        TENANT_A, lo_id, datetime.now(timezone.utc), user_id, uuid.uuid4(),
    )


# measurements.patient_id
@pytest.mark.integration
async def test_fk_measurements_patient_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-MEAS-PAT")
    await _expect_fk(conn,
        """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
           value, unit, recorded_at, recorded_by, source)
           VALUES ($1, $2, 'bmi', 22.0, 'kg/m2', $3, $4, 'manual')""",
        TENANT_A, uuid.uuid4(), datetime.now(timezone.utc), user_id,
    )


# mfa_configs.user_id
@pytest.mark.integration
async def test_fk_mfa_configs_user_id(conn):
    await _expect_fk(conn,
        """INSERT INTO mfa_configs (totp_secret_encrypted, user_id)
           VALUES ('encrypted-secret', $1)""",
        uuid.uuid4(),
    )


# patient_versions.patient_id
@pytest.mark.integration
async def test_fk_patient_versions_patient_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-PV")
    await _expect_fk(conn,
        """INSERT INTO patient_versions (patient_id, tenant_id, version_number,
           changed_by, change_type, changes, snapshot)
           VALUES ($1, $2, 1, $3, 'create', '{}'::jsonb, '{}'::jsonb)""",
        uuid.uuid4(), TENANT_A, user_id,
    )


# prescriptions.patient_id
@pytest.mark.integration
async def test_fk_prescriptions_patient_id(conn):
    _, user_id = await _seed_patient(conn, "MRN-FK-RX-PAT")
    await _expect_fk(conn,
        """INSERT INTO prescriptions (tenant_id, patient_id, drug_name, atc_code,
           dosage, frequency, route, prescribed_by)
           VALUES ($1, $2, 'TestDrug', 'A01AA01', '10mg', 'bid', 'oral', $3)""",
        TENANT_A, uuid.uuid4(), user_id,
    )


# prescriptions.encounter_id
@pytest.mark.integration
async def test_fk_prescriptions_encounter_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-RX-ENC")
    await _expect_fk(conn,
        """INSERT INTO prescriptions (tenant_id, patient_id, encounter_id,
           drug_name, atc_code, dosage, frequency, route, prescribed_by)
           VALUES ($1, $2, $3, 'TestDrug', 'A01AA01', '10mg', 'bid', 'oral', $4)""",
        TENANT_A, patient_id, uuid.uuid4(), user_id,
    )


# procedures.encounter_id
@pytest.mark.integration
async def test_fk_procedures_encounter_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-PROC-ENC")
    await _expect_fk(conn,
        """INSERT INTO procedures (tenant_id, encounter_id, patient_id,
           code, description, performed_by, performed_at)
           VALUES ($1, $2, $3, '99213', 'Office visit', $4, $5)""",
        TENANT_A, uuid.uuid4(), patient_id, user_id, datetime.now(timezone.utc),
    )


# procedures.patient_id
@pytest.mark.integration
async def test_fk_procedures_patient_id(conn):
    patient_id, user_id = await _seed_patient(conn, "MRN-FK-PROC-PAT")
    enc_id = await _seed_encounter(conn, patient_id, user_id)
    await _expect_fk(conn,
        """INSERT INTO procedures (tenant_id, encounter_id, patient_id,
           code, description, performed_by, performed_at)
           VALUES ($1, $2, $3, '99213', 'Office visit', $4, $5)""",
        TENANT_A, enc_id, uuid.uuid4(), user_id, datetime.now(timezone.utc),
    )


# refresh_tokens.user_id
@pytest.mark.integration
async def test_fk_refresh_tokens_user_id(conn):
    await _expect_fk(conn,
        """INSERT INTO refresh_tokens (token_hash, family_id, expires_at, user_id)
           VALUES ($1, $2, $3, $4)""",
        "hash-" + uuid.uuid4().hex, uuid.uuid4(),
        datetime.now(timezone.utc), uuid.uuid4(),
    )
