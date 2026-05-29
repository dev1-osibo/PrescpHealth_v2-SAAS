"""
PrescpHealth Backend — Forecast Engine Pydantic Schemas.

Request/response models for forecast API endpoints.
All models follow standard envelope format: {success, data, meta}.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
import uuid

from pydantic import BaseModel, Field


# ============================================================================
# Request Models
# ============================================================================

class ComputeForecastRequest(BaseModel):
    """Request to trigger forecast computation. No body required."""

    pass


class RunSimulationRequest(BaseModel):
    """Request to run intervention simulation."""

    intervention_type: str = Field(
        ...,
        description="Type: 'weight_loss', 'smoking_cessation', 'medication_addition', 'exercise_increase'"
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Intervention parameters (e.g., {'target_weight_kg': 85})"
    )


# ============================================================================
# Response Models
# ============================================================================

class ForecastDataResponse(BaseModel):
    """Single forecast at one horizon for one target."""

    point_estimate: float = Field(..., description="Best prediction")
    confidence_lower: float = Field(..., description="95% CI lower bound")
    confidence_upper: float = Field(..., description="95% CI upper bound")
    data_quality: str = Field(..., description="'full_data', 'sparse_data', or 'prior_only'")
    model_weights: Dict[str, float] = Field(..., description="Ensemble weights {tft, lstm, prophet}")
    computed_at: str = Field(..., description="ISO timestamp when forecast was computed")


class ForecastTargetResponse(BaseModel):
    """Forecasts for one target (all horizons)."""

    horizon_3m: Optional[ForecastDataResponse] = None
    horizon_6m: Optional[ForecastDataResponse] = None
    horizon_12m: Optional[ForecastDataResponse] = None


class ForecastLatestResponse(BaseModel):
    """All latest forecasts for a patient (all targets, all horizons)."""

    systolic_bp: Optional[ForecastTargetResponse] = None
    stroke: Optional[ForecastTargetResponse] = None
    diabetes: Optional[ForecastTargetResponse] = None
    cvd: Optional[ForecastTargetResponse] = None
    ckd: Optional[ForecastTargetResponse] = None


class ForecastComputationResponse(BaseModel):
    """Response to trigger forecast computation."""

    success: bool = Field(..., description="Always true on success")
    data: Dict[str, Any] = Field(
        ...,
        description="Always {task_id: '...'} (for polling /tasks/{task_id}/status)"
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata {request_id, timestamp, ...}"
    )


class SimulationResultItem(BaseModel):
    """One simulated outcome."""

    horizon: int = Field(..., description="3, 6, or 12 months")
    metric: str = Field(..., description="e.g., 'systolic_bp'")
    baseline_value: float = Field(..., description="Baseline prediction")
    simulated_value: float = Field(..., description="Prediction under intervention")
    delta: float = Field(..., description="Change (simulated - baseline)")


class SimulationResponse(BaseModel):
    """Response to run intervention simulation."""

    success: bool = Field(..., description="Always true on success")
    data: Dict[str, Any] = Field(
        ...,
        description="Always {task_id: '...'} (for polling /tasks/{task_id}/status)"
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata {request_id, timestamp, ...}"
    )


# ============================================================================
# Standard Envelope (used by router)
# ============================================================================

class StandardResponse(BaseModel):
    """Standard response envelope for all API endpoints."""

    success: bool = Field(..., description="true for 2xx, false for errors")
    data: Optional[Any] = Field(None, description="Response payload")
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata {request_id, timestamp, pagination, etc.}"
    )
