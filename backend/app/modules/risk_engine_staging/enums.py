"""
PrescpHealth Backend — Risk Engine Enums.

Enumerations for disease types and risk strata used throughout the
risk engine module. These are the six diseases covered by PrescpHealth
and the four risk classification levels.

Design:
    - Disease names match what the ML models expect
    - Strata bounds are: Low (0–24), Moderate (25–49), High (50–74), Critical (75–100)
    - Enums ensure type safety and prevent typos in risk computations
"""

from enum import Enum


class Disease(str, Enum):
    """
    The six chronic diseases covered by PrescpHealth risk prediction engine.

    Each disease has its own ensemble model trained on disease-specific features.
    All six models run simultaneously for every patient.
    """

    STROKE = "stroke"
    CARDIOVASCULAR_DISEASE = "cvd"
    TYPE_2_DIABETES = "diabetes"
    CHRONIC_KIDNEY_DISEASE = "ckd"
    HYPERTENSIVE_CRISIS = "hypertensive_crisis"
    COPD = "copd"

    @classmethod
    def all_diseases(cls) -> list[str]:
        """Return list of all disease string values for iteration."""
        return [d.value for d in cls]


class RiskStratum(str, Enum):
    """
    Four-level risk stratification based on Risk_Score (0–100).

    Boundaries:
    - LOW: 0–24 (minimal risk)
    - MODERATE: 25–49 (moderate risk, monitor closely)
    - HIGH: 50–74 (high risk, intervention recommended)
    - CRITICAL: 75–100 (critical risk, urgent clinical action)

    Clinical Context:
        Higher strata trigger stricter escalation rules, more frequent
        monitoring, and more aggressive interventions. The AI assistant
        flags Critical-stratum patients as requiring immediate review.
    """

    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    CRITICAL = "Critical"

    @classmethod
    def from_score(cls, score: float) -> "RiskStratum":
        """
        Determine stratum from a numeric risk score (0–100).

        Args:
            score: Risk score between 0 and 100 (inclusive).

        Returns:
            RiskStratum: The corresponding stratum level.

        Raises:
            ValueError: If score is outside [0, 100].
        """
        if not 0 <= score <= 100:
            raise ValueError(f"Risk score must be in [0, 100], got {score}")

        if score < 25:
            return cls.LOW
        elif score < 50:
            return cls.MODERATE
        elif score < 75:
            return cls.HIGH
        else:
            return cls.CRITICAL
