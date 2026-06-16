"""
PrescpHealth Backend — Bed Management ORM Models.

Tables:
    wards           — Hospital wards / units
    beds            — Individual beds within wards
    admissions      — Patient admission records
    nursing_notes   — Nursing documentation per admission

All tables use TenantMixin (RLS + timestamps).
Unique constraint on (tenant_id, ward_id, bed_number) prevents duplicate beds.
NursingNote.content is PHI — never logged; only note_id appears in logs.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.bed_management.enums import (
    AdmissionStatus,
    BedStatus,
    BedType,
    DischargeType,
    NoteType,
)


class Ward(TenantMixin, Base):
    """A hospital ward or unit containing multiple beds."""

    __tablename__ = "wards"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        comment="Surrogate PK",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    floor: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    specialty: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True,
        comment="Clinical specialty (e.g., cardiology, paediatrics)",
    )
    total_beds: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    beds: Mapped[list["Bed"]] = relationship("Bed", back_populates="ward", lazy="select")


class Bed(TenantMixin, Base):
    """An individual hospital bed within a ward."""

    __tablename__ = "beds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    ward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("wards.id"), nullable=False, index=True,
    )
    bed_number: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="Human-readable bed identifier within the ward (e.g., A-01)",
    )
    status: Mapped[BedStatus] = mapped_column(
        String(32), nullable=False, default=BedStatus.AVAILABLE,
    )
    bed_type: Mapped[BedType] = mapped_column(String(32), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Bed number must be unique within a ward per tenant
        UniqueConstraint("tenant_id", "ward_id", "bed_number", name="uq_bed_per_ward"),
    )

    ward: Mapped["Ward"] = relationship("Ward", back_populates="beds")
    admissions: Mapped[list["Admission"]] = relationship(
        "Admission", back_populates="bed", lazy="select",
    )


class Admission(TenantMixin, Base):
    """
    Patient admission record binding a patient to a specific bed.

    Contains the full admission lifecycle:
        active → discharged / transferred

    discharge_plan: JSONB — structured clinical discharge info.
    PHI NOTE: reason and notes fields may contain clinical text — never log values.
    """

    __tablename__ = "admissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True,
    )
    bed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("beds.id"), nullable=False, index=True,
    )
    encounter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("encounters.id"), nullable=True,
    )
    admitting_doctor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discharged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    discharge_type: Mapped[Optional[DischargeType]] = mapped_column(
        String(32), nullable=True,
    )
    # JSONB discharge plan — PHI, not logged
    discharge_plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[AdmissionStatus] = mapped_column(
        String(32), nullable=False, default=AdmissionStatus.ACTIVE,
    )
    # reason and notes: clinical PHI — stored, never logged
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    bed: Mapped["Bed"] = relationship("Bed", back_populates="admissions")
    nursing_notes: Mapped[list["NursingNote"]] = relationship(
        "NursingNote", back_populates="admission", lazy="select",
    )


class NursingNote(TenantMixin, Base):
    """
    A nursing documentation entry for an active admission.

    content is PHI (clinical observations) — NEVER logged.
    Only note_id and note_type appear in log messages.
    """

    __tablename__ = "nursing_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    admission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admissions.id"), nullable=False, index=True,
    )
    nurse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False,
    )
    # content is PHI — never appears in logs
    content: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[NoteType] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    admission: Mapped["Admission"] = relationship("Admission", back_populates="nursing_notes")
