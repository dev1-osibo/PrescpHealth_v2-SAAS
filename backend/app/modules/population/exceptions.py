"""
PrescpHealth Backend — Population Analytics Exceptions.

Defines the exception hierarchy for the population analytics module.
All exceptions extend PopulationError so callers can catch the base
class for broad handling or subclasses for fine-grained recovery.
"""


class PopulationError(Exception):
    """Base exception for all population analytics errors."""

    def __init__(self, message: str = "Population analytics error") -> None:
        """
        Args:
            message: Human-readable description of the error.
        """
        self.message = message
        super().__init__(message)


class MetricNotFoundError(PopulationError):
    """Raised when a requested population metric does not exist in cache or DB."""

    def __init__(self, metric_type: str) -> None:
        """
        Args:
            metric_type: The metric key that could not be found.
        """
        super().__init__(f"Metric not found: {metric_type}")


class ComputationError(PopulationError):
    """Raised when metric computation fails due to a data or query error."""

    def __init__(self, detail: str = "Metric computation failed") -> None:
        """
        Args:
            detail: Additional context describing the computation failure.
        """
        super().__init__(detail)
