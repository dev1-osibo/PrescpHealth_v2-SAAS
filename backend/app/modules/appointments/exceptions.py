"""
Appointments Module — Custom Exceptions
=========================================
All domain-specific exceptions for the appointments module.
Callers catch these to return appropriate HTTP status codes
without leaking internal details.
"""


class AppointmentNotFoundError(Exception):
    """Raised when a requested appointment UUID does not exist in the tenant scope."""

    def __init__(self, appointment_id: str) -> None:
        """Initialise with the appointment UUID (never include PHI)."""
        super().__init__(f"Appointment not found: {appointment_id}")
        self.appointment_id = appointment_id


class DoubleBookingError(Exception):
    """Raised when a clinician already has an overlapping appointment in the requested window."""

    def __init__(self, clinician_id: str) -> None:
        """Initialise with the clinician UUID (never include PHI)."""
        super().__init__(f"Clinician {clinician_id} already has an appointment in this time slot.")
        self.clinician_id = clinician_id


class InvalidAppointmentStateError(Exception):
    """Raised when an operation is invalid for the current appointment status."""

    def __init__(self, appointment_id: str, current_status: str, attempted_action: str) -> None:
        """Initialise with appointment UUID and state details."""
        super().__init__(
            f"Cannot perform '{attempted_action}' on appointment {appointment_id} "
            f"with status '{current_status}'."
        )
        self.appointment_id = appointment_id
        self.current_status = current_status
        self.attempted_action = attempted_action
