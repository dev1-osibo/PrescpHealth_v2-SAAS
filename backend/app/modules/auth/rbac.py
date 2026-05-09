"""
PrescpHealth Backend — Role-Based Access Control (RBAC).

Implements the 5-level role hierarchy and permission enforcement:
    Patient_User < Nurse < Doctor < Clinic_Admin < Super_Admin

Each higher role inherits ALL permissions of lower roles. This means:
- A Doctor can do everything a Nurse can do, plus Doctor-specific actions
- A Clinic_Admin can do everything a Doctor can do, plus admin actions
- A Super_Admin can do everything, including cross-tenant operations

Permission Enforcement:
    Use the equire_role() dependency in route definitions:

    @router.get("/patients")
    async def list_patients(user = Depends(require_role(Role.NURSE, Role.DOCTOR))):
        ...

    This checks that the authenticated user has AT LEAST one of the specified
    roles (or a higher role in the hierarchy). Returns 403 if insufficient.

Design Decisions:
- Role hierarchy is a simple ordered list (not a complex permission matrix)
- Higher roles inherit lower permissions automatically (monotonic)
- Super_Admin bypasses tenant isolation (with full audit logging)
- Permissions are checked AFTER authentication (JWT must be valid first)

HIPAA Compliance:
- Minimum necessary principle: each role only accesses what it needs
- All permission denials are logged for security audit
- Role changes are audit-logged (who changed whose role, when)
"""

from enum import IntEnum
from typing import Callable

import structlog
from fastapi import Depends, Request

from app.core.exceptions import AuthError, ForbiddenError

# ---------------------------------------------------------------------------
# Module logger — logs access control decisions without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Role Hierarchy (IntEnum for ordering)
# ---------------------------------------------------------------------------
class Role(IntEnum):
    """
    User roles ordered by privilege level.

    Using IntEnum so we can compare roles with < > operators:
        Role.NURSE < Role.DOCTOR  # True
        Role.DOCTOR >= Role.NURSE  # True

    This makes hierarchy checks trivial and the monotonicity property
    (higher role = superset of permissions) easy to enforce.
    """

    PATIENT_USER = 1
    NURSE = 2
    DOCTOR = 3
    CLINIC_ADMIN = 4
    SUPER_ADMIN = 5


# Map string role names (from JWT/DB) to Role enum values
ROLE_MAP: dict[str, Role] = {
    "Patient_User": Role.PATIENT_USER,
    "Nurse": Role.NURSE,
    "Doctor": Role.DOCTOR,
    "Clinic_Admin": Role.CLINIC_ADMIN,
    "Super_Admin": Role.SUPER_ADMIN,
}


def parse_role(role_string: str) -> Role:
    """
    Convert a role string (from JWT or database) to Role enum.

    Args:
        role_string: Role name as stored in DB/JWT (e.g., "Doctor")

    Returns:
        Role: The corresponding Role enum value.

    Raises:
        AuthError: If the role string is not recognized.
    """
    role = ROLE_MAP.get(role_string)
    if role is None:
        logger.error("invalid_role_string", role=role_string)
        raise AuthError(message="Invalid role in token")
    return role


# ---------------------------------------------------------------------------
# Permission Checker — FastAPI Dependency
# ---------------------------------------------------------------------------
def require_role(*allowed_roles: Role) -> Callable:
    """
    Create a FastAPI dependency that enforces role-based access.

    Checks that the authenticated user has AT LEAST one of the specified
    roles, OR a higher role in the hierarchy (monotonic inheritance).

    Args:
        *allowed_roles: One or more Role values that are permitted.
            The user needs ANY ONE of these (OR logic), and higher roles
            automatically qualify due to hierarchy.

    Returns:
        A FastAPI dependency function that validates the user's role.

    Usage:
        # Only Doctors and above can compute risk scores
        @router.post("/risk/compute")
        async def compute_risk(user = Depends(require_role(Role.DOCTOR))):
            ...

        # Nurses and Doctors can submit measurements
        @router.post("/measurements")
        async def add_measurement(user = Depends(require_role(Role.NURSE, Role.DOCTOR))):
            ...

    Raises:
        AuthError: If user is not authenticated (no valid JWT).
        ForbiddenError: If user's role is insufficient.
    """

    # Find the minimum required role level
    # Due to hierarchy, if NURSE is allowed, DOCTOR/ADMIN/SUPER also qualify
    min_required_level = min(allowed_roles)

    async def role_checker(request: Request):
        """
        Validate the current user's role against required permissions.

        Extracts role from request.state (set by auth middleware/dependency)
        and checks against the minimum required level.
        """
        # Get user role from request state (set by auth dependency)
        user_role_str = getattr(request.state, "user_role", None)
        user_id = getattr(request.state, "user_id", None)

        # If no role on request state, user isn't authenticated
        if user_role_str is None:
            raise AuthError(message="Authentication required")

        # Parse the role string to enum for comparison
        user_role = parse_role(user_role_str)

        # Hierarchy check: user's role level must be >= minimum required
        # This enforces monotonicity: higher roles inherit all lower permissions
        if user_role < min_required_level:
            logger.warning(
                "access_denied_insufficient_role",
                user_id=user_id,
                user_role=user_role_str,
                required_minimum=min_required_level.name,
                path=request.url.path,
            )
            raise ForbiddenError(
                message="You do not have permission to perform this action"
            )

        # Access granted — return user context for downstream use
        return {
            "user_id": user_id,
            "role": user_role,
            "role_str": user_role_str,
            "tenant_id": getattr(request.state, "tenant_id", None),
        }

    return role_checker


# ---------------------------------------------------------------------------
# Convenience Dependencies (pre-built for common patterns)
# ---------------------------------------------------------------------------

# Any authenticated user (including Patient_User)
require_authenticated = require_role(Role.PATIENT_USER)

# Clinical staff only (Nurse and above)
require_clinical = require_role(Role.NURSE)

# Doctor-level access (Doctor and above)
require_doctor = require_role(Role.DOCTOR)

# Admin access (Clinic_Admin and above)
require_admin = require_role(Role.CLINIC_ADMIN)

# Super Admin only (cross-tenant operations)
require_super_admin = require_role(Role.SUPER_ADMIN)
