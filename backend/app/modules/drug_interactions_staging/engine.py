"""
PrescpHealth Backend — Drug Interaction Matching Engine.

Core logic for detecting and assessing drug-drug (DDI) and drug-health (DHI) interactions.

Components:
- check_ddi(new_drug_code, active_medication_codes) → list of DDI matches
- check_dhi(drug_code, patient_conditions, patient_factors) → list of DHI matches
- assess_severity(interaction) → severity with patient factor adjustments

HIPAA Compliance:
    - Never log drug names or patient conditions (only codes and IDs)
    - Interaction results are PHI (encrypted in DB)
"""

import structlog
from typing import Optional

logger = structlog.get_logger(__name__)


class InteractionEngine:
    """
    Drug interaction detection engine.

    Matches patient's medications against known interaction database.
    Considers patient factors (age, sex, renal function) for DHI assessment.
    """

    def __init__(self, db_session):
        """
        Initialize engine.

        Args:
            db_session: AsyncSession for accessing drug_interactions_db
        """
        self.db = db_session

    async def check_ddi(
        self,
        new_drug_code: str,
        active_medication_codes: list[str],
    ) -> list[dict]:
        """
        Check for drug-drug interactions (DDI).

        Compares new drug against all active medications using drug_interactions_db.

        Args:
            new_drug_code: RxNorm/ATC code of newly prescribed drug
            active_medication_codes: List of RxNorm/ATC codes for currently active meds

        Returns:
            list of dicts: [{
                "interaction_id": "...",
                "drug_a_code": "...",
                "drug_a_name": "...",
                "drug_b_code": "...",
                "drug_b_name": "...",
                "severity": "Contraindicated|Major|Moderate|Minor",
                "mechanism": "...",
                "adverse_outcome": "...",
                "recommended_action": "...",
                "evidence_level": "High|Moderate|Low",
            }]
        """
        interactions = []

        # Query drug_interactions_db for all DDI involving new_drug_code
        # Try: new_drug_code + each active drug_code
        from sqlalchemy import select
        from app.modules.drug_interactions_staging.models import DrugInteractionsDB

        for active_code in active_medication_codes:
            # Check both directions (A+B and B+A)
            stmt = select(DrugInteractionsDB).where(
                DrugInteractionsDB.interaction_type == "DDI",
                DrugInteractionsDB.is_active == True,
                (
                    (
                        (DrugInteractionsDB.drug_a_code == new_drug_code)
                        & (DrugInteractionsDB.drug_b_code == active_code)
                    )
                    | (
                        (DrugInteractionsDB.drug_a_code == active_code)
                        & (DrugInteractionsDB.drug_b_code == new_drug_code)
                    )
                ),
            )

            result = await self.db.execute(stmt)
            matches = result.scalars().all()

            for match in matches:
                interactions.append({
                    "interaction_id": str(match.id),
                    "drug_a_code": match.drug_a_code,
                    "drug_a_name": match.drug_a_name,
                    "drug_b_code": match.drug_b_code,
                    "drug_b_name": match.drug_b_name,
                    "severity": match.severity,
                    "mechanism": match.mechanism,
                    "adverse_outcome": match.adverse_outcome,
                    "recommended_action": match.recommended_action,
                    "evidence_level": match.evidence_level,
                })

        logger.info(
            "ddi_check_completed",
            new_drug_code=new_drug_code,
            interaction_count=len(interactions),
        )

        return interactions

    async def check_dhi(
        self,
        drug_code: str,
        patient_conditions: list[str],
        patient_factors: Optional[dict] = None,
    ) -> list[dict]:
        """
        Check for drug-health interactions (DHI).

        Checks if drug has contraindications or warnings with patient's conditions.
        Adjusts severity based on patient factors (age, renal function, etc.).

        Args:
            drug_code: RxNorm/ATC code of drug
            patient_conditions: List of ICD-10 codes or condition names (e.g., "CKD stage 4", "hepatic_impairment")
            patient_factors: Optional dict {age, sex, egfr, hemoglobin, ...}

        Returns:
            list of dicts: [{
                "interaction_id": "...",
                "drug_code": "...",
                "drug_name": "...",
                "health_condition": "...",
                "severity": "Contraindicated|Major|Moderate|Minor",
                "severity_adjusted": "..." (accounting for patient factors),
                "mechanism": "...",
                "adverse_outcome": "...",
                "recommended_action": "...",
                "evidence_level": "High|Moderate|Low",
                "patient_factor_notes": "...",
            }]
        """
        interactions = []

        from sqlalchemy import select
        from app.modules.drug_interactions_staging.models import DrugInteractionsDB

        # Query for DHI involving this drug and any of patient's conditions
        for condition in patient_conditions:
            stmt = select(DrugInteractionsDB).where(
                DrugInteractionsDB.interaction_type == "DHI",
                DrugInteractionsDB.is_active == True,
                DrugInteractionsDB.drug_a_code == drug_code,
                DrugInteractionsDB.health_condition == condition,
            )

            result = await self.db.execute(stmt)
            matches = result.scalars().all()

            for match in matches:
                # Assess severity with patient factors
                severity, notes = self._adjust_severity_for_patient_factors(
                    match.severity,
                    patient_factors or {},
                    condition,
                )

                interactions.append({
                    "interaction_id": str(match.id),
                    "drug_code": match.drug_a_code,
                    "drug_name": match.drug_a_name,
                    "health_condition": match.health_condition,
                    "severity": match.severity,
                    "severity_adjusted": severity,
                    "mechanism": match.mechanism,
                    "adverse_outcome": match.adverse_outcome,
                    "recommended_action": match.recommended_action,
                    "evidence_level": match.evidence_level,
                    "patient_factor_notes": notes,
                })

        logger.info(
            "dhi_check_completed",
            drug_code=drug_code,
            condition_count=len(patient_conditions),
            interaction_count=len(interactions),
        )

        return interactions

    def _adjust_severity_for_patient_factors(
        self,
        base_severity: str,
        patient_factors: dict,
        condition: str,
    ) -> tuple[str, str]:
        """
        Adjust interaction severity based on patient demographics and health status.

        Examples:
        - Metformin + CKD: Severity increases if eGFR <30 (contraindicated)
        - ACE inhibitor + CKD: Severity increases with younger age + advanced CKD
        - NSAIDs + HTN: Severity increases with age >65

        Args:
            base_severity: Original severity from drug_interactions_db
            patient_factors: {age, sex, egfr, hemoglobin, ...}
            condition: Health condition (e.g., "CKD stage 4")

        Returns:
            tuple: (adjusted_severity: str, notes: str)
        """
        age = patient_factors.get("age", 60)
        sex = patient_factors.get("sex", "M")
        egfr = patient_factors.get("egfr", 60)
        hemoglobin = patient_factors.get("hemoglobin", 13.5)

        notes = []
        severity = base_severity

        # Example: Metformin + severe CKD
        if "metformin" in condition.lower() or "diabetes" in condition.lower():
            if egfr and egfr < 30:
                severity = "Contraindicated"
                notes.append("eGFR <30 (severe renal impairment): risk of lactic acidosis")
            elif egfr and egfr < 45:
                severity = "Major"
                notes.append("eGFR <45 (moderate renal impairment): requires dose adjustment")

        # Example: NSAIDs + advanced age + HTN
        if "nsaid" in condition.lower() and age and age >= 65:
            if severity == "Moderate":
                severity = "Major"
            notes.append(f"Age {age}: increased GI bleed risk with NSAIDs + HTN")

        # Example: ACE inhibitor + CKD + hyperkalemia risk
        if "ace" in condition.lower() and "ckd" in condition.lower():
            if egfr and egfr < 30:
                severity = "Major"
                notes.append("eGFR <30: high hyperkalemia risk with ACE inhibitors")

        return severity, "; ".join(notes) if notes else "No patient factor adjustments"

    async def get_critical_interactions(
        self,
        active_medication_codes: list[str],
        patient_conditions: list[str],
        patient_factors: Optional[dict] = None,
    ) -> list[dict]:
        """
        Get all critical (Contraindicated or Major) interactions for a patient.

        Used by safety summary endpoint to highlight urgent issues.

        Args:
            active_medication_codes: List of active drug codes
            patient_conditions: List of patient conditions
            patient_factors: Optional patient demographics/labs

        Returns:
            list of dicts: Interactions with severity in [Contraindicated, Major]
        """
        critical = []

        # Check all DDI pairs
        from sqlalchemy import select
        from app.modules.drug_interactions_staging.models import DrugInteractionsDB

        for i, drug_code_a in enumerate(active_medication_codes):
            for drug_code_b in active_medication_codes[i + 1 :]:
                stmt = select(DrugInteractionsDB).where(
                    DrugInteractionsDB.interaction_type == "DDI",
                    DrugInteractionsDB.is_active == True,
                    DrugInteractionsDB.severity.in_(["Contraindicated", "Major"]),
                    (
                        (
                            (DrugInteractionsDB.drug_a_code == drug_code_a)
                            & (DrugInteractionsDB.drug_b_code == drug_code_b)
                        )
                        | (
                            (DrugInteractionsDB.drug_a_code == drug_code_b)
                            & (DrugInteractionsDB.drug_b_code == drug_code_a)
                        )
                    ),
                )

                result = await self.db.execute(stmt)
                matches = result.scalars().all()
                critical.extend([{"type": "DDI", "match": m} for m in matches])

        # Check all DHI pairs
        for drug_code in active_medication_codes:
            for condition in patient_conditions:
                stmt = select(DrugInteractionsDB).where(
                    DrugInteractionsDB.interaction_type == "DHI",
                    DrugInteractionsDB.is_active == True,
                    DrugInteractionsDB.severity.in_(["Contraindicated", "Major"]),
                    DrugInteractionsDB.drug_a_code == drug_code,
                    DrugInteractionsDB.health_condition == condition,
                )

                result = await self.db.execute(stmt)
                matches = result.scalars().all()
                critical.extend([{"type": "DHI", "match": m} for m in matches])

        return critical
