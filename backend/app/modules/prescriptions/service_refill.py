"""
PrescpHealth Backend — Prescription Refill Service.

Handles the refill processing logic for active prescriptions. A refill
creates a new Dispensing record and decrements the remaining refill count.

Business Rules:
    1. Prescription status MUST be "active" to process a refill
    2. refills_remaining MUST be > 0
    3. Each refill decrements refills_remaining by 1
    4. A Dispensing record is created with is_refill=True
    5. All refill operations are audit-logged (prescription_id only, no PHI)

HIPAA Compliance:
    - Never log drug names, dosages, or dispensed quantities
    - Only log prescription_id (opaque UUID) in audit entries
    - Dispensing details are PHI — stored but never logged

Usage:
    from app.modules.prescriptions.service_refill import RefillService

    refill_svc = RefillService()
    dispensing = await refill_svc.process_refill(
        db=session,
        prescription_id=rx_id,
        user_id=pharmacist_id,
        dispensed_quantity="30 tablets",
    )
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.prescriptions.dispensing_model import Dispensing
from app.modules.prescriptions.enums import PrescriptionStatus
from app.modules.prescriptions.exceptions import (
    InvalidPrescriptionStatusError,
    NoRefillsRemainingError,
    PrescriptionNotFoundError,
)
from app.modules.prescriptions.prescription_model import Prescription

# ---------------------------------------------------------------------------
# Module logger — logs refill operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Shared audit service instance
_audit = AuditService()


class RefillService:
    """
    Processes prescription refills with guard checks.

    Enforces the two-condition refill guard:
    1. Prescription status must be "active"
    2. refills_remaining must be > 0

    If both conditions pass, creates a Dispensing record and decrements
    the remaining count. All operations are audit-logged.
    """

    async def process_refill(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
        user_id: uuid.UUID,
        dispensed_quantity: str,
    ) -> Dispensing:
        """
        Process a prescription refill.

        Validates that the prescription is active and has remaining refills,
        then creates a Dispensing record and decrements refills_remaining.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription to refill.
            user_id: UUID of the staff member processing the refill.
            dispensed_quantity: Amount dispensed (e.g., "30 tablets").

        Returns:
            The created Dispensing record.

        Raises:
            PrescriptionNotFoundError: If prescription_id doesn't exist.
            InvalidPrescriptionStatusError: If status is not "active".
            NoRefillsRemainingError: If refills_remaining is 0.
        """
        # Fetch the prescription
        prescription = await self._get_prescription(db, prescription_id)

        # Guard 1: Status must be "active"
        if prescription.status != PrescriptionStatus.ACTIVE:
            raise InvalidPrescriptionStatusError(
                prescription_id=str(prescription_id),
                current_status=prescription.status,
                required_status=PrescriptionStatus.ACTIVE.value,
                operation="refill",
            )

        # Guard 2: Must have remaining refills
        if prescription.refills_remaining <= 0:
            raise NoRefillsRemainingError(
                prescription_id=str(prescription_id),
            )

        # Decrement refills_remaining
        prescription.refills_remaining -= 1

        # Create the Dispensing record
        dispensing = Dispensing(
            tenant_id=prescription.tenant_id,
            prescription_id=prescription.id,
            dispensed_quantity=dispensed_quantity,
            dispensed_by=user_id,
            dispensed_at=datetime.now(timezone.utc),
            is_refill=True,
        )
        db.add(dispensing)
        await db.flush()

        # Audit log — only prescription_id, never drug details (HIPAA)
        await _audit.log(
            db=db,
            tenant_id=prescription.tenant_id,
            user_id=user_id,
            action="prescription.refill",
            resource_type="prescription",
            resource_id=prescription.id,
            changes={
                "refills_remaining": {
                    "old": prescription.refills_remaining + 1,
                    "new": prescription.refills_remaining,
                },
            },
        )

        logger.info(
            "prescription_refill_processed",
            prescription_id=str(prescription_id),
            refills_remaining=prescription.refills_remaining,
        )

        return dispensing

    async def _get_prescription(
        self,
        db: AsyncSession,
        prescription_id: uuid.UUID,
    ) -> Prescription:
        """
        Fetch a prescription by ID or raise PrescriptionNotFoundError.

        Args:
            db: Async database session.
            prescription_id: UUID of the prescription.

        Returns:
            The Prescription model instance.

        Raises:
            PrescriptionNotFoundError: If not found.
        """
        stmt = select(Prescription).where(Prescription.id == prescription_id)
        result = await db.execute(stmt)
        prescription = result.scalar_one_or_none()

        if prescription is None:
            raise PrescriptionNotFoundError(
                prescription_id=str(prescription_id)
            )

        return prescription
