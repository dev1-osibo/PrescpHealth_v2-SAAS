"""
PrescpHealth Backend — SOAP Note Service.

Handles CRUD operations for SOAP (Subjective, Objective, Assessment, Plan)
clinical notes within encounters. Each encounter can have multiple SOAP notes
(e.g., initial assessment, follow-up within the same visit).

HIPAA Compliance (Critical):
- SOAP note content is PHI — NEVER log subjective, objective, assessment, or plan
- Only log note_id (UUID) and encounter_id for operational tracing
- All CUD operations are audit-logged via AuditService (without content)
- Content is encrypted at rest via PostgreSQL TDE / column-level encryption

Usage:
    from app.modules.encounters.service_soap import SOAPNoteService

    soap_service = SOAPNoteService()
    note = await soap_service.add_soap_note(db, encounter_id, ...)
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.encounters.enums import EncounterStatus
from app.modules.encounters.exceptions import (
    EncounterAlreadyCompletedError,
    EncounterNotFoundError,
)
from app.modules.encounters.encounter_model import Encounter
from app.modules.encounters.soap_note_model import SOAPNote

# ---------------------------------------------------------------------------
# Module logger — NEVER log SOAP note content (PHI)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# Shared audit service instance
_audit = AuditService()


class SOAPNoteService:
    """
    Service for SOAP note CRUD operations.

    SOAP notes are the primary clinical documentation format. Each note
    has four sections (Subjective, Objective, Assessment, Plan) that
    capture the clinician's findings and treatment decisions.

    All operations validate that the parent encounter exists and is
    not yet completed (completed encounters are immutable).
    """

    async def add_soap_note(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        subjective: str | None = None,
        objective: str | None = None,
        assessment: str | None = None,
        plan: str | None = None,
    ) -> SOAPNote:
        """
        Add a new SOAP note to an encounter.

        Validates that the encounter exists and is still in progress
        before allowing note creation. Completed encounters cannot
        receive new notes (clinical documentation integrity).

        Args:
            db: Async database session.
            encounter_id: Parent encounter UUID.
            tenant_id: Tenant context for RLS isolation.
            user_id: Clinician authoring the note.
            subjective: Patient-reported symptoms (PHI — never logged).
            objective: Clinician observations (PHI — never logged).
            assessment: Clinical assessment (PHI — never logged).
            plan: Treatment plan (PHI — never logged).

        Returns:
            The newly created SOAPNote instance.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist.
            EncounterAlreadyCompletedError: If encounter is completed.
        """
        # Validate encounter exists and is modifiable
        await self._validate_encounter_modifiable(db, encounter_id)

        note = SOAPNote(
            encounter_id=encounter_id,
            tenant_id=tenant_id,
            recorded_by=user_id,
            subjective=subjective,
            objective=objective,
            assessment=assessment,
            plan=plan,
        )

        db.add(note)
        await db.flush()

        # Audit log — NEVER include SOAP content (PHI)
        await _audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="soap_note.create",
            resource_type="soap_note",
            resource_id=note.id,
        )

        logger.info(
            "soap_note_created",
            note_id=str(note.id),
            encounter_id=str(encounter_id),
            tenant_id=str(tenant_id),
        )

        return note

    async def update_soap_note(
        self,
        db: AsyncSession,
        note_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict,
    ) -> SOAPNote:
        """
        Update an existing SOAP note's sections.

        Only allows updates if the parent encounter is not completed.
        Updatable fields: subjective, objective, assessment, plan.

        Args:
            db: Async database session.
            note_id: UUID of the SOAP note to update.
            user_id: User performing the update (for audit).
            data: Dict of SOAP sections to update.

        Returns:
            Updated SOAPNote instance.

        Raises:
            EncounterNotFoundError: If parent encounter doesn't exist.
            EncounterAlreadyCompletedError: If parent encounter is completed.
            ValueError: If note_id doesn't exist.
        """
        # Load the note
        stmt = select(SOAPNote).where(SOAPNote.id == note_id)
        result = await db.execute(stmt)
        note = result.scalar_one_or_none()

        if note is None:
            raise ValueError(f"SOAP note not found: {note_id}")

        # Validate parent encounter is still modifiable
        await self._validate_encounter_modifiable(db, note.encounter_id)

        # Update allowed SOAP sections
        if "subjective" in data:
            note.subjective = data["subjective"]
        if "objective" in data:
            note.objective = data["objective"]
        if "assessment" in data:
            note.assessment = data["assessment"]
        if "plan" in data:
            note.plan = data["plan"]

        await db.flush()

        # Audit log — log field names updated, NEVER content (PHI)
        await _audit.log(
            db=db,
            tenant_id=note.tenant_id,
            user_id=user_id,
            action="soap_note.update",
            resource_type="soap_note",
            resource_id=note.id,
            changes={"fields_updated": list(data.keys())},
        )

        logger.info(
            "soap_note_updated",
            note_id=str(note.id),
            encounter_id=str(note.encounter_id),
        )

        return note

    async def get_soap_notes(
        self,
        db: AsyncSession,
        encounter_id: uuid.UUID,
    ) -> list[SOAPNote]:
        """
        Retrieve all SOAP notes for an encounter.

        Returns notes ordered by creation time descending (most recent first).

        Args:
            db: Async database session.
            encounter_id: Encounter whose notes to retrieve.

        Returns:
            List of SOAPNote instances for the encounter.
        """
        stmt = (
            select(SOAPNote)
            .where(SOAPNote.encounter_id == encounter_id)
            .order_by(SOAPNote.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    # -----------------------------------------------------------------------
    # Private Helpers
    # -----------------------------------------------------------------------

    async def _validate_encounter_modifiable(
        self, db: AsyncSession, encounter_id: uuid.UUID
    ) -> None:
        """
        Ensure the encounter exists and is not in a terminal state.

        Raises:
            EncounterNotFoundError: If encounter doesn't exist.
            EncounterAlreadyCompletedError: If encounter is completed.
        """
        stmt = select(Encounter.id, Encounter.status).where(
            Encounter.id == encounter_id
        )
        result = await db.execute(stmt)
        row = result.one_or_none()

        if row is None:
            raise EncounterNotFoundError(encounter_id)

        if row.status == EncounterStatus.COMPLETED:
            raise EncounterAlreadyCompletedError(encounter_id)
