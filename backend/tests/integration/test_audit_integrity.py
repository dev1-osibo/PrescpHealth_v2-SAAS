"""
Audit log append-only integrity tests.

Audit_logs has only INSERT and SELECT policies; UPDATE and DELETE policies do
not exist, so RLS blocks both operations for non-superusers.

  1. INSERT audit row → attempt UPDATE → 0 rows affected (RLS blocks).
  2. INSERT audit row → attempt DELETE → 0 rows affected (RLS blocks).

The 'test' role (non-superuser) is required because postgres bypasses RLS.
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
async def test_audit_log_update_blocked_by_rls(conn):
    """No UPDATE policy on audit_logs — non-superuser update affects 0 rows."""
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, created_at)
           VALUES ($1, $2, 'patient.create', 'patient', $3)""",
        TENANT_A, user_id, datetime.now(timezone.utc),
    )
    await conn.execute("SET LOCAL ROLE test")
    await conn.execute(f"SET LOCAL app.current_tenant = '{TENANT_A}'")
    result = await conn.execute(
        "UPDATE audit_logs SET action = 'tampered' WHERE user_id = $1",
        user_id,
    )
    rows_affected = int(result.split(" ")[-1])
    assert rows_affected == 0, (
        f"Audit log UPDATE not blocked by RLS — {rows_affected} rows affected"
    )


@pytest.mark.integration
async def test_audit_log_delete_blocked_by_rls(conn):
    """No DELETE policy on audit_logs — non-superuser delete affects 0 rows."""
    user_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, created_at)
           VALUES ($1, $2, 'patient.delete', 'patient', $3)""",
        TENANT_A, user_id, datetime.now(timezone.utc),
    )
    await conn.execute("SET LOCAL ROLE test")
    await conn.execute(f"SET LOCAL app.current_tenant = '{TENANT_A}'")
    result = await conn.execute(
        "DELETE FROM audit_logs WHERE user_id = $1",
        user_id,
    )
    rows_affected = int(result.split(" ")[-1])
    assert rows_affected == 0, (
        f"Audit log DELETE not blocked by RLS — {rows_affected} rows affected"
    )
