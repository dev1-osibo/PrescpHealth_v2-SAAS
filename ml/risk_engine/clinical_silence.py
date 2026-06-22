"""
PrescpHealth ML Engine — Confidence-Calibrated Clinical Silence (Layer 5b, Patent Claim 7).

Core patent innovation: NOT every risk score should generate an alert.
Alert fatigue is the #1 cause of clinicians ignoring clinical decision support.
This module implements "clinical silence" — the system WITHHOLDS information
when confidence is low, preventing false alarms that erode trust.

Triple-threshold decision logic:
    - ALERT: high risk × high confidence × high ensemble agreement → notify clinician
    - INFORM: moderate signal on any axis → show in dashboard, don't push notification
    - SILENT: low confidence OR low agreement → suppress entirely (log for audit only)

The thresholds are configurable per disease and per clinician role:
    - An attending physician may want a lower alert threshold (see more)
    - A nurse practitioner may want a higher threshold (see only critical)
    - Emergency physicians want alerts only for imminent events
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default thresholds per disease.
# Format: (risk_threshold, confidence_threshold, agreement_threshold)
# All three must be exceeded for ALERT status.
# If only risk is high but confidence/agreement are low → INFORM (not confident enough)
DEFAULT_THRESHOLDS: dict[str, dict[str, float]] = {
    "stroke": {
        "alert_risk": 0.70,
        "alert_confidence": 0.60,
        "alert_agreement": 0.65,
        "inform_risk": 0.40,
        "inform_confidence": 0.30,
    },
    "cvd": {
        "alert_risk": 0.65,
        "alert_confidence": 0.55,
        "alert_agreement": 0.60,
        "inform_risk": 0.35,
        "inform_confidence": 0.25,
    },
    "diabetes": {
        "alert_risk": 0.60,
        "alert_confidence": 0.50,
        "alert_agreement": 0.55,
        "inform_risk": 0.30,
        "inform_confidence": 0.25,
    },
    "ckd": {
        "alert_risk": 0.60,
        "alert_confidence": 0.50,
        "alert_agreement": 0.55,
        "inform_risk": 0.30,
        "inform_confidence": 0.25,
    },
    "hypertensive_crisis": {
        # Lower thresholds for acute events — err on the side of alerting
        "alert_risk": 0.55,
        "alert_confidence": 0.45,
        "alert_agreement": 0.50,
        "inform_risk": 0.30,
        "inform_confidence": 0.20,
    },
    "copd": {
        "alert_risk": 0.65,
        "alert_confidence": 0.55,
        "alert_agreement": 0.60,
        "inform_risk": 0.35,
        "inform_confidence": 0.25,
    },
}

# Role-based threshold multipliers — adjust sensitivity per clinician role.
# Values < 1.0 LOWER thresholds (more alerts), > 1.0 RAISE them (fewer alerts).
ROLE_MULTIPLIERS: dict[str, float] = {
    "attending_physician": 0.85,     # Sees more alerts (lower bar)
    "specialist": 0.80,              # Specialists want early signals
    "nurse_practitioner": 1.0,       # Standard thresholds
    "resident": 1.10,                # Slightly higher bar (avoid overwhelming)
    "emergency_physician": 1.20,     # Only critical/imminent events
}


class ClinicalSilenceEngine:
    """Confidence-Calibrated Clinical Silence — suppress low-confidence alerts.

    Prevents alert fatigue by only surfacing predictions the system is
    confident about. A 90% stroke risk score with 20% confidence should
    NOT trigger an alert — it would erode clinician trust in the system.

    The triple-threshold (risk × confidence × agreement) ensures alerts
    are actionable: high risk that the system believes in and that multiple
    models agree on.
    """

    def __init__(self, role: str = "nurse_practitioner") -> None:
        """Initialize with role-specific threshold adjustments.

        Args:
            role: Clinician role for threshold multiplier application.
        """
        self._role: str = role
        self._multiplier: float = ROLE_MULTIPLIERS.get(role, 1.0)
        self._thresholds: dict[str, dict[str, float]] = self._build_thresholds()

    def _build_thresholds(self) -> dict[str, dict[str, float]]:
        """Apply role multiplier to base thresholds.

        Multiplier adjusts ALL thresholds proportionally — a specialist
        with multiplier 0.8 gets 20% lower thresholds (more sensitive).
        """
        adjusted: dict[str, dict[str, float]] = {}
        for disease, base in DEFAULT_THRESHOLDS.items():
            adjusted[disease] = {
                key: min(1.0, val * self._multiplier)
                for key, val in base.items()
            }
        return adjusted

    def should_alert(
        self,
        disease: str,
        risk_score: float,
        confidence: float,
        ensemble_agreement: float,
    ) -> str:
        """Determine alert disposition using triple-threshold logic.

        Decision hierarchy:
            1. If ALL three signals exceed alert thresholds → "ALERT"
            2. If risk and confidence exceed inform thresholds → "INFORM"
            3. Otherwise → "SILENT" (suppress, log only for audit)

        Args:
            disease: Disease being evaluated.
            risk_score: Final blended risk score in [0.0, 1.0].
            confidence: Model confidence in [0.0, 1.0].
            ensemble_agreement: Fraction of experts that agree on direction
                               (e.g., 0.75 = 3 of 4 experts predict high risk).

        Returns:
            One of "ALERT", "INFORM", or "SILENT".
        """
        thresholds = self._thresholds.get(disease, DEFAULT_THRESHOLDS.get("cvd", {}))

        # Triple-threshold check for ALERT
        alert_risk = thresholds.get("alert_risk", 0.65)
        alert_conf = thresholds.get("alert_confidence", 0.55)
        alert_agree = thresholds.get("alert_agreement", 0.60)

        if (risk_score >= alert_risk
                and confidence >= alert_conf
                and ensemble_agreement >= alert_agree):
            return "ALERT"

        # Double-threshold check for INFORM (less stringent)
        inform_risk = thresholds.get("inform_risk", 0.35)
        inform_conf = thresholds.get("inform_confidence", 0.25)

        if risk_score >= inform_risk and confidence >= inform_conf:
            return "INFORM"

        # Below all thresholds — suppress to avoid alert fatigue
        return "SILENT"

    def get_thresholds(self, disease: str) -> dict[str, float]:
        """Return current thresholds for a disease (useful for debugging/audit).

        Args:
            disease: Disease to retrieve thresholds for.

        Returns:
            Dict of threshold_name -> value.
        """
        return dict(self._thresholds.get(disease, {}))
