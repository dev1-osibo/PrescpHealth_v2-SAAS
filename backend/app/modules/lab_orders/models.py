"""
PrescpHealth Backend — Lab Order and Lab Result SQLAlchemy Models.

Defines the database models for laboratory order management:
- LabOrder: A clinician's request for a laboratory test
- LabResult: The outcome/value produced by the lab for an order

Schema Design Decisions:
- loinc_code validated against CodeCatalog before persistence
- status tracks the full lab workflow lifecycle (ordered → resulted)
- priority determines processing urgency (routine, urgent, stat)
- fhir_json stores FHIR R4 ServiceRequest/Observation for interop
- encounter_id is nullable (labs can be ordered outside encounters)
- specimen_collected_at tracks when the specimen was actually taken

PHI Fields (Protected Health Information):
    Lab results are PHI when combined with patient_id:
    - test_name: The lab test ordered
    - value/numeric_value: The result reading
    - clinical_indication: Why the test was ordered

    These must be:
    - Encrypted at rest (column-level or TDE)
    - Never logged (only log lab_order_id UUID and status)
    - Never cached in browser-accessible storage

RLS: Both tables use tenant_id for Row-Level Security isolation.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin
from app.modules.lab_orders.enums import LabOrderStatus, LabPriority


# ---------------------------------------------------------------------------
# LabOrder Model
# ---------------------------------------------------------------------------
class LabOrder(TenantMixin, Base):
    """
    Laboratory test order record.

    Represents a clinician's request for a specific lab test on a patient.
    Tracks the full lifecycle from order placement through specimen
    collection to final result availability.

    Integration Points:
    - Validates loinc_code against CodeCatalog (LOINC classification)
    - Links to Encounter when ordered during a visit (nullable)
    - Results create Measurement records for risk computation pipeline
    - Abnormal results trigger alerts via the Alert system

    RLS: Tenant-scoped — orders only visible within their tenant.

    HIPAA Compliance:
    - PHI fields (test_name, clinical_indication) encrypted at rest
    - Never log test names or clinical indications
    - Soft delete only (retained 7+ years per HIPAA)
    """

    __tablename__ = "lab_orders"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique lab order identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Patient Reference — FK to patients table
    # -----------------------------------------------------------------------
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient this lab order belongs to",
    )

    # -----------------------------------------------------------------------
    # Encounter Reference — nullable (labs can be ordered standalone)
    # -----------------------------------------------------------------------
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("encounters.id", ondelete="SET NULL"),
        nullable=True,
        comment="Originating encounter (NULL if ordered outside a visit)",
    )

    # -----------------------------------------------------------------------
    # Test Identification — PHI when combined with patient_id
    # -----------------------------------------------------------------------
    test_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="PHI: Human-readable lab test name (e.g., 'Complete Blood Count')",
    )

    loinc_code: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="LOINC code — validated against CodeCatalog before storage",
    )

    # -----------------------------------------------------------------------
    # Clinical Context — PHI
    # -----------------------------------------------------------------------
    clinical_indication: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="PHI: Clinical reason for ordering this test",
    )

    # -----------------------------------------------------------------------
    # Priority and Status
    # -----------------------------------------------------------------------
    priority: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Processing urgency: routine, urgent, or stat",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=LabOrderStatus.ORDERED.value,
        comment="Lifecycle status: ordered, specimen_collected, in_progress, resulted, cancelled",
    )

    # -----------------------------------------------------------------------
    # Ordering Clinician
    # -----------------------------------------------------------------------
    ordered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the clinician who ordered this test",
    )

    # -----------------------------------------------------------------------
    # Specimen Collection Tracking
    # -----------------------------------------------------------------------
    specimen_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="When the specimen was collected from the patient",
    )

    # -----------------------------------------------------------------------
    # FHIR Interoperability — stores FHIR R4 ServiceRequest JSON
    # -----------------------------------------------------------------------
    fhir_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="FHIR R4 ServiceRequest resource JSON (computed on write)",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    results: Mapped[list["LabResult"]] = relationship(
        "LabResult",
        back_populates="lab_order",
        lazy="selectin",
    )


# ---------------------------------------------------------------------------
# LabResult Model
# ---------------------------------------------------------------------------
class LabResult(TenantMixin, Base):
    """
    Laboratory test result record.

    Stores the outcome of a lab order — the actual measured value,
    reference ranges, and abnormality flag. When a result is recorded:
    1. is_abnormal is computed by comparing numeric_value to reference range
    2. A Measurement record is created to feed the risk computation pipeline
    3. If abnormal, an alert is generated via the Alert system

    Integration Points:
    - measurement_id links to the Measurement record created from this result
    - Publishes MeasurementSaved event for risk engine consumption
    - Triggers alert generation when is_abnormal = True

    RLS: Tenant-scoped — results only visible within their tenant.

    HIPAA Compliance:
    - PHI fields (value, numeric_value, unit) encrypted at rest
    - Never log result values — only log lab_result_id and is_abnormal flag
    - Soft delete only (retained 7+ years per HIPAA)
    """

    __tablename__ = "lab_results"

    # -----------------------------------------------------------------------
    # Primary Key
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique lab result identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Parent Lab Order Reference
    # -----------------------------------------------------------------------
    lab_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lab_orders.id", ondelete="CASCADE"),
        nullable=False,
        comment="Parent lab order this result belongs to",
    )

    # -----------------------------------------------------------------------
    # Result Value — PHI
    # -----------------------------------------------------------------------
    value: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: Result value as string (supports non-numeric results like 'Positive')",
    )

    numeric_value: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="PHI: Parsed numeric value for range comparison (NULL for qualitative results)",
    )

    unit: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Unit of measurement (e.g., mg/dL, mmol/L, cells/μL)",
    )

    # -----------------------------------------------------------------------
    # Reference Range — used to compute is_abnormal flag
    # -----------------------------------------------------------------------
    reference_range_low: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="Lower bound of normal reference range",
    )

    reference_range_high: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        default=None,
        comment="Upper bound of normal reference range",
    )

    # -----------------------------------------------------------------------
    # Abnormality Flag — triggers alert when True
    # -----------------------------------------------------------------------
    is_abnormal: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="True if value falls outside reference range (triggers alert)",
    )

    # -----------------------------------------------------------------------
    # Result Metadata
    # -----------------------------------------------------------------------
    resulted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the result was produced by the lab",
    )

    resulted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the user who entered/recorded this result",
    )

    # -----------------------------------------------------------------------
    # Measurement Integration — links to Measurement record when created
    # -----------------------------------------------------------------------
    measurement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("measurements.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
        comment="Linked Measurement record (created when result feeds risk pipeline)",
    )

    # -----------------------------------------------------------------------
    # FHIR Interoperability — stores FHIR R4 Observation JSON
    # -----------------------------------------------------------------------
    fhir_json: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="FHIR R4 Observation resource JSON (computed on write)",
    )

    # -----------------------------------------------------------------------
    # Relationships
    # -----------------------------------------------------------------------
    lab_order: Mapped["LabOrder"] = relationship(
        "LabOrder",
        back_populates="results",
    )
