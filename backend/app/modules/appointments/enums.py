"""
Appointments Module — Enumerations
====================================
Defines all enum types used across the appointments module.
Using str-based enums ensures JSON serialisability and
database compatibility with SQLAlchemy's Enum column type.
"""

from enum import Enum


class AppointmentType(str, Enum):
    """Clinical appointment type classification."""

    CONSULTATION = "consultation"
    FOLLOW_UP = "follow_up"
    PROCEDURE = "procedure"
    SCREENING = "screening"
    URGENT = "urgent"


class AppointmentStatus(str, Enum):
    """Lifecycle status of a single appointment."""

    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class WaitlistStatus(str, Enum):
    """Status of a patient's position on the appointment waitlist."""

    WAITING = "waiting"
    OFFERED = "offered"   # A slot has been offered to this patient
    BOOKED = "booked"     # Patient accepted the offered slot
    EXPIRED = "expired"   # Offer window passed without response
    CANCELLED = "cancelled"
