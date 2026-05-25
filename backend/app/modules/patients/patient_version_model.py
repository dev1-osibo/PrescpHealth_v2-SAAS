"""
PrescpHealth Backend — PatientVersion SQLAlchemy Model.

Defines the immutable version history model for patient profile changes.
Every modification to a Patient record creates a PatientVersion entry.

Extracted from models.py to comply with the ~150 lines of logic per
file rule. Re-exported from models.py for backward compatibility.

This provides:
- Full audit trail of who changed what and when
- Point-in-time recovery via the snapshot field
- Diff view via the changes field ({field: {old, new}})

The version_number auto-increments per patient, providing a simple
ordering mechanism independent of timestamps.

RLS: Tenant-scoped (same as Patient).
Immutability: These records are never updated or deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.patients.enums import PatientChangeType

if TYPE_CHECKING:
    from app.modules.patients.patient_model import Patient


# ---------------------------------------------------------------------------
# Patient Version History Model
# ---------------------------------------------------------------------------
class PatientVersion(TenantMixin, Base):
    """
    Immutable version history for patient profile changes.

    Every modification to a Patient record creates a PatientVersion entry.
    This provides:
    - Full audit trail of who changed what and when
    - Point-in-time recovery via the snapshot field
    - Diff view via the changes field ({field: {old, new}})

    The version_number auto-increments per patient, providing a simple
    human-readable ordering mechanism independent of timestamps.

    RLS: Tenant-scoped (same as Patient).
    Immutability: These records are never updated or deleted.
    """

    __tablename__ = "patient_versions"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Version record identifier",
    )

    # Reference to the patient being versioned
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Patient this version belongs to",
    )

    # Version ordering — auto-incrementing per patient
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Sequential version number per patient (1, 2, 3, ...)",
    )

    # Who made the change
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the user who made this change",
    )

    # When the change was made
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="Timestamp when this change was made (UTC)",
    )

    # What type of change (create, update, soft_delete, restore)
    change_type: Mapped[PatientChangeType] = mapped_column(
        String(20),
        nullable=False,
        comment="Type of change: create, update, soft_delete, restore",
    )

    # Diff: which fields changed and their old/new values
    changes: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Change diff: {field_name: {old: value, new: value}}",
    )

    # Full snapshot of patient state at this version
    # Enables point-in-time recovery without replaying all changes
    snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Full patient state at this version (for point-in-time recovery)",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    patient: Mapped["Patient"] = relationship(
        "Patient",
        back_populates="versions",
    )
