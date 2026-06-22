"""
PrescpHealth ML Engine — Disease Cascade Network (Layer 3, Patent Claim 1).

Core patent innovation: diseases don't exist in isolation. Hypertension cascades
into stroke risk. Diabetes cascades into CKD. This module implements a
Graph Neural Network (GNN) message-passing layer that propagates risk across
a disease-disease interaction graph.

Architecture:
    - Nodes: 6 diseases (stroke, cvd, diabetes, ckd, hypertensive_crisis, copd)
    - Edges: learned cascade weights initialized from clinical knowledge
    - Message passing: h_i^(l+1) = σ(W × h_i^(l) + Σ w_ji × h_j^(l))
    - Iatrogenic edges: medication data adds additional edge features
      (e.g., corticosteroids → diabetes, NSAIDs → CKD)

This uses pure numpy for matrix operations — no PyTorch Geometric dependency.
The graph is small (6 nodes, ~12 edges) so numpy is efficient enough.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Disease node ordering — consistent index mapping throughout the module
DISEASE_NODES: list[str] = [
    "stroke", "cvd", "diabetes", "ckd", "hypertensive_crisis", "copd"
]
DISEASE_INDEX: dict[str, int] = {d: i for i, d in enumerate(DISEASE_NODES)}
NUM_NODES: int = len(DISEASE_NODES)

# Clinical knowledge-initialized edge weights.
# Format: (source_disease, target_disease, initial_weight)
# Weight represents how much risk in source disease CASCADES into target.
# These are learned during training but initialized from clinical literature.
CLINICAL_EDGES: list[tuple[str, str, float]] = [
    ("hypertensive_crisis", "stroke", 0.35),   # Hypertension → stroke is well-established
    ("hypertensive_crisis", "cvd", 0.25),      # Hypertension → cardiovascular disease
    ("hypertensive_crisis", "ckd", 0.20),      # Hypertension damages kidneys
    ("diabetes", "ckd", 0.30),                 # Diabetic nephropathy is leading CKD cause
    ("diabetes", "cvd", 0.25),                 # Diabetes doubles CVD risk
    ("diabetes", "stroke", 0.15),              # Diabetes increases stroke risk
    ("ckd", "cvd", 0.20),                      # CKD patients have high CVD mortality
    ("cvd", "stroke", 0.20),                   # Heart disease → stroke (embolism)
    ("copd", "cvd", 0.15),                     # COPD-CVD comorbidity well documented
    ("stroke", "hypertensive_crisis", 0.10),   # Post-stroke BP instability
]

# Iatrogenic cascade edges — medications that CAUSE disease cascades.
# These are activated when specific medication classes are present in patient data.
IATROGENIC_EDGES: dict[str, list[tuple[str, float]]] = {
    # Corticosteroids increase diabetes risk (steroid-induced diabetes)
    "corticosteroids": [("diabetes", 0.20)],
    # NSAIDs damage kidneys — cascade into CKD
    "nsaids": [("ckd", 0.15)],
    # Beta-blockers can mask hypoglycemia — indirect diabetes risk
    "beta_blockers": [("diabetes", 0.05)],
    # Thiazide diuretics can elevate glucose
    "thiazide_diuretics": [("diabetes", 0.10)],
    # Antipsychotics cause metabolic syndrome
    "antipsychotics": [("diabetes", 0.15), ("cvd", 0.10)],
}


class CascadeNetwork:
    """Disease Cascade Network implementing GNN message passing.

    Takes raw expert risk scores (one per disease) and propagates risk
    through clinically-established disease-disease pathways. A high
    diabetes score will ELEVATE the CKD score because diabetes causes
    kidney damage — even if the CKD expert alone wouldn't flag the risk.

    This captures comorbidity interactions that single-disease models miss.
    """

    def __init__(self) -> None:
        """Initialize adjacency matrix and transformation weights."""
        # Adjacency matrix: adj[i][j] = weight of edge from node j to node i
        # (how much j's risk cascades INTO i)
        self._adjacency: np.ndarray = np.zeros((NUM_NODES, NUM_NODES), dtype=np.float64)
        # Self-transformation weight matrix (diagonal dominance ensures
        # a disease's own score remains the primary signal)
        self._self_weight: np.ndarray = np.eye(NUM_NODES, dtype=np.float64) * 0.7

        # Initialize edges from clinical knowledge
        for source, target, weight in CLINICAL_EDGES:
            src_idx = DISEASE_INDEX[source]
            tgt_idx = DISEASE_INDEX[target]
            self._adjacency[tgt_idx][src_idx] = weight

        # Number of message passing iterations (layers in the GNN)
        self._num_layers: int = 2

    def _apply_iatrogenic_edges(
        self, medications: list[str]
    ) -> np.ndarray:
        """Build iatrogenic adjacency adjustment from patient medications.

        When a patient is on corticosteroids, we add an edge that boosts
        diabetes risk from all contributing diseases. This models the
        drug-induced cascade effect.

        Args:
            medications: List of medication class identifiers for the patient.

        Returns:
            Adjustment matrix to add to the base adjacency during propagation.
        """
        adjustment = np.zeros((NUM_NODES, NUM_NODES), dtype=np.float64)
        for med_class in medications:
            edges = IATROGENIC_EDGES.get(med_class.lower(), [])
            for target_disease, boost in edges:
                tgt_idx = DISEASE_INDEX.get(target_disease)
                if tgt_idx is not None:
                    # Iatrogenic boost applied uniformly from all source nodes
                    # (the drug itself is the "source", not another disease)
                    adjustment[tgt_idx, :] += boost / NUM_NODES
        return adjustment

    def propagate(
        self,
        risk_scores: dict[str, float],
        medications: list[str] | None = None,
    ) -> dict[str, float]:
        """Run GNN message passing to propagate risk across diseases.

        Implements: h_i^(l+1) = sigmoid(W_self × h_i^(l) + Σ_j adj[i,j] × h_j^(l))

        The sigmoid activation ensures output stays in [0, 1] (valid probability).
        Multiple layers allow transitive cascades (A→B→C in 2 layers).

        Args:
            risk_scores: Raw expert predictions per disease, values in [0, 1].
            medications: Optional list of medication classes for iatrogenic edges.

        Returns:
            Cascade-adjusted risk scores per disease, values in [0, 1].
        """
        # Build node feature vector from input scores
        h = np.array(
            [risk_scores.get(d, 0.5) for d in DISEASE_NODES],
            dtype=np.float64,
        )

        # Compute effective adjacency (base + iatrogenic adjustments)
        adj = self._adjacency.copy()
        if medications:
            adj += self._apply_iatrogenic_edges(medications)

        # Message passing: iterate through GNN layers
        for _ in range(self._num_layers):
            # Self-transformation + neighbor aggregation
            self_contrib = self._self_weight @ h
            neighbor_contrib = adj @ h
            # Combine and apply sigmoid activation
            h_raw = self_contrib + neighbor_contrib
            h = 1.0 / (1.0 + np.exp(-self._logit_scale(h_raw)))

        # Convert back to dict, clipping to valid probability range
        return {
            disease: float(np.clip(h[i], 0.0, 1.0))
            for i, disease in enumerate(DISEASE_NODES)
        }

    @staticmethod
    def _logit_scale(probabilities: np.ndarray) -> np.ndarray:
        """Transform probabilities through logit for sigmoid activation.

        We need to go probability → logit → add messages → sigmoid → probability.
        This prevents double-squashing that would compress the output range.
        """
        # Clip to avoid log(0) or log(1) numerical issues
        clipped = np.clip(probabilities, 1e-7, 1.0 - 1e-7)
        return np.log(clipped / (1.0 - clipped))

    def update_weights(self, learned_adjacency: np.ndarray) -> None:
        """Update edge weights from trained values (post-training refinement).

        Args:
            learned_adjacency: 6x6 matrix of learned cascade weights.
        """
        if learned_adjacency.shape != (NUM_NODES, NUM_NODES):
            logger.warning("Invalid adjacency shape — expected (%d, %d)", NUM_NODES, NUM_NODES)
            return
        self._adjacency = learned_adjacency.copy()
        logger.info("Updated cascade network with learned edge weights")
