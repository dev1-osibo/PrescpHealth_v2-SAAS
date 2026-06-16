"""
PrescpHealth Backend — Billing Pydantic Schemas.

Request bodies and response models for the billing API.
All monetary fields use Decimal (never float).
PHI fields (patient names, diagnoses) are NEVER included in schemas.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.modules.billing.enums import (
    ClaimStatus,
    InvoiceStatus,
    ItemType,
    PaymentMethod,
)


# ---------------------------------------------------------------------------
# Invoice Schemas
# ---------------------------------------------------------------------------

class InvoiceGenerateRequest(BaseModel):
    """Body for POST /api/v1/invoices — generate invoice from encounter."""

    encounter_id: uuid.UUID = Field(..., description="Encounter to bill")
    currency: str = Field(default="USD", max_length=3, description="ISO 4217 code")
    notes: Optional[str] = Field(None, max_length=1024)


class LineItemOut(BaseModel):
    """Single invoice line item in a response."""

    id: uuid.UUID
    item_type: ItemType
    description: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    code: Optional[str] = None

    class Config:
        from_attributes = True


class PaymentOut(BaseModel):
    """Payment record in a response."""

    id: uuid.UUID
    amount: Decimal
    payment_method: PaymentMethod
    reference_number: Optional[str] = None
    paid_at: datetime
    recorded_by: uuid.UUID
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class InvoiceOut(BaseModel):
    """Full invoice response including line items and payments."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    patient_id: uuid.UUID
    encounter_id: uuid.UUID
    invoice_number: str
    status: InvoiceStatus
    total_amount: Decimal
    paid_amount: Decimal
    currency: str
    issued_at: Optional[datetime] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    created_by: uuid.UUID
    created_at: datetime
    line_items: list[LineItemOut] = []
    payments: list[PaymentOut] = []

    class Config:
        from_attributes = True


class InvoiceListItem(BaseModel):
    """Slim invoice record for list responses."""

    id: uuid.UUID
    invoice_number: str
    status: InvoiceStatus
    total_amount: Decimal
    paid_amount: Decimal
    currency: str
    issued_at: Optional[datetime] = None
    due_date: Optional[date] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Payment Schemas
# ---------------------------------------------------------------------------

class PaymentRecordRequest(BaseModel):
    """Body for POST /api/v1/invoices/{id}/payments."""

    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_method: PaymentMethod
    reference_number: Optional[str] = Field(None, max_length=128)
    paid_at: Optional[datetime] = None  # Defaults to now(utc) in service
    notes: Optional[str] = Field(None, max_length=1024)


# ---------------------------------------------------------------------------
# Insurance Claim Schemas
# ---------------------------------------------------------------------------

class ClaimSubmitRequest(BaseModel):
    """Body for POST /api/v1/insurance-claims."""

    invoice_id: uuid.UUID
    insurance_provider: str = Field(..., max_length=255)
    policy_number: str = Field(..., max_length=128)
    submitted_amount: Decimal = Field(..., gt=0, decimal_places=2)


class ClaimStatusUpdateRequest(BaseModel):
    """Body for PUT /api/v1/insurance-claims/{id}/status."""

    status: ClaimStatus
    approved_amount: Optional[Decimal] = Field(None, decimal_places=2)
    denial_reason: Optional[str] = Field(None, max_length=2048)
    claim_number: Optional[str] = Field(None, max_length=128)


class ClaimOut(BaseModel):
    """Insurance claim response object."""

    id: uuid.UUID
    invoice_id: uuid.UUID
    patient_id: uuid.UUID
    insurance_provider: str
    policy_number: str
    claim_number: Optional[str] = None
    status: ClaimStatus
    submitted_amount: Decimal
    approved_amount: Optional[Decimal] = None
    denial_reason: Optional[str] = None
    submitted_at: datetime
    resolved_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Void schema
# ---------------------------------------------------------------------------

class VoidRequest(BaseModel):
    """Body for voiding an invoice."""

    reason: str = Field(..., min_length=5, max_length=1024)
