"""
PrescpHealth Backend — Billing Exceptions.

Domain-specific exception classes for the billing module.
All error messages are PHI-safe — they reference IDs, not patient data.
"""

import uuid
from typing import Optional


class BillingError(Exception):
    """Base class for all billing-related errors."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvoiceNotFoundError(BillingError):
    """Raised when an invoice cannot be located (not found or hidden by RLS)."""

    def __init__(self, invoice_id: uuid.UUID) -> None:
        super().__init__(
            # Log UUID only — never include patient name or PHI
            message=f"Invoice {invoice_id} not found",
            status_code=404,
        )
        self.invoice_id = invoice_id


class InvoiceAlreadyVoidError(BillingError):
    """Raised when attempting to mutate a voided invoice."""

    def __init__(self, invoice_id: uuid.UUID) -> None:
        super().__init__(
            message=f"Invoice {invoice_id} is already void and cannot be modified",
            status_code=409,
        )


class InvalidInvoiceStatusError(BillingError):
    """Raised when a status transition is not permitted."""

    def __init__(
        self,
        invoice_id: uuid.UUID,
        current: str,
        attempted: str,
    ) -> None:
        super().__init__(
            message=(
                f"Invoice {invoice_id}: cannot transition from "
                f"'{current}' to '{attempted}'"
            ),
            status_code=422,
        )


class ClaimNotFoundError(BillingError):
    """Raised when an insurance claim cannot be located."""

    def __init__(self, claim_id: uuid.UUID) -> None:
        super().__init__(
            message=f"Insurance claim {claim_id} not found",
            status_code=404,
        )
        self.claim_id = claim_id


class EncounterBillingError(BillingError):
    """Raised when an encounter cannot be billed (missing data, wrong status)."""

    def __init__(self, encounter_id: uuid.UUID, reason: str) -> None:
        super().__init__(
            # reason must be non-PHI (status info only)
            message=f"Cannot bill encounter {encounter_id}: {reason}",
            status_code=422,
        )


class DuplicateInvoiceError(BillingError):
    """Raised when an invoice for the encounter already exists."""

    def __init__(self, encounter_id: uuid.UUID) -> None:
        super().__init__(
            message=f"An invoice already exists for encounter {encounter_id}",
            status_code=409,
        )
