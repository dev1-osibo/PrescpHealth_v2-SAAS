"""
Cross-module flow integration tests (DB-layer verification).

These tests verify the persistence-layer behavior of the four flows enumerated
in AGENTS.md, exercising real schemas, FKs, and constraints across modules.

Application-layer behavior (chronic_conditions JSONB sync, LOINC→Measurement
creation) is covered by the property-based tests in
  backend/tests/property/test_emr_encounters.py
  backend/tests/property/test_emr_lab_orders.py
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


async def _mk_patient(conn, mrn: str, chronic_conditions: list | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()
    import json
    cc = json.dumps(chronic_conditions or [])
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by, chronic_conditions)
           VALUES ($1, $2, $3, 'Test', 'XFlow', '1990-01-01', 'Male', $4, $5::jsonb)""",
        patient_id, TENANT_A, mrn, user_id, cc,
    )
    return patient_id, user_id


# ---------------------------------------------------------------------------
# Flow 1: Patient → Encounter → Diagnosis (chronic) → verify chronic_conditions
#         JSONB ARRAY GETS THE CODE APPENDED AT DB LAYER VIA EXPLICIT UPDATE.
# We assert that the persistence schema supports the chronic-condition sync
# pattern: after inserting a chronic diagnosis and performing the documented
# JSONB merge, the patient's chronic_conditions array contains the ICD-10 code.
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_flow_patient_encounter_chronic_diagnosis_sync(conn):
    patient_id, user_id = await _mk_patient(conn, "MRN-XF-CHRONIC", chronic_conditions=[])
    enc_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO encounters (id, tenant_id, patient_id, clinician_id,
           status, encounter_class, reason_for_visit)
           VALUES ($1, $2, $3, $4, 'in_progress', 'ambulatory', 'flow test')""",
        enc_id, TENANT_A, patient_id, user_id,
    )
    dx_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO diagnoses (id, tenant_id, encounter_id, patient_id,
           icd10_code, display_name, is_chronic, is_primary, recorded_by)
           VALUES ($1, $2, $3, $4, 'E11.9', 'Type 2 diabetes', true, true, $5)""",
        dx_id, TENANT_A, enc_id, patient_id, user_id,
    )

    # Persist the chronic-condition into patient JSONB (the service layer does this).
    await conn.execute(
        """UPDATE patients
           SET chronic_conditions = chronic_conditions ||
               jsonb_build_array(jsonb_build_object('code', 'E11.9',
                                                    'display_name', 'Type 2 diabetes'))
           WHERE id = $1""",
        patient_id,
    )

    row = await conn.fetchrow(
        "SELECT chronic_conditions FROM patients WHERE id = $1", patient_id
    )
    import json
    cc = json.loads(row["chronic_conditions"])
    codes = [c["code"] for c in cc]
    assert "E11.9" in codes, f"Expected E11.9 in chronic_conditions, got {codes}"

    # Diagnosis is linked to BOTH patient and encounter
    linked = await conn.fetchrow(
        """SELECT d.id, d.is_chronic, e.patient_id
           FROM diagnoses d JOIN encounters e ON d.encounter_id = e.id
           WHERE d.id = $1""",
        dx_id,
    )
    assert linked is not None and linked["is_chronic"] is True
    assert linked["patient_id"] == patient_id


# ---------------------------------------------------------------------------
# Flow 2: Patient → Encounter → Prescription → verify linked
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_flow_patient_encounter_prescription_linked(conn):
    patient_id, user_id = await _mk_patient(conn, "MRN-XF-RX")
    enc_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO encounters (id, tenant_id, patient_id, clinician_id,
           status, encounter_class, reason_for_visit)
           VALUES ($1, $2, $3, $4, 'in_progress', 'ambulatory', 'flow rx')""",
        enc_id, TENANT_A, patient_id, user_id,
    )
    rx_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO prescriptions (id, tenant_id, patient_id, encounter_id,
           drug_name, atc_code, dosage, frequency, route, prescribed_by,
           refills_allowed, refills_remaining)
           VALUES ($1, $2, $3, $4, 'TestDrug', 'A01AA01', '10mg', 'bid', 'oral', $5, 3, 3)""",
        rx_id, TENANT_A, patient_id, enc_id, user_id,
    )
    row = await conn.fetchrow(
        """SELECT p.id, p.encounter_id, p.patient_id, e.patient_id AS enc_patient
           FROM prescriptions p JOIN encounters e ON p.encounter_id = e.id
           WHERE p.id = $1""",
        rx_id,
    )
    assert row is not None
    assert row["encounter_id"] == enc_id
    assert row["patient_id"] == patient_id
    assert row["enc_patient"] == patient_id


# ---------------------------------------------------------------------------
# Flow 3: Patient → Lab Order → Lab Result → linked Measurement
# We verify the schema supports linking lab_results.measurement_id to a
# created measurement (the service layer creates it from LOINC mapping).
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_flow_patient_lab_order_result_creates_measurement_link(conn):
    patient_id, user_id = await _mk_patient(conn, "MRN-XF-LAB")
    lo_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO lab_orders (id, tenant_id, patient_id, test_name,
           loinc_code, priority, status, ordered_by)
           VALUES ($1, $2, $3, 'Glucose Fasting', '1558-6', 'routine', 'in_progress', $4)""",
        lo_id, TENANT_A, patient_id, user_id,
    )
    # Service layer creates a measurement when LOINC maps; we insert one here
    meas_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO measurements (id, tenant_id, patient_id, measurement_type,
           value, unit, recorded_at, recorded_by, source, is_validated)
           VALUES ($1, $2, $3, 'blood_glucose_fasting', 95.0, 'mg/dL', $4, $5, 'import', true)""",
        meas_id, TENANT_A, patient_id,
        datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc), user_id,
    )
    lr_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO lab_results (id, tenant_id, lab_order_id, value, numeric_value,
           unit, is_abnormal, resulted_at, resulted_by, measurement_id)
           VALUES ($1, $2, $3, '95', 95.0, 'mg/dL', false, $4, $5, $6)""",
        lr_id, TENANT_A, lo_id,
        datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc), user_id, meas_id,
    )
    row = await conn.fetchrow(
        """SELECT lr.id, lr.measurement_id, m.measurement_type, m.patient_id,
                  lo.patient_id AS lo_patient
           FROM lab_results lr
           JOIN measurements m ON lr.measurement_id = m.id
           JOIN lab_orders lo ON lr.lab_order_id = lo.id
           WHERE lr.id = $1""",
        lr_id,
    )
    assert row is not None
    assert row["measurement_id"] == meas_id
    assert row["measurement_type"] == "blood_glucose_fasting"
    assert row["patient_id"] == patient_id
    assert row["lo_patient"] == patient_id


# ---------------------------------------------------------------------------
# Flow 4: Patient → Measurement → Duplicate insert → idempotency unique fires
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_flow_patient_measurement_duplicate_idempotency(conn):
    patient_id, user_id = await _mk_patient(conn, "MRN-XF-IDEMP")
    recorded_at = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    await conn.execute(
        """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
           value, unit, recorded_at, recorded_by, source)
           VALUES ($1, $2, 'systolic_bp', 118.0, 'mmHg', $3, $4, 'manual')""",
        TENANT_A, patient_id, recorded_at, user_id,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
               value, unit, recorded_at, recorded_by, source)
               VALUES ($1, $2, 'systolic_bp', 118.0, 'mmHg', $3, $4, 'manual')""",
            TENANT_A, patient_id, recorded_at, user_id,
        )
