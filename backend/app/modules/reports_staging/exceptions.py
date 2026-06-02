"""
PrescpHealth Backend — Report Module Exceptions.

Domain-specific exception hierarchy for the reports module.
All exceptions are non-PHI: they carry IDs and structural context only,
never patient names, clinical values, or raw payload data.
"""


class ReportError(Exception):
    """
    Base exception for all report-related errors.

    Subclass for specific failure modes; catch at the router layer
    and translate to HTTP responses.

    Args:
        message: Human-readable description (no PHI).
    """

    def __init__(self, message: str) -> None:
        """Initialize with a descriptive, PHI-free message."""
        self.message = message
        super().__init__(message)


class ReportNotFoundError(ReportError):
    """
    Raised when a requested report record cannot be found.

    Typically occurs when polling a task_id that does not exist
    in the current tenant scope.
    """

    pass


class ReportGenerationError(ReportError):
    """
    Raised when PDF or document generation fails.

    Wraps underlying builder errors without leaking PHI from
    internal exceptions into log or API responses.
    """

    pass


class ExportError(ReportError):
    """
    Raised when a CSV export operation fails.

    Covers database query failures, streaming errors, and
    generator-level faults during measurement or population export.
    """

    pass
