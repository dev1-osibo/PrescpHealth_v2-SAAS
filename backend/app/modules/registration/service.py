"""
Registration Module — RegistrationService
===========================================
Manages the patient intake registration workflow:
  1. start_intake — create minimal patient record
  2. update_registration — incrementally add fields
  3. complete_registration — validate + generate MRN + activate

PHI NOTICE: No patient names, DOBs, or identifiers in log messages.
Log only patient UUID and action name.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .exceptions import RegistrationNotFoundError, RegistrationIncompleteError

log = structlog.get_logger(__name__)
_audit = AuditService()

# Required fields that must be present to complete registration
_REQUIRED_FIELDS = [
    "first_name", "last_name", "date_of_birth",
    "phone", "address",
]


class RegistrationService:
    """Service layer for patient intake and registration workflows."""

    async def start_intake(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        first_name: str,
        last_name: str,
        date_of_birth: Any,
        created_by: uuid.UUID,
    ) -> Any:
        """
        Create a partial patient record with name and DOB only.

        Imports Patient model at call time to avoid circular imports.
        Returns the newly created Patient ORM object.
        """
        # Late import to avoid potential circular dependency
        from sqlalchemy import text

        # We create a minimal patient record using raw SQL-safe ORM construction.
        # The actual Patient model lives in the patients module.
        # For staging, we define a lightweight dict-like structure and delegate
        # to the patients table via direct ORM insert.
        from sqlalchemy import insert

        patient_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        stmt = text(
            """
            INSERT INTO patients (id, tenant_id, first_name, last_name, date_of_birth,
                                  status, created_at, updated_at)
            VALUES (:id, :tenant_id, :first_name, :last_name, :date_of_birth,
                    'intake', :now, :now)
            RETURNING id
            """
        )
        await db.execute(
            stmt,
            {
                "id": patient_id, "tenant_id": tenant_id,
                "first_name": first_name, "last_name": last_name,
                "date_of_birth": date_of_birth, "now": now,
            },
        )
        await db.flush()
        await _audit.log_action(
            db, action="registration.intake_started", resource_id=str(patient_id),
            tenant_id=str(tenant_id), user_id=str(created_by),
        )
        await db.commit()
        log.info("registration.intake_started", patient_id=str(patient_id))
        return patient_id

    async def update_registration(
        self, db: AsyncSession, patient_id: uuid.UUID,
        data: dict[str, Any], user_id: uuid.UUID,
    ) -> None:
        """
        Incrementally update patient registration fields.
        Only non-None values in data are applied.
        """
        from sqlalchemy import text, update

        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return
        update_data["updated_at"] = datetime.now(timezone.utc)
        set_clause = ", ".join(f"{k} = :{k}" for k in update_data)
        stmt = text(
            f"UPDATE patients SET {set_clause} WHERE id = :patient_id"
        )
        update_data["patient_id"] = patient_id
        await db.execute(stmt, update_data)
        await db.flush()
        await _audit.log_action(
            db, action="registration.updated", resource_id=str(patient_id),
            tenant_id="unknown", user_id=str(user_id),
        )
        await db.commit()

    async def complete_registration(
        self, db: AsyncSession, patient_id: uuid.UUID, user_id: uuid.UUID,
    ) -> str:
        """
        Validate that all required fields are present, generate MRN,
        and set patient status to active. Returns generated MRN string.
        """
        from sqlalchemy import text

        result = await db.execute(
            text("SELECT * FROM patients WHERE id = :id"),
            {"id": patient_id},
        )
        row = result.mappings().first()
        if not row:
            raise RegistrationNotFoundError(str(patient_id))
        missing = [f for f in _REQUIRED_FIELDS if not row.get(f)]
        if missing:
            raise RegistrationIncompleteError(missing)

        mrn = await self.generate_mrn(db, uuid.UUID(str(row["tenant_id"])))
        now = datetime.now(timezone.utc)
        await db.execute(
            text(
                "UPDATE patients SET status = 'active', mrn = :mrn, updated_at = :now "
                "WHERE id = :id"
            ),
            {"mrn": mrn, "now": now, "id": patient_id},
        )
        await db.flush()
        await _audit.log_action(
            db, action="registration.completed", resource_id=str(patient_id),
            tenant_id=str(row["tenant_id"]), user_id=str(user_id),
        )
        await db.commit()
        log.info("registration.completed", patient_id=str(patient_id))
        return mrn

    async def generate_mrn(
        self, db: AsyncSession, tenant_id: uuid.UUID,
    ) -> str:
        """
        Generate a unique MRN in format MRN-{TENANT_SHORT}-{SEQUENCE}.

        TENANT_SHORT = first 6 hex chars of tenant_id (no hyphens).
        SEQUENCE = count of existing patients for tenant + 1, zero-padded to 6 digits.
        """
        from sqlalchemy import text

        result = await db.execute(
            text("SELECT COUNT(*) FROM patients WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        count = result.scalar_one()
        tenant_short = tenant_id.hex[:6].upper()
        sequence = str(count + 1).zfill(6)
        return f"MRN-{tenant_short}-{sequence}"
