"""
PrescpHealth Backend — Lab Order FHIR R4 Mapper.

Maps internal LabOrder and LabResult models to FHIR R4 resources:
- order_to_fhir(): LabOrder → FHIR R4 ServiceRequest
- result_to_fhir(): LabResult → FHIR R4 DiagnosticReport + Observation
- from_fhir_order(): FHIR R4 JSON → internal field dict

FHIR R4 ServiceRequest resource includes:
- resourceType, id, status, intent, priority
- code (LOINC CodeableConcept)
- subject (patient reference), requester (clinician reference)
- encounter (optional encounter reference)

FHIR R4 DiagnosticReport + Observation:
- DiagnosticReport wraps the overall result
- Observation contains the actual value, unit, and reference range

HIPAA Compliance:
- fhir_json contains PHI (test names, values) — encrypted at rest
- Never log FHIR content — only log resource IDs
- Returned only with proper RBAC authorization

Usage:
    from app.modules.lab_orders.fhir_mapper import order_to_fhir
    fhir = order_to_fhir(lab_order)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.lab_orders.models import LabOrder, LabResult


# ---------------------------------------------------------------------------
# Internal status → FHIR ServiceRequest.status mapping
# ---------------------------------------------------------------------------
_ORDER_STATUS_TO_FHIR: dict[str, str] = {
    "ordered": "active",
    "specimen_collected": "active",
    "in_progress": "active",
    "resulted": "completed",
    "cancelled": "revoked",
}

# Internal priority → FHIR ServiceRequest.priority mapping
_PRIORITY_TO_FHIR: dict[str, str] = {
    "routine": "routine",
    "urgent": "urgent",
    "stat": "stat",
}


def order_to_fhir(lab_order: LabOrder) -> dict[str, Any]:
    """
    Map an internal LabOrder model to a FHIR R4 ServiceRequest resource.

    Produces a conformant FHIR R4 ServiceRequest JSON with:
    - status mapped from internal lifecycle to FHIR value set
    - intent set to "order" (clinician-authorized lab request)
    - priority mapped from internal enum
    - code as LOINC CodeableConcept
    - subject as Patient reference
    - requester as Practitioner reference
    - encounter as optional Encounter reference

    Args:
        lab_order: The LabOrder SQLAlchemy model instance.

    Returns:
        Dict representing a FHIR R4 ServiceRequest resource.
    """
    # Map internal status to FHIR ServiceRequest status
    fhir_status = _ORDER_STATUS_TO_FHIR.get(lab_order.status, "unknown")

    # Map priority to FHIR priority value set
    fhir_priority = _PRIORITY_TO_FHIR.get(lab_order.priority, "routine")

    # Build the FHIR ServiceRequest resource
    resource: dict[str, Any] = {
        "resourceType": "ServiceRequest",
        "id": str(lab_order.id),
        "status": fhir_status,
        "intent": "order",
        "priority": fhir_priority,
        "code": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": lab_order.loinc_code,
                    "display": lab_order.test_name,
                }
            ],
            "text": lab_order.test_name,
        },
        "subject": {"reference": f"Patient/{lab_order.patient_id}"},
        "requester": {"reference": f"Practitioner/{lab_order.ordered_by}"},
    }

    # Add encounter reference if linked to an encounter
    if lab_order.encounter_id:
        resource["encounter"] = {
            "reference": f"Encounter/{lab_order.encounter_id}"
        }

    # Add clinical indication as reasonCode if present
    if lab_order.clinical_indication:
        resource["reasonCode"] = [{"text": lab_order.clinical_indication}]

    return resource


def result_to_fhir(lab_result: LabResult) -> dict[str, Any]:
    """
    Map an internal LabResult to FHIR R4 DiagnosticReport + Observation.

    Produces a FHIR R4 structure containing:
    - DiagnosticReport as the wrapper with status and conclusion
    - Embedded Observation with value, unit, and reference range
    - interpretation flag for abnormal results

    Args:
        lab_result: The LabResult SQLAlchemy model instance.

    Returns:
        Dict representing a FHIR R4 DiagnosticReport with contained
        Observation resource.
    """
    # Build the Observation resource (contained within DiagnosticReport)
    observation: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"obs-{lab_result.id}",
        "status": "final",
        "valueString": lab_result.value,
    }

    # Add numeric value with unit if available
    if lab_result.numeric_value is not None:
        observation["valueQuantity"] = {
            "value": lab_result.numeric_value,
            "unit": lab_result.unit,
            "system": "http://unitsofmeasure.org",
        }

    # Add reference range if defined
    if lab_result.reference_range_low is not None or lab_result.reference_range_high is not None:
        ref_range: dict[str, Any] = {}
        if lab_result.reference_range_low is not None:
            ref_range["low"] = {
                "value": lab_result.reference_range_low,
                "unit": lab_result.unit,
            }
        if lab_result.reference_range_high is not None:
            ref_range["high"] = {
                "value": lab_result.reference_range_high,
                "unit": lab_result.unit,
            }
        observation["referenceRange"] = [ref_range]

    # Add interpretation for abnormal results
    if lab_result.is_abnormal:
        observation["interpretation"] = [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": "A",
                        "display": "Abnormal",
                    }
                ]
            }
        ]

    # Build the DiagnosticReport wrapper
    resource: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "id": str(lab_result.id),
        "status": "final",
        "effectiveDateTime": _format_dt(lab_result.resulted_at),
        "contained": [observation],
        "result": [{"reference": f"#obs-{lab_result.id}"}],
    }

    return resource


def from_fhir_order(fhir_json: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a FHIR R4 ServiceRequest back to internal field dict.

    Extracts key fields from a FHIR ServiceRequest JSON and returns
    them in a format suitable for creating/updating an internal model.

    Args:
        fhir_json: Dict representing a FHIR R4 ServiceRequest.

    Returns:
        Dict with internal field names: test_name, loinc_code,
        priority, patient_id, encounter_id, clinical_indication.
    """
    result: dict[str, Any] = {}

    # Extract priority (reverse map)
    _reverse_priority = {v: k for k, v in _PRIORITY_TO_FHIR.items()}
    if "priority" in fhir_json:
        result["priority"] = _reverse_priority.get(
            fhir_json["priority"], "routine"
        )

    # Extract test code (LOINC)
    code = fhir_json.get("code", {})
    if isinstance(code, dict):
        result["test_name"] = code.get("text", "")
        codings = code.get("coding", [])
        if codings and isinstance(codings, list):
            result["loinc_code"] = codings[0].get("code", "")

    # Extract patient reference
    subject = fhir_json.get("subject", {})
    if isinstance(subject, dict) and "reference" in subject:
        ref = subject["reference"]
        result["patient_id"] = ref.replace("Patient/", "")

    # Extract encounter reference
    encounter = fhir_json.get("encounter", {})
    if isinstance(encounter, dict) and "reference" in encounter:
        ref = encounter["reference"]
        result["encounter_id"] = ref.replace("Encounter/", "")

    # Extract clinical indication from reasonCode
    reason_codes = fhir_json.get("reasonCode", [])
    if reason_codes and isinstance(reason_codes, list):
        result["clinical_indication"] = reason_codes[0].get("text", "")

    return result


# ---------------------------------------------------------------------------
# Private Helpers
# ---------------------------------------------------------------------------
def _format_dt(dt: datetime | None) -> str | None:
    """Format a datetime to ISO-8601 string, or return None."""
    if dt is None:
        return None
    return dt.isoformat()
