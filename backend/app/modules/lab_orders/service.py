"""
PrescpHealth Backend — Lab Order Service (Orchestrator).

Manages the lab order lifecycle: creation, status transitions, specimen
collection, and querying. This is the primary entry point for all lab
order operations except result recording (see service_results.py).

Responsibilities:
- Create lab orders with LOINC code validation
- Enforce valid status transitions (state machine)
- Track specimen collection timestamps
- Provide paginated queries for patient history and lab queue

Integration Points:
- CodeCatalogService: Validates LOINC codes before order creation
- AuditService: Logs all CUD operations for HIPAA compliance

HIPAA Compliance:
- Never logs test names, clinical indications, or patient identifiers
- Only logs lab_order_id (UUID) and status transitions
- All queries are tenant-scoped via RLS

Performance:
- create_lab_order: <500ms (includes LOINC validation)
- get_lab_order: <200ms (indexed PK lookup with selectin results)
- list_patient_lab_orders: <300ms (indexed query with pagination)

Usage:
    from app.modules.lab_orders.service import LabOrderService

    service = LabOrderService()
    order = await service.create_lab_order(db, tenant_id, patient_id, ...)
"""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.audit.service import AuditService
from app.modules.code_catalogs.enums import CatalogType
from app.modules.code_catalogs.service import CodeCatalogService
from app.modules.lab_orders.enums import LabOrderStatus, LabPriority
from app.modules.lab_orders.exceptions import (
    InvalidLabOrderStatusTransitionError,
    LabOrderNotFoundError,
)
from app.modules.lab_orders.models import LabOrder

# ---------------------------------------------------------------------------
# Module logger — HIPAA safe: never logs PHI (test names, values)
# ---------------------------------------------------------------------------
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Valid Status Transitions (state machine)
# ---------------------------------------------------------------------------
# Defines which status transitions are allowed. Any transition not in this
# map is rejected with InvalidLabOrderStatusTransitionError.
_VALID_TRANSITIONS: dict[str, set[str]] = {
    LabOrderStatus.ORDERED.value: {
        LabOrderStatus.SPECIMEN_COLLECTED.value,
        LabOrderStatus.CANCELLED.value,
    },
    LabOrderStatus.SPECIMEN_COLLECTED.value: {
        LabOrderStatus.IN_PROGRESS.value,
        LabOrderStatus.CANCELLED.value,
    },
    LabOrderStatus.IN_PROGRESS.value: {
        LabOrderStatus.RESULTED.value,
    },
    # Terminal states — no transitions allowed
    LabOrderStatus.RESULTED.value: set(),
    LabOrderStatus.CANCELLED.value: set(),
}


class LabOrderService:
    """
    Orchestrates lab order lifecycle operations.

    Handles creation, status management, specimen collection, and
    querying. Result recording is delegated to service_results.py
    to keep file size manageable and responsibilities clear.
    """

    def __init__(self) -> None:
        """Initialize with code catalog and audit service instances."""
        self._code_catalog = CodeCatalogService()
        self._audit = AuditService()

    # -----------------------------------------------------------------------
    # Create Lab Order
    # -----------------------------------------------------------------------
    async def create_lab_order(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        patient_id: uuid.UUID,
        user_id: uuid.UUID,
        encounter_id: uuid.UUID | None,
        test_name: str,
        loinc_code: str,
        priority: str,
        clinical_indication: str | None = None,
    ) -> LabOrder:
        """
        Create a new lab order with LOINC code validation.

        Validates the LOINC code against the code catalog before creating
        the order. Sets initial status to 'ordered'.

        Args:
            db: Async database session (tenant-scoped via RLS).
            tenant_id: Tenant UUID for RLS isolation.
            patient_id: Patient this order is for.
            user_id: Clinician placing the order.
            encounter_id: Originating encounter (nullable).
            test_name: Human-readable test name (PHI — never logged).
            loinc_code: LOINC code to validate and store.
            priority: Processing urgency (routine, urgent, stat).
            clinical_indication: Why the test is ordered (PHI — never logged).

        Returns:
            The created LabOrder model instance.

        Raises:
            InvalidCodeError: If LOINC code is invalid or inactive.
        """
        # Step 1: Validate LOINC code against the code catalog
        await self._code_catalog.validate_code(db, CatalogType.LOINC, loinc_code)

        # Step 2: Create the lab order record
        lab_order = LabOrder(
            tenant_id=tenant_id,
            patient_id=patient_id,
            encounter_id=encounter_id,
            test_name=test_name,
            loinc_code=loinc_code,
            priority=priority,
            status=LabOrderStatus.ORDERED.value,
            ordered_by=user_id,
            clinical_indication=clinical_indication,
        )

        db.add(lab_order)
        await db.flush()

        # Step 3: Audit log — only log order_id and status, never PHI
        await self._audit.log(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            action="lab_order.create",
            resource_type="lab_order",
            resource_id=lab_order.id,
            metadata={"status": LabOrderStatus.ORDERED.value},
        )

        logger.info(
            "lab_order_created",
            lab_order_id=str(lab_order.id),
            status=LabOrderStatus.ORDERED.value,
        )

        return lab_order

    # -----------------------------------------------------------------------
    # Get Lab Order (with results)
    # -----------------------------------------------------------------------
    async def get_lab_order(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
    ) -> LabOrder:
        """
        Retrieve a lab order by ID, including its results.

        Uses selectinload to eagerly fetch associated LabResult records
        in a single query for performance.

        Args:
            db: Async database session.
            order_id: UUID of the lab order to retrieve.

        Returns:
            LabOrder with results loaded.

        Raises:
            LabOrderNotFoundError: If order doesn't exist.
        """
        stmt = (
            select(LabOrder)
            .options(selectinload(LabOrder.results))
            .where(LabOrder.id == order_id)
        )
        result = await db.execute(stmt)
        lab_order = result.scalar_one_or_none()

        if lab_order is None:
            raise LabOrderNotFoundError(order_id)

        return lab_order

    # -----------------------------------------------------------------------
    # Update Status (with transition validation)
    # -----------------------------------------------------------------------
    async def update_status(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        new_status: str,
        user_id: uuid.UUID,
    ) -> LabOrder:
        """
        Update a lab order's status with transition validation.

        Only allows transitions defined in the state machine. Rejects
        invalid transitions with a clear error.

        Args:
            db: Async database session.
            order_id: UUID of the lab order to update.
            new_status: The target status string.
            user_id: User performing the status change.

        Returns:
            Updated LabOrder instance.

        Raises:
            LabOrderNotFoundError: If order doesn't exist.
            InvalidLabOrderStatusTransitionError: If transition is invalid.
        """
        lab_order = await self.get_lab_order(db, order_id)
        current_status = lab_order.status

        # Validate the transition against the state machine
        allowed = _VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise InvalidLabOrderStatusTransitionError(
                order_id=order_id,
                current_status=current_status,
                requested_status=new_status,
            )

        # Apply the transition
        lab_order.status = new_status
        await db.flush()

        # Audit the status change — safe to log status strings (not PHI)
        await self._audit.log(
            db=db,
            tenant_id=lab_order.tenant_id,
            user_id=user_id,
            action="lab_order.update_status",
            resource_type="lab_order",
            resource_id=order_id,
            metadata={"old_status": current_status, "new_status": new_status},
        )

        logger.info(
            "lab_order_status_updated",
            lab_order_id=str(order_id),
            old_status=current_status,
            new_status=new_status,
        )

        return lab_order

    # -----------------------------------------------------------------------
    # Collect Specimen
    # -----------------------------------------------------------------------
    async def collect_specimen(
        self,
        db: AsyncSession,
        order_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> LabOrder:
        """
        Record specimen collection for a lab order.

        Sets status to 'specimen_collected' and records the collection
        timestamp. This is a convenience method that combines status
        transition with timestamp recording.

        Args:
            db: Async database session.
            order_id: UUID of the lab order.
            user_id: User who collected the specimen.

        Returns:
            Updated LabOrder with specimen_collected_at set.

        Raises:
            LabOrderNotFoundError: If order doesn't exist.
            InvalidLabOrderStatusTransitionError: If not in 'ordered' status.
        """
        lab_order = await self.get_lab_order(db, order_id)

        # Validate transition: must be in 'ordered' state
        if lab_order.status != LabOrderStatus.ORDERED.value:
            raise InvalidLabOrderStatusTransitionError(
                order_id=order_id,
                current_status=lab_order.status,
                requested_status=LabOrderStatus.SPECIMEN_COLLECTED.value,
            )

        # Update status and record collection timestamp
        lab_order.status = LabOrderStatus.SPECIMEN_COLLECTED.value
        lab_order.specimen_collected_at = datetime.now(timezone.utc)
        await db.flush()

        # Audit log
        await self._audit.log(
            db=db,
            tenant_id=lab_order.tenant_id,
            user_id=user_id,
            action="lab_order.specimen_collected",
            resource_type="lab_order",
            resource_id=order_id,
            metadata={"status": LabOrderStatus.SPECIMEN_COLLECTED.value},
        )

        logger.info(
            "lab_order_specimen_collected",
            lab_order_id=str(order_id),
        )

        return lab_order

    # -----------------------------------------------------------------------
    # List Patient Lab Orders (paginated)
    # -----------------------------------------------------------------------
    async def list_patient_lab_orders(
        self,
        db: AsyncSession,
        patient_id: uuid.UUID,
        status_filter: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[LabOrder], int]:
        """
        List lab orders for a patient with optional status filter.

        Returns paginated results ordered by creation date (newest first).
        Uses the (tenant_id, patient_id, status) index for performance.

        Args:
            db: Async database session (tenant-scoped via RLS).
            patient_id: Patient UUID to filter by.
            status_filter: Optional status to filter (e.g., "ordered").
            limit: Max results per page (default 25, max 100).
            offset: Number of records to skip for pagination.

        Returns:
            Tuple of (list of LabOrders, total count).
        """
        # Cap limit to prevent excessive payloads
        limit = min(limit, 100)

        # Base query filtered by patient
        base_query = select(LabOrder).where(LabOrder.patient_id == patient_id)
        count_query = select(func.count(LabOrder.id)).where(
            LabOrder.patient_id == patient_id
        )

        # Apply optional status filter
        if status_filter:
            base_query = base_query.where(LabOrder.status == status_filter)
            count_query = count_query.where(LabOrder.status == status_filter)

        # Get total count for pagination metadata
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Fetch paginated results, newest first
        stmt = (
            base_query
            .options(selectinload(LabOrder.results))
            .order_by(LabOrder.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        orders = list(result.scalars().all())

        return orders, total

    # -----------------------------------------------------------------------
    # List Pending Orders (lab queue dashboard)
    # -----------------------------------------------------------------------
    async def list_pending_orders(
        self,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        priority_filter: str | None = None,
    ) -> list[LabOrder]:
        """
        List pending lab orders for the lab queue dashboard.

        Returns orders that are not yet resulted or cancelled, ordered
        by priority (stat first) then creation date (oldest first).
        Uses the (tenant_id, status, priority) index.

        Args:
            db: Async database session.
            tenant_id: Tenant UUID for scoping.
            priority_filter: Optional priority filter (routine, urgent, stat).

        Returns:
            List of pending LabOrders for the lab queue.
        """
        # Pending = not in terminal states (resulted, cancelled)
        pending_statuses = [
            LabOrderStatus.ORDERED.value,
            LabOrderStatus.SPECIMEN_COLLECTED.value,
            LabOrderStatus.IN_PROGRESS.value,
        ]

        stmt = select(LabOrder).where(
            LabOrder.tenant_id == tenant_id,
            LabOrder.status.in_(pending_statuses),
        )

        # Apply optional priority filter
        if priority_filter:
            stmt = stmt.where(LabOrder.priority == priority_filter)

        # Order by priority (stat > urgent > routine) then oldest first
        # Using CASE expression for priority ordering
        priority_order = func.array_position(
            ["stat", "urgent", "routine"], LabOrder.priority
        )
        stmt = stmt.order_by(priority_order, LabOrder.created_at.asc())

        result = await db.execute(stmt)
        return list(result.scalars().all())
