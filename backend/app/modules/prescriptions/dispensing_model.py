"""
PrescpHealth Backend — Dispensing SQLAlchemy Model.

Defines the Dispensing database model representing a single medication
dispensing event. Each dispensing is linked to a parent prescription and
records what was dispensed, by whom, and when.

Dispensing records are created when:
- A prescription is initially filled (is_refill=False)
- A refill is processed (is_refill=True, decrements refills_remaining)

PHI Fields:
    - dispensed_quantity: Medication amount (PHI when combined with patient)

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from app.modules.prescriptions.prescription_model import Prescription


# ---------------------------------------------------------------------------
# Dispensing Model
# ---------------------------------------------------------------------------
class Dispensing(TimestampMixin, Base):
    """
    Medication dispensing record.

    Tracks each time a prescription is filled or refilled. Links to the
    parent prescription and records the quantity, dispensing staff, and
    whether this is a refill or initial fill.

    RLS: Tenant-scoped — dispensings only visible within their tenant.

    HIPAA Compliance:
    - Dispensed quantity is PHI when combined with patient identity
    - Never log dispensing details (only log dispensing id)
    - Records retained for 7+ years per HIPAA retention policy
    """

    __tablename__ = "dispensings"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable dispensing record identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Tenant Isolation
    # -----------------------------------------------------------------------
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Tenant UUID for RLS isolation — every query filtered by this",
    )

    # -----------------------------------------------------------------------
    # Foreign Key — links to parent prescription
    # -----------------------------------------------------------------------
    prescription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prescriptions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Parent prescription — FK to prescriptions.id",
    )

    # -----------------------------------------------------------------------
    # Dispensing Details
    # -----------------------------------------------------------------------
    dispensed_quantity: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: Quantity dispensed (e.g., '30 tablets', '100ml')",
    )
    dispensed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the staff member who dispensed the medication",
    )
    dispensed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the medication was dispensed (UTC)",
    )

    # -----------------------------------------------------------------------
    # Refill Flag
    # -----------------------------------------------------------------------
    is_refill: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="True if this is a refill, False for initial dispensing",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    prescription: Mapped["Prescription"] = relationship(
        "Prescription",
        back_populates="dispensings",
    )
