"""
PrescpHealth Backend — Patient Enums.

Defines the enumeration types used across the patient module:
- PatientGender: Inclusive gender options for clinical documentation
- PatientStatus: Patient record lifecycle states
- PatientChangeType: Types of changes tracked in version history

These enums are extracted from models.py to comply with the ~150 lines
of logic per file rule. They are re-exported from models.py for
backward compatibility.

Usage:
    from app.modules.patients.enums import PatientGender, PatientStatus
    # OR (backward compatible):
    from app.modules.patients.models import PatientGender, PatientStatus
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Patient Gender Enum
# ---------------------------------------------------------------------------
class PatientGender(str, Enum):
    """
    Patient gender options.

    Inclusive set supporting clinical documentation needs while
    respecting patient preference not to disclose.
    """

    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    PREFER_NOT_TO_SAY = "Prefer_Not_To_Say"


# ---------------------------------------------------------------------------
# Patient Status Enum
# ---------------------------------------------------------------------------
class PatientStatus(str, Enum):
    """
    Patient record lifecycle status.

    - Active: Currently receiving care at this clinic
    - Inactive: No longer actively managed (e.g., moved away)
    - Deceased: Patient has passed away (record retained per HIPAA)
    - Transferred: Care transferred to another facility
    """

    ACTIVE = "Active"
    INACTIVE = "Inactive"
    DECEASED = "Deceased"
    TRANSFERRED = "Transferred"


# ---------------------------------------------------------------------------
# Patient Change Type Enum
# ---------------------------------------------------------------------------
class PatientChangeType(str, Enum):
    """
    Types of changes tracked in patient version history.

    Used to categorize what kind of modification was made,
    enabling filtered audit queries (e.g., "show all soft deletes").
    """

    CREATE = "create"
    UPDATE = "update"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"
