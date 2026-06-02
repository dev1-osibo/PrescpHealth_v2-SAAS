"""
PrescpHealth Backend — Admin Module Exceptions.

Defines the exception hierarchy for the admin_staging module.
All admin errors derive from AdminError for consistent catch blocks.
"""


class AdminError(Exception):
    """
    Base exception for all admin module errors.

    Args:
        message: Human-readable error description (no PHI).
    """

    def __init__(self, message: str = "Admin operation failed") -> None:
        """Initialize with a descriptive message."""
        self.message = message
        super().__init__(message)


class TenantNotFoundError(AdminError):
    """Raised when the requested tenant does not exist or is out of scope."""

    def __init__(self, tenant_id: str) -> None:
        """Initialize with the tenant UUID that was not found."""
        super().__init__(f"Tenant not found: {tenant_id}")


class TenantAlreadyExistsError(AdminError):
    """Raised when attempting to create a tenant whose name already exists."""

    def __init__(self, name: str) -> None:
        """Initialize with the conflicting tenant name."""
        super().__init__(f"Tenant already exists: {name}")


class ModelVersionNotFoundError(AdminError):
    """Raised when a requested model version is not present in the registry."""

    def __init__(self, disease: str, version: str) -> None:
        """Initialize with disease and version identifiers."""
        super().__init__(f"Model version not found: {disease}@{version}")


class ModelDeploymentError(AdminError):
    """Raised when a model deployment operation fails."""

    def __init__(self, message: str = "Model deployment failed") -> None:
        """Initialize with a deployment-specific error message."""
        super().__init__(message)


class RollbackError(AdminError):
    """Raised when a model rollback cannot be completed."""

    def __init__(self, message: str = "Model rollback failed") -> None:
        """Initialize with a rollback-specific error message."""
        super().__init__(message)
