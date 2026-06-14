"""
Referrals Module — Enumerations
=================================
Defines urgency levels and workflow status values for referrals.
Using str-based enums ensures JSON serialisability across the API.
"""

from enum import Enum


class ReferralUrgency(str, Enum):
    """Clinical urgency classification for a referral."""

    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENT = "emergent"


class ReferralStatus(str, Enum):
    """
    Lifecycle status of a referral.

    Valid transitions (enforced by service layer):
        pending  → accepted | declined | cancelled
        accepted → scheduled | cancelled
        scheduled → in_progress | cancelled
        in_progress → completed
        completed, cancelled, declined = terminal (no further transitions)
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    DECLINED = "declined"


# Mapping of valid forward transitions for status validation
VALID_TRANSITIONS: dict[str, list[str]] = {
    ReferralStatus.PENDING: [
        ReferralStatus.ACCEPTED,
        ReferralStatus.DECLINED,
        ReferralStatus.CANCELLED,
    ],
    ReferralStatus.ACCEPTED: [
        ReferralStatus.SCHEDULED,
        ReferralStatus.CANCELLED,
    ],
    ReferralStatus.SCHEDULED: [
        ReferralStatus.IN_PROGRESS,
        ReferralStatus.CANCELLED,
    ],
    ReferralStatus.IN_PROGRESS: [
        ReferralStatus.COMPLETED,
    ],
    # Terminal states — no outbound transitions
    ReferralStatus.COMPLETED: [],
    ReferralStatus.CANCELLED: [],
    ReferralStatus.DECLINED: [],
}
