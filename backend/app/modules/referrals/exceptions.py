"""
Referrals Module — Custom Exceptions
======================================
Domain-specific exceptions for the referrals module.
HTTP layer maps these to appropriate status codes.
"""


class ReferralNotFoundError(Exception):
    """Raised when a requested referral UUID does not exist in the tenant scope."""

    def __init__(self, referral_id: str) -> None:
        """Initialise with the referral UUID (never include PHI)."""
        super().__init__(f"Referral not found: {referral_id}")
        self.referral_id = referral_id


class InvalidStatusTransitionError(Exception):
    """Raised when an attempted status transition is not permitted."""

    def __init__(self, referral_id: str, from_status: str, to_status: str) -> None:
        """Initialise with referral UUID and transition details."""
        super().__init__(
            f"Invalid transition for referral {referral_id}: "
            f"'{from_status}' → '{to_status}' is not allowed."
        )
        self.referral_id = referral_id
        self.from_status = from_status
        self.to_status = to_status
