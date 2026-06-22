"""
PrescpHealth ML Engine — Retrieval-Augmented Prediction (Patent Claim 4).

Core patent innovation: "patients like this one" — find historical patients
with similar measurement trajectories and use their OUTCOMES to augment
the current patient's feature set.

This is retrieval-augmented generation (RAG) applied to clinical prediction:
    1. Compute the current patient's trajectory (sequence of measurements over time)
    2. Find K most similar historical trajectories using Dynamic Time Warping (DTW)
    3. Extract outcome features from those similar patients
    4. Add those outcomes as additional input features to the expert models

Example: Patient has BP trajectory [140, 145, 155, 160] over 4 months.
    - DTW finds 5 similar trajectories in the database
    - 3 of those patients had a stroke within 6 months
    - Feature 'similar_patient_stroke_rate' = 0.6 is added to model input

This uses simplified DTW (no scipy dependency for the core algorithm).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _dtw_distance(seq_a: list[float], seq_b: list[float]) -> float:
    """Compute Dynamic Time Warping distance between two sequences.

    DTW finds the optimal alignment between two time series that may
    differ in speed (e.g., one patient's BP rose over 3 months, another
    over 6 months — DTW considers them similar).

    This is a simplified O(n*m) implementation suitable for short clinical
    sequences (typically < 100 measurements).

    Args:
        seq_a: First measurement sequence.
        seq_b: Second measurement sequence.

    Returns:
        DTW distance (lower = more similar).
    """
    n, m = len(seq_a), len(seq_b)
    if n == 0 or m == 0:
        return float("inf")

    # Dynamic programming matrix
    dtw_matrix = np.full((n + 1, m + 1), np.inf)
    dtw_matrix[0, 0] = 0.0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(seq_a[i - 1] - seq_b[j - 1])
            dtw_matrix[i, j] = cost + min(
                dtw_matrix[i - 1, j],      # insertion
                dtw_matrix[i, j - 1],      # deletion
                dtw_matrix[i - 1, j - 1],  # match
            )

    return float(dtw_matrix[n, m])


class TrajectoryRetriever:
    """Retrieval-Augmented Prediction using DTW-based trajectory matching.

    Finds historical patients with similar measurement patterns and uses
    their outcomes to enrich the current patient's feature set. This
    provides a "wisdom of similar cases" signal to the expert models.

    The trajectory database is populated incrementally as patients
    accumulate measurement histories and outcome labels.
    """

    def __init__(self) -> None:
        """Initialize with empty trajectory database."""
        # In-memory trajectory store: list of (trajectory, outcome_dict)
        # In production this would be backed by a vector database
        self._database: list[dict[str, Any]] = []

    def add_trajectory(
        self,
        patient_id: str,
        trajectory: list[dict[str, Any]],
        outcomes: dict[str, bool],
    ) -> None:
        """Add a patient's trajectory and outcomes to the retrieval database.

        Args:
            patient_id: Opaque patient identifier (UUID, no PHI).
            trajectory: List of measurement dicts with 'type', 'value', 'recorded_at'.
            outcomes: Dict of disease -> True/False (whether event occurred).
        """
        # Extract numeric sequence for DTW computation
        values = [float(m.get("value", 0.0)) for m in trajectory if m.get("value") is not None]
        self._database.append({
            "patient_id": patient_id,
            "values": values,
            "trajectory": trajectory,
            "outcomes": outcomes,
        })

    def find_similar(
        self, patient_trajectory: list[dict[str, Any]], k: int = 5
    ) -> list[dict[str, Any]]:
        """Find K most similar historical trajectories using DTW.

        Args:
            patient_trajectory: Current patient's measurement sequence.
            k: Number of similar trajectories to retrieve.

        Returns:
            List of K most similar trajectory records, each containing:
                - 'patient_id': opaque identifier
                - 'distance': DTW distance (lower = more similar)
                - 'outcomes': disease outcome dict
        """
        if not self._database:
            return []

        # Extract query sequence
        query_values = [
            float(m.get("value", 0.0))
            for m in patient_trajectory
            if m.get("value") is not None
        ]
        if not query_values:
            return []

        # Compute DTW distance to all stored trajectories
        distances: list[tuple[float, int]] = []
        for idx, record in enumerate(self._database):
            stored_values = record.get("values", [])
            if stored_values:
                dist = _dtw_distance(query_values, stored_values)
                distances.append((dist, idx))

        # Sort by distance and take top K
        distances.sort(key=lambda x: x[0])
        top_k = distances[:k]

        results: list[dict[str, Any]] = []
        for dist, idx in top_k:
            record = self._database[idx]
            results.append({
                "patient_id": record["patient_id"],
                "distance": round(dist, 4),
                "outcomes": record.get("outcomes", {}),
            })
        return results

    def augment_features(
        self, original: dict[str, float], retrieved_outcomes: list[dict[str, Any]]
    ) -> dict[str, float]:
        """Augment patient features with retrieval-based outcome statistics.

        Computes the empirical outcome rate among similar patients and adds
        it as additional features for the expert models.

        Args:
            original: Original patient feature dict.
            retrieved_outcomes: Output of find_similar() — list of similar records.

        Returns:
            Augmented feature dict with additional 'similar_*' features.
        """
        augmented = dict(original)

        if not retrieved_outcomes:
            # No similar patients found — add neutral features
            augmented["similar_patient_count"] = 0.0
            return augmented

        augmented["similar_patient_count"] = float(len(retrieved_outcomes))

        # Compute per-disease outcome rate among retrieved patients
        all_diseases: set[str] = set()
        for record in retrieved_outcomes:
            outcomes = record.get("outcomes", {})
            all_diseases.update(outcomes.keys())

        for disease in all_diseases:
            positive_count = sum(
                1 for r in retrieved_outcomes
                if r.get("outcomes", {}).get(disease, False)
            )
            rate = positive_count / len(retrieved_outcomes)
            # Feature name signals this came from retrieval (model can learn weight)
            augmented[f"similar_{disease}_rate"] = rate

        return augmented
