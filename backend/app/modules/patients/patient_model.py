"""
PrescpHealth Backend — Patient SQLAlchemy Model.

Defines the core Patient database model with demographics, medical
history, contact information, and lifecycle status.

This is the central entity that measurements, risk scores, forecasts,
and AI conversations reference.

Extracted from models.py to comply with the ~150 lines of logic per
file rule. Re-exported from models.py for backward compatibility.

PHI Fields (Protected Health Information):
    The following fields contain PHI and must be:
    - Encrypted at rest (column-level or TDE)
    - Never logged (only log patient_id UUID)
    - Never cached in browser-accessible storage
    - Returned only with proper RBAC authorization

    PHI fields: first_name, last_name, date_of_birth, phone_number,
    email, address, emergency_contact, notes

RLS: Uses tenant_id for Row-Level Security isolation.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.patients.enums import PatientGender, PatientStatus

if TYPE_CHECKING:
    from app.modules.patients.patient_version_model import PatientVersion


# ---------------------------------------------------------------------------
# Patient Model
# ---------------------------------------------------------------------------
class Patient(TenantMixin, Base):
    """
    Core patient profile model.

    Stores demographics, medical history, and clinical metadata.
    This is the central entity that measurements, risk scores,
    forecasts, and AI conversations reference.

    RLS: Tenant-scoped — patients are only visible within their tenant.
    Soft Delete: Uses deleted_at (nullable) instead of hard delete.
    Versioning: All changes create a PatientVersion record.

    HIPAA Compliance:
    - PHI fields clearly marked in column comments
    - Soft delete only (deleted_at, never DROP/DELETE)
    - 7-year minimum retention after soft delete
    - Encrypted at rest via PostgreSQL TDE or column-level encryption
    """

    __tablename__ = "patients"

    # -----------------------------------------------------------------------
    # Primary Key — immutable UUID assigned at creation (Requirement 4.3)
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Immutable patient identifier (UUID, assigned at creation)",
    )

    # -----------------------------------------------------------------------
    # Clinic-assigned identifier — unique per tenant
    # -----------------------------------------------------------------------
    medical_record_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Clinic-assigned MRN — unique per tenant, used for lookup",
    )

    # -----------------------------------------------------------------------
    # Demographics — PHI fields
    # -----------------------------------------------------------------------
    first_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="PHI: Patient first name (encrypted at rest)",
    )
    last_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="PHI: Patient last name (encrypted at rest)",
    )
    date_of_birth: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="PHI: Patient date of birth",
    )
    gender: Mapped[PatientGender] = mapped_column(
        String(20),
        nullable=False,
        comment="Patient gender (Male, Female, Other, Prefer_Not_To_Say)",
    )

    # -----------------------------------------------------------------------
    # Contact Information — PHI fields (optional)
    # -----------------------------------------------------------------------
    phone_number: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
        comment="PHI: Patient phone number (optional, encrypted at rest)",
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        comment="PHI: Patient email address (optional, encrypted at rest)",
    )
    address: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="PHI: Structured address {street, city, state, country, postal_code}",
    )
    emergency_contact: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Emergency contact {name, phone, relationship}",
    )

    # -----------------------------------------------------------------------
    # Medical Information
    # -----------------------------------------------------------------------
    blood_type: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        default=None,
        comment="Blood type (e.g., A+, O-, AB+)",
    )
    allergies: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="List of allergy strings (e.g., ['Penicillin', 'Latex'])",
    )
    chronic_conditions: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="List of ICD-10 coded conditions [{code, display_name}]",
    )
    current_medications: Mapped[list | None] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
        comment="Active medications [{name, dosage, frequency, start_date}]",
    )
    insurance_info: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Insurance details {provider, policy_number, group_number}",
    )

    # -----------------------------------------------------------------------
    # Clinical Notes — PHI
    # -----------------------------------------------------------------------
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Free-text clinician notes (encrypted at rest)",
    )

    # -----------------------------------------------------------------------
    # Record Status and Lifecycle
    # -----------------------------------------------------------------------
    status: Mapped[PatientStatus] = mapped_column(
        String(20),
        nullable=False,
        default=PatientStatus.ACTIVE,
        server_default="Active",
        comment="Patient lifecycle status (Active, Inactive, Deceased, Transferred)",
    )

    # -----------------------------------------------------------------------
    # Ownership and Audit
    # -----------------------------------------------------------------------
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the user who created this patient record",
    )

    # -----------------------------------------------------------------------
    # Soft Delete — HIPAA requires retention, never hard delete
    # -----------------------------------------------------------------------
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Soft delete timestamp (NULL = active, set = logically deleted)",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    versions: Mapped[list["PatientVersion"]] = relationship(
        "PatientVersion",
        back_populates="patient",
        cascade="all, delete-orphan",
        order_by="PatientVersion.version_number.desc()",
    )

    # -----------------------------------------------------------------------
    # Table Constraints and Indexes
    # -----------------------------------------------------------------------
    __table_args__ = (
        # MRN unique per tenant (different clinics can reuse MRN schemes)
        UniqueConstraint(
            "tenant_id",
            "medical_record_number",
            name="uq_patient_tenant_mrn",
        ),
    )
