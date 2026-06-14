"""
Appointments Module — WaitlistService
=======================================
Manages patient waitlist entries and promotion logic.
When a slot is freed (via cancellation), the highest-priority
waiting entry for the same clinician/type is offered the slot.
No PHI in log messages — UUIDs only.
"""

import uuid
from datetime import datetime, date, time
from typing import Optional

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .models import Waitlist
from .enums import AppointmentType, WaitlistStatus

log = structlog.get_logger(__name__)
_audit = AuditService()


class WaitlistService:
    """Service layer for waitlist entry management."""

    async def add_to_waitlist(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        appt_type: AppointmentType,
        preferred_date_start: date,
        created_by: uuid.UUID,
        clinician_id: Optional[uuid.UUID] = None,
        preferred_date_end: Optional[date] = None,
        preferred_time_start: Optional[time] = None,
        preferred_time_end: Optional[time] = None,
        priority: int = 0,
        notes: Optional[str] = None,
    ) -> Waitlist:
        """Create a new waitlist entry for the given patient and appointment type."""
        entry = Waitlist(
            tenant_id=tenant_id,
            patient_id=patient_id,
            clinician_id=clinician_id,
            appointment_type=appt_type,
            preferred_date_start=preferred_date_start,
            preferred_date_end=preferred_date_end,
            preferred_time_start=preferred_time_start,
            preferred_time_end=preferred_time_end,
            priority=priority,
            notes=notes,
            status=WaitlistStatus.WAITING,
        )
        db.add(entry)
        await db.flush()
        await _audit.log_action(
            db,
            action="waitlist.added",
            resource_id=str(entry.id),
            tenant_id=str(tenant_id),
            user_id=str(created_by),
        )
        await db.commit()
        await db.refresh(entry)
        return entry

    async def promote_from_waitlist(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        clinician_id: uuid.UUID,
        freed_slot_start: datetime,
        freed_slot_end: datetime,
    ) -> Optional[Waitlist]:
        """
        Find the highest-priority WAITING entry for the given clinician and
        offer them the freed time slot by updating status to OFFERED.

        Returns the promoted entry, or None if no matching entries exist.
        Priority is ascending integer — lower value = higher priority.
        """
        stmt = (
            select(Waitlist)
            .where(
                and_(
                    Waitlist.tenant_id == tenant_id,
                    Waitlist.clinician_id == clinician_id,
                    Waitlist.status == WaitlistStatus.WAITING,
                )
            )
            .order_by(Waitlist.priority.asc(), Waitlist.created_at.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        entry = result.scalars().first()
        if not entry:
            log.info("waitlist.no_candidates", clinician_id=str(clinician_id))
            return None
        entry.status = WaitlistStatus.OFFERED
        await db.flush()
        await _audit.log_action(
            db,
            action="waitlist.promoted",
            resource_id=str(entry.id),
            tenant_id=str(tenant_id),
            user_id="system",
        )
        # NOTE: commit is deferred to caller (cancel()) to keep transaction atomic
        log.info("waitlist.offered", entry_id=str(entry.id))
        return entry
