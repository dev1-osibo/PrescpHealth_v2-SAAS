"""
PrescpHealth Backend — Measurement Service (Main Orchestrator).

The primary service layer for clinical measurement management. Orchestrates:
- Save measurement (with validation, idempotency, deviation detection)
- Validate measurement (clinician approval of Patient_User submissions)
- Bulk import (CSV-style multi-row import with per-row validation)
- History queries (time-series with cursor-based pagination)
- Latest measurements (one per type for risk engine feature extraction)
- Baseline computation (mean/std for deviation detection)

Architecture:
    MeasurementService is a thin orchestration layer that coordinates:
    - Save logic (app.modules.measurements.save)
    - Validation logic (app.modules.measurements.validate_record)
    - Bulk import (app.modules.measurements.bulk_import)
    - History queries (app.modules.measurements.history)
    - Baseline computation (app.modules.measurements.baseline)
    - Audit logging (app.modules.audit.service)

    Each concern is in its own module for testability and clarity.

HIPAA Compliance:
    - Never logs PHI (only measurement_id UUID and type in log messages)
    - Every CUD operation creates an audit log entry
    - RLS enforces tenant isolation at the database level
    - Measurement values are never exposed in errors or logs

Usage:
    from app.modules.measurements.service import MeasurementService

    service = MeasurementService()
    measurement = await service.save_measurement(db, tenant_id, patient_id, user_id, data)
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResponse, PaginationParams
from app.modules.audit.service import AuditService
from app.modules.measurements.baseline import (
    BaselineResult,
    compute_baseline,
)
from app.modules.measurements.bulk_import import (
    BulkImportResult,
    bulk_import,
)
from app.modules.measurements.data_sufficiency import (
    DataSufficiencyResult,
    check_data_sufficiency,
)
from app.modules.measurements.feature_vector import get_feature_vector
from app.modules.measurements.history import (
    HistoryFilters,
    get_latest_measurements,
    get_measurement_history,
)
from app.modules.measurements.models import Measurement
from app.modules.measurements.save import save_measurement
from app.modules.measurements.validate_record import validate_measurement_record


class MeasurementService:
    """
    Clinical measurement management service.

    Provides the complete API for measurement CRUD, validation, bulk import,
    and history queries. All methods are async and expect a database session
    to be passed in (dependency injection pattern).

    Every mutation (save, validate) automatically:
    1. Logs to the audit service (HIPAA compliance)
    2. Publishes domain events for downstream processing

    Usage:
        service = MeasurementService()
        measurement = await service.save_measurement(db, tenant_id, patient_id, user_id, data)
    """

    def __init__(self) -> None:
        """Initialize with audit service dependency."""
        self._audit = AuditService()

    # -----------------------------------------------------------------------
    # SAVE MEASUREMENT
    # -----------------------------------------------------------------------
    async def save_measurement(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        data: dict[str, Any],
    ) -> Measurement:
        """
        Save a clinical measurement with full validation pipeline.

        Delegates to the save module which handles:
        1. Physiological range validation
        2. Idempotency check (returns existing if duplicate)
        3. Baseline deviation detection (flags >2σ)
        4. Persistence
        5. MeasurementSaved event publishing
        6. Audit logging

        Args:
            db: Database session (tenant-scoped via RLS).
            tenant_id: Tenant UUID for the measurement.
            patient_id: UUID of the patient.
            user_id: UUID of the user recording the measurement.
            data: Measurement data (measurement_type, value, unit, recorded_at, source).

        Returns:
            The saved (or existing duplicate) Measurement instance.

        Raises:
            ValidationError: If value is outside physiological range.
        """
        return await save_measurement(
            db=db,
            tenant_id=tenant_id,
            patient_id=patient_id,
            user_id=user_id,
            data=data,
            audit_service=self._audit,
        )

    # -----------------------------------------------------------------------
    # VALIDATE MEASUREMENT (Clinician Approval)
    # -----------------------------------------------------------------------
    async def validate_measurement(
        self,
        db: AsyncSession,
        measurement_id: uuid.UUID,
        user_id: uuid.UUID,
        user_role: str,
    ) -> Measurement:
        """
        Mark a measurement as validated by a clinician.

        Only clinician roles (Doctor, Nurse, Clinic_Admin, Super_Admin)
        can validate measurements. Patient_User is forbidden.

        Args:
            db: Database session (tenant-scoped via RLS).
            measurement_id: UUID of the measurement to validate.
            user_id: UUID of the clinician performing validation.
            user_role: Role string of the user.

        Returns:
            The updated Measurement with is_validated=True.

        Raises:
            MeasurementNotFoundError: If measurement doesn't exist.
            MeasurementValidationForbiddenError: If user is not a clinician.
        """
        return await validate_measurement_record(
            db=db,
            measurement_id=measurement_id,
            user_id=user_id,
            user_role=user_role,
            audit_service=self._audit,
        )

    # -----------------------------------------------------------------------
    # BULK IMPORT
    # -----------------------------------------------------------------------
    async def bulk_import(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        measurements_list: list[dict[str, Any]],
    ) -> BulkImportResult:
        """
        Import multiple measurements with per-row validation.

        Valid rows succeed, invalid rows are reported with line numbers.
        Duplicates are skipped (idempotent). Source is set to "import".

        Args:
            db: Database session (tenant-scoped via RLS).
            tenant_id: Tenant UUID for all measurements.
            patient_id: UUID of the patient.
            user_id: UUID of the user performing the import.
            measurements_list: List of measurement data dicts.

        Returns:
            BulkImportResult with created, skipped_duplicates, and errors.
        """
        return await bulk_import(
            db=db,
            tenant_id=tenant_id,
            patient_id=patient_id,
            user_id=user_id,
            measurements_list=measurements_list,
            audit_service=self._audit,
        )

    # -----------------------------------------------------------------------
    # HISTORY (Time-Series Query)
    # -----------------------------------------------------------------------
    async def get_measurement_history(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        measurement_type: str,
        pagination: PaginationParams,
        filters: HistoryFilters | None = None,
    ) -> PaginatedResponse:
        """
        Get time-series measurement history for a patient and type.

        Ordered by recorded_at DESC with cursor-based pagination.
        Supports filtering by date range, validated-only, flagged-only.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.
            measurement_type: The measurement type to query.
            pagination: Page size and optional cursor.
            filters: Optional date range and status filters.

        Returns:
            PaginatedResponse with measurement items and pagination metadata.
        """
        return await get_measurement_history(
            db=db,
            patient_id=patient_id,
            measurement_type=measurement_type,
            pagination=pagination,
            filters=filters,
        )

    # -----------------------------------------------------------------------
    # LATEST MEASUREMENTS (Risk Engine Feature Extraction)
    # -----------------------------------------------------------------------
    async def get_latest_measurements(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> list[Measurement]:
        """
        Get the most recent measurement of each type for a patient.

        Used by the risk engine for feature extraction — provides the
        latest value of each measurement type as ML model inputs.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.

        Returns:
            List of Measurement objects — one per type that has data.
        """
        return await get_latest_measurements(db=db, patient_id=patient_id)

    # -----------------------------------------------------------------------
    # BASELINE COMPUTATION
    # -----------------------------------------------------------------------
    async def compute_baseline(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        measurement_type: str,
    ) -> BaselineResult | None:
        """
        Compute mean and std from validated measurements.

        Uses the larger of: last 90 days or last 10 readings.
        Used by deviation detection to flag >2σ measurements.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.
            measurement_type: The measurement type to compute baseline for.

        Returns:
            BaselineResult with mean, std, sample_count, has_sufficient_data.
            None if no validated measurements exist.
        """
        return await compute_baseline(
            db=db,
            patient_id=patient_id,
            measurement_type=measurement_type,
        )

    # -----------------------------------------------------------------------
    # FEATURE VECTOR (Risk Engine Input — Task 9)
    # -----------------------------------------------------------------------
    async def get_feature_vector(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        staleness_threshold_days: int = 90,
    ) -> dict[str, dict]:
        """
        Extract a structured feature vector for the Risk Engine.

        Returns the latest measurement of each type as a dict with
        value, unit, recorded_at, age_days, is_validated, and is_stale.
        Measurement types with no data are absent from the result.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.
            staleness_threshold_days: Measurements older than this are
                marked is_stale=True. Default 90 days.

        Returns:
            Dict keyed by measurement_type with feature metadata.
            Empty dict if patient has no measurements.
        """
        return await get_feature_vector(
            db=db,
            patient_id=patient_id,
            staleness_threshold_days=staleness_threshold_days,
        )

    # -----------------------------------------------------------------------
    # DATA SUFFICIENCY CHECK (Risk Engine Pre-Check — Task 9)
    # -----------------------------------------------------------------------
    async def check_data_sufficiency(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
    ) -> DataSufficiencyResult:
        """
        Check if a patient has sufficient data for each disease model.

        Evaluates validated measurements against the minimum requirements
        for each of the 6 disease risk models. Returns per-disease status
        and an overall quality assessment.

        Args:
            db: Database session (tenant-scoped via RLS).
            patient_id: UUID of the patient.

        Returns:
            DataSufficiencyResult with per-disease status and overall quality.
        """
        return await check_data_sufficiency(db=db, patient_id=patient_id)
