"""
Registration Module — ConsentService
=======================================
Manages consent capture, revocation, and active-consent checks.

PHI NOTICE:
  - digital_signature field is NEVER logged — it contains biometric data.
  - patient_id logged as UUID only.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .models import Consent
from .enums import ConsentType
from .exceptions import ConsentNotFoundError, ConsentAlreadyRevokedError

log = structlog.get_logger(__name__)
_audit = AuditService()


class ConsentService:
    """Service layer for patient consent management."""

    async def capture_consent(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        consent_type: ConsentType,
        version: str,
        is_granted: bool,
        captured_by: uuid.UUID,
        digital_signature: Optional[str] = None,
        witness_name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        metadata: Optional[dict] = None,
    ) -> Consent:
        """
        Record a patient consent event.

        digital_signature is stored as-is (base64) but is NEVER written to logs.
        """
        consent = Consent(
            tenant_id=tenant_id,
            patient_id=patient_id,
            consent_type=consent_type,
            version=version,
            is_granted=is_granted,
            granted_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            digital_signature=digital_signature,  # PHI — never log
            witness_name=witness_name,
            captured_by=captured_by,
            consent_metadata=metadata,
        )
        db.add(consent)
        await db.flush()
        # Log consent UUID and type only — NO patient name, NO signature
        await _audit.log_action(
            db,
            action=f"consent.captured.{consent_type}",
            resource_id=str(consent.id),
            tenant_id=str(tenant_id),
            user_id=str(captured_by),
        )
        await db.commit()
        await db.refresh(consent)
        log.info(
            "consent.captured",
            consent_id=str(consent.id),
            consent_type=consent_type,
            is_granted=is_granted,
        )
        return consent

    async def get_active_consents(
        self, db: AsyncSession, patient_id: uuid.UUID,
    ) -> list[Consent]:
        """
        Return all non-revoked, non-expired consent records for the patient.

        A consent is active if: revoked_at is NULL AND (expires_at is NULL OR expires_at > now()).
        """
        now = datetime.now(timezone.utc)
        stmt = select(Consent).where(
            and_(
                Consent.patient_id == patient_id,
                Consent.revoked_at.is_(None),
                (Consent.expires_at.is_(None)) | (Consent.expires_at > now),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def revoke_consent(
        self,
        db: AsyncSession,
        consent_id: uuid.UUID,
        reason: str,
        user_id: uuid.UUID,
    ) -> Consent:
        """
        Soft-revoke a consent by setting revoked_at and revocation_reason.
        Raises ConsentAlreadyRevokedError if already revoked.
        """
        stmt = select(Consent).where(Consent.id == consent_id)
        result = await db.execute(stmt)
        consent = result.scalars().first()
        if not consent:
            raise ConsentNotFoundError(str(consent_id))
        if consent.revoked_at is not None:
            raise ConsentAlreadyRevokedError(str(consent_id))
        consent.revoked_at = datetime.now(timezone.utc)
        consent.revocation_reason = reason
        await db.flush()
        await _audit.log_action(
            db,
            action="consent.revoked",
            resource_id=str(consent.id),
            tenant_id=str(consent.tenant_id),
            user_id=str(user_id),
        )
        await db.commit()
        await db.refresh(consent)
        log.info("consent.revoked", consent_id=str(consent.id))
        return consent

    async def check_consent(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        consent_type: ConsentType,
    ) -> bool:
        """
        Return True if the patient has an active (non-revoked, non-expired)
        granted consent of the specified type.
        """
        now = datetime.now(timezone.utc)
        stmt = select(Consent).where(
            and_(
                Consent.patient_id == patient_id,
                Consent.consent_type == consent_type,
                Consent.is_granted.is_(True),
                Consent.revoked_at.is_(None),
                (Consent.expires_at.is_(None)) | (Consent.expires_at > now),
            )
        )
        result = await db.execute(stmt)
        return result.scalars().first() is not None
