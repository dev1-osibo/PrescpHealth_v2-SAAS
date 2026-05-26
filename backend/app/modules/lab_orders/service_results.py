"""
PrescpHealth Backend — Lab Order Result Recording Service.

Handles the complete flow for recording a lab result:
1. Validate the lab order exists and is in a valid state
2. Compute is_abnormal flag from reference range comparison
3. Create the LabResult record
4. Set lab order status to 'resulted'
5. Create a Measurement record (if LOINC maps to a measurement type)
6. Publish MeasurementSaved event (for risk pipeline)
7. Publish LabResultReceived event (for downstream consumers)
8. Audit log the operation

This is the CRITICAL integration point between the lab module and the
risk computation pipeline. Lab results that map to known measurement
types automatically feed into risk scoring.

HIPAA Compliance:
- Never logs result values, test names, or patient identifiers
- Only logs lab_order_id, lab_result_id, and is_abnormal flag
- Audit records contain only resource UUIDs and action metadata

Usage:
    from app.modules.lab_orders.service_results import LabResultService

    service = LabResultService()
    result = await service.record_result(db, order_id, tenant_id, ...)
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import (
    LabResultReceived,
    MeasurementSaved,
    event_bus,
)
from app.core.request_context import get_request_id
from app.modules.audit.service import AuditService
from app.modules.lab_orders.enums import LabOrderStatus
from app.modules.lab_orders.exceptions import (
    LabOrderAlreadyResultedError,
    LabOrderNotFoundError,
)
from app.modules.lab_orders.loinc_to_measurement import map_loinc_to_measurement
from app.modules.lab_orders.models import LabOrder, LabResult
from app.modules.lab_orders.service import LabOrderService
from app.modules.measurements.models import Measurement

# ---------------------------------------------------------------------------
# Module logger — HIPAA safe: never logs result values or test names
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)


class LabResultService:
    """
    Records lab results and integrates with the measurement pipeline.

    This service is responsible for the critical data flow:
    Lab Result → Measurement → MeasurementSaved event → Risk Engine

    The measurement integration ensures that lab results automatically
    feed into the risk computation pipeline without manual intervention.
    """

    def __init__(self) -> None:
        """Initialize with lab order service and audit service."""
        self._lab_order_service = LabOrderService()
        self._audit = AuditService()

    async def record_result(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        value: str,
        numeric_value: float | None,
        unit: str,
        reference_range_low: float | None,
        reference_range_high: float | None,
        resulted_at: datetime,
    ) -> LabResult:
        """
        Record a lab result with full pipeline integration.

        Complete flow:
        1. Fetch and validate the lab order (must not be already resulted)
        2. Compute is_abnormal from reference range comparison
        3. Create LabResult record
        4. Transition lab order to 'resulted' status
        5. Create Measurement record if LOINC maps to a type
        6. Publish MeasurementSaved event for risk pipeline
        7. Publish LabResultReceived event for downstream consumers
        8. Audit log

        Args:
            db: Async database session (tenant-scoped via RLS).
            order_id: Parent lab order UUID.
            tenant_id: Tenant UUID for RLS and event context.
            user_id: User recording the result.
            value: Result value as string (supports qualitative results).
            numeric_value: Parsed numeric value (None for qualitative).
            unit: Unit of measurement (e.g., "mg/dL").
            reference_range_low: Lower bound of normal range (nullable).
            reference_range_high: Upper bound of normal range (nullable).
            resulted_at: When the result was produced by the lab.

        Returns:
            The created LabResult model instance.

        Raises:
            LabOrderNotFoundError: If order doesn't exist.
            LabOrderAlreadyResultedError: If order already has results.
        """
        # --- Step 1: Fetch and validate lab order ---
        lab_order = await self._lab_order_service.get_lab_order(db, order_id)

        if lab_order.status == LabOrderStatus.RESULTED.value:
            raise LabOrderAlreadyResultedError(order_id)

        # --- Step 2: Compute is_abnormal flag ---
        is_abnormal = self._compute_abnormal_flag(
            numeric_value, reference_range_low, reference_range_high
        )

        # --- Step 3: Create LabResult record ---
        lab_result = LabResult(
            tenant_id=tenant_id,
            lab_order_id=order_id,
            value=value,
            numeric_value=numeric_value,
            unit=unit,
            reference_range_low=reference_range_low,
            reference_range_high=reference_range_high,
            is_abnormal=is_abnormal,
            resulted_at=resulted_at,
            resulted_by=user_id,
        )
        db.add(lab_result)
        await db.flush()

        # --- Step 4: Transition lab order to 'resulted' ---
        lab_order.status = LabOrderStatus.RESULTED.value
        await db.flush()

        # --- Step 5: Create Measurement if LOINC maps to a type ---
        measurement = await self._create_measurement_if_mapped(
            db=db,
            lab_order=lab_order,
            lab_result=lab_result,
            tenant_id=tenant_id,
            user_id=user_id,
            resulted_at=resulted_at,
        )

        # Link measurement to the lab result if one was created
        if measurement:
            lab_result.measurement_id = measurement.id
            await db.flush()

        # --- Step 6: Publish MeasurementSaved event (if measurement created) ---
        if measurement:
            correlation_id = get_request_id() or str(uuid.uuid4())
            await event_bus.publish(
                MeasurementSaved(
                    correlation_id=correlation_id,
                    tenant_id=tenant_id,
                    patient_id=lab_order.patient_id,
                    measurement_type=measurement.measurement_type,
                    measurement_id=measurement.id,
                    is_flagged=False,
                    is_validated=True,  # Lab results are pre-validated
                )
            )

        # --- Step 7: Publish LabResultReceived event ---
        correlation_id = get_request_id() or str(uuid.uuid4())
        await event_bus.publish(
            LabResultReceived(
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                patient_id=lab_order.patient_id,
                lab_order_id=order_id,
                lab_result_id=lab_result.id,
                is_abnormal=is_abnormal,
                loinc_code=lab_order.loinc_code,
            )
        )

        # --- Step 8: Audit log ---
        await self._audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="lab_result.create",
            resource_type="lab_result",
            resource_id=lab_result.id,
            metadata={
                "lab_order_id": str(order_id),
                "is_abnormal": is_abnormal,
                "status": LabOrderStatus.RESULTED.value,
            },
        )

        logger.info(
            "lab_result_recorded",
            lab_order_id=str(order_id),
            lab_result_id=str(lab_result.id),
            is_abnormal=is_abnormal,
        )

        return lab_result

    # -----------------------------------------------------------------------
    # Private: Compute Abnormal Flag
    # -----------------------------------------------------------------------
    def _compute_abnormal_flag(
        self,
        numeric_value: float | None,
        reference_range_low: float | None,
        reference_range_high: float | None,
    ) -> bool:
        """
        Determine if a result is abnormal based on reference range.

        A result is abnormal if the numeric value falls outside the
        reference range (below low OR above high). If no numeric value
        or no reference range is provided, the result is not flagged.

        This is the core logic for Requirement 3.6:
        "WHEN a lab result value falls outside the reference range,
        THE Lab_Order_Service SHALL flag the result as abnormal"

        Args:
            numeric_value: The parsed numeric result (None for qualitative).
            reference_range_low: Lower bound of normal (None if not defined).
            reference_range_high: Upper bound of normal (None if not defined).

        Returns:
            True if the value is outside the reference range, False otherwise.
        """
        # Cannot determine abnormality without a numeric value
        if numeric_value is None:
            return False

        # Check below lower bound (if defined)
        if reference_range_low is not None and numeric_value < reference_range_low:
            return True

        # Check above upper bound (if defined)
        if reference_range_high is not None and numeric_value > reference_range_high:
            return True

        return False

    # -----------------------------------------------------------------------
    # Private: Create Measurement If LOINC Maps to a Type
    # -----------------------------------------------------------------------
    async def _create_measurement_if_mapped(
        self,
        db: AsyncSession,
        lab_order: LabOrder,
        lab_result: LabResult,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        resulted_at: datetime,
    ) -> Measurement | None:
        """
        Create a Measurement record if the LOINC code maps to a type.

        This is the critical integration point: lab results that correspond
        to risk-relevant measurement types (glucose, cholesterol, creatinine,
        etc.) are automatically converted into Measurement records that feed
        the risk computation pipeline.

        Not all lab results map to measurements — only those with LOINC codes
        in the mapping table. For example, a CBC or culture result won't
        create a Measurement because those don't feed the risk engine.

        Args:
            db: Async database session.
            lab_order: The parent lab order (has loinc_code, patient_id).
            lab_result: The lab result (has numeric_value, unit).
            tenant_id: Tenant UUID for the measurement.
            user_id: User who recorded the result.
            resulted_at: When the result was produced.

        Returns:
            The created Measurement if LOINC maps, None otherwise.
        """
        # Check if this LOINC code maps to a measurement type
        measurement_type = map_loinc_to_measurement(lab_order.loinc_code)

        if measurement_type is None:
            # This lab doesn't feed the risk engine — that's fine
            logger.debug(
                "lab_result_no_measurement_mapping",
                lab_order_id=str(lab_order.id),
            )
            return None

        # Must have a numeric value to create a measurement
        if lab_result.numeric_value is None:
            logger.debug(
                "lab_result_no_numeric_value_for_measurement",
                lab_order_id=str(lab_order.id),
            )
            return None

        # Create the Measurement record
        # Source is "device" because lab results come from lab instruments
        measurement = Measurement(
            tenant_id=tenant_id,
            patient_id=lab_order.patient_id,
            measurement_type=measurement_type.value,
            value=lab_result.numeric_value,
            unit=lab_result.unit,
            recorded_at=resulted_at,
            recorded_by=user_id,
            source="device",
            is_validated=True,  # Lab results are inherently validated
            is_flagged=False,
            notes=None,
        )

        db.add(measurement)
        await db.flush()

        logger.info(
            "measurement_created_from_lab_result",
            measurement_id=str(measurement.id),
            measurement_type=measurement_type.value,
            lab_order_id=str(lab_order.id),
        )

        return measurement
