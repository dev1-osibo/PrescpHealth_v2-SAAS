"""
PrescpHealth Backend — Prescription FHIR R4 Mapper.

Maps internal Prescription model to FHIR R4 MedicationRequest resource:
- prescription_to_fhir(): Prescription → FHIR R4 MedicationRequest
- from_fhir_prescription(): FHIR R4 JSON → internal field dict

FHIR R4 MedicationRequest resource includes:
- resourceType, id, status, intent
- medicationCodeableConcept (drug_name + ATC code)
- subject (patient reference)
- requester (prescribing clinician reference)
- dosageInstruction (dosage, frequency, route)
- dispenseRequest (refills allowed, duration)

HIPAA Compliance:
- fhir_json contains PHI (drug names, dosages) — encrypted at rest
- Never log FHIR content — only log prescription_id
- Returned only with proper RBAC authorization

Usage:
    from app.modules.prescriptions.fhir_mapper import prescription_to_fhir
    fhir = prescription_to_fhir(prescription)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.modules.prescriptions.prescription_model import Prescription


# ---------------------------------------------------------------------------
# Internal status → FHIR MedicationRequest.status mapping
# ---------------------------------------------------------------------------
_STATUS_TO_FHIR: dict[str, str] = {
    "active": "active",
    "completed": "completed",
    "discontinued": "stopped",
    "on_hold": "on-hold",
}


def prescription_to_fhir(prescription: Prescription) -> dict[str, Any]:
    """
    Map an internal Prescription model to a FHIR R4 MedicationRequest.

    Produces a conformant FHIR R4 MedicationRequest JSON with:
    - status mapped from internal enum to FHIR value set
    - intent set to "order" (clinician-authorized prescription)
    - medicationCodeableConcept with ATC coding + drug name
    - subject as Patient reference
    - requester as Practitioner reference
    - dosageInstruction with dose, frequency, and route
    - dispenseRequest with refills and duration

    Args:
        prescription: The Prescription SQLAlchemy model instance.

    Returns:
        Dict representing a FHIR R4 MedicationRequest resource.
    """
    # Map internal status to FHIR status value set
    status_value = prescription.status
    if hasattr(status_value, "value"):
        status_value = status_value.value
    fhir_status = _STATUS_TO_FHIR.get(status_value, "unknown")

    # Build dosage instruction with route, dose, and timing
    dosage_instruction: dict[str, Any] = {
        "text": f"{prescription.dosage} {prescription.frequency}",
        "route": {
            "coding": [
                {
                    "system": "http://snomed.info/sct",
                    "display": prescription.route,
                }
            ]
        },
        "doseAndRate": [
            {"doseQuantity": {"value": prescription.dosage}}
        ],
        "timing": {"code": {"text": prescription.frequency}},
    }

    # Build dispense request with refills and optional duration
    dispense_request: dict[str, Any] = {
        "numberOfRepeatsAllowed": prescription.refills_allowed,
    }
    if prescription.duration_days:
        dispense_request["expectedSupplyDuration"] = {
            "value": prescription.duration_days,
            "unit": "days",
            "system": "http://unitsofmeasure.org",
            "code": "d",
        }

    # Assemble the full FHIR MedicationRequest resource
    resource: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": str(prescription.id),
        "status": fhir_status,
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.whocc.no/atc",
                    "code": prescription.atc_code,
                    "display": prescription.drug_name,
                }
            ],
            "text": prescription.drug_name,
        },
        "subject": {"reference": f"Patient/{prescription.patient_id}"},
        "requester": {
            "reference": f"Practitioner/{prescription.prescribed_by}"
        },
        "dosageInstruction": [dosage_instruction],
        "dispenseRequest": dispense_request,
    }

    return resource


def from_fhir_prescription(fhir_json: dict[str, Any]) -> dict[str, Any]:
    """
    Parse a FHIR R4 MedicationRequest back to internal field dict.

    Extracts key fields from a FHIR MedicationRequest JSON and returns
    them in a format suitable for creating/updating an internal model.

    Args:
        fhir_json: Dict representing a FHIR R4 MedicationRequest.

    Returns:
        Dict with internal field names: drug_name, atc_code, dosage,
        frequency, route, refills_allowed, duration_days, patient_id.
    """
    result: dict[str, Any] = {}

    # Reverse map FHIR status to internal status
    _reverse_status = {v: k for k, v in _STATUS_TO_FHIR.items()}
    if "status" in fhir_json:
        result["status"] = _reverse_status.get(
            fhir_json["status"], fhir_json["status"]
        )

    # Extract medication (drug_name + atc_code)
    med = fhir_json.get("medicationCodeableConcept", {})
    if isinstance(med, dict):
        result["drug_name"] = med.get("text", "")
        codings = med.get("coding", [])
        if codings and isinstance(codings, list):
            result["atc_code"] = codings[0].get("code", "")

    # Extract patient reference
    subject = fhir_json.get("subject", {})
    if isinstance(subject, dict) and "reference" in subject:
        ref = subject["reference"]
        result["patient_id"] = ref.replace("Patient/", "")

    # Extract dosage instruction
    dosage_list = fhir_json.get("dosageInstruction", [])
    if dosage_list and isinstance(dosage_list, list):
        dosage = dosage_list[0]
        # Extract route
        route_obj = dosage.get("route", {})
        route_codings = route_obj.get("coding", []) if isinstance(route_obj, dict) else []
        if route_codings:
            result["route"] = route_codings[0].get("display", "oral")
        # Extract timing as frequency
        timing = dosage.get("timing", {})
        if isinstance(timing, dict):
            code = timing.get("code", {})
            if isinstance(code, dict):
                result["frequency"] = code.get("text", "")
        # Extract dose
        dose_and_rate = dosage.get("doseAndRate", [])
        if dose_and_rate and isinstance(dose_and_rate, list):
            dose_qty = dose_and_rate[0].get("doseQuantity", {})
            if isinstance(dose_qty, dict):
                result["dosage"] = str(dose_qty.get("value", ""))

    # Extract dispense request
    dispense = fhir_json.get("dispenseRequest", {})
    if isinstance(dispense, dict):
        result["refills_allowed"] = dispense.get("numberOfRepeatsAllowed", 0)
        supply_duration = dispense.get("expectedSupplyDuration", {})
        if isinstance(supply_duration, dict):
            result["duration_days"] = supply_duration.get("value")

    return result
