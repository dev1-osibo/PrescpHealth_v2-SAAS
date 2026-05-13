"""
PrescpHealth Backend — Patient SQLAlchemy Models.

Defines the database models for patient profile management:
- Patient: Core patient record with demographics, medical history, and status
- PatientVersion: Immutable version history for all profile changes

Schema Design Decisions:
- Patient uses soft-delete (deleted_at) — HIPAA requires 7-year retention
- medical_record_number is unique per tenant (clinic-assigned identifier)
- JSONB fields for flexible structured data (allergies, conditions, medications)
- Gender uses an enum with inclusive options
- PatientVersion stores both a diff (changes) and full snapshot for
  point-in-time recovery without needing to replay all changes

PHI Fields (Protected Health Information):
    The following fields contain PHI and must be:
    - Encrypted at rest (column-level or TDE)
    - Never logged (only log patient_id UUID)
    - Never cached in browser-accessible storage
    - Returned only with proper RBAC authorization

    PHI fields: first_name, last_name, date_of_birth, phone_number,
    email, address, emergency_contact, notes

RLS: Both tables use tenant_id for Row-Level Security isolation.
"""

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class PatientGender(str, Enum):
    """
    Patient gender options.

    Inclusive set supporting clinical documentation needs while
    respecting patient preference not to disclose.
    """

    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    PREFER_NOT_TO_SAY = "Prefer_Not_To_Say"


class PatientStatus(str, Enum):
    """
    Patient record lifecycle status.

    - Active: Currently receiving care at this clinic
    - Inactive: No longer actively managed (e.g., moved away)
    - Deceased: Patient has passed away (record retained per HIPAA)
    - Transferred: Care transferred to another facility
    """

    ACTIVE = "Active"
    INACTIVE = "Inactive"
    DECEASED = "Deceased"
    TRANSFERRED = "Transferred"


class PatientChangeType(str, Enum):
    """
    Types of changes tracked in patient version history.

    Used to categorize what kind of modification was made,
    enabling filtered audit queries (e.g., "show all soft deletes").
    """

    CREATE = "create"
    UPDATE = "update"
    SOFT_DELETE = "soft_delete"
    RESTORE = "restore"


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
    ordering mechanism independent of timestamps.

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
    patient: Mapped["Patient"] = relationship(back_populates="versions")
