"""
Unique constraint tests — one per constraint defined in AGENTS.md.

- measurements: (patient_id, measurement_type, recorded_at, value)
- patients: (tenant_id, medical_record_number)
- code_catalogs: (catalog_type, code)
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


@pytest.mark.integration
async def test_unique_constraint_measurement_idempotency(conn):
    """Duplicate (patient_id, measurement_type, recorded_at, value) rejected."""
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, $2, 'MRN-UQ-MEAS', 'Test', 'Beta', '1990-01-01', 'Male', $3)""",
        patient_id, TENANT_A, user_id,
    )
    recorded_at = datetime(2026, 2, 1, 8, 0, tzinfo=timezone.utc)
    await conn.execute(
        """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
           value, unit, recorded_at, recorded_by, source)
           VALUES ($1, $2, 'hba1c', 6.5, '%', $3, $4, 'manual')""",
        TENANT_A, patient_id, recorded_at, user_id,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            """INSERT INTO measurements (tenant_id, patient_id, measurement_type,
               value, unit, recorded_at, recorded_by, source)
               VALUES ($1, $2, 'hba1c', 6.5, '%', $3, $4, 'manual')""",
            TENANT_A, patient_id, recorded_at, user_id,
        )


@pytest.mark.integration
async def test_unique_constraint_patient_tenant_mrn(conn):
    """Duplicate (tenant_id, medical_record_number) rejected."""
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO patients (tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, 'MRN-DUP-001', 'Test', 'Gamma', '1985-05-05', 'Female', $2)""",
        TENANT_A, user_id,
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            """INSERT INTO patients (tenant_id, medical_record_number,
               first_name, last_name, date_of_birth, gender, created_by)
               VALUES ($1, 'MRN-DUP-001', 'Test', 'Delta', '1986-06-06', 'Male', $2)""",
            TENANT_A, user_id,
        )


@pytest.mark.integration
async def test_unique_constraint_code_catalog_type_code(conn):
    """Duplicate (catalog_type, code) rejected."""
    await conn.execute(
        """INSERT INTO code_catalogs (catalog_type, code, display_name_en)
           VALUES ('icd10', 'TEST.UNIQ.001', 'Synthetic test code')""",
    )
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(
            """INSERT INTO code_catalogs (catalog_type, code, display_name_en)
               VALUES ('icd10', 'TEST.UNIQ.001', 'Duplicate attempt')""",
        )
