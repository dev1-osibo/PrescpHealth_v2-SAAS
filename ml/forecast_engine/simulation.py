"""
PrescpHealth Forecast Engine — Intervention Simulation (Patent Claim 5).

Implements counterfactual analysis: "What would happen to this patient's
health trajectory if they undertook a specific intervention?"

Supported interventions:
    - weight_loss: Simulates BMI/weight reduction over time
    - smoking_cessation: Removes smoking risk factor
    - medication_addition: Adds medication effect to risk profile
    - exercise_increase: Simulates cardiovascular fitness improvement

Process:
    1. Take baseline patient features
    2. Modify features according to intervention type and parameters
    3. Re-run forecast engine on modified features
    4. Compare baseline vs. simulated trajectories at 3/6/12 month horizons
    5. Return deltas showing intervention impact
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Standard forecast horizons (months) for intervention comparison
HORIZONS: list[int] = [3, 6, 12]


@dataclass
class HorizonDelta:
    """Change in predicted value at a specific time horizon.

    Attributes:
        horizon_months: The time point being compared.
        baseline_value: Predicted value WITHOUT intervention.
        simulated_value: Predicted value WITH intervention.
        absolute_delta: simulated - baseline (negative = improvement for risk).
        relative_delta_pct: Percentage change from baseline.
    """

    horizon_months: int
    baseline_value: float
    simulated_value: float
    absolute_delta: float
    relative_delta_pct: float


@dataclass
class SimulationResult:
    """Complete result of an intervention simulation.

    Contains baseline vs. simulated comparison at each standard horizon,
    along with metadata about the intervention applied.
    """

    intervention_type: str
    parameters: dict[str, Any] = field(default_factory=dict)
    deltas: list[HorizonDelta] = field(default_factory=list)
    summary: str = ""

    def __repr__(self) -> str:
        """Human-readable simulation summary."""
        lines = [f"SimulationResult: {self.intervention_type}"]
        lines.append(f"  Parameters: {self.parameters}")
        for d in self.deltas:
            direction = "improvement" if d.absolute_delta < 0 else "worsening"
            lines.append(
                f"  {d.horizon_months}m: {d.baseline_value:.1f} -> "
                f"{d.simulated_value:.1f} ({d.absolute_delta:+.1f}, "
                f"{d.relative_delta_pct:+.1f}% {direction})"
            )
        if self.summary:
            lines.append(f"  Summary: {self.summary}")
        return "\n".join(lines)


# Intervention effect modifiers — how each intervention changes patient features.
# These are evidence-based estimates from clinical literature.
_INTERVENTION_EFFECTS: dict[str, dict[str, Any]] = {
    "weight_loss": {
        # Per 1 kg lost: systolic BP drops ~1 mmHg, BMI recalculated
        "systolic_bp_per_kg": -1.0,
        "bmi_per_kg": -0.33,  # Approximate for average height
    },
    "smoking_cessation": {
        # Immediate: remove smoking flag; gradual: BP drops 5-10 mmHg over months
        "systolic_bp_reduction": -8.0,
        "remove_smoking_flag": True,
    },
    "medication_addition": {
        # Antihypertensive: typically drops systolic 10-15 mmHg
        "systolic_bp_reduction": -12.0,
    },
    "exercise_increase": {
        # Regular exercise: systolic BP -5 to -8 mmHg, BMI reduction over time
        "systolic_bp_reduction": -6.0,
        "bmi_reduction": -0.5,
    },
}


class InterventionSimulator:
    """Simulates the effect of health interventions on patient trajectories.

    Takes patient features, applies an intervention's expected physiological
    effects, re-runs the forecast engine, and returns the delta between
    baseline (no intervention) and simulated (with intervention) trajectories.
    """

    def simulate(
        self,
        patient_features: dict[str, Any],
        measurements: list[dict],
        intervention_type: str,
        parameters: dict[str, Any],
        forecast_engine: Any,
    ) -> SimulationResult:
        """Run counterfactual simulation for a given intervention.

        Args:
            patient_features: Current patient feature set.
            measurements: Historical measurement time series.
            intervention_type: One of weight_loss, smoking_cessation,
                medication_addition, exercise_increase.
            parameters: Intervention-specific params (e.g., target_weight_kg).
            forecast_engine: The ForecastOrchestrator instance for re-prediction.

        Returns:
            SimulationResult with baseline vs. simulated deltas at each horizon.
        """
        if intervention_type not in _INTERVENTION_EFFECTS:
            logger.warning("Unknown intervention type: %s", intervention_type)
            return SimulationResult(
                intervention_type=intervention_type,
                parameters=parameters,
                summary=f"Unknown intervention: {intervention_type}",
            )

        # Modify patient features according to intervention effects
        modified_features = self._apply_intervention(
            patient_features, intervention_type, parameters
        )

        # Also adjust measurements to reflect intervention's immediate impact
        # on the target metric (counterfactual: "what if BP was already lower?")
        modified_measurements = self._adjust_measurements(
            measurements, patient_features, modified_features
        )

        # Run forecast for both baseline and simulated scenarios
        deltas: list[HorizonDelta] = []
        targets = ["systolic_bp"]  # Primary target for comparison

        baseline_result = forecast_engine.predict(
            patient_features=patient_features,
            measurements=measurements,
            targets=targets,
        )
        simulated_result = forecast_engine.predict(
            patient_features=modified_features,
            measurements=modified_measurements,
            targets=targets,
        )

        # Compare at each horizon
        for target in targets:
            baseline_forecasts = baseline_result.forecasts.get(target, {})
            simulated_forecasts = simulated_result.forecasts.get(target, {})

            for horizon in HORIZONS:
                b_val = baseline_forecasts.get(horizon, 0.0)
                s_val = simulated_forecasts.get(horizon, 0.0)
                abs_delta = s_val - b_val
                rel_delta = (abs_delta / b_val * 100.0) if b_val != 0 else 0.0

                deltas.append(HorizonDelta(
                    horizon_months=horizon,
                    baseline_value=round(b_val, 2),
                    simulated_value=round(s_val, 2),
                    absolute_delta=round(abs_delta, 2),
                    relative_delta_pct=round(rel_delta, 1),
                ))

        return SimulationResult(
            intervention_type=intervention_type,
            parameters=parameters,
            deltas=deltas,
            summary=f"Simulated {intervention_type} effect over {HORIZONS[-1]} months",
        )

    def _adjust_measurements(
        self,
        measurements: list[dict],
        original_features: dict[str, Any],
        modified_features: dict[str, Any],
    ) -> list[dict]:
        """Adjust measurement values to reflect intervention effects.

        Applies the same delta (modified - original) to measurement values
        so the forecasters see the counterfactual time series.
        """
        # Compute BP delta from feature modification
        original_bp = original_features.get("systolic_bp", 0)
        modified_bp = modified_features.get("systolic_bp", 0)
        bp_delta = modified_bp - original_bp

        adjusted = []
        for m in measurements:
            entry = m.copy()
            if m.get("type") == "systolic_bp" and bp_delta != 0:
                entry["value"] = m["value"] + bp_delta
            adjusted.append(entry)
        return adjusted

    def _apply_intervention(
        self,
        features: dict[str, Any],
        intervention_type: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Modify patient features according to intervention effects.

        Returns a COPY of features with intervention-specific modifications.
        Original features dict is never mutated (functional approach).
        """
        modified = features.copy()
        effects = _INTERVENTION_EFFECTS[intervention_type]

        if intervention_type == "weight_loss":
            current_weight = features.get("weight_kg", 80.0)
            target_weight = parameters.get("target_weight_kg", current_weight - 5)
            kg_lost = current_weight - target_weight
            # Apply BP reduction proportional to weight loss
            bp_change = effects["systolic_bp_per_kg"] * kg_lost
            modified["systolic_bp"] = features.get("systolic_bp", 130) + bp_change
            modified["weight_kg"] = target_weight
            modified["bmi"] = features.get("bmi", 28.0) + effects["bmi_per_kg"] * kg_lost

        elif intervention_type == "smoking_cessation":
            modified["systolic_bp"] = (
                features.get("systolic_bp", 130) + effects["systolic_bp_reduction"]
            )
            modified["smoking"] = 0

        elif intervention_type == "medication_addition":
            modified["systolic_bp"] = (
                features.get("systolic_bp", 130) + effects["systolic_bp_reduction"]
            )

        elif intervention_type == "exercise_increase":
            modified["systolic_bp"] = (
                features.get("systolic_bp", 130) + effects["systolic_bp_reduction"]
            )
            modified["bmi"] = features.get("bmi", 28.0) + effects["bmi_reduction"]

        return modified
