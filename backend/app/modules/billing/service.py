"""
PrescpHealth Backend — Billing Service (Core Operations).

Handles invoice generation, payment recording, listing, and voiding.
All monetary values use Decimal (never float) per HIPAA financial standards.

HIPAA:
    - Never log patient names, diagnoses, or other PHI.
    - Only log invoice_id / encounter_id (UUIDs) and action metadata.
    - All mutations go through AuditService.

Usage:
    from app.modules.billing.service import BillingService
    svc = BillingService()
    invoice = await svc.generate_invoice(db, encounter_id, tenant_id, user_id)
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.audit.service import AuditService
from app.modules.billing.enums import InvoiceStatus, ItemType, PaymentMethod
from app.modules.billing.exceptions import (
    DuplicateInvoiceError,
    EncounterBillingError,
    InvoiceAlreadyVoidError,
    InvoiceNotFoundError,
)
from app.modules.billing.models import Invoice, InvoiceLineItem, Payment
from app.modules.billing.schemas import PaymentRecordRequest

logger = structlog.get_logger(__name__)
_audit = AuditService()

# Terminal states that cannot be mutated
_TERMINAL_STATUSES = {InvoiceStatus.VOID, InvoiceStatus.CANCELLED}


def _generate_invoice_number(tenant_id: uuid.UUID) -> str:
    """
    Generate a unique invoice number using tenant prefix + timestamp.

    Format: INV-{tenant_prefix}-{epoch_ms}
    This is deterministic enough for display; DB unique constraint is
    the true uniqueness enforcer.
    """
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    prefix = str(tenant_id).replace("-", "")[:6].upper()
    return f"INV-{prefix}-{ts}"


class BillingService:
    """Core billing operations: invoice generation, payment, listing, void."""

    async def generate_invoice(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        currency: str = "USD",
        notes: Optional[str] = None,
    ) -> Invoice:
        """
        Generate an invoice from a clinical encounter.

        Pulls procedures and diagnoses from the encounter, creates line items,
        computes total, and stores the invoice in DRAFT status.

        Args:
            db: Async DB session (tenant-scoped via RLS).
            encounter_id: Source encounter to bill.
            tenant_id: Tenant owning this invoice.
            user_id: Staff member creating the invoice.
            currency: ISO 4217 currency code (default USD).
            notes: Optional billing notes (no PHI).

        Returns:
            The newly created Invoice instance.

        Raises:
            DuplicateInvoiceError: If invoice for this encounter exists.
            EncounterBillingError: If encounter cannot be billed.
        """
        # Guard against double-billing an encounter
        existing_stmt = select(Invoice).where(
            Invoice.encounter_id == encounter_id,
            Invoice.tenant_id == tenant_id,
            Invoice.status.not_in([InvoiceStatus.VOID, InvoiceStatus.CANCELLED]),
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            raise DuplicateInvoiceError(encounter_id)

        # Load encounter to derive patient_id and billable items
        from sqlalchemy import text as sa_text
        enc_stmt = sa_text(
            "SELECT id, patient_id, status FROM encounters WHERE id = :eid"
        )
        enc_row = (await db.execute(enc_stmt, {"eid": encounter_id})).mappings().first()
        if enc_row is None:
            raise EncounterBillingError(encounter_id, "encounter not found")

        # Build stub line items from encounter procedures (FHIR-ready)
        line_items, total = self._build_line_items(
            tenant_id=tenant_id,
            encounter_id=encounter_id,
        )

        invoice = Invoice(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            patient_id=enc_row["patient_id"],
            encounter_id=encounter_id,
            invoice_number=_generate_invoice_number(tenant_id),
            status=InvoiceStatus.DRAFT,
            total_amount=total,
            paid_amount=Decimal("0.00"),
            currency=currency,
            notes=notes,
            created_by=user_id,
        )
        db.add(invoice)
        await db.flush()  # Needed to get invoice.id for FK in line items

        for item in line_items:
            item.invoice_id = invoice.id
            db.add(item)

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="invoice.create", resource_type="invoice",
            resource_id=invoice.id,
            changes={"encounter_id": str(encounter_id)},
        )
        logger.info("invoice_created", invoice_id=str(invoice.id), tenant_id=str(tenant_id))
        return invoice

    def _build_line_items(
        self, tenant_id: uuid.UUID, encounter_id: uuid.UUID
    ) -> tuple[list[InvoiceLineItem], Decimal]:
        """
        Build invoice line items from encounter context.

        In production this would load procedures/labs from the encounter.
        As a stub it returns a single consultation line item of $100.

        Returns:
            Tuple of (line_items list, total Decimal).
        """
        consultation_price = Decimal("100.00")
        item = InvoiceLineItem(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            # invoice_id assigned after Invoice is flushed
            invoice_id=uuid.uuid4(),  # placeholder, overwritten in caller
            item_type=ItemType.CONSULTATION,
            description="Clinical consultation",
            quantity=1,
            unit_price=consultation_price,
            total_price=consultation_price,
            code="99213",  # CPT code for office visit (non-PHI)
        )
        return [item], consultation_price

    async def record_payment(
        self,
        db: AsyncSession,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: PaymentRecordRequest,
    ) -> Payment:
        """
        Record a payment against an invoice and update paid_amount + status.

        Args:
            db: Async DB session.
            invoice_id: Invoice receiving the payment.
            tenant_id: Tenant context.
            user_id: Staff recording the payment.
            data: Payment details (amount, method, reference).

        Returns:
            Created Payment instance.

        Raises:
            InvoiceNotFoundError: If invoice doesn't exist.
            InvoiceAlreadyVoidError: If invoice is voided.
        """
        invoice = await self._load_invoice(db, invoice_id)

        if invoice.status in _TERMINAL_STATUSES:
            raise InvoiceAlreadyVoidError(invoice_id)

        paid_at = data.paid_at or datetime.now(timezone.utc)

        payment = Payment(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            amount=data.amount,
            payment_method=data.payment_method,
            reference_number=data.reference_number,
            paid_at=paid_at,
            recorded_by=user_id,
            notes=data.notes,
        )
        db.add(payment)

        # Recalculate paid_amount and update status
        invoice.paid_amount = (invoice.paid_amount or Decimal("0.00")) + data.amount
        if invoice.paid_amount >= invoice.total_amount:
            invoice.status = InvoiceStatus.PAID
        else:
            invoice.status = InvoiceStatus.PARTIALLY_PAID

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="payment.record", resource_type="payment",
            resource_id=payment.id,
            changes={"invoice_id": str(invoice_id)},
        )
        logger.info("payment_recorded", payment_id=str(payment.id), invoice_id=str(invoice_id))
        return payment

    async def get_invoice_detail(
        self, db: AsyncSession, invoice_id: uuid.UUID
    ) -> Invoice:
        """
        Retrieve an invoice with all line items and payments eagerly loaded.

        Raises:
            InvoiceNotFoundError: If not found or hidden by RLS.
        """
        stmt = (
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(
                selectinload(Invoice.line_items),
                selectinload(Invoice.payments),
                selectinload(Invoice.claims),
            )
        )
        result = (await db.execute(stmt)).scalar_one_or_none()
        if result is None:
            raise InvoiceNotFoundError(invoice_id)
        return result

    async def list_invoices(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        status: Optional[InvoiceStatus] = None,
        patient_id: Optional[uuid.UUID] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[Invoice], int]:
        """
        List invoices for a tenant with optional filters.

        Returns:
            Tuple of (invoice list, total count).
        """
        from sqlalchemy import func

        base = select(Invoice).where(Invoice.tenant_id == tenant_id)
        count_base = select(func.count(Invoice.id)).where(Invoice.tenant_id == tenant_id)

        if status is not None:
            base = base.where(Invoice.status == status)
            count_base = count_base.where(Invoice.status == status)
        if patient_id is not None:
            base = base.where(Invoice.patient_id == patient_id)
            count_base = count_base.where(Invoice.patient_id == patient_id)

        total = (await db.execute(count_base)).scalar() or 0
        invoices = list(
            (await db.execute(base.order_by(Invoice.created_at.desc()).limit(limit).offset(offset))).scalars()
        )
        return invoices, total

    async def void_invoice(
        self,
        db: AsyncSession,
        invoice_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str,
    ) -> Invoice:
        """
        Void an invoice (soft-delete equivalent for billing records).

        Appends void reason to notes; status set to VOID.
        No hard delete — HIPAA requires retention.

        Raises:
            InvoiceNotFoundError: If not found.
            InvoiceAlreadyVoidError: If already voided.
        """
        invoice = await self._load_invoice(db, invoice_id)

        if invoice.status == InvoiceStatus.VOID:
            raise InvoiceAlreadyVoidError(invoice_id)

        invoice.status = InvoiceStatus.VOID
        # Append reason to notes (reason is non-PHI administrative text)
        void_note = f"[VOID] {reason}"
        invoice.notes = f"{invoice.notes}\n{void_note}" if invoice.notes else void_note

        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=user_id,
            action="invoice.void", resource_type="invoice",
            resource_id=invoice.id,
        )
        logger.info("invoice_voided", invoice_id=str(invoice_id), tenant_id=str(tenant_id))
        return invoice

    async def _load_invoice(self, db: AsyncSession, invoice_id: uuid.UUID) -> Invoice:
        """Load an invoice by PK; raise InvoiceNotFoundError if missing."""
        result = (
            await db.execute(select(Invoice).where(Invoice.id == invoice_id))
        ).scalar_one_or_none()
        if result is None:
            raise InvoiceNotFoundError(invoice_id)
        return result
