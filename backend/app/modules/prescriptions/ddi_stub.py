"""
PrescpHealth Backend — Drug-Drug Interaction (DDI) Stub.

PLACEHOLDER MODULE — This is a temporary stub that will be replaced by
the real Drug Interaction engine when Task 12 (drug_interactions module)
is implemented. The real engine will check:
- Drug-Drug Interactions (DDI): conflicts between two medications
- Drug-Health Interactions (DHI): conflicts between a drug and a condition

Current Behavior:
    Returns an empty list (no interactions detected) for all inputs.
    This allows the prescription service to be fully functional and
    testable while the DDI engine is being developed separately.

Integration Plan:
    When the real drug_interactions module is ready:
    1. Replace the import in service.py from this stub to the real module
    2. The function signature will remain the same (no service.py changes)
    3. Delete this file once the real module is wired in

Interface Contract:
    check_drug_interactions(patient_id, atc_code, active_medications)
    → Returns: list[dict] where each dict has:
        - severity: "Contraindicated" | "Major" | "Moderate" | "Minor"
        - interaction_type: "ddi" | "dhi"
        - description: Human-readable explanation (safe to show to Doctor)
        - conflicting_drug: ATC code of the conflicting medication (for DDI)
        - conflicting_condition: ICD-10 code (for DHI)

HIPAA Note:
    This module does NOT handle PHI directly. It receives opaque IDs
    and ATC codes (public reference data). The real DDI engine will
    follow the same principle — no PHI in interaction check logic.
"""

import uuid

import structlog

# ---------------------------------------------------------------------------
# Module logger — safe to log (no PHI in DDI checks)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Stub: Drug Interaction Check
# ---------------------------------------------------------------------------
async def check_drug_interactions(
    patient_id: uuid.UUID,
    atc_code: str,
    active_medications: list[str],
) -> list[dict]:
    """
    Check for drug-drug and drug-health interactions.

    STUB IMPLEMENTATION — Always returns empty list (no interactions).
    Will be replaced by real DDI engine in Task 12.

    The real implementation will:
    1. Query the patient's active conditions (via patient_id)
    2. Check the new drug (atc_code) against each active medication
    3. Check the new drug against each active health condition
    4. Return all detected interactions with severity levels

    Args:
        patient_id: UUID of the patient (used to look up conditions in
            the real implementation).
        atc_code: ATC code of the drug being prescribed.
        active_medications: List of ATC codes for the patient's current
            active prescriptions.

    Returns:
        List of interaction dicts. Each dict contains:
        - severity: str — "Contraindicated", "Major", "Moderate", "Minor"
        - interaction_type: str — "ddi" or "dhi"
        - description: str — Human-readable explanation

        Currently returns [] (no interactions detected).
    """
    # Log that the stub was called (helps track when real engine is needed)
    logger.info(
        "ddi_stub_called",
        patient_id=str(patient_id),
        atc_code=atc_code,
        active_medication_count=len(active_medications),
    )

    # STUB: No interactions detected
    # TODO: Replace with real DDI engine call when drug_interactions module
    # is implemented (Task 12 in the main spec)
    return []
