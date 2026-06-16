"""
PrescpHealth Backend — FHIR R4 Resource Validator.

Validates that incoming FHIR R4 JSON payloads contain the minimum required
fields for each supported resource type.

Design:
    - Validation is structural only (required fields present, correct types).
    - Deep FHIR profile validation is out of scope for this stub.
    - Returns an OperationOutcome-like dict on failure.

FHIR R4 Reference:
    https://www.hl7.org/fhir/R4/

PHI:
    Validation errors reference field paths only — never field values.
"""

from typing import Any


# ---------------------------------------------------------------------------
# Minimum required fields per resource type (FHIR R4 invariants)
# ---------------------------------------------------------------------------
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "Encounter": ["resourceType", "status", "class", "subject"],
    "MedicationRequest": ["resourceType", "status", "intent", "subject", "medicationCodeableConcept"],
    "ServiceRequest": ["resourceType", "status", "intent", "code", "subject"],
    "DiagnosticReport": ["resourceType", "status", "code", "subject"],
    "Patient": ["resourceType", "id"],
}

# Valid status values per resource type
_VALID_STATUSES: dict[str, set[str]] = {
    "Encounter": {
        "planned", "arrived", "triaged", "in-progress",
        "onleave", "finished", "cancelled",
    },
    "MedicationRequest": {
        "active", "on-hold", "cancelled", "completed",
        "entered-in-error", "stopped", "draft", "unknown",
    },
    "ServiceRequest": {
        "draft", "active", "on-hold", "revoked",
        "completed", "entered-in-error", "unknown",
    },
    "DiagnosticReport": {
        "registered", "partial", "preliminary", "final",
        "amended", "corrected", "appended", "cancelled", "entered-in-error",
    },
}


def validate_fhir_resource(
    resource_type: str,
    fhir_json: dict[str, Any],
) -> list[str]:
    """
    Validate a FHIR R4 resource for required fields and basic invariants.

    Args:
        resource_type: Expected FHIR resource type (e.g., "Encounter").
        fhir_json: The parsed JSON payload from the request.

    Returns:
        List of validation error strings.
        Empty list means the resource passed validation.

    Examples:
        >>> errors = validate_fhir_resource("Encounter", {"resourceType": "Encounter"})
        >>> assert "status" in errors[0]  # Missing status
    """
    errors: list[str] = []

    # Check resourceType matches the route parameter
    actual_type = fhir_json.get("resourceType")
    if actual_type != resource_type:
        errors.append(
            f"resourceType mismatch: expected '{resource_type}', got '{actual_type}'"
        )
        # Cannot continue validation if resource type is wrong
        return errors

    # Check all required fields for this resource type
    required = _REQUIRED_FIELDS.get(resource_type, [])
    for field in required:
        if field not in fhir_json or fhir_json[field] is None:
            errors.append(f"Missing required field: '{field}'")

    # Validate status value if present
    if "status" in fhir_json and resource_type in _VALID_STATUSES:
        status_value = fhir_json.get("status")
        valid_statuses = _VALID_STATUSES[resource_type]
        if status_value not in valid_statuses:
            errors.append(
                f"Invalid status '{status_value}' for {resource_type}. "
                f"Must be one of: {sorted(valid_statuses)}"
            )

    # Patient-specific: id must be a non-empty string if present
    if resource_type == "Patient" and "id" in fhir_json:
        if not isinstance(fhir_json["id"], str) or not fhir_json["id"].strip():
            errors.append("Patient.id must be a non-empty string")

    return errors


def build_operation_outcome(
    errors: list[str],
    severity: str = "error",
) -> dict[str, Any]:
    """
    Build a FHIR R4 OperationOutcome resource from validation error strings.

    Args:
        errors: List of human-readable error messages.
        severity: FHIR issue severity (error, warning, information).

    Returns:
        FHIR R4 OperationOutcome dict ready for JSON serialization.
    """
    return {
        "resourceType": "OperationOutcome",
        "issue": [
            {
                "severity": severity,
                "code": "required",
                "diagnostics": error,
            }
            for error in errors
        ],
    }
