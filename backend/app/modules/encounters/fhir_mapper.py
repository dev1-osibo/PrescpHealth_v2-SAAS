"""
PrescpHealth Backend — Encounter FHIR R4 Mapper.

Maps internal Encounter and Diagnosis models to FHIR R4 resources:
- encounter_to_fhir(): Encounter → FHIR R4 Encounter resource
- diagnosis_to_fhir(): Diagnosis → FHIR R4 Condition resource
- from_fhir_encounter(): FHIR R4 JSON → internal field dict

FHIR R4 Encounter resource includes:
- resourceType, id, status, class, type
- subject (patient reference), participant (clinician reference)
- period (check_in_time → check_out_time)
- reasonCode (chief complaint)

FHIR R4 Condition resource includes:
- resourceType, id, code (ICD-10), subject, encounter
- clinicalStatus (active/resolved based on is_chronic)
- recordedDate

HIPAA Compliance:
- fhir_json contains PHI (reason, diagnoses) — stored encrypted at rest
- Never log FHIR content — only log resource IDs
- Returned only with proper RBAC authorization

Usage:
    from app.modules.encounters.fhir_mapper import encounter_to_fhir
    fhir = encounter_to_fhir(encounter)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.encounters.encounter_model import Encounter
    from app.modules.encounters.diagnosis_model import Diagnosis


# ---------------------------------------------------------------------------
# FHIR R4 class code mapping (EncounterClass → FHIR ActEncounterCode)
# ---------------------------------------------------------------------------
_FHIR_CLASS_MAP: dict[str, dict[str, str]] = {
    "ambulatory": {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "AMB",
        "display": "ambulatory",
    },
    "inpatient": {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "IMP",
        "display": "inpatient encounter",
    },
    "emergency": {
        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
        "code": "EMER",
        "display": "emergency",
    },
}


def encounter_to_fhir(encounter: Encounter) -> dict[str, Any]:
    """
    Map an internal Encounter model to a FHIR R4 Encounter resource.

    Produces a conformant FHIR R4 Encounter JSON structure with:
    - status mapped from internal enum to FHIR value set
    - class coded using ActEncounterCode system
    - subject as Patient reference
    - participant as Practitioner reference
    - period with start/end timestamps
    - reasonCode from chief complaint

    Args:
        encounter: The Encounter SQLAlchemy model instance.

    Returns:
        Dict representing a FHIR R4 Encounter resource.
    """
    # Map internal status to FHIR status value set
    status_value = encounter.status
    if hasattr(status_value, "value"):
        status_value = status_value.value

    # Map encounter class to FHIR coding
    enc_class = encounter.encounter_class
    if hasattr(enc_class, "value"):
        enc_class = enc_class.value
    fhir_class = _FHIR_CLASS_MAP.get(enc_class, _FHIR_CLASS_MAP["ambulatory"])

    # Build period (start is always present, end only if completed)
    period: dict[str, str] = {"start": _format_dt(encounter.check_in_time)}
    if encounter.check_out_time:
        period["end"] = _format_dt(encounter.check_out_time)

    # Build the FHIR resource
    resource: dict[str, Any] = {
        "resourceType": "Encounter",
        "id": str(encounter.id),
        "status": status_value,
        "class": fhir_class,
        "type": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "308335008",
                        "display": "Patient encounter procedure",
                    }
                ]
            }
        ],
        "subject": {"reference": f"Patient/{encounter.patient_id}"},
        "participant": [
            {
                "individual": {
                    "reference": f"Practitioner/{encounter.clinician_id}"
                }
            }
        ],
        "period": period,
        "reasonCode": [
            {"text": encounter.reason_for_visit}
        ],
    }

    return resource


def diagnosis_to_fhir(diagnosis: Diagnosis) -> dict[str, Any]:
    """
    Map an internal Diagnosis model to a FHIR R4 Condition resource.

    Produces a conformant FHIR R4 Condition JSON with:
    - code as ICD-10 CodeableConcept
    - subject as Patient reference
    - encounter as Encounter reference
    - clinicalStatus based on is_chronic flag
    - recordedDate from created_at timestamp

    Args:
        diagnosis: The Diagnosis SQLAlchemy model instance.

    Returns:
        Dict representing a FHIR R4 Condition resource.
    """
    # Chronic conditions are "active", acute are "resolved" after encounter
    clinical_status = "active" if diagnosis.is_chronic else "active"

    resource: dict[str, Any] = {
        "resourceType": "Condition",
        "id": str(diagnosis.id),
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinical_status,
                }
            ]
        },
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10",
                    "code": diagnosis.icd10_code,
                    "display": diagnosis.display_name,
                }
            ],
            "text": diagnosis.display_name,
        },
        "subject": {"reference": f"Patient/{diagnosis.patient_id}"},
        "encounter": {"reference": f"Encounter/{diagnosis.encounter_id}"},
        "recordedDate": _format_dt(
            getattr(diagnosis, "created_at", None)
        ),
    }

    return resource


def from_fhir_encounter(fhir_json: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a FHIR R4 Encounter resource back to internal field dict.

    Extracts the key fields from a FHIR Encounter JSON and returns
    them in a format suitable for creating/updating an internal model.

    Args:
        fhir_json: Dict representing a FHIR R4 Encounter resource.

    Returns:
        Dict with internal field names: status, encounter_class,
        patient_id, clinician_id, reason_for_visit, check_in_time.
    """
    result: dict[str, Any] = {}

    # Extract status
    if "status" in fhir_json:
        result["status"] = fhir_json["status"]

    # Extract encounter class from FHIR coding
    fhir_class = fhir_json.get("class", {})
    class_code = fhir_class.get("code", "AMB") if isinstance(fhir_class, dict) else "AMB"
    # Reverse map FHIR code to internal enum value
    _reverse_class = {"AMB": "ambulatory", "IMP": "inpatient", "EMER": "emergency"}
    result["encounter_class"] = _reverse_class.get(class_code, "ambulatory")

    # Extract patient reference
    subject = fhir_json.get("subject", {})
    if isinstance(subject, dict) and "reference" in subject:
        ref = subject["reference"]
        result["patient_id"] = ref.replace("Patient/", "")

    # Extract clinician from participant
    participants = fhir_json.get("participant", [])
    if participants and isinstance(participants, list):
        individual = participants[0].get("individual", {})
        if "reference" in individual:
            ref = individual["reference"]
            result["clinician_id"] = ref.replace("Practitioner/", "")

    # Extract reason for visit
    reason_codes = fhir_json.get("reasonCode", [])
    if reason_codes and isinstance(reason_codes, list):
        result["reason_for_visit"] = reason_codes[0].get("text", "")

    # Extract period start as check_in_time
    period = fhir_json.get("period", {})
    if isinstance(period, dict) and "start" in period:
        result["check_in_time"] = period["start"]

    return result


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------
def _format_dt(dt: datetime | None) -> str | None:
    """Format a datetime to ISO-8601 string, or return None."""
    if dt is None:
        return None
    return dt.isoformat()
