"""
PrescpHealth Backend — Billing Module (Staging).

Provides invoice generation, payment recording, and insurance claim
management for clinical encounters.

Submodules:
    enums            — InvoiceStatus, PaymentMethod, ClaimStatus enums
    exceptions       — Domain-specific error classes
    models           — Invoice, InvoiceLineItem, Payment, InsuranceClaim ORM models
    schemas          — Pydantic request/response schemas
    service          — Core billing operations
    service_claims   — Insurance claim operations
    router           — FastAPI route definitions

HIPAA Note:
    All responses carry no-store cache headers.
    PHI (patient names, diagnoses) is NEVER logged — only UUIDs.
"""

from app.modules.billing.enums import (  # noqa: F401
    InvoiceStatus,
    PaymentMethod,
    ItemType,
    ClaimStatus,
)
from app.modules.billing.models import (  # noqa: F401
    Invoice,
    InvoiceLineItem,
    Payment,
    InsuranceClaim,
)

__all__ = [
    "InvoiceStatus",
    "PaymentMethod",
    "ItemType",
    "ClaimStatus",
    "Invoice",
    "InvoiceLineItem",
    "Payment",
    "InsuranceClaim",
]
