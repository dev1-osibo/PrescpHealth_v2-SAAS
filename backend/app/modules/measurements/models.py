"""
PrescpHealth Backend — Measurement SQLAlchemy Model.

Defines the database model for clinical measurements (vital signs,
lab results, lifestyle factors). Each measurement is a single data
point recorded for a patient at a specific time.

Schema Design Decisions:
- MeasurementType enum covers all 22 supported measurement types
- value stored as Float (sufficient precision for clinical measurements)
- unit stored alongside value for self-documenting records
- recorded_at is when the measurement was taken (not when it was entered)
- source tracks provenance: manual, device, import, patient_portal
- is_validated gates inclusion in risk computation (Patient_User entries
  must be validated by a clinician before affecting risk scores)
- is_flagged marks deviations from patient baseline (>2σ)
- Idempotency enforced via unique constraint on
  (patient_id, measurement_type, recorded_at, value)

PHI Fields (Protected Health Information):
    The measurement value itself is PHI when combined with patient_id.
    - value: The numeric measurement reading
    - notes: Free-text clinician notes about the measurement

    These must be:
    - Encrypted at rest (column-level or TDE)
    - Never logged (only log measurement_id UUID and measurement_type)
    - Never cached in browser-accessible storage

RLS: Uses tenant_id for Row-Level Security isolation.
"""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TenantMixin


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class MeasurementType(str, Enum):
    """
    All supported clinical measurement types.

    Covers vital signs, metabolic markers, renal function, respiratory
    function, anthropometrics, and lifestyle factors needed for the
    six-disease risk prediction engine.

    Each type has a corresponding physiological validation range
    defined in validators.py.
    """

    # --- Cardiovascular ---
    SYSTOLIC_BP = "systolic_bp"
    DIASTOLIC_BP = "diastolic_bp"
    HEART_RATE = "heart_rate"

    # --- Metabolic ---
    BMI = "bmi"
    BLOOD_GLUCOSE_FASTING = "blood_glucose_fasting"
    BLOOD_GLUCOSE_RANDOM = "blood_glucose_random"
    HBA1C = "hba1c"

    # --- Lipid Panel ---
    TOTAL_CHOLESTEROL = "total_cholesterol"
    HDL_CHOLESTEROL = "hdl_cholesterol"
    LDL_CHOLESTEROL = "ldl_cholesterol"
    TRIGLYCERIDES = "triglycerides"

    # --- Renal Function ---
    CREATININE = "creatinine"
    EGFR = "egfr"
    URINE_ALBUMIN = "urine_albumin"

    # --- Respiratory ---
    FEV1 = "fev1"
    FVC = "fvc"
    SPO2 = "spo2"
    RESPIRATORY_RATE = "respiratory_rate"

    # --- Anthropometrics ---
    WEIGHT = "weight"
    HEIGHT = "height"
    WAIST_CIRCUMFERENCE = "waist_circumference"

    # --- Lifestyle ---
    SMOKING_STATUS = "smoking_status"


class MeasurementSource(str, Enum):
    """
    Source of the measurement data.

    Tracks provenance for audit and validation purposes:
    - manual: Clinician entered directly during consultation
    - device: Imported from a connected medical device
    - import: Bulk imported via CSV upload
    - patient_portal: Self-reported by Patient_User (requires validation)
    """

    MANUAL = "manual"
    DEVICE = "device"
    IMPORT = "import"
    PATIENT_PORTAL = "patient_portal"


# ---------------------------------------------------------------------------
# Measurement Model
# ---------------------------------------------------------------------------
class Measurement(TenantMixin, Base):
    """
    Clinical measurement record.

    Stores a single data point for a patient: one measurement type,
    one value, at one point in time. Multiple measurements can be
    recorded simultaneously (e.g., systolic + diastolic BP in one visit).

    Validation Flow:
    1. Value validated against physiological range for the type
    2. Idempotency checked via unique constraint
    3. Deviation from baseline checked (flag if >2σ)
    4. If source is patient_portal, is_validated defaults to False
    5. MeasurementSaved event published for downstream processing

    RLS: Tenant-scoped — measurements only visible within their tenant.
    Idempotency: (patient_id, measurement_type, recorded_at, value) is unique.

    HIPAA Compliance:
    - PHI fields (value, notes) encrypted at rest
    - Never log measurement values — only log measurement_id and type
    - Soft delete only (via TenantMixin timestamps, no hard delete)
    """

    __tablename__ = "measurements"

    # -----------------------------------------------------------------------
    # Primary Key — UUID for globally unique identification
    # -----------------------------------------------------------------------
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique measurement identifier (UUID)",
    )

    # -----------------------------------------------------------------------
    # Patient Reference — FK to patients table
    # -----------------------------------------------------------------------
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient this measurement belongs to",
    )

    # -----------------------------------------------------------------------
    # Measurement Data — PHI when combined with patient_id
    # -----------------------------------------------------------------------
    measurement_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type key (e.g., systolic_bp, hba1c, bmi)",
    )

    value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="PHI: Numeric measurement value (validated against physiological range)",
    )

    unit: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Unit of measurement (e.g., mmHg, mg/dL, kg, %)",
    )

    # -----------------------------------------------------------------------
    # Temporal Context — when the measurement was actually taken
    # -----------------------------------------------------------------------
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the measurement was taken (not when it was entered into the system)",
    )

    # -----------------------------------------------------------------------
    # Provenance — who recorded it and from what source
    # -----------------------------------------------------------------------
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="UUID of the user who recorded/submitted this measurement",
    )

    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Data source: manual, device, import, patient_portal",
    )

    # -----------------------------------------------------------------------
    # Validation Status — Patient_User submissions need clinician approval
    # Requirement 5.4: Patient_User measurements excluded from risk
    # computation until a Clinician validates them.
    # -----------------------------------------------------------------------
    is_validated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="Whether a clinician has validated this measurement (Patient_User entries start False)",
    )

    validated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        default=None,
        comment="UUID of the clinician who validated this measurement",
    )

    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        comment="Timestamp when the measurement was validated by a clinician",
    )

    # -----------------------------------------------------------------------
    # Deviation Flagging — Requirement 5.6
    # Flag if value deviates >2σ from patient's personal baseline
    # -----------------------------------------------------------------------
    is_flagged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="True if value deviates >2σ from patient baseline (requires clinician review)",
    )

    flag_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
        comment="Explanation of why this measurement was flagged (e.g., '2.3σ above baseline')",
    )

    # -----------------------------------------------------------------------
    # Clinical Notes — PHI
    # -----------------------------------------------------------------------
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="PHI: Optional clinician notes about this measurement (encrypted at rest)",
    )

    # -----------------------------------------------------------------------
    # Table Constraints and Indexes
    # -----------------------------------------------------------------------
    __table_args__ = (
        # Idempotency constraint: same patient, same type, same time, same value
        # prevents duplicate entries from retries or bulk import re-runs
        UniqueConstraint(
            "patient_id",
            "measurement_type",
            "recorded_at",
            "value",
            name="uq_measurement_idempotency",
        ),
    )
