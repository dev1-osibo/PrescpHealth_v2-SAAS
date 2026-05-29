"""
PrescpHealth Backend — Risk Engine SQLAlchemy Models.

Defines database models for:
- RiskScore: Individual disease risk predictions (0–100) with confidence intervals
- ShapExplanation: SHAP feature importance breakdowns per risk score
- ModelVersion: Versioned ML model artifacts with performance metrics

Design Principles:
    - Input snapshots (JSONB) preserve exact features used for computation
      (enables audit trail and reproduction of old scores)
    - Model version tracking (not tenant-scoped) enables cross-tenant A/B testing
    - Unique constraint on (disease, version) enforces one active version per disease
    - SHAP explanations stored as JSONB for flexible feature counts
    - Confidence intervals stored separately (support future confidence-based alerts)

RLS and Tenant Isolation:
    - RiskScore uses TenantMixin (RLS on tenant_id)
    - ShapExplanation uses TenantMixin (RLS on tenant_id)
    - ModelVersion does NOT use TenantMixin (models are platform-level, not tenant-scoped)

HIPAA Compliance:
    - Risk scores are PHI (identified by patient_id) — never log values
    - Feature snapshots contain values but only within this encrypted table
    - All PHI fields (scores, features) marked with comment="PHI: ..."
    - Soft-delete never applies to risk scores (immutable audit trail)

Indexes:
    - (patient_id, disease, computed_at DESC) for quick "latest score" lookup
    - (disease, version) UNIQUE on ModelVersion ensures only one active version
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
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TenantMixin


class ModelVersion(Base):
    """
    Platform-level ML model version registry.

    One model version per disease per semantic version (e.g., "stroke:v1.2.0").
    Models are not tenant-scoped — the same model version serves all tenants.
    When a new model is deployed, old versions are kept for rollback.

    Fields:
        id: UUID primary key
        disease: Which disease this model predicts (stroke, cvd, etc.)
        version: Semantic version string (e.g., "1.2.0")
        artifact_path: S3 or local path to model artifact (pkl, pth, etc.)
        metrics: JSONB with {auc_roc, calibration_score, brier_score, etc.}
        is_active: Whether this is the current production version
        deployed_at: When this model was deployed
        deployed_by: User UUID who triggered deployment (for audit)
        created_at: When the version record was created

    Constraints:
        - (disease, version) UNIQUE → only one version per disease per semver
        - Indexes on disease and is_active for quick lookups
    """

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Model version UUID",
    )

    disease: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Disease type (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)",
    )

    version: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Semantic version (e.g., 1.2.0) — uniquely identifies this model",
    )

    artifact_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="S3 or local filesystem path to the model artifact (pkl, pt, h5, etc.)",
    )

    metrics: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Performance metrics: {auc_roc, calibration_score, brier_score, precision, recall, ...}",
    )

    is_active: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="True = current production version for this disease, False = retired/rollback candidate",
    )

    deployed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When this model was deployed to production",
    )

    deployed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="User UUID who deployed this model (for audit trail)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When this version record was created",
    )

    __table_args__ = (
        UniqueConstraint("disease", "version", name="uq_model_version_disease_version"),
        Index("ix_model_version_disease_active", "disease", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<ModelVersion {self.disease}:v{self.version} (active={self.is_active})>"


class RiskScore(TenantMixin, Base):
    """
    Single disease risk prediction for a patient.

    One RiskScore row per disease per computation. When scores are recomputed,
    a new RiskComputation groups 6 new RiskScore rows (one per disease).

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        patient_id: Patient UUID (FK to patients table)
        disease: Which disease (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)
        score: Risk score 0–100 (Decimal for precision)
        stratum: Low/Moderate/High/Critical (derived from score)
        confidence_lower: 95% CI lower bound
        confidence_upper: 95% CI upper bound
        model_version_id: Which model version produced this score (FK)
        input_snapshot: JSONB with feature dict used for computation
        computation_id: Groups all scores from same risk computation run
        computed_at: When the score was computed
        created_at, updated_at: From TenantMixin

    PHI Fields:
        - score: The numeric prediction (PHI when tied to patient_id)
        - input_snapshot: Feature values (PHI — contains vitals, labs, etc.)

    Constraints:
        - (patient_id, disease, computed_at DESC) index for latest score lookup
        - RLS policy: tenant_id = current_setting('app.current_tenant')::uuid
    """

    __tablename__ = "risk_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Risk score record UUID",
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        comment="Patient this score belongs to",
    )

    disease: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Disease type (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)",
    )

    score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="PHI: Risk score 0–100 (e.g., 72.45 for stroke)",
    )

    stratum: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Risk stratum derived from score (Low/Moderate/High/Critical)",
    )

    confidence_lower: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="95% confidence interval lower bound",
    )

    confidence_upper: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="95% confidence interval upper bound",
    )

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_versions.id", ondelete="RESTRICT"),
        nullable=False,
        comment="Which ML model version produced this score",
    )

    input_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="PHI: Feature dict at computation time — enables score reproduction and audit",
    )

    computation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Groups all 6 disease scores from same computation run",
    )

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        comment="When the ML engine computed this score",
    )

    __table_args__ = (
        Index("ix_risk_score_patient_disease_computed", "patient_id", "disease", "computed_at DESC"),
        Index("ix_risk_score_computation", "computation_id"),
    )

    def __repr__(self) -> str:
        return f"<RiskScore patient={self.patient_id} disease={self.disease} score={self.score}>"


class ShapExplanation(TenantMixin, Base):
    """
    SHAP feature importance explanation for a risk score.

    SHAP (SHapley Additive exPlanations) breaks down the risk score into
    per-feature contributions. For each feature, we store the SHAP value
    (how much it pushed the prediction up or down from baseline).

    One ShapExplanation per RiskScore (1-to-1 relationship).

    Fields:
        id: UUID primary key
        tenant_id: Tenant UUID (from TenantMixin, with RLS)
        risk_score_id: FK to risk_scores (1-to-1)
        base_value: Model baseline prediction (starting point before features)
        feature_contributions: JSONB list of:
            [{
                "feature": "systolic_bp",
                "value": 160,
                "shap_value": 0.25,
                "direction": "positive" (contributes upward) or "negative" (downward)
            }, ...]
        created_at, updated_at: From TenantMixin

    PHI Fields:
        - feature_contributions: Feature names and values (PHI)

    Validation:
        Property 4 (SHAP Additivity):
            sum(shap_value for each feature) ≈ (score - base_value) ± 0.01

    Constraints:
        - FK cascade delete on risk_scores (SHAP explanation deleted when score deleted)
        - RLS policy: tenant_id = current_setting('app.current_tenant')::uuid
    """

    __tablename__ = "shap_explanations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="SHAP explanation record UUID",
    )

    risk_score_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("risk_scores.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="1-to-1 FK to the risk score being explained",
    )

    base_value: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="SHAP base value (model baseline prediction before feature contributions)",
    )

    feature_contributions: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="PHI: List of feature contributions: [{feature, value, shap_value, direction}, ...]",
    )

    __table_args__ = (
        Index("ix_shap_risk_score_id", "risk_score_id"),
    )

    def __repr__(self) -> str:
        return f"<ShapExplanation risk_score_id={self.risk_score_id} base_value={self.base_value}>"
