"""
Appointments Module — RecurrenceService
=========================================
Generates child appointments from a parent appointment and a recurrence rule.

Supported rule dict keys:
  - frequency: "daily" | "weekly" | "monthly"
  - interval: int (e.g. 1 = every week, 2 = every two weeks)
  - count: int (number of occurrences to generate, including parent)

Generated appointments inherit all fields from the parent but receive
a new UUID and have parent_appointment_id set to the original.
No PHI in log messages — UUIDs only.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from .models import Appointment
from .enums import AppointmentStatus
from .service import AppointmentService

log = structlog.get_logger(__name__)
_audit = AuditService()

# Mapping of frequency label to timedelta factory
_FREQUENCY_DELTAS: dict[str, Any] = {
    "daily": lambda interval: timedelta(days=interval),
    "weekly": lambda interval: timedelta(weeks=interval),
    "monthly": lambda interval: timedelta(days=30 * interval),  # approximation
}


class RecurrenceService:
    """Service layer for generating recurring appointment series."""

    async def generate_recurring(
        self,
        db: AsyncSession,
        appointment_id: uuid.UUID,
        rule: dict[str, Any],
        user_id: uuid.UUID,
    ) -> list[Appointment]:
        """
        Given a parent appointment and a recurrence rule, create N-1 child
        appointments (the parent itself counts as occurrence #1).

        Args:
            db: Async database session.
            appointment_id: UUID of the parent appointment.
            rule: Dict with keys: frequency (str), interval (int), count (int).
            user_id: UUID of the user triggering the recurrence generation.

        Returns:
            List of newly created child Appointment instances.
        """
        appt_svc = AppointmentService()
        parent = await appt_svc.get_appointment(db, appointment_id)

        frequency: str = rule.get("frequency", "weekly")
        interval: int = int(rule.get("interval", 1))
        count: int = int(rule.get("count", 1))

        if frequency not in _FREQUENCY_DELTAS:
            raise ValueError(
                f"Unsupported recurrence frequency '{frequency}'. "
                f"Valid options: {list(_FREQUENCY_DELTAS.keys())}"
            )

        delta = _FREQUENCY_DELTAS[frequency](interval)
        duration = parent.scheduled_end - parent.scheduled_start

        # Mark parent as recurring and store the rule
        parent.is_recurring = True
        parent.recurrence_rule = rule
        await db.flush()

        children: list[Appointment] = []
        current_start = parent.scheduled_start

        # Generate occurrences 2..count (parent is occurrence 1)
        for _ in range(count - 1):
            current_start = current_start + delta
            current_end = current_start + duration

            child = Appointment(
                tenant_id=parent.tenant_id,
                patient_id=parent.patient_id,
                clinician_id=parent.clinician_id,
                appointment_type=parent.appointment_type,
                status=AppointmentStatus.SCHEDULED,
                scheduled_start=current_start,
                scheduled_end=current_end,
                reason=parent.reason,
                notes=parent.notes,
                is_recurring=True,
                recurrence_rule=rule,
                parent_appointment_id=parent.id,
                created_by=user_id,
            )
            db.add(child)
            await db.flush()
            await _audit.log_action(
                db,
                action="appointment.recurring_child_created",
                resource_id=str(child.id),
                tenant_id=str(parent.tenant_id),
                user_id=str(user_id),
            )
            children.append(child)

        await db.commit()
        log.info(
            "recurrence.generated",
            parent_id=str(parent.id),
            children_count=len(children),
        )
        return children
