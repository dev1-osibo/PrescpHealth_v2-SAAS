"""
Referrals Module — ReferralService
=====================================
Core CRUD and workflow operations for referrals.
Status transitions are validated against the allowed transition map.
All mutations are audit-logged. No PHI in log messages.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .models import Referral
from .enums import ReferralUrgency, ReferralStatus, VALID_TRANSITIONS
from .exceptions import ReferralNotFoundError, InvalidStatusTransitionError

log = structlog.get_logger(__name__)
_audit = AuditService()


class ReferralService:
    """Service layer for referral lifecycle management."""

    async def create_referral(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        referring_clinician_id: uuid.UUID,
        specialty: str,
        urgency: ReferralUrgency,
        reason: str,
        encounter_id: Optional[uuid.UUID] = None,
        receiving_clinician_id: Optional[uuid.UUID] = None,
        clinical_summary: Optional[str] = None,
        referral_letter: Optional[dict] = None,
        scheduled_date: Optional[datetime] = None,
    ) -> Referral:
        """Create a new referral record in PENDING status."""
        ref = Referral(
            tenant_id=tenant_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            referring_clinician_id=referring_clinician_id,
            receiving_clinician_id=receiving_clinician_id,
            specialty=specialty,
            urgency=urgency,
            reason=reason,
            clinical_summary=clinical_summary,
            referral_letter=referral_letter,
            scheduled_date=scheduled_date,
            status=ReferralStatus.PENDING,
        )
        db.add(ref)
        await db.flush()
        await _audit.log_action(
            db, action="referral.created", resource_id=str(ref.id),
            tenant_id=str(tenant_id), user_id=str(referring_clinician_id),
        )
        await db.commit()
        await db.refresh(ref)
        return ref

    async def update_status(
        self,
        db: AsyncSession,
        referral_id: uuid.UUID,
        new_status: ReferralStatus,
        user_id: uuid.UUID,
    ) -> Referral:
        """Validate and apply a status transition to the referral."""
        ref = await self.get_referral(db, referral_id)
        allowed = VALID_TRANSITIONS.get(ref.status, [])
        if new_status not in allowed:
            raise InvalidStatusTransitionError(str(referral_id), ref.status, new_status)
        ref.status = new_status
        await db.flush()
        await _audit.log_action(
            db, action=f"referral.status_updated.{new_status}",
            resource_id=str(ref.id), tenant_id=str(ref.tenant_id),
            user_id=str(user_id),
        )
        await db.commit()
        await db.refresh(ref)
        return ref

    async def complete_referral(
        self,
        db: AsyncSession,
        referral_id: uuid.UUID,
        specialist_findings: str,
        specialist_recommendations: str,
        user_id: uuid.UUID,
    ) -> Referral:
        """
        Record specialist findings and transition status to completed.
        Referral must currently be in IN_PROGRESS status.
        """
        ref = await self.get_referral(db, referral_id)
        # Transition through in_progress → completed
        if ref.status == ReferralStatus.ACCEPTED or ref.status == ReferralStatus.SCHEDULED:
            ref.status = ReferralStatus.IN_PROGRESS
            await db.flush()
        if ref.status != ReferralStatus.IN_PROGRESS:
            raise InvalidStatusTransitionError(
                str(referral_id), ref.status, ReferralStatus.COMPLETED
            )
        ref.specialist_findings = specialist_findings
        ref.specialist_recommendations = specialist_recommendations
        ref.status = ReferralStatus.COMPLETED
        ref.completed_at = datetime.now(timezone.utc)
        await db.flush()
        await _audit.log_action(
            db, action="referral.completed", resource_id=str(ref.id),
            tenant_id=str(ref.tenant_id), user_id=str(user_id),
        )
        await db.commit()
        await db.refresh(ref)
        return ref

    async def get_referral(
        self, db: AsyncSession, referral_id: uuid.UUID,
    ) -> Referral:
        """Fetch a single referral by primary key or raise ReferralNotFoundError."""
        stmt = select(Referral).where(Referral.id == referral_id)
        result = await db.execute(stmt)
        ref = result.scalars().first()
        if not ref:
            raise ReferralNotFoundError(str(referral_id))
        return ref

    async def list_referrals(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: Optional[uuid.UUID] = None,
        status: Optional[ReferralStatus] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[Referral], int]:
        """Return a paginated list of referrals filtered by optional patient or status."""
        filters = [Referral.tenant_id == tenant_id]
        if patient_id:
            filters.append(Referral.patient_id == patient_id)
        if status:
            filters.append(Referral.status == status)
        stmt = (
            select(Referral)
            .where(and_(*filters))
            .order_by(Referral.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items = list(result.scalars().all())
        # Count total matching rows
        from sqlalchemy import func
        count_stmt = select(func.count(Referral.id)).where(and_(*filters))
        count_result = await db.execute(count_stmt)
        total = count_result.scalar_one()
        return items, total
