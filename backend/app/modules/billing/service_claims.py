"""
PrescpHealth Backend — Billing Service: Insurance Claims.

Handles insurance claim submission and status updates.
Separated from the core billing service to keep files under 150 lines.

HIPAA:
    - denial_reason is clinical text — logged as field name only, never value.
    - Only claim UUIDs appear in log messages.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.billing.enums import ClaimStatus
from app.modules.billing.exceptions import (
    ClaimNotFoundError,
    InvoiceNotFoundError,
)
from app.modules.billing.models import InsuranceClaim, Invoice
from app.modules.billing.schemas import (
    ClaimStatusUpdateRequest,
    ClaimSubmitRequest,
)

logger = structlog.get_logger(__name__)
_audit = AuditService()

# Statuses that indicate the claim has reached a final resolution
_RESOLVED_STATUSES = {ClaimStatus.APPROVED, ClaimStatus.PARTIALLY_APPROVED, ClaimStatus.DENIED}


class ClaimsService:
    """Insurance claim lifecycle management."""

    async def submit_claim(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ClaimSubmitRequest,
    ) -> InsuranceClaim:
        """
        Submit an insurance claim for an invoice.

        Verifies the invoice exists, creates the claim in SUBMITTED status,
        and audit-logs the action.

        Args:
            db: Async DB session (tenant RLS applied).
            tenant_id: Tenant owning the claim.
            user_id: Staff member submitting the claim.
            data: Claim submission details.

        Returns:
            Newly created InsuranceClaim instance.

        Raises:
            InvoiceNotFoundError: If the referenced invoice doesn't exist.
        """
        # Verify invoice exists (RLS ensures tenant isolation)
        inv_result = (
            await db.execute(select(Invoice).where(Invoice.id == data.invoice_id))
        ).scalar_one_or_none()
        if inv_result is None:
            raise InvoiceNotFoundError(data.invoice_id)

        claim = InsuranceClaim(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            invoice_id=data.invoice_id,
            patient_id=inv_result.patient_id,
            insurance_provider=data.insurance_provider,
            policy_number=data.policy_number,
            claim_number=None,  # Assigned by insurer after submission
            status=ClaimStatus.SUBMITTED,
            submitted_amount=data.submitted_amount,
            approved_amount=None,
            denial_reason=None,
            submitted_at=datetime.now(timezone.utc),
            resolved_at=None,
        )
        db.add(claim)
        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="insurance_claim.submit", resource_type="insurance_claim",
            resource_id=claim.id,
            changes={"invoice_id": str(data.invoice_id)},
        )
        logger.info("claim_submitted", claim_id=str(claim.id), tenant_id=str(tenant_id))
        return claim

    async def update_claim_status(
        self,
        db: AsyncSession,
        claim_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: ClaimStatusUpdateRequest,
    ) -> InsuranceClaim:
        """
        Update claim status (approval, partial approval, denial, resubmission).

        Sets resolved_at timestamp when the claim reaches a terminal status.

        Args:
            db: Async DB session.
            claim_id: Claim to update.
            tenant_id: Tenant context.
            user_id: Staff member processing the update.
            data: New status and optional supporting fields.

        Returns:
            Updated InsuranceClaim instance.

        Raises:
            ClaimNotFoundError: If claim doesn't exist or hidden by RLS.
        """
        claim = await self._load_claim(db, claim_id)

        claim.status = data.status

        if data.claim_number is not None:
            claim.claim_number = data.claim_number

        if data.approved_amount is not None:
            claim.approved_amount = data.approved_amount

        # denial_reason: log only that it was set, never log the value (PHI risk)
        if data.denial_reason is not None:
            claim.denial_reason = data.denial_reason

        # Mark resolved timestamp when a final state is reached
        if data.status in _RESOLVED_STATUSES:
            claim.resolved_at = datetime.now(timezone.utc)

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="insurance_claim.status_update", resource_type="insurance_claim",
            resource_id=claim.id,
            changes={"new_status": data.status.value},
        )
        logger.info(
            "claim_status_updated",
            claim_id=str(claim_id),
            new_status=data.status.value,
            tenant_id=str(tenant_id),
        )
        return claim

    async def list_claims(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        status: Optional[ClaimStatus] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[InsuranceClaim], int]:
        """
        List insurance claims for a tenant with optional status filter.

        Returns:
            Tuple of (claims list, total count).
        """
        from sqlalchemy import func

        base = select(InsuranceClaim).where(InsuranceClaim.tenant_id == tenant_id)
        count_base = select(func.count(InsuranceClaim.id)).where(
            InsuranceClaim.tenant_id == tenant_id
        )

        if status is not None:
            base = base.where(InsuranceClaim.status == status)
            count_base = count_base.where(InsuranceClaim.status == status)

        total = (await db.execute(count_base)).scalar() or 0
        claims = list(
            (
                await db.execute(
                    base.order_by(InsuranceClaim.submitted_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).scalars()
        )
        return claims, total

    async def _load_claim(self, db: AsyncSession, claim_id: uuid.UUID) -> InsuranceClaim:
        """Load claim by PK; raise ClaimNotFoundError if missing."""
        result = (
            await db.execute(
                select(InsuranceClaim).where(InsuranceClaim.id == claim_id)
            )
        ).scalar_one_or_none()
        if result is None:
            raise ClaimNotFoundError(claim_id)
        return result
