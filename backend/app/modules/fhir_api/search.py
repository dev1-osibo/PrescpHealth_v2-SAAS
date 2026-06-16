"""
PrescpHealth Backend — FHIR R4 Search Parameter Parsing.

Parses FHIR search parameters from HTTP query strings and translates
them into SQLAlchemy filter clauses.

Supported parameters: _id, patient, date, status, code

FHIR Search Reference:
    https://www.hl7.org/fhir/R4/search.html

PHI:
    Search parameters may contain patient IDs (UUIDs) — these are safe to log.
    Code values (e.g., ICD-10) are metadata, not PHI per se.
"""

import uuid
from datetime import date, datetime
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)

# Supported FHIR search parameters and their internal column mappings
_PARAM_MAP: dict[str, dict[str, str]] = {
    "Encounter": {
        "_id": "id",
        "patient": "patient_id",
        "status": "status",
        "date": "check_in_time",
    },
    "MedicationRequest": {
        "_id": "id",
        "patient": "patient_id",
        "status": "status",
    },
    "ServiceRequest": {
        "_id": "id",
        "patient": "patient_id",
        "status": "status",
        "code": "code",
    },
    "DiagnosticReport": {
        "_id": "id",
        "patient": "patient_id",
        "status": "status",
        "code": "code",
    },
    "Patient": {
        "_id": "id",
    },
}


class FHIRSearchParams:
    """
    Parsed and validated FHIR search parameters.

    Created by parse_search_params(). Used by FHIRService to apply filters.
    """

    def __init__(
        self,
        resource_type: str,
        _id: Optional[uuid.UUID] = None,
        patient: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        code: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> None:
        self.resource_type = resource_type
        self._id = _id
        self.patient = patient
        self.status = status
        self.date_from = date_from
        self.date_to = date_to
        self.code = code
        self.limit = min(limit, 100)   # Cap at 100 per request
        self.offset = offset


def parse_search_params(
    resource_type: str,
    raw_params: dict[str, str],
) -> FHIRSearchParams:
    """
    Parse and validate FHIR search query parameters.

    Supported params: _id, patient, date, status, code, _count, _offset.
    Unknown parameters are silently ignored (FHIR spec §2.1.1.3).

    Args:
        resource_type: The FHIR resource type being searched.
        raw_params: Raw query string parameters from the HTTP request.

    Returns:
        FHIRSearchParams with parsed values and defaults applied.

    Examples:
        >>> params = parse_search_params("Encounter", {"patient": "abc-uuid", "status": "finished"})
        >>> params.patient  # uuid.UUID("abc-uuid")
    """
    _id: Optional[uuid.UUID] = None
    patient: Optional[uuid.UUID] = None
    status: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    code: Optional[str] = None
    limit = int(raw_params.get("_count", "20"))
    offset = int(raw_params.get("_offset", "0"))

    # Parse _id — must be a valid UUID
    if "_id" in raw_params:
        try:
            _id = uuid.UUID(raw_params["_id"])
        except ValueError:
            logger.warning("fhir_search_invalid_id", raw_id=raw_params["_id"])

    # Parse patient reference — FHIR format is "Patient/{uuid}"
    if "patient" in raw_params:
        raw_patient = raw_params["patient"]
        # Strip "Patient/" prefix if present
        patient_str = raw_patient.replace("Patient/", "")
        try:
            patient = uuid.UUID(patient_str)
        except ValueError:
            logger.warning("fhir_search_invalid_patient", raw=raw_patient)

    # Parse status
    if "status" in raw_params:
        status = raw_params["status"]

    # Parse date range (FHIR date prefix: ge=>=, le=<=, gt=>, lt=<, eq==)
    if "date" in raw_params:
        date_from, date_to = _parse_date_param(raw_params["date"])

    # Parse code (CPT, SNOMED, ICD-10)
    if "code" in raw_params:
        code = raw_params["code"]

    return FHIRSearchParams(
        resource_type=resource_type,
        _id=_id,
        patient=patient,
        status=status,
        date_from=date_from,
        date_to=date_to,
        code=code,
        limit=limit,
        offset=offset,
    )


def _parse_date_param(date_str: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Parse a FHIR date search parameter with optional prefix.

    FHIR date prefixes: ge (>=), le (<=), gt (>), lt (<), eq (=).
    Default prefix is eq.

    Returns:
        Tuple of (date_from, date_to). One will be None for open-ended ranges.
    """
    prefix = "eq"
    value = date_str

    # Extract prefix if present (2-char FHIR prefix)
    if len(date_str) > 2 and date_str[:2].isalpha():
        prefix = date_str[:2]
        value = date_str[2:]

    try:
        # Try full datetime first, then date-only
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = datetime.fromisoformat(f"{value}T00:00:00+00:00")
    except ValueError:
        return None, None

    if prefix in ("ge", "gt", "eq"):
        return parsed, None
    elif prefix in ("le", "lt"):
        return None, parsed
    return parsed, None
