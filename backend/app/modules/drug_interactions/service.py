"""
PrescpHealth Backend — Drug Interaction Service.

High-level service for medication management and interaction checking.

Key Responsibilities:
    - Add medication and run DDI + DHI checks
    - Get consolidated safety summary (Safe/Caution/Action Required)
    - Override interactions with mandatory justification
    - Re-evaluate interactions when patient health changes
    - Audit all mutations via AuditService

HIPAA Compliance:
    - Never log drug names or patient conditions (only codes/IDs)
    - Interaction results and overrides are PHI (encrypted in DB)
    - All operations audited
"""

import uuid
from datetime import datetime, date, timezone
from typing import Optional

import structlog
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.audit.service import AuditService
from app.modules.drug_interactions.models import (
    MedicationRecord,
    InteractionResult,
)
from app.modules.drug_interactions.engine import InteractionEngine

logger = structlog.get_logger(__name__)


class DrugInteractionService:
    """
    Service for medication management and drug interaction checking.

    Orchestrates medication lifecycle, interaction detection, and safety tracking.
    """

    def __init__(
        self,
        db: AsyncSession,
        audit_service: AuditService,
        engine: InteractionEngine,
    ):
        """
        Initialize DrugInteractionService.

        Args:
            db: AsyncSession for database operations
            audit_service: AuditService for audit logging
            engine: InteractionEngine for DDI/DHI checking
        """
        self.db = db
        self.audit_service = audit_service
        self.engine = engine

    async def add_medication(
        self,
        patient_id: uuid.UUID,
        drug_name: str,
        drug_code: str,
        dosage: str,
        frequency: str,
        route: str,
        start_date: date,
        prescribed_by: uuid.UUID,
    ) -> dict:
        """
        Add medication and check for DDI + DHI interactions.

        Orchestrates:
        1. Save medication record
        2. Get active medications (for DDI check)
        3. Get patient conditions (for DHI check)
        4. Run DDI + DHI checks via engine
        5. Store InteractionResult records for detected interactions
        6. Audit the action

        Args:
            patient_id: Patient UUID
            drug_name: Drug name
            drug_code: RxNorm/ATC code
            dosage: Dosage string
            frequency: Frequency string
            route: Route (oral, IV, etc.)
            start_date: When prescribed
            prescribed_by: Clinician UUID

        Returns:
            dict: {
                "medication_id": "...",
                "ddi_count": N,
                "dhi_count": M,
                "safety_status": "Safe|Caution|Action Required",
                "critical_interactions": [...],
                "recommended_actions": [...]
            }
        """
        # Create medication record
        med = MedicationRecord(
            patient_id=patient_id,
            drug_name=drug_name,
            drug_code=drug_code,
            dosage=dosage,
            frequency=frequency,
            route=route,
            start_date=start_date,
            prescribed_by=prescribed_by,
            is_active=True,
        )
        self.db.add(med)
        await self.db.flush()

        # Get active medications (excluding this one)
        active_meds = await self._get_active_medications(patient_id, exclude_id=med.id)
        active_codes = [m.drug_code for m in active_meds]

        # Get patient conditions (TODO: integrate with patient/health module)
        patient_conditions = await self._get_patient_conditions(patient_id)

        # Get patient factors (age, renal function, etc.)
        patient_factors = await self._get_patient_factors(patient_id)

        # Check DDI
        ddi_matches = await self.engine.check_ddi(drug_code, active_codes)

        # Check DHI
        dhi_matches = await self.engine.check_dhi(
            drug_code,
            patient_conditions,
            patient_factors,
        )

        # Store interaction results
        critical_interactions = []
        for match in ddi_matches:
            severity = match["severity"]
            interaction = InteractionResult(
                patient_id=patient_id,
                interaction_type="DDI",
                medication_a_id=med.id,
                # TODO: Find medication_b_id by drug_code
                medication_b_id=None,
                severity=severity,
                mechanism=match["mechanism"],
                adverse_outcome=match["adverse_outcome"],
                recommended_action=match["recommended_action"],
            )
            self.db.add(interaction)

            if severity in ["Contraindicated", "Major"]:
                critical_interactions.append({
                    "type": "DDI",
                    "severity": severity,
                    "action": match["recommended_action"],
                })

        for match in dhi_matches:
            severity = match["severity_adjusted"]
            interaction = InteractionResult(
                patient_id=patient_id,
                interaction_type="DHI",
                medication_a_id=med.id,
                medication_b_id=None,
                health_condition=match["health_condition"],
                severity=severity,
                mechanism=match["mechanism"],
                adverse_outcome=match["adverse_outcome"],
                recommended_action=match["recommended_action"],
            )
            self.db.add(interaction)

            if severity in ["Contraindicated", "Major"]:
                critical_interactions.append({
                    "type": "DHI",
                    "condition": match["health_condition"],
                    "severity": severity,
                    "action": match["recommended_action"],
                })

        await self.db.flush()
        await self.db.commit()

        # Determine safety status
        safety_status = "Safe"
        if critical_interactions:
            safety_status = "Action Required"
        elif ddi_matches or dhi_matches:
            safety_status = "Caution"

        # Audit
        await self.audit_service.log_action(
            action="medication_added",
            resource_type="patient",
            resource_id=patient_id,
            user_id=prescribed_by,
            changes={
                "drug_code": drug_code,
                "ddi_count": len(ddi_matches),
                "dhi_count": len(dhi_matches),
                "safety_status": safety_status,
            },
        )

        logger.info(
            "medication_added",
            patient_id=str(patient_id),
            drug_code=drug_code,
            ddi_count=len(ddi_matches),
            dhi_count=len(dhi_matches),
        )

        return {
            "medication_id": str(med.id),
            "ddi_count": len(ddi_matches),
            "dhi_count": len(dhi_matches),
            "safety_status": safety_status,
            "critical_interactions": critical_interactions,
        }

    async def get_safety_summary(
        self,
        patient_id: uuid.UUID,
    ) -> dict:
        """
        Get consolidated safety summary for all medications.

        Returns:
        - overall_status: Safe / Caution / Action Required
        - critical_issue_count: Count of Contraindicated or Major interactions
        - moderate_issue_count: Count of Moderate interactions
        - recommendations: Ordered list of clinical actions

        Args:
            patient_id: Patient UUID

        Returns:
            dict: {
                "overall_status": "Safe|Caution|Action Required",
                "critical_issue_count": N,
                "moderate_issue_count": M,
                "active_medication_count": K,
                "recommendations": [...],
            }
        """
        # Get all non-overridden interactions for this patient
        stmt = select(InteractionResult).where(
            InteractionResult.patient_id == patient_id,
            InteractionResult.is_overridden == False,
        ).order_by(
            desc(InteractionResult.severity),
        )

        result = await self.db.execute(stmt)
        interactions = result.scalars().all()

        critical_count = sum(1 for i in interactions if i.severity == "Contraindicated" or i.severity == "Major")
        moderate_count = sum(1 for i in interactions if i.severity == "Moderate")

        # Determine status
        if critical_count > 0:
            status = "Action Required"
        elif moderate_count > 0:
            status = "Caution"
        else:
            status = "Safe"

        # Build recommendations
        recommendations = []
        for interaction in interactions[:10]:  # Top 10 most critical
            recommendations.append({
                "interaction_id": str(interaction.id),
                "type": interaction.interaction_type,
                "severity": interaction.severity,
                "action": interaction.recommended_action,
            })

        # Get active med count
        stmt = select(MedicationRecord).where(
            MedicationRecord.patient_id == patient_id,
            MedicationRecord.is_active == True,
        )
        result = await self.db.execute(stmt)
        active_meds = result.scalars().all()

        return {
            "overall_status": status,
            "critical_issue_count": critical_count,
            "moderate_issue_count": moderate_count,
            "active_medication_count": len(active_meds),
            "recommendations": recommendations,
        }

    async def override_interaction(
        self,
        interaction_id: uuid.UUID,
        doctor_id: uuid.UUID,
        justification: str,
    ) -> dict:
        """
        Override a detected interaction with mandatory justification.

        Records who overrode it, when, and why (immutable audit trail).

        Args:
            interaction_id: InteractionResult UUID
            doctor_id: Clinician UUID
            justification: Mandatory clinical justification (min 20 chars)

        Returns:
            dict: {success: true, message: "..."}

        Raises:
            ValueError: If justification is too short
        """
        if len(justification) < 20:
            raise ValueError("Override justification must be at least 20 characters")

        interaction = await self.db.get(InteractionResult, interaction_id)
        if not interaction:
            raise ValueError(f"Interaction {interaction_id} not found")

        interaction.is_overridden = True
        interaction.override_justification = justification
        interaction.overridden_by = doctor_id
        interaction.overridden_at = datetime.now(timezone.utc)

        await self.db.commit()

        # Audit
        await self.audit_service.log_action(
            action="interaction_overridden",
            resource_type="interaction_result",
            resource_id=interaction_id,
            user_id=doctor_id,
            changes={
                "patient_id": str(interaction.patient_id),
                "interaction_type": interaction.interaction_type,
            },
        )

        logger.info(
            "interaction_overridden",
            interaction_id=str(interaction_id),
            doctor_id=str(doctor_id),
        )

        return {
            "success": True,
            "message": "Interaction overridden with justification recorded",
        }

    async def re_evaluate_on_health_change(
        self,
        patient_id: uuid.UUID,
        triggered_by_user_id: uuid.UUID,
    ) -> dict:
        """
        Re-evaluate all interactions when patient's health status changes.

        Called when:
        - New lab results change eGFR (impacts CKD DHI severity)
        - New diagnosis added
        - Patient age milestone reached
        - Health condition resolved/improved

        Args:
            patient_id: Patient UUID
            triggered_by_user_id: User who triggered re-evaluation

        Returns:
            dict: {
                "re_evaluated_count": N,
                "new_critical_interactions": [...],
                "severity_changes": [...],
            }
        """
        # Get all active medications
        stmt = select(MedicationRecord).where(
            MedicationRecord.patient_id == patient_id,
            MedicationRecord.is_active == True,
        )
        result = await self.db.execute(stmt)
        active_meds = result.scalars().all()

        # Re-check all interactions
        new_critical = []
        severity_changes = []

        for med in active_meds:
            # Re-check DDI
            active_codes = [m.drug_code for m in active_meds if m.id != med.id]
            ddi_matches = await self.engine.check_ddi(med.drug_code, active_codes)

            # Re-check DHI
            patient_conditions = await self._get_patient_conditions(patient_id)
            patient_factors = await self._get_patient_factors(patient_id)
            dhi_matches = await self.engine.check_dhi(
                med.drug_code,
                patient_conditions,
                patient_factors,
            )

            # Check for new critical interactions
            for match in ddi_matches + dhi_matches:
                severity = match.get("severity_adjusted") or match.get("severity")
                if severity in ["Contraindicated", "Major"]:
                    new_critical.append({
                        "drug_code": med.drug_code,
                        "severity": severity,
                        "type": "DDI" if "drug_b_name" in match else "DHI",
                    })

        # Audit
        await self.audit_service.log_action(
            action="interactions_reevaluated",
            resource_type="patient",
            resource_id=patient_id,
            user_id=triggered_by_user_id,
            changes={
                "medication_count": len(active_meds),
                "new_critical_count": len(new_critical),
            },
        )

        logger.info(
            "interactions_reevaluated",
            patient_id=str(patient_id),
            new_critical_count=len(new_critical),
        )

        return {
            "re_evaluated_count": len(active_meds),
            "new_critical_interactions": new_critical,
        }

    # Private helper methods

    async def _get_active_medications(
        self,
        patient_id: uuid.UUID,
        exclude_id: Optional[uuid.UUID] = None,
    ) -> list[MedicationRecord]:
        """Get active medications for a patient."""
        stmt = select(MedicationRecord).where(
            MedicationRecord.patient_id == patient_id,
            MedicationRecord.is_active == True,
        )
        if exclude_id:
            stmt = stmt.where(MedicationRecord.id != exclude_id)

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def _get_patient_conditions(self, patient_id: uuid.UUID) -> list[str]:
        """
        Get patient's health conditions (ICD-10 codes or condition names).

        TODO: Integrate with patient/health module.
        For now, returns empty list (mock implementation).
        """
        # TODO: Query from patient health module
        return []

    async def _get_patient_factors(self, patient_id: uuid.UUID) -> dict:
        """
        Get patient demographics and lab values for severity adjustment.

        TODO: Integrate with measurements module.
        For now, returns defaults.
        """
        # TODO: Query from measurements module
        return {
            "age": 65,
            "sex": "M",
            "egfr": 45,
            "hemoglobin": 13.5,
        }
