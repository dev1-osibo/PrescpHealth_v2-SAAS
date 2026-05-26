"""
PrescpHealth Backend — Encounter Service (Orchestrator).

Central service for encounter lifecycle management. Coordinates
creation, retrieval, updates, completion, and discharge summary
generation. Delegates SOAP notes and diagnoses to their respective
sub-services for modularity.

Responsibilities:
- Create encounters with audit logging
- Retrieve encounters with related SOAP notes, diagnoses, procedures
- Update encounter fields (status, reason, clinician)
- Complete encounters: generate discharge summary, publish event
- List patient encounters with cursor-based pagination

HIPAA Compliance:
- NEVER log reason_for_visit, discharge_summary, or SOAP content
- Only log encounter_id (UUID) and action metadata
- All CUD operations are audit-logged via AuditService

Usage:
    from app.modules.encounters.service import EncounterService

    service = EncounterService()
    encounter = await service.create_encounter(db, tenant_id, ...)
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.events import EncounterCompleted, event_bus
from app.core.request_context import get_request_id
from app.modules.audit.service import AuditService
from app.modules.encounters.encounter_model import Encounter
from app.modules.encounters.enums import EncounterClass, EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
    InvalidEncounterStatusTransitionError,
)

# ---------------------------------------------------------------------------
# Module logger — logs encounter operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Allowed status transitions (current_status → set of valid next statuses)
_VALID_TRANSITIONS: dict[EncounterStatus, set[EncounterStatus]] = {
    EncounterStatus.PLANNED: {EncounterStatus.IN_PROGRESS, EncounterStatus.CANCELLED},
    EncounterStatus.IN_PROGRESS: {EncounterStatus.COMPLETED, EncounterStatus.CANCELLED},
    EncounterStatus.COMPLETED: set(),  # Terminal state — no transitions allowed
    EncounterStatus.CANCELLED: set(),  # Terminal state — no transitions allowed
}

# Shared audit service instance
_audit = AuditService()


class EncounterService:
    """
    Orchestrator service for encounter lifecycle management.

    Handles creation, retrieval, updates, completion (with discharge
    summary generation), and paginated listing of encounters.

    All mutations are audit-logged. Completion publishes an
    EncounterCompleted domain event for downstream subscribers.
    """

    async def create_encounter(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        clinician_id: uuid.UUID,
        reason: str,
        encounter_class: EncounterClass = EncounterClass.AMBULATORY,
    ) -> Encounter:
        """
        Create a new encounter (patient check-in).

        Creates the encounter record and logs the action to the audit trail.
        The encounter starts in IN_PROGRESS status by default (patient has
        arrived and is being seen).

        Args:
            db: Async database session.
            tenant_id: Tenant context for RLS isolation.
            patient_id: Patient being seen.
            clinician_id: Assigned clinician UUID.
            reason: Chief complaint / reason for visit (PHI — never logged).
            encounter_class: Setting classification (ambulatory, inpatient, emergency).

        Returns:
            The newly created Encounter instance.
        """
        encounter = Encounter(
            tenant_id=tenant_id,
            patient_id=patient_id,
            clinician_id=clinician_id,
            reason_for_visit=reason,
            encounter_class=encounter_class,
            status=EncounterStatus.IN_PROGRESS,
            check_in_time=datetime.now(timezone.utc),
        )

        db.add(encounter)
        await db.flush()

        # Audit log — never include reason_for_visit (PHI)
        await _audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=clinician_id,
            action="encounter.create",
            resource_type="encounter",
            resource_id=encounter.id,
        )

        logger.info(
            "encounter_created",
            encounter_id=str(encounter.id),
            tenant_id=str(tenant_id),
            patient_id=str(patient_id),
        )

        return encounter

    async def get_encounter(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
    ) -> Encounter:
        """
        Retrieve an encounter with all related clinical data.

        Eagerly loads SOAP notes, diagnoses, and procedures to avoid
        N+1 queries when the caller needs the full encounter context.

        Args:
            db: Async database session.
            encounter_id: UUID of the encounter to retrieve.

        Returns:
            Encounter with loaded relationships.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist or is hidden by RLS.
        """
        stmt = (
            select(Encounter)
            .where(Encounter.id == encounter_id)
            .options(
                selectinload(Encounter.soap_notes),
                selectinload(Encounter.diagnoses),
                selectinload(Encounter.procedures),
            )
        )
        result = await db.execute(stmt)
        encounter = result.scalar_one_or_none()

        if encounter is None:
            raise EncounterNotFoundError(encounter_id)

        return encounter

    async def update_encounter(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict,
    ) -> Encounter:
        """
        Update mutable encounter fields.

        Only allows updates while encounter is not completed.
        Updatable fields: status, clinician_id, encounter_class.
        Status changes are validated against allowed transitions.

        Args:
            db: Async database session.
            encounter_id: UUID of the encounter to update.
            user_id: User performing the update (for audit).
            data: Dict of fields to update.

        Returns:
            Updated Encounter instance.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist.
            EncounterAlreadyCompletedError: If encounter is completed.
            InvalidEncounterStatusTransitionError: If status change is invalid.
        """
        encounter = await self._get_encounter_for_update(db, encounter_id)

        # Validate status transition if status is being changed
        if "status" in data:
            new_status = EncounterStatus(data["status"])
            self._validate_transition(encounter, new_status)
            encounter.status = new_status

        # Update allowed fields (never update reason_for_visit via this method)
        if "clinician_id" in data:
            encounter.clinician_id = data["clinician_id"]
        if "encounter_class" in data:
            encounter.encounter_class = EncounterClass(data["encounter_class"])

        await db.flush()

        # Audit the update — log field names changed, not values (PHI safety)
        await _audit.log(
            db=db,
            tenant_id=encounter.tenant_id,
            user_id=user_id,
            action="encounter.update",
            resource_type="encounter",
            resource_id=encounter.id,
            changes={"fields_updated": list(data.keys())},
        )

        return encounter

    async def complete_encounter(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Encounter:
        """
        Complete an encounter: generate discharge summary and publish event.

        This is the final step in the encounter lifecycle. It:
        1. Validates the encounter can be completed (must be in_progress)
        2. Generates a discharge summary JSONB from related data
        3. Sets status to COMPLETED and records check_out_time
        4. Publishes EncounterCompleted domain event
        5. Audit logs the completion

        Args:
            db: Async database session.
            encounter_id: UUID of the encounter to complete.
            user_id: Clinician completing the encounter.

        Returns:
            Completed Encounter with discharge_summary populated.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist.
            EncounterAlreadyCompletedError: If already completed.
            InvalidEncounterStatusTransitionError: If not in_progress.
        """
        # Load encounter with all related data for discharge summary
        encounter = await self.get_encounter(db, encounter_id)

        # Validate transition to completed
        self._validate_transition(encounter, EncounterStatus.COMPLETED)

        # Generate discharge summary from encounter data
        encounter.discharge_summary = self._build_discharge_summary(encounter)
        encounter.status = EncounterStatus.COMPLETED
        encounter.check_out_time = datetime.now(timezone.utc)

        await db.flush()

        # Audit log the completion
        await _audit.log(
            db=db,
            tenant_id=encounter.tenant_id,
            user_id=user_id,
            action="encounter.complete",
            resource_type="encounter",
            resource_id=encounter.id,
        )

        # Publish EncounterCompleted event for downstream subscribers
        await event_bus.publish(
            EncounterCompleted(
                correlation_id=get_request_id() or str(uuid.uuid4()),
                tenant_id=encounter.tenant_id,
                encounter_id=encounter.id,
                patient_id=encounter.patient_id,
            )
        )

        logger.info(
            "encounter_completed",
            encounter_id=str(encounter.id),
            tenant_id=str(encounter.tenant_id),
        )

        return encounter

    async def list_patient_encounters(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        limit: int = 25,
        cursor: datetime | None = None,
    ) -> list[Encounter]:
        """
        List encounters for a patient with cursor-based pagination.

        Returns encounters ordered by check_in_time descending (most recent first).
        Uses cursor-based pagination on check_in_time for scalability.

        Args:
            db: Async database session.
            patient_id: Patient whose encounters to list.
            limit: Maximum results per page (default 25, max 100).
            cursor: check_in_time cursor — return encounters older than this.

        Returns:
            List of Encounter instances (without eager-loaded relationships).
        """
        # Clamp limit to allowed range
        limit = min(max(limit, 1), 100)

        stmt = (
            select(Encounter)
            .where(Encounter.patient_id == patient_id)
            .order_by(Encounter.check_in_time.desc())
            .limit(limit)
        )

        # Apply cursor filter if provided (pagination)
        if cursor is not None:
            stmt = stmt.where(Encounter.check_in_time < cursor)

        result = await db.execute(stmt)
        return list(result.scalars().all())

    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------

    async def _get_encounter_for_update(
        self, db: AsyncSession, encounter_id: uuid.UUID
    ) -> Encounter:
        """
        Load encounter for mutation, checking it's not already completed.

        Raises:
            EncounterNotFoundError: If not found.
            EncounterAlreadyCompletedError: If status is COMPLETED.
        """
        stmt = select(Encounter).where(Encounter.id == encounter_id)
        result = await db.execute(stmt)
        encounter = result.scalar_one_or_none()

        if encounter is None:
            raise EncounterNotFoundError(encounter_id)

        if encounter.status == EncounterStatus.COMPLETED:
            raise EncounterAlreadyCompletedError(encounter_id)

        return encounter

    def _validate_transition(
        self, encounter: Encounter, new_status: EncounterStatus
    ) -> None:
        """
        Validate that the status transition is allowed.

        Raises:
            EncounterAlreadyCompletedError: If encounter is completed.
            InvalidEncounterStatusTransitionError: If transition is invalid.
        """
        current = EncounterStatus(encounter.status)

        if current == EncounterStatus.COMPLETED:
            raise EncounterAlreadyCompletedError(encounter.id)

        if new_status not in _VALID_TRANSITIONS.get(current, set()):
            raise InvalidEncounterStatusTransitionError(
                encounter_id=encounter.id,
                current_status=current.value,
                attempted_status=new_status.value,
            )

    def _build_discharge_summary(self, encounter: Encounter) -> dict:
        """
        Build the discharge summary JSONB from encounter data.

        The discharge summary contains:
        - diagnoses: List of {icd10_code, display_name, is_primary, is_chronic}
        - procedures: List of {code, description, performed_at}
        - prescriptions: Placeholder list (populated by prescription service)
        - follow_up: Instructions text (placeholder for clinician input)

        Args:
            encounter: Encounter with loaded relationships.

        Returns:
            Dict suitable for JSONB storage.
        """
        diagnoses_list = [
            {
                "icd10_code": dx.icd10_code,
                "display_name": dx.display_name,
                "is_primary": dx.is_primary,
                "is_chronic": dx.is_chronic,
            }
            for dx in encounter.diagnoses
        ]

        procedures_list = [
            {
                "code": proc.code,
                "description": proc.description,
                "performed_at": proc.performed_at.isoformat()
                if proc.performed_at
                else None,
            }
            for proc in encounter.procedures
        ]

        return {
            "diagnoses": diagnoses_list,
            "procedures": procedures_list,
            "prescriptions": [],  # Populated by prescription module if linked
            "follow_up": None,  # Clinician fills via update or separate endpoint
        }
