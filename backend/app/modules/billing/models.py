"""
PrescpHealth Backend — Billing ORM Models.

Defines four tables:
    invoices            — Per-encounter billing records
    invoice_line_items  — Individual charges on an invoice
    payments            — Cash/card/insurance payments against invoices
    insurance_claims    — Insurance claim lifecycle records

All tables:
    - Use TenantMixin (RLS + timestamps)
    - Use Decimal(10, 2) for all monetary columns (NEVER float)
    - Are soft-deletable via InvoiceStatus.VOID / ClaimStatus.DENIED
    - Use string-based ForeignKey references to avoid circular imports
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.billing.enums import (
    ClaimStatus,
    InvoiceStatus,
    ItemType,
    PaymentMethod,
)


class Invoice(TenantMixin, Base):
    """Patient invoice generated from a completed encounter."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Surrogate PK",
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True,
    )
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=False, index=True,
    )
    # invoice_number is unique per tenant (enforced via unique constraint below)
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        String(32), nullable=False, default=InvoiceStatus.DRAFT,
    )
    # Decimal(10,2) — never float for money
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0.00"),
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", comment="ISO 4217 currency code",
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )

    __table_args__ = (
        # invoice_number uniqueness scoped per tenant
        UniqueConstraint("tenant_id", "invoice_number", name="uq_invoice_number_per_tenant"),
    )

    # Relationships for eager loading
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem", back_populates="invoice", lazy="select",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="invoice", lazy="select",
    )
    claims: Mapped[list["InsuranceClaim"]] = relationship(
        "InsuranceClaim", back_populates="invoice", lazy="select",
    )


class InvoiceLineItem(TenantMixin, Base):
    """A single billable line on an invoice (procedure, lab, medication, etc.)."""

    __tablename__ = "invoice_line_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True,
    )
    item_type: Mapped[ItemType] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Billing code (CPT, ICD-10-PCS, etc.) — not PHI
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="line_items")


class Payment(TenantMixin, Base):
    """A payment recorded against an invoice."""

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[PaymentMethod] = mapped_column(String(32), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="payments")


class InsuranceClaim(TenantMixin, Base):
    """Insurance claim filed against an invoice."""

    __tablename__ = "insurance_claims"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True,
    )
    insurance_provider: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_number: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[ClaimStatus] = mapped_column(
        String(32), nullable=False, default=ClaimStatus.SUBMITTED,
    )
    submitted_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="claims")
