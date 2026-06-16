"""
PrescpHealth Backend — Bed Management: Nursing Service.

Handles nursing notes and vitals charting for admitted patients.
Separated from the core service to maintain file size under 150 lines.

HIPAA:
    - NursingNote.content is PHI — only note_id appears in log messages.
    - Vitals values may be PHI — only measurement_id and admission_id are logged.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditService
from app.modules.bed_management.enums import AdmissionStatus, NoteType
from app.modules.bed_management.exceptions import (
    AdmissionAlreadyDischargedError,
    AdmissionNotFoundError,
)
from app.modules.bed_management.models import Admission, NursingNote
from app.modules.bed_management.schemas import NursingNoteRequest, VitalsRequest

logger = structlog.get_logger(__name__)
_audit = AuditService()


class NursingService:
    """Nursing notes and vitals charting for inpatient admissions."""

    async def add_nursing_note(
        self,
        db: AsyncSession,
        admission_id: uuid.UUID,
        tenant_id: uuid.UUID,
        nurse_id: uuid.UUID,
        data: NursingNoteRequest,
    ) -> NursingNote:
        """
        Add a nursing note to an active admission.

        Note content is PHI and is stored in the DB but never logged.
        Only the note_id and note_type appear in log/audit entries.

        Args:
            db: Async DB session.
            admission_id: Admission to attach the note to.
            tenant_id: Tenant context.
            nurse_id: Nurse creating the note.
            data: Note request (content, type, timestamp).

        Returns:
            Newly created NursingNote.

        Raises:
            AdmissionNotFoundError: If admission not found.
            AdmissionAlreadyDischargedError: If admission is closed.
        """
        await self._assert_admission_active(db, admission_id)

        recorded_at = data.recorded_at or datetime.now(timezone.utc)

        note = NursingNote(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            admission_id=admission_id,
            nurse_id=nurse_id,
            content=data.content,  # PHI — stored only
            note_type=data.note_type,
            recorded_at=recorded_at,
        )
        db.add(note)
        await db.flush()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=nurse_id,
            action="nursing_note.create", resource_type="nursing_note",
            resource_id=note.id,
            # PHI-safe: log only note_type, never content
            changes={"note_type": data.note_type.value, "admission_id": str(admission_id)},
        )
        # Log only IDs — content is PHI
        logger.info(
            "nursing_note_added",
            note_id=str(note.id),
            note_type=data.note_type.value,
            admission_id=str(admission_id),
        )
        return note

    async def chart_vitals(
        self,
        db: AsyncSession,
        admission_id: uuid.UUID,
        tenant_id: uuid.UUID,
        nurse_id: uuid.UUID,
        data: VitalsRequest,
    ) -> dict[str, Any]:
        """
        Chart vitals for an admitted patient.

        Publishes a MeasurementSaved-equivalent event (stub).
        In production, this would create Measurement records via the
        measurements module and publish domain events.

        Args:
            db: Async DB session.
            admission_id: Target admission.
            tenant_id: Tenant context.
            nurse_id: Nurse recording vitals.
            data: Vitals values (may be PHI — not logged as values).

        Returns:
            Dict with measurement metadata (not values).

        Raises:
            AdmissionNotFoundError: If admission not found.
            AdmissionAlreadyDischargedError: If admission is closed.
        """
        await self._assert_admission_active(db, admission_id)

        # Build a metadata record of which vitals were provided
        # In production: create Measurement rows via measurements module
        recorded_fields = [
            field for field, value in data.model_dump(exclude_none=True).items()
            if field != "notes" and value is not None
        ]

        measurement_id = uuid.uuid4()

        await _audit.log(
            db=db, tenant_id=tenant_id, user_id=nurse_id,
            action="vitals.chart", resource_type="measurement",
            resource_id=measurement_id,
            # Log field names only — values may be PHI
            changes={"recorded_fields": recorded_fields, "admission_id": str(admission_id)},
        )
        logger.info(
            "vitals_charted",
            measurement_id=str(measurement_id),
            fields_count=len(recorded_fields),
            admission_id=str(admission_id),
        )

        return {
            "measurement_id": str(measurement_id),
            "admission_id": str(admission_id),
            "recorded_fields": recorded_fields,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            # STUB: In production, publish MeasurementSaved domain event here
            "event_published": False,
        }

    async def list_nursing_notes(
        self,
        db: AsyncSession,
        admission_id: uuid.UUID,
        note_type: Optional[NoteType] = None,
        limit: int = 50,
    ) -> list[NursingNote]:
        """
        List nursing notes for an admission, newest first.

        Args:
            db: Async DB session.
            admission_id: Target admission.
            note_type: Optional filter by note type.
            limit: Maximum notes to return.

        Returns:
            Ordered list of NursingNote instances.
        """
        stmt = (
            select(NursingNote)
            .where(NursingNote.admission_id == admission_id)
            .order_by(NursingNote.recorded_at.desc())
            .limit(limit)
        )
        if note_type is not None:
            stmt = stmt.where(NursingNote.note_type == note_type)

        return list((await db.execute(stmt)).scalars())

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    async def _assert_admission_active(
        self, db: AsyncSession, admission_id: uuid.UUID
    ) -> None:
        """
        Assert that an admission exists and is in ACTIVE status.

        Raises:
            AdmissionNotFoundError: If not found.
            AdmissionAlreadyDischargedError: If already discharged.
        """
        result = (
            await db.execute(
                select(Admission).where(Admission.id == admission_id)
            )
        ).scalar_one_or_none()

        if result is None:
            raise AdmissionNotFoundError(admission_id)
        if result.status == AdmissionStatus.DISCHARGED:
            raise AdmissionAlreadyDischargedError(admission_id)
