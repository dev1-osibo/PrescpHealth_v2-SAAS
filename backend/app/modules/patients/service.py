"""
PrescpHealth Backend — Patient Service (Main Orchestrator).

The primary service layer for patient profile management. Orchestrates:
- CRUD operations (create, read, update, soft-delete, restore)
- Versioning (every mutation creates an immutable version record)
- Search (delegated to search module)
- Timeline (placeholder for future extension)
- Audit logging (every CUD operation logged for HIPAA compliance)

Architecture:
    PatientService is a thin orchestration layer that coordinates:
    - Patient model operations (SQLAlchemy queries)
    - Versioning (app.modules.patients.versioning)
    - Search (app.modules.patients.search)
    - Serialization (app.modules.patients.serialization)
    - Audit logging (app.modules.audit.service)

    Each concern is in its own module for testability and clarity.

HIPAA Compliance:
    - Never logs PHI (only patient_id UUID in log messages)
    - Soft-delete only (HIPAA requires 7-year retention)
    - Every CUD operation creates an audit log entry
    - Every mutation creates an immutable version record
    - RLS enforces tenant isolation at the database level

Usage:
    from app.modules.patients.service import PatientService

    service = PatientService()
    patient = await service.create_patient(db, tenant_id, user_id, data)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResponse, PaginationParams
from app.modules.audit.service import AuditService
from app.modules.patients.exceptions import (
    DuplicateMRNError,
    PatientAlreadyDeletedError,
    PatientNotDeletedError,
    PatientNotFoundError,
)
from app.modules.patients.models import Patient, PatientChangeType
from app.modules.patients.search import PatientSearchFilters, search_patients
from app.modules.patients.serialization import (
    compute_diff,
    patient_to_snapshot,
)
from app.modules.patients.versioning import (
    create_version,
    get_version_at,
    get_versions,
)

# ---------------------------------------------------------------------------
# Module logger — logs patient operations without PHI
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


class PatientService:
    """
    Patient profile management service.

    Provides the complete API for patient CRUD, versioning, search,
    and timeline operations. All methods are async and expect a
    database session to be passed in (dependency injection pattern).

    Every mutation (create, update, delete, restore) automatically:
    1. Creates a PatientVersion record (immutable audit trail)
    2. Logs to the audit service (HIPAA compliance)
    3. Commits the transaction

    Usage:
        service = PatientService()
        patient = await service.create_patient(db, tenant_id, user_id, data)
    """

    def __init__(self) -> None:
        """Initialize with audit service dependency."""
        self._audit = AuditService()

    # -----------------------------------------------------------------------
    # CREATE
    # -----------------------------------------------------------------------
    async def create_patient(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict[str, Any],
    ) -> Patient:
        """
        Create a new patient record with initial version.

        Flow:
        1. Create Patient model instance
        2. Flush to get the generated ID
        3. Create version 1 (change_type=create, full snapshot)
        4. Log to audit trail
        5. Commit transaction

        Args:
            db: Database session (tenant-scoped via RLS).
            tenant_id: Tenant UUID for the new patient.
            user_id: UUID of the user creating the patient.
            data: Patient field values (validated by caller/schema).

        Returns:
            The created Patient model instance.

        Raises:
            DuplicateMRNError: If MRN already exists for this tenant.
        """
        # Build the patient model from provided data
        patient = Patient(
            tenant_id=tenant_id,
            created_by=user_id,
            **data,
        )

        db.add(patient)

        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            # Check if it's a duplicate MRN violation
            if "uq_patient_tenant_mrn" in str(exc.orig):
                raise DuplicateMRNError(data.get("medical_record_number", ""))
            raise

        # Create initial version (version 1) with full snapshot
        snapshot = patient_to_snapshot(patient)
        await create_version(
            db=db,
            tenant_id=tenant_id,
            patient_id=patient.id,
            user_id=user_id,
            change_type=PatientChangeType.CREATE,
            changes={},  # No diff for creation — snapshot IS the initial state
            snapshot=snapshot,
        )

        # Audit log — HIPAA requirement for all CUD operations
        await self._audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="patient.create",
            resource_type="patient",
            resource_id=patient.id,
        )

        await db.commit()

        logger.info(
            "patient_created",
            patient_id=str(patient.id),
            tenant_id=str(tenant_id),
        )

        return patient

    # -----------------------------------------------------------------------
    # READ
    # -----------------------------------------------------------------------
    async def get_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> Patient:
        """
        Get a single patient by ID.

        RLS handles tenant isolation — if the patient belongs to a
        different tenant, the query returns None (same as not found).
        Soft-deleted patients are still returned (caller decides visibility).

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient to retrieve.

        Returns:
            The Patient model instance.

        Raises:
            PatientNotFoundError: If patient doesn't exist or wrong tenant.
        """
        result = await db.execute(
            select(Patient).where(Patient.id == patient_id)
        )
        patient = result.scalar_one_or_none()

        if patient is None:
            raise PatientNotFoundError(patient_id)

        return patient

    # -----------------------------------------------------------------------
    # UPDATE
    # -----------------------------------------------------------------------
    async def update_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict[str, Any],
    ) -> Patient:
        """
        Update patient fields and create a new version with diff.

        Flow:
        1. Load existing patient
        2. Snapshot the current state (before changes)
        3. Apply field updates
        4. Snapshot the new state (after changes)
        5. Compute diff between old and new
        6. Create version record with diff and new snapshot
        7. Log to audit trail
        8. Commit transaction

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient to update.
            user_id: UUID of the user making the change.
            data: Dict of field names to new values (partial update).

        Returns:
            The updated Patient model instance.

        Raises:
            PatientNotFoundError: If patient doesn't exist.
            DuplicateMRNError: If new MRN conflicts with existing.
        """
        patient = await self.get_patient(db, patient_id)

        # Snapshot BEFORE applying changes (for diff computation)
        old_snapshot = patient_to_snapshot(patient)

        # Apply updates to the model
        for field, value in data.items():
            if hasattr(patient, field):
                setattr(patient, field, value)

        try:
            await db.flush()
        except IntegrityError as exc:
            await db.rollback()
            if "uq_patient_tenant_mrn" in str(exc.orig):
                raise DuplicateMRNError(data.get("medical_record_number", ""))
            raise

        # Snapshot AFTER changes
        new_snapshot = patient_to_snapshot(patient)

        # Compute what actually changed
        changes = compute_diff(old_snapshot, new_snapshot)

        # Only create a version if something actually changed
        if changes:
            await create_version(
                db=db,
                tenant_id=patient.tenant_id,
                patient_id=patient.id,
                user_id=user_id,
                change_type=PatientChangeType.UPDATE,
                changes=changes,
                snapshot=new_snapshot,
            )

            # Audit log with field names that changed (not values — no PHI)
            await self._audit.log(
                db=db,
                tenant_id=patient.tenant_id,
                user_id=user_id,
                action="patient.update",
                resource_type="patient",
                resource_id=patient.id,
                changes={"fields_changed": list(changes.keys())},
            )

        await db.commit()

        logger.info(
            "patient_updated",
            patient_id=str(patient_id),
            fields_changed=list(changes.keys()) if changes else [],
        )

        return patient

    # -----------------------------------------------------------------------
    # SOFT DELETE
    # -----------------------------------------------------------------------
    async def soft_delete_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Patient:
        """
        Soft-delete a patient (set deleted_at timestamp).

        HIPAA requires 7-year retention — we never hard-delete patient data.
        Soft-deleted patients are excluded from search by default but
        remain accessible for audit and compliance purposes.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient to delete.
            user_id: UUID of the user performing the deletion.

        Returns:
            The soft-deleted Patient model instance.

        Raises:
            PatientNotFoundError: If patient doesn't exist.
            PatientAlreadyDeletedError: If already soft-deleted.
        """
        patient = await self.get_patient(db, patient_id)

        # Prevent double-deletion (would corrupt audit trail)
        if patient.deleted_at is not None:
            raise PatientAlreadyDeletedError(patient_id)

        # Snapshot before deletion
        old_snapshot = patient_to_snapshot(patient)

        # Apply soft delete
        patient.deleted_at = datetime.now(timezone.utc)

        await db.flush()

        # Snapshot after deletion
        new_snapshot = patient_to_snapshot(patient)
        changes = compute_diff(old_snapshot, new_snapshot)

        # Create version with soft_delete change type
        await create_version(
            db=db,
            tenant_id=patient.tenant_id,
            patient_id=patient.id,
            user_id=user_id,
            change_type=PatientChangeType.SOFT_DELETE,
            changes=changes,
            snapshot=new_snapshot,
        )

        # Audit log
        await self._audit.log(
            db=db,
            tenant_id=patient.tenant_id,
            user_id=user_id,
            action="patient.soft_delete",
            resource_type="patient",
            resource_id=patient.id,
        )

        await db.commit()

        logger.info("patient_soft_deleted", patient_id=str(patient_id))

        return patient

    # -----------------------------------------------------------------------
    # RESTORE
    # -----------------------------------------------------------------------
    async def restore_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Patient:
        """
        Restore a soft-deleted patient (clear deleted_at).

        Reverses a soft-delete operation. The patient becomes visible
        in search results again and can be modified normally.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient to restore.
            user_id: UUID of the user performing the restoration.

        Returns:
            The restored Patient model instance.

        Raises:
            PatientNotFoundError: If patient doesn't exist.
            PatientNotDeletedError: If patient isn't currently deleted.
        """
        patient = await self.get_patient(db, patient_id)

        # Can only restore a deleted patient
        if patient.deleted_at is None:
            raise PatientNotDeletedError(patient_id)

        # Snapshot before restore
        old_snapshot = patient_to_snapshot(patient)

        # Clear the soft-delete marker
        patient.deleted_at = None

        await db.flush()

        # Snapshot after restore
        new_snapshot = patient_to_snapshot(patient)
        changes = compute_diff(old_snapshot, new_snapshot)

        # Create version with restore change type
        await create_version(
            db=db,
            tenant_id=patient.tenant_id,
            patient_id=patient.id,
            user_id=user_id,
            change_type=PatientChangeType.RESTORE,
            changes=changes,
            snapshot=new_snapshot,
        )

        # Audit log
        await self._audit.log(
            db=db,
            tenant_id=patient.tenant_id,
            user_id=user_id,
            action="patient.restore",
            resource_type="patient",
            resource_id=patient.id,
        )

        await db.commit()

        logger.info("patient_restored", patient_id=str(patient_id))

        return patient

    # -----------------------------------------------------------------------
    # SEARCH
    # -----------------------------------------------------------------------
    async def search_patients(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        filters: PatientSearchFilters,
        pagination: PaginationParams,
    ) -> PaginatedResponse:
        """
        Search patients with filters and cursor-based pagination.

        Delegates to the search module for query construction.
        See app.modules.patients.search for filter details.

        Args:
            db: Database session (tenant-scoped via RLS).
            tenant_id: Tenant UUID for explicit filtering.
            filters: Search criteria (name, MRN, status, date range).
            pagination: Page size and cursor.

        Returns:
            PaginatedResponse with patient items and pagination metadata.
        """
        return await search_patients(db, tenant_id, filters, pagination)

    # -----------------------------------------------------------------------
    # VERSIONING
    # -----------------------------------------------------------------------
    async def get_patient_versions(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> list:
        """
        Get all version records for a patient.

        Returns the complete version history ordered newest first.
        Each version includes: version_number, change_type, changes,
        snapshot, changed_by, changed_at.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.

        Returns:
            List of PatientVersion records, newest first.
        """
        # Verify patient exists (raises PatientNotFoundError if not)
        await self.get_patient(db, patient_id)
        return await get_versions(db, patient_id)

    async def get_patient_at_version(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        version_number: int,
    ):
        """
        Get the patient snapshot at a specific version number.

        Used for point-in-time recovery — returns the full patient
        state as it existed at that version.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.
            version_number: The version to retrieve (1-based).

        Returns:
            PatientVersion record with snapshot at that version.

        Raises:
            PatientNotFoundError: If patient doesn't exist.
            PatientVersionNotFoundError: If version number doesn't exist.
        """
        # Verify patient exists
        await self.get_patient(db, patient_id)
        return await get_version_at(db, patient_id, version_number)

    # -----------------------------------------------------------------------
    # TIMELINE (placeholder — will be extended with measurements, alerts)
    # -----------------------------------------------------------------------
    async def get_patient_timeline(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """
        Get the patient timeline as a list of events.

        Currently returns version history formatted as timeline events.
        Will be extended in future phases to include:
        - Measurements recorded
        - Risk score computations
        - Alerts generated
        - AI assistant interactions

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.

        Returns:
            List of timeline event dicts, newest first.
            Each event has: type, timestamp, description, metadata.
        """
        # Verify patient exists
        await self.get_patient(db, patient_id)

        # Get version history as timeline events
        versions = await get_versions(db, patient_id)

        timeline_events: list[dict[str, Any]] = []
        for version in versions:
            event = {
                "type": "profile_change",
                "subtype": version.change_type.value,
                "timestamp": version.changed_at.isoformat(),
                "version_number": version.version_number,
                "changed_by": str(version.changed_by),
                "description": _describe_change(
                    version.change_type, version.changes
                ),
            }
            timeline_events.append(event)

        return timeline_events


def _describe_change(
    change_type: PatientChangeType,
    changes: dict[str, Any],
) -> str:
    """
    Generate a human-readable description of a patient change.

    Used in timeline display to summarize what happened without
    exposing PHI values. Only mentions field names, not values.

    Args:
        change_type: The type of change (create, update, etc.).
        changes: The diff dict ({field: {old, new}}).

    Returns:
        Human-readable description string.
    """
    if change_type == PatientChangeType.CREATE:
        return "Patient record created"
    elif change_type == PatientChangeType.SOFT_DELETE:
        return "Patient record deleted"
    elif change_type == PatientChangeType.RESTORE:
        return "Patient record restored"
    elif change_type == PatientChangeType.UPDATE:
        field_count = len(changes)
        field_names = ", ".join(changes.keys())
        return f"Updated {field_count} field(s): {field_names}"
    return "Unknown change"
