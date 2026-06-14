"""
RLS Isolation tests for new tenant-scoped tables added in modules:
  ai_assistant   -> conversations, messages
  drug_interactions -> medication_records, interaction_results
  risk_engine    -> risk_scores, shap_explanations
  forecast_engine -> forecasts, intervention_simulations
  auth/patients  -> users, patient_versions

For each table:
  1. Insert a row as tenant A (superuser, bypasses RLS for setup).
  2. SET LOCAL ROLE test  (non-superuser, RLS enforced).
  3. SET LOCAL app.current_tenant = '<tenant_B_uuid>'.
  4. SELECT must return zero rows.

Each test wraps in BEGIN/ROLLBACK so the DB stays clean.
"""

import json
import uuid
from datetime import date, datetime, timezone

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


async def _seed_patient(conn, tenant_id: uuid.UUID, mrn: str):
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    await conn.execute(
        """INSERT INTO patients (id, tenant_id, medical_record_number,
           first_name, last_name, date_of_birth, gender, created_by)
           VALUES ($1, $2, $3, 'Test', 'Alpha', '1990-01-01', 'Male', $4)""",
        pid, tenant_id, mrn, uid,
    )
    return pid, uid


async def _seed_user(conn, tenant_id: uuid.UUID, email: str):
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO users (id, tenant_id, email, password_hash, full_name, role)
           VALUES ($1, $2, $3, '$2b$12$fakehashfortest000000000000000000', 'Test User', 'Doctor')""",
        user_id, tenant_id, email,
    )
    return user_id


async def _seed_model_version(conn):
    """Insert a platform-level ModelVersion (not tenant-scoped)."""
    mv_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO model_versions (id, disease, version, artifact_path, metrics, is_active)
           VALUES ($1, 'stroke', '9.9.9-test', '/dev/null', '{}', false)""",
        mv_id,
    )
    return mv_id


async def _switch_to_tenant_b(conn):
    await conn.execute("SET LOCAL ROLE test")
    await conn.execute(f"SET LOCAL app.current_tenant = '{TENANT_B}'")


# ---------------------------------------------------------------------------
# 1. users
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_users(conn):
    user_id = await _seed_user(conn, TENANT_A, "rls-test-user@test-synth.local")
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM users WHERE id = $1", user_id)
    assert row is None, "RLS failed on users: tenant B can see tenant A's user"


# ---------------------------------------------------------------------------
# 2. patient_versions
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_patient_versions(conn):
    pid, uid = await _seed_patient(conn, TENANT_A, "MRN-RLS-PV-001")
    pv_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO patient_versions
           (id, tenant_id, patient_id, version_number, changed_by, change_type, changes, snapshot)
           VALUES ($1, $2, $3, 1, $4, 'create', '{}', '{}')""",
        pv_id, TENANT_A, pid, uid,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM patient_versions WHERE id = $1", pv_id)
    assert row is None, "RLS failed on patient_versions"


# ---------------------------------------------------------------------------
# 3. conversations
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_conversations(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-CONV-001")
    clinician_id = await _seed_user(conn, TENANT_A, "rls-clinician@test-synth.local")
    conv_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO conversations (id, tenant_id, patient_id, clinician_id)
           VALUES ($1, $2, $3, $4)""",
        conv_id, TENANT_A, pid, clinician_id,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM conversations WHERE id = $1", conv_id)
    assert row is None, "RLS failed on conversations"


# ---------------------------------------------------------------------------
# 4. messages
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_messages(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-MSG-001")
    clinician_id = await _seed_user(conn, TENANT_A, "rls-clinician-msg@test-synth.local")
    conv_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO conversations (id, tenant_id, patient_id, clinician_id)
           VALUES ($1, $2, $3, $4)""",
        conv_id, TENANT_A, pid, clinician_id,
    )
    msg_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO messages (id, tenant_id, conversation_id, role, content)
           VALUES ($1, $2, $3, 'user', 'Synthetic test message content')""",
        msg_id, TENANT_A, conv_id,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM messages WHERE id = $1", msg_id)
    assert row is None, "RLS failed on messages"


# ---------------------------------------------------------------------------
# 5. medication_records
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_medication_records(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-MED-001")
    prescriber_id = await _seed_user(conn, TENANT_A, "rls-prescriber@test-synth.local")
    med_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO medication_records
           (id, tenant_id, patient_id, drug_name, drug_code, dosage, frequency,
            route, start_date, prescribed_by)
           VALUES ($1, $2, $3, 'TestDrug-Synth', 'T00001', '10mg', 'once daily',
                   'oral', $4, $5)""",
        med_id, TENANT_A, pid, date(2026, 1, 1), prescriber_id,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM medication_records WHERE id = $1", med_id)
    assert row is None, "RLS failed on medication_records"


# ---------------------------------------------------------------------------
# 6. interaction_results
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_interaction_results(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-IR-001")
    prescriber_id = await _seed_user(conn, TENANT_A, "rls-prescriber-ir@test-synth.local")
    med_a_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO medication_records
           (id, tenant_id, patient_id, drug_name, drug_code, dosage, frequency,
            route, start_date, prescribed_by)
           VALUES ($1, $2, $3, 'DrugA-Synth', 'A00001', '5mg', 'bid',
                   'oral', $4, $5)""",
        med_a_id, TENANT_A, pid, date(2026, 1, 1), prescriber_id,
    )
    ir_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO interaction_results
           (id, tenant_id, patient_id, interaction_type, medication_a_id,
            severity, mechanism, adverse_outcome, recommended_action)
           VALUES ($1, $2, $3, 'DDI', $4, 'Minor', 'Test mechanism',
                   'Test adverse outcome', 'Monitor patient')""",
        ir_id, TENANT_A, pid, med_a_id,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM interaction_results WHERE id = $1", ir_id)
    assert row is None, "RLS failed on interaction_results"


# ---------------------------------------------------------------------------
# 7. risk_scores
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_risk_scores(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-RS-001")
    mv_id = await _seed_model_version(conn)
    rs_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO risk_scores
           (id, tenant_id, patient_id, disease, score, stratum,
            confidence_lower, confidence_upper, model_version_id,
            input_snapshot, computation_id)
           VALUES ($1, $2, $3, 'stroke', 42.00, 'Moderate',
                   38.00, 46.00, $4, '{}', $5)""",
        rs_id, TENANT_A, pid, mv_id, uuid.uuid4(),
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM risk_scores WHERE id = $1", rs_id)
    assert row is None, "RLS failed on risk_scores"


# ---------------------------------------------------------------------------
# 8. shap_explanations
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_shap_explanations(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-SHAP-001")
    mv_id = await _seed_model_version(conn)
    rs_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO risk_scores
           (id, tenant_id, patient_id, disease, score, stratum,
            confidence_lower, confidence_upper, model_version_id,
            input_snapshot, computation_id)
           VALUES ($1, $2, $3, 'cvd', 55.00, 'High',
                   50.00, 60.00, $4, '{}', $5)""",
        rs_id, TENANT_A, pid, mv_id, uuid.uuid4(),
    )
    shap_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO shap_explanations
           (id, tenant_id, risk_score_id, base_value, feature_contributions)
           VALUES ($1, $2, $3, 30.00, '[]')""",
        shap_id, TENANT_A, rs_id,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM shap_explanations WHERE id = $1", shap_id)
    assert row is None, "RLS failed on shap_explanations"


# ---------------------------------------------------------------------------
# 9. forecasts
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_forecasts(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-FC-001")
    fc_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO forecasts
           (id, tenant_id, patient_id, forecast_type, target,
            horizon_months, point_estimate, confidence_lower, confidence_upper)
           VALUES ($1, $2, $3, 'metric', 'systolic_bp', 6, 140.00, 130.00, 150.00)""",
        fc_id, TENANT_A, pid,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM forecasts WHERE id = $1", fc_id)
    assert row is None, "RLS failed on forecasts"


# ---------------------------------------------------------------------------
# 10. intervention_simulations
# ---------------------------------------------------------------------------
@pytest.mark.integration
async def test_rls_isolation_intervention_simulations(conn):
    pid, _ = await _seed_patient(conn, TENANT_A, "MRN-RLS-IS-001")
    fc_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO forecasts
           (id, tenant_id, patient_id, forecast_type, target,
            horizon_months, point_estimate, confidence_lower, confidence_upper)
           VALUES ($1, $2, $3, 'metric', 'systolic_bp', 6, 140.00, 130.00, 150.00)""",
        fc_id, TENANT_A, pid,
    )
    sim_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO intervention_simulations
           (id, tenant_id, patient_id, intervention_type, parameters,
            baseline_forecast_id, simulated_results)
           VALUES ($1, $2, $3, 'weight_loss', '{}', $4, '[]')""",
        sim_id, TENANT_A, pid, fc_id,
    )
    await _switch_to_tenant_b(conn)
    row = await conn.fetchrow("SELECT id FROM intervention_simulations WHERE id = $1", sim_id)
    assert row is None, "RLS failed on intervention_simulations"
