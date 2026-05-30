"""
PrescpHealth Backend — Risk Engine Pydantic Schemas.

Request and response models for risk engine API endpoints.

Design:
    - Request models validate user input at API boundary
    - Response models enforce standard envelope (success, data, meta)
    - All responses include request_id for correlation
    - PHI-containing responses note HIPAA implications
    - Confidence intervals always included (enable future confidence-based alerts)

HIPAA Note:
    Responses containing risk scores (PHI) must have:
    Cache-Control: no-store, no-cache, must-revalidate
    (enforced by router via @hipaa_no_cache decorator)
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Request Models
# ============================================================================
class ComputeRiskRequest(BaseModel):
    """
    Request to trigger risk computation for a patient.

    Empty request body (patient_id comes from URL path).
    Triggers enqueue of Celery task, returns task_id for polling.
    """

    pass


# ============================================================================
# Response Models
# ============================================================================
class ShapFeatureContribution(BaseModel):
    """Single feature's contribution to a risk score."""

    feature: str = Field(..., description="Feature name (e.g., 'systolic_bp')")
    value: float = Field(..., description="Feature value at computation time")
    shap_value: float = Field(..., description="SHAP contribution (-1 to +1)")
    direction: str = Field(..., description="positive or negative")


class ShapExplanationResponse(BaseModel):
    """SHAP feature importance breakdown for a risk score."""

    base_value: float = Field(..., description="Model baseline prediction")
    feature_contributions: list[ShapFeatureContribution] = Field(
        default_factory=list,
        description="Top features and their SHAP contributions",
    )


class RiskScoreResponse(BaseModel):
    """Single disease risk score with confidence interval and SHAP."""

    disease: str = Field(..., description="Disease (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)")
    score: float = Field(..., description="Risk score 0–100", ge=0, le=100)
    stratum: str = Field(..., description="Risk level (Low, Moderate, High, Critical)")
    confidence_lower: float = Field(..., description="95% CI lower bound")
    confidence_upper: float = Field(..., description="95% CI upper bound")
    model_version: str = Field(..., description="ML model version used")
    computed_at: str = Field(..., description="ISO-8601 timestamp")
    shap: Optional[ShapExplanationResponse] = Field(None, description="SHAP explanation (optional)")


class RiskComputationResponse(BaseModel):
    """Response when triggering async computation."""

    success: bool = Field(default=True)
    data: dict = Field(
        default_factory=lambda: {"task_id": "..."},
        description="task_id for polling /tasks/{task_id}/status",
    )
    meta: dict = Field(
        default_factory=dict,
        description="Metadata (request_id, timestamp, etc.)",
    )


class RiskScoresListResponse(BaseModel):
    """Response listing latest scores for all 6 diseases."""

    success: bool = Field(default=True)
    data: dict[str, Optional[RiskScoreResponse]] = Field(
        ...,
        description="Mapping of disease -> score (or None if not computed)",
    )
    meta: dict = Field(
        default_factory=dict,
        description="Metadata (request_id, timestamp, cache headers)",
    )


class RiskHistoryResponse(BaseModel):
    """Paginated response listing historical scores for one disease."""

    success: bool = Field(default=True)
    data: list[RiskScoreResponse] = Field(
        default_factory=list,
        description="List of historical scores (most recent first)",
    )
    meta: dict = Field(
        default_factory=dict,
        description="Metadata (request_id, pagination cursor, etc.)",
    )


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    success: bool = Field(default=False)
    error: dict = Field(
        default_factory=dict,
        description="Error details: {code, message, details, request_id}",
    )
