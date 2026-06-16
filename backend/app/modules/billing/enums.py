"""
PrescpHealth Backend — Billing Enums.

Defines all enumeration types used by the billing module.
Using Python's str-Enum so values serialise cleanly to JSON strings.
"""

from enum import Enum


class InvoiceStatus(str, Enum):
    """
    Lifecycle states for a patient invoice.

    Transitions:
        draft → issued → paid / partially_paid / overdue
        any   → cancelled / void (terminal)
    """

    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
    VOID = "void"


class PaymentMethod(str, Enum):
    """
    Accepted payment methods for recording a payment against an invoice.
    """

    CASH = "cash"
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    MOBILE_MONEY = "mobile_money"
    INSURANCE = "insurance"


class ItemType(str, Enum):
    """
    Classification of a line item on an invoice.
    """

    CONSULTATION = "consultation"
    PROCEDURE = "procedure"
    LAB_TEST = "lab_test"
    MEDICATION = "medication"
    SUPPLY = "supply"
    OTHER = "other"


class ClaimStatus(str, Enum):
    """
    Insurance claim workflow states.

    Transitions:
        submitted → pending_review → approved / partially_approved / denied
        denied    → resubmitted → pending_review (retry cycle)
    """

    SUBMITTED = "submitted"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    DENIED = "denied"
    RESUBMITTED = "resubmitted"
