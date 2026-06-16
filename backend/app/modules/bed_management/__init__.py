"""
PrescpHealth Backend — Bed Management Module (Staging).

Provides inpatient bed assignment, admission lifecycle management,
nursing notes, and vitals charting for admitted patients.

Submodules:
    enums            — BedStatus, BedType, AdmissionStatus, NoteType, DischargeType
    exceptions       — Domain-specific error classes
    models           — Ward, Bed, Admission, NursingNote ORM models
    schemas          — Pydantic request/response schemas
    service          — Core admission and bed operations
    service_nursing  — Nursing notes and vitals charting
    router           — FastAPI route definitions

HIPAA Note:
    All responses carry no-store cache headers.
    Nursing note content is PHI — logged by ID only.
"""

from app.modules.bed_management.enums import (  # noqa: F401
    AdmissionStatus,
    BedStatus,
    BedType,
    DischargeType,
    NoteType,
)
from app.modules.bed_management.models import (  # noqa: F401
    Admission,
    Bed,
    NursingNote,
    Ward,
)

__all__ = [
    "AdmissionStatus",
    "BedStatus",
    "BedType",
    "DischargeType",
    "NoteType",
    "Ward",
    "Bed",
    "Admission",
    "NursingNote",
]
