"""
PrescpHealth Backend — Forecast Engine SQLAlchemy Models.

Defines database models for:
- Forecast: Disease trajectory predictions at multiple horizons (3/6/12 months)
- InterventionSimulation: Counterfactual analysis (what if patient changes behavior?)

Design Principles:
    - Forecast stores ensemble weights (TFT, LSTM, Prophet) for explainability
    - Data quality indicator (full_data, sparse_data, prior_only) flags confidence
    - Intervention simulations reference baseline forecasts for comparison
    - All results stored as immutable audit records (no soft-delete)

RLS and Tenant Isolation:
    - Forecast uses TenantMixin (RLS on tenant_id)
    - InterventionSimulation uses TenantMixin (RLS on tenant_id)

HIPAA Compliance:
    - Forecasts are PHI (identified by patient_id) — never log values
    - Simulated results may contain clinical references — treat as PHI
    - All PHI fields (forecasts, simulations) marked with comment="PHI: ..."
    - Audit trail via AuditService

Indexes:
    - (patient_id, target, computed_at DESC) on forecasts for quick lookup
    - (patient_id, intervention_type, computed_at DESC) on simulations
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    Numeric,
    ForeignKey,
    String,
    Integer,
    Text,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin


class Forecast(TenantMixin, Base):
    """
    Disease trajectory prediction for a patient.

    Stores forecast at multiple horizons (3, 6, 12 months) for a given target
    (measurement type like "systolic_bp" or disease key like "stroke").

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        patient_id: Patient UUID (FK to patients table)
        forecast_type: "metric" (predict a measurement) or "risk_trajectory" (predict risk change)
        target: What we're forecasting (e.g., "systolic_bp", "stroke", "diabetes")
        horizon_months: 3, 6, or 12 months ahead
        point_estimate: Best prediction (Decimal)
        confidence_lower: 95% CI lower bound
        confidence_upper: 95% CI upper bound
        data_quality: "full_data" (enough historical), "sparse_data", or "prior_only" (bootstrap)
        model_ensemble_weights: JSONB with {tft: 0.4, lstm: 0.35, prophet: 0.25} (explainability)
        computed_at: When forecast was generated
        created_at, updated_at: From TenantMixin

    Design Note:
        - One row per target per horizon (3 rows for stroke at 3/6/12 months)
        - New computation appends new rows (no overwrite)
        - Ensemble weights enable clinician understanding (which model drove the forecast)
        - Data quality flag warns if forecast is based on limited data
    """

    __tablename__ = "forecasts"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient UUID",
    )

    forecast_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type: 'metric' (predict measurement) or 'risk_trajectory' (predict disease risk)",
    )

    target: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="PHI: What we forecast (e.g., 'systolic_bp', 'stroke', 'diabetes')",
    )

    horizon_months: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Forecast horizon: 3, 6, or 12 months",
    )

    point_estimate: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        comment="PHI: Best point prediction (e.g., 145.23 for systolic BP, 68.5 for risk score)",
    )

    confidence_lower: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        comment="PHI: 95% confidence interval lower bound",
    )

    confidence_upper: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        nullable=False,
        comment="PHI: 95% confidence interval upper bound",
    )

    data_quality: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="full_data",
        comment="Indicator of forecast confidence: 'full_data', 'sparse_data', or 'prior_only'",
    )

    model_ensemble_weights: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"tft": 0.4, "lstm": 0.35, "prophet": 0.25}',
        comment="Model weights for explainability: {tft: w, lstm: w, prophet: w}",
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When this forecast was computed",
    )

    __table_args__ = (
        Index("ix_forecast_patient_target_computed", "patient_id", "target", computed_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<Forecast patient={self.patient_id} target={self.target} horizon={self.horizon_months}m>"


class InterventionSimulation(TenantMixin, Base):
    """
    Counterfactual "what-if" simulation for clinical interventions.

    Compares baseline forecast with simulated outcomes if patient takes action
    (e.g., weight loss, smoking cessation, medication addition).

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        patient_id: Patient UUID (FK to patients table)
        intervention_type: "weight_loss", "smoking_cessation", "medication_addition", "exercise_increase"
        parameters: JSONB with intervention details (e.g., {"target_weight_kg": 85, "duration_months": 6})
        baseline_forecast_id: UUID FK to forecasts (the baseline we're comparing against)
        simulated_results: JSONB with [{horizon, metric, baseline_value, simulated_value, delta}, ...]
        computed_at: When simulation was run
        created_at, updated_at: From TenantMixin

    Design Note:
        - Used by clinicians to communicate expected outcomes
        - Example: "If you lose 10kg, your systolic BP forecast improves from 160 to 145"
        - Multiple simulations per patient (one per intervention type explored)
        - Immutable records (append-only for audit trail)
    """

    __tablename__ = "intervention_simulations"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient UUID",
    )

    intervention_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of intervention: 'weight_loss', 'smoking_cessation', 'medication_addition', 'exercise_increase'",
    )

    parameters: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{}',
        comment="Intervention parameters (e.g., {target_weight_kg: 85, duration_months: 6})",
    )

    baseline_forecast_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("forecasts.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Reference forecast for comparison",
    )

    simulated_results: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='[]',
        comment="PHI: Simulation results [{horizon, metric, baseline_value, simulated_value, delta}, ...]",
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When this simulation was computed",
    )

    __table_args__ = (
        Index("ix_simulation_patient_intervention_computed", "patient_id", "intervention_type", computed_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<InterventionSimulation patient={self.patient_id} intervention={self.intervention_type}>"
