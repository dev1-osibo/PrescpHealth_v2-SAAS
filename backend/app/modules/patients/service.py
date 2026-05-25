"""
PrescpHealth Backend — Patient Service (Orchestrator).

Thin orchestrator that exposes the PatientService class and delegates to:
- service_create.py — create_patient()
- service_update.py — update_patient()
- service_delete.py — soft_delete_patient(), restore_patient()
- service_search.py — search_patients()
- service_versions.py — get_patient_versions(), get_patient_at_version(),
                         get_patient_timeline(), _describe_change()

This file maintains the public API surface that all consumers depend on:
- PatientService class with all CRUD, search, versioning, and timeline methods
- _describe_change helper (used by tests)

Architecture:
    PatientService methods delegate to module-level functions in the
    service_* sub-modules. This keeps each file under ~150 lines of logic
    while preserving the class-based interface that the router and tests
    depend on.

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
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResponse, PaginationParams
from app.modules.audit.service import AuditService
from app.modules.patients.exceptions import PatientNotFoundError
from app.modules.patients.patient_model import Patient
from app.modules.patients.search import PatientSearchFilters
from app.modules.patients.service_create import create_patient as _create_patient
from app.modules.patients.service_delete import (
    restore_patient as _restore_patient,
    soft_delete_patient as _soft_delete_patient,
)
from app.modules.patients.service_search import search_patients as _search_patients
from app.modules.patients.service_update import update_patient as _update_patient
from app.modules.patients.service_versions import (
    _describe_change,
    get_patient_at_version as _get_patient_at_version,
    get_patient_timeline as _get_patient_timeline,
    get_patient_versions as _get_patient_versions,
)

# Re-export _describe_change for backward compatibility (used by tests)
_describe_change = _describe_change  # noqa: F841


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

    async def create_patient(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict[str, Any],
    ) -> Patient:
        """Create a new patient record with initial version."""
        return await _create_patient(db, tenant_id, user_id, data, self._audit)

    async def get_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> Patient:
        """
        Get a single patient by ID.

        RLS handles tenant isolation — if the patient belongs to a
        different tenant, the query returns None (same as not found).

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

    async def update_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict[str, Any],
    ) -> Patient:
        """Update patient fields and create a new version with diff."""
        patient = await self.get_patient(db, patient_id)
        return await _update_patient(db, patient, user_id, data, self._audit)

    async def soft_delete_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Patient:
        """Soft-delete a patient (set deleted_at timestamp)."""
        patient = await self.get_patient(db, patient_id)
        return await _soft_delete_patient(db, patient, user_id, self._audit)

    async def restore_patient(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Patient:
        """Restore a soft-deleted patient (clear deleted_at)."""
        patient = await self.get_patient(db, patient_id)
        return await _restore_patient(db, patient, user_id, self._audit)

    async def search_patients(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        filters: PatientSearchFilters,
        pagination: PaginationParams,
    ) -> PaginatedResponse:
        """Search patients with filters and cursor-based pagination."""
        return await _search_patients(db, tenant_id, filters, pagination)

    async def get_patient_versions(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> list:
        """Get all version records for a patient."""
        # Verify patient exists (raises PatientNotFoundError if not)
        await self.get_patient(db, patient_id)
        return await _get_patient_versions(db, patient_id)

    async def get_patient_at_version(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        version_number: int,
    ):
        """Get the patient snapshot at a specific version number."""
        # Verify patient exists
        await self.get_patient(db, patient_id)
        return await _get_patient_at_version(db, patient_id, version_number)

    async def get_patient_timeline(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Get the patient timeline as a list of events."""
        # Verify patient exists
        await self.get_patient(db, patient_id)
        return await _get_patient_timeline(db, patient_id)
