"""
PrescpHealth ML Engine — Bayesian Prior Transfer (Patent Claim 3).

Core patent innovation: the system works from DAY 1 with ZERO local patient data.
How? By starting with population-level priors (Beta distributions) derived from
published epidemiological data, then progressively updating them as local
patient outcomes are observed.

This is Bayesian inference in action:
    Prior: Beta(α, β) from published literature for target population
    Likelihood: observed patient outcomes (binary: event occurred or not)
    Posterior: Beta(α + successes, β + failures) — conjugate update

Example: For stroke risk in West African males aged 60-70:
    Prior: Beta(3, 97) — ~3% baseline from published data
    After observing 2 strokes in 50 local patients: Beta(5, 145) — updated
    This posterior becomes the new prior for the next batch of observations.

This enables deployment to new clinics/populations without cold-start failure.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Epidemiological priors per disease per population.
# Format: (alpha, beta) for Beta distribution — mean = α/(α+β)
# Sources: WHO Global Health Estimates, Lancet population studies.
# "general" is the fallback when specific population isn't available.
POPULATION_PRIORS: dict[str, dict[str, tuple[float, float]]] = {
    "stroke": {
        "general": (3.0, 97.0),           # ~3% annual incidence
        "west_african": (4.0, 96.0),      # Higher prevalence (hypertension burden)
        "east_african": (3.5, 96.5),
        "south_asian": (4.5, 95.5),       # Higher stroke rates
        "european": (2.5, 97.5),
    },
    "cvd": {
        "general": (8.0, 92.0),           # ~8% 10-year risk
        "west_african": (6.0, 94.0),      # Lower than European (younger population)
        "east_african": (5.5, 94.5),
        "south_asian": (10.0, 90.0),      # Higher CVD burden
        "european": (9.0, 91.0),
    },
    "diabetes": {
        "general": (9.0, 91.0),           # ~9% global prevalence
        "west_african": (5.0, 95.0),      # Lower but rising rapidly
        "east_african": (4.5, 95.5),
        "south_asian": (12.0, 88.0),      # Very high diabetes prevalence
        "european": (7.0, 93.0),
    },
    "ckd": {
        "general": (10.0, 90.0),          # ~10% global CKD prevalence
        "west_african": (14.0, 86.0),     # Higher (APOL1 genetic risk)
        "east_african": (12.0, 88.0),
        "south_asian": (11.0, 89.0),
        "european": (8.0, 92.0),
    },
    "hypertensive_crisis": {
        "general": (1.0, 99.0),           # ~1% annual incidence
        "west_african": (2.0, 98.0),      # Higher HTN burden
        "east_african": (1.5, 98.5),
        "south_asian": (1.5, 98.5),
        "european": (0.8, 99.2),
    },
    "copd": {
        "general": (5.0, 95.0),           # ~5% global prevalence
        "west_african": (3.0, 97.0),      # Lower smoking rates
        "east_african": (2.5, 97.5),
        "south_asian": (6.0, 94.0),       # Higher (biomass fuel exposure)
        "european": (7.0, 93.0),          # Historical smoking
    },
}


class PopulationTransfer:
    """Bayesian Prior Transfer for zero-shot deployment to new populations.

    Enables the risk engine to produce calibrated predictions from day 1
    by starting with epidemiological priors, then updating them incrementally
    as local outcome data becomes available.

    The priors are NOT the final predictions — they inform the meta-learner's
    clinical standard baseline when local ML models haven't been trained yet.
    """

    def __init__(self) -> None:
        """Initialize with published epidemiological priors."""
        # Working posteriors — start as priors, updated with local data
        self._posteriors: dict[str, dict[str, tuple[float, float]]] = {
            disease: dict(pops)
            for disease, pops in POPULATION_PRIORS.items()
        }

    def get_prior(self, disease: str, population: str = "general") -> tuple[float, float]:
        """Get the current Beta(α, β) prior/posterior for a disease-population pair.

        Args:
            disease: Target disease (e.g., 'stroke', 'diabetes').
            population: Population identifier (e.g., 'west_african', 'general').

        Returns:
            Tuple of (alpha, beta) parameters. Mean risk = alpha / (alpha + beta).
        """
        disease_priors = self._posteriors.get(disease, {})
        # Fall back to general if specific population not available
        return disease_priors.get(population, disease_priors.get("general", (5.0, 95.0)))

    def get_mean_risk(self, disease: str, population: str = "general") -> float:
        """Get the mean risk (expected probability) from the prior/posterior.

        Args:
            disease: Target disease.
            population: Population identifier.

        Returns:
            Mean risk probability in [0.0, 1.0].
        """
        alpha, beta = self.get_prior(disease, population)
        return alpha / (alpha + beta)

    def update_posterior(
        self, disease: str, outcomes: list[bool], population: str = "general"
    ) -> tuple[float, float]:
        """Incrementally update posterior with observed outcomes (conjugate update).

        Binary outcomes: True = event occurred (e.g., stroke happened),
                        False = event did not occur.

        Beta-Bernoulli conjugacy:
            posterior_α = prior_α + count(True)
            posterior_β = prior_β + count(False)

        Args:
            disease: Disease to update.
            outcomes: List of binary outcomes from local patient data.
            population: Population to update prior for.

        Returns:
            Updated (alpha, beta) posterior parameters.
        """
        alpha, beta = self.get_prior(disease, population)
        successes = sum(1 for o in outcomes if o)
        failures = len(outcomes) - successes

        new_alpha = alpha + successes
        new_beta = beta + failures

        # Store updated posterior
        if disease not in self._posteriors:
            self._posteriors[disease] = {}
        self._posteriors[disease][population] = (new_alpha, new_beta)

        logger.info(
            "Updated %s/%s posterior: Beta(%.1f, %.1f) → Beta(%.1f, %.1f)",
            disease, population, alpha, beta, new_alpha, new_beta,
        )
        return (new_alpha, new_beta)

    def get_confidence_interval(
        self, disease: str, population: str = "general", level: float = 0.95
    ) -> tuple[float, float]:
        """Compute credible interval for the risk estimate.

        Useful for reporting uncertainty to clinicians:
        "Stroke risk is 4.2% (95% CI: 2.1% - 6.8%)"

        Args:
            disease: Target disease.
            population: Population identifier.
            level: Credible interval level (default 95%).

        Returns:
            Tuple of (lower_bound, upper_bound) probabilities.
        """
        from scipy.stats import beta as beta_dist

        alpha, beta_param = self.get_prior(disease, population)
        tail = (1.0 - level) / 2.0
        lower = float(beta_dist.ppf(tail, alpha, beta_param))
        upper = float(beta_dist.ppf(1.0 - tail, alpha, beta_param))
        return (lower, upper)
