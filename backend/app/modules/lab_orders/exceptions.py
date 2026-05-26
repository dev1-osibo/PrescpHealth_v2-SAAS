"""
PrescpHealth Backend — Lab Order Module Exceptions.

Custom exception classes for the lab_orders module. These provide
clear, typed error handling for lab order operations without exposing
PHI in error messages.

Exception Hierarchy:
- LabOrderNotFoundError: Raised when a lab order UUID doesn't exist
- InvalidLabOrderStatusTransitionError: Raised for illegal state changes
- LabOrderAlreadyResultedError: Raised when attempting to re-result an order

HIPAA Compliance:
    Error messages contain only lab_order_id (UUID) and status strings.
    Never include test names, patient identifiers, or result values.

Usage:
    from app.modules.lab_orders.exceptions import (
        LabOrderNotFoundError,
        InvalidLabOrderStatusTransitionError,
        LabOrderAlreadyResultedError,
    )
"""

import uuid


# ---------------------------------------------------------------------------
# Lab Order Not Found
# ---------------------------------------------------------------------------
class LabOrderNotFoundError(Exception):
    """
    Raised when a lab order cannot be found by its ID.

    This is a 404-equivalent error — the requested resource doesn't exist
    or is not accessible within the current tenant (RLS handles isolation).

    Attributes:
        order_id: The UUID that was looked up.
        message: Human-readable error message (no PHI).
    """

    def __init__(self, order_id: uuid.UUID) -> None:
        self.order_id = order_id
        self.message = f"Lab order not found: {order_id}"
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Invalid Status Transition
# ---------------------------------------------------------------------------
class InvalidLabOrderStatusTransitionError(Exception):
    """
    Raised when a status transition violates the allowed state machine.

    Valid transitions:
        ordered → specimen_collected → in_progress → resulted
        ordered → cancelled
        specimen_collected → cancelled

    Any other transition is invalid and raises this error.

    Attributes:
        order_id: The lab order UUID.
        current_status: The order's current status.
        requested_status: The status that was requested.
        message: Human-readable error message (no PHI).
    """

    def __init__(
        self,
        order_id: uuid.UUID,
        current_status: str,
        requested_status: str,
    ) -> None:
        self.order_id = order_id
        self.current_status = current_status
        self.requested_status = requested_status
        self.message = (
            f"Invalid status transition for lab order {order_id}: "
            f"'{current_status}' → '{requested_status}' is not allowed"
        )
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Already Resulted
# ---------------------------------------------------------------------------
class LabOrderAlreadyResultedError(Exception):
    """
    Raised when attempting to record a result for an already-resulted order.

    Once a lab order has status='resulted', no additional results can be
    recorded. This prevents accidental overwrites of clinical data.

    Attributes:
        order_id: The lab order UUID.
        message: Human-readable error message (no PHI).
    """

    def __init__(self, order_id: uuid.UUID) -> None:
        self.order_id = order_id
        self.message = (
            f"Lab order {order_id} has already been resulted. "
            "Cannot record additional results."
        )
        super().__init__(self.message)
