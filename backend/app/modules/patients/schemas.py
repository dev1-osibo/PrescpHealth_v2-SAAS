"""
PrescpHealth Backend — Patient Pydantic Schemas (Re-export Hub).

This file re-exports all patient schemas from their individual modules
for backward compatibility. All existing imports of the form:

    from app.modules.patients.schemas import PatientCreate, PatientUpdate
    from app.modules.patients.schemas import PatientResponse

continue to work unchanged.

The actual implementations live in:
- schemas_request.py — PatientCreate, PatientUpdate
- schemas_response.py — PatientResponse, PatientListResponse,
                         PatientVersionResponse, PatientTimelineResponse
- schemas_query.py — PatientSearchParams

This split was done to comply with the ~150 lines of logic per file rule.
"""

# ---------------------------------------------------------------------------
# Re-export request schemas
# ---------------------------------------------------------------------------
from app.modules.patients.schemas_request import (  # noqa: F401
    PatientCreate,
    PatientUpdate,
)

# ---------------------------------------------------------------------------
# Re-export response schemas
# ---------------------------------------------------------------------------
from app.modules.patients.schemas_response import (  # noqa: F401
    PatientListResponse,
    PatientResponse,
    PatientTimelineResponse,
    PatientVersionResponse,
)

# ---------------------------------------------------------------------------
# Re-export query schemas
# ---------------------------------------------------------------------------
from app.modules.patients.schemas_query import PatientSearchParams  # noqa: F401

# ---------------------------------------------------------------------------
# Public API — everything importable from this module
# ---------------------------------------------------------------------------
__all__ = [
    "PatientCreate",
    "PatientUpdate",
    "PatientResponse",
    "PatientListResponse",
    "PatientVersionResponse",
    "PatientTimelineResponse",
    "PatientSearchParams",
]
