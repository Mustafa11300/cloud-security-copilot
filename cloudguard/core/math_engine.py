"""
GOVERNANCE & ROI MATH ENGINE
==============================
Subsystem 5 — Phase 1 Foundation

Implements the complete mathematical framework for CloudGuard-B:

1. Equilibrium Function J:
   J = min Σᵢ (w_R · Rᵢ + w_C · Cᵢ)
   Expressed as 0–100% Governed.

2. Economic Logic:
   - ROSI (Return on Security Investment)
   - ALE  (Annualized Loss Expectancy)
   - Time to Break-Even

3. Weighting Methods:
   - EWM  (Entropy Weight Method) — information-theoretic risk prioritization
   - CRITIC (Criteria Importance Through Intercriteria Correlation)
   Both use NetworkX dependency graph centrality.

Academic References:
  - Multi-Objective Optimization: Deb et al. (2002) NSGA-II
  - EWM: Shannon Entropy Weighting (Shannon, 1948)
  - CRITIC: Diakoulaki et al. (1995)
  - ROSI: Gordon & Loeb (2002) — Economics of Information Security
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ResourceRiskCost:
    """
    Per-resource risk and cost vector for J optimization.
    Each resource i contributes (R_i, C_i) to the equilibrium function.
    """
    resource_id: str
    risk_score: float          # R_i ∈ [0, 100]
    monthly_cost_usd: float    # C_i in USD
    normalized_risk: float = 0.0    # R_i normalized to [0, 1]
    normalized_cost: float = 0.0    # C_i normalized to [0, 1]
    centrality: float = 0.0        # NetworkX betweenness centrality


@dataclass
class ROSIResult:
    """Return on Security Investment calculation result."""
    ale_before: float          # ALE before remediation
    ale_after: float           # ALE after remediation
    remediation_cost: float    # Cost of remediation
    rosi: float                # ROSI = (ALE_before - ALE_after - cost) / cost
    time_to_breakeven_months: float  # Months until investment is recovered
    is_positive: bool          # Whether the investment has positive ROI


@dataclass
class JEquilibriumResult:
    """Result of the multi-objective equilibrium calculation."""
    j_score: float             # J value (lower = better governed)
    j_percentage: float        # J expressed as 0–100% Governed
    w_risk: float              # Risk weight used
    w_cost: float              # Cost weight used
    per_resource: list[dict] = field(default_factory=list)
    pareto_front: list[dict] = field(default_factory=list)


@dataclass
class EWMResult:
    """Entropy Weight Method result."""
    weights: dict[str, float]  # Criterion name → computed weight
    entropy_values: dict[str, float]
    divergence_values: dict[str, float]


@dataclass
class CRITICResult:
    """CRITIC weighting method result."""
    weights: dict[str, float]  # Criterion name → computed weight
    std_devs: dict[str, float]
    correlations: dict[str, float]
    information_content: dict[str, float]


# ═══════════════════════════════════════════════════════════════════════════════
# MATH ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class MathEngine:
    """
    Core mathematical engine for CloudGuard-B governance optimization.

    Implements multi-objective optimization, economic analysis, and
    dynamic risk weighting using entropy-based methods.

    Usage:
        engine = MathEngine()

        # Calculate equilibrium
        result = engine.calculate_j(resources, w_risk=0.6, w_cost=0.4)

        # Calculate ROSI for a single remediation
        rosi = engine.calculate_rosi(
            ale_before=50000, ale_after=5000, remediation_cost=10000
        )

        # Dynamic weighting via EWM
        weights = engine.calculate_ewm(criteria_matrix, criterion_names)
    """

    def __init__(self) -> None:
        """Initialize the MathEngine with optional NetworkX graph."""
        self._dependency_graph: Optional[nx.DiGraph] = None if not HAS_NETWORKX else nx.DiGraph()

    # ─── 1. Equilibrium Function J ────────────────────────────────────────────

    def calculate_j(
        self,
        resources: list[ResourceRiskCost],
        w_risk: float = 0.6,
        w_cost: float = 0.4,
    ) -> JEquilibriumResult:
        """
        Calculate the multi-objective equilibrium function:
          J = min Σᵢ (w_R · R̂ᵢ + w_C · Ĉᵢ)

        Where R̂ᵢ and Ĉᵢ are min-max normalized risk and cost values.

        Args:
            resources: List of per-resource risk and cost vectors.
            w_risk: Weight for risk objective (w_R).
            w_cost: Weight for cost objective (w_C).

        Returns:
            JEquilibriumResult with J score and per-resource breakdown.

        Interpretation:
            J=0.0 → perfectly governed (all risk and cost minimized)
            J=1.0 → worst governance (maximum risk and cost)
            J%   → (1 - J) * 100 expressed as "% Governed"
        """
        if abs(w_risk + w_cost - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0: w_R={w_risk}, w_C={w_cost}")

        if not resources:
            return JEquilibriumResult(
                j_score=0.0, j_percentage=100.0,
                w_risk=w_risk, w_cost=w_cost
            )

        # Min-max normalization
        risks = np.array([r.risk_score for r in resources])
        costs = np.array([r.monthly_cost_usd for r in resources])

        risk_min, risk_max = risks.min(), risks.max()
        cost_min, cost_max = costs.min(), costs.max()

        risk_range = risk_max - risk_min if risk_max > risk_min else 1.0
        cost_range = cost_max - cost_min if cost_max > cost_min else 1.0

        per_resource = []
        j_components = []

        for i, res in enumerate(resources):
            r_norm = (res.risk_score - risk_min) / risk_range
            c_norm = (res.monthly_cost_usd - cost_min) / cost_range

            res.normalized_risk = r_norm
            res.normalized_cost = c_norm

            j_i = w_risk * r_norm + w_cost * c_norm
            j_components.append(j_i)

            per_resource.append({
                "resource_id": res.resource_id,
                "risk_raw": res.risk_score,
                "cost_raw": res.monthly_cost_usd,
                "risk_norm": round(r_norm, 4),
                "cost_norm": round(c_norm, 4),
                "j_contribution": round(j_i, 4),
                "centrality": round(res.centrality, 4),
            })

        # J = mean of all per-resource contributions (normalized to [0, 1])
        j_score = float(np.mean(j_components))
        j_percentage = round((1.0 - j_score) * 100, 2)

        # Compute simple Pareto front (non-dominated solutions)
        pareto_front = self._compute_pareto_front(resources)

        return JEquilibriumResult(
            j_score=round(j_score, 6),
            j_percentage=j_percentage,
            w_risk=w_risk,
            w_cost=w_cost,
            per_resource=per_resource,
            pareto_front=pareto_front,
        )

    def _compute_pareto_front(
        self, resources: list[ResourceRiskCost]
    ) -> list[dict]:
        """
        Compute the Pareto front for the bi-objective (risk, cost) space.
        A resource is Pareto-optimal if no other resource dominates it
        on BOTH risk and cost simultaneously.
        """
        pareto = []
        for i, ri in enumerate(resources):
            dominated = False
            for j, rj in enumerate(resources):
                if i == j:
                    continue
                if (rj.normalized_risk <= ri.normalized_risk and
                    rj.normalized_cost <= ri.normalized_cost and
                    (rj.normalized_risk < ri.normalized_risk or
                     rj.normalized_cost < ri.normalized_cost)):
                    dominated = True
                    break
            if not dominated:
                pareto.append({
                    "resource_id": ri.resource_id,
                    "risk_norm": round(ri.normalized_risk, 4),
                    "cost_norm": round(ri.normalized_cost, 4),
                })
        return pareto

    # ─── Self-Correction Logic Gate ───────────────────────────────────────────

    def should_rollback(
        self, j_old: float, j_new: float
    ) -> bool:
        """
        Self-correction logic gate (Subsystem 4):
        If J_new ≥ J_old after a fix, the fix made things worse.
        Trigger automatic branch.rollback().

        Returns:
            True if rollback should be triggered (fix was harmful).
        """
        return j_new >= j_old

    # ─── 2. ROSI / ALE / Break-Even ──────────────────────────────────────────

    def calculate_rosi(
        self,
        ale_before: float,
        ale_after: float,
        remediation_cost: float,
    ) -> ROSIResult:
        """
        Calculate Return on Security Investment (ROSI).

        ROSI = (ALE_before - ALE_after - Remediation_Cost) / Remediation_Cost

        Based on Gordon & Loeb (2002) economic model for information security.

        Args:
            ale_before: Annualized Loss Expectancy before remediation.
            ale_after: Annualized Loss Expectancy after remediation.
            remediation_cost: One-time cost of remediation.

        Returns:
            ROSIResult with ROSI ratio and break-even analysis.
        """
        if remediation_cost <= 0:
            return ROSIResult(
                ale_before=ale_before,
                ale_after=ale_after,
                remediation_cost=0.0,
                rosi=float("inf") if ale_before > ale_after else 0.0,
                time_to_breakeven_months=0.0,
                is_positive=ale_before > ale_after,
            )

        risk_reduction = ale_before - ale_after
        rosi = (risk_reduction - remediation_cost) / remediation_cost

        # Time to break-even: months until cumulative savings exceed cost
        monthly_savings = risk_reduction / 12.0
        if monthly_savings > 0:
            breakeven_months = remediation_cost / monthly_savings
        else:
            breakeven_months = float("inf")

        return ROSIResult(
            ale_before=ale_before,
            ale_after=ale_after,
            remediation_cost=remediation_cost,
            rosi=round(rosi, 4),
            time_to_breakeven_months=round(breakeven_months, 2),
            is_positive=rosi > 0,
        )

    def calculate_ale(
        self,
        asset_value: float,
        exposure_factor: float,
        annual_rate_of_occurrence: float,
    ) -> float:
        """
        Calculate Annualized Loss Expectancy.
          ALE = Asset_Value × Exposure_Factor × ARO

        Args:
            asset_value: Value of the asset in USD.
            exposure_factor: Fraction of asset lost per incident (0–1).
            annual_rate_of_occurrence: Expected incidents per year.

        Returns:
            ALE in USD.
        """
        sle = asset_value * exposure_factor  # Single Loss Expectancy
        ale = sle * annual_rate_of_occurrence
        return round(ale, 2)

    # ─── 3. Entropy Weight Method (EWM) ───────────────────────────────────────

    def calculate_ewm(
        self,
        criteria_matrix: np.ndarray,
        criterion_names: list[str],
    ) -> EWMResult:
        """
        Entropy Weight Method for dynamic criterion weighting.

        Based on Shannon Information Entropy (1948):
        Higher entropy → less discriminating → lower weight.
        Lower entropy → more discriminating → higher weight.

        Steps:
          1. Normalize the decision matrix (min-max)
          2. Compute probability matrix P_ij = x_ij / Σ x_ij
          3. Compute entropy E_j = -k Σ (P_ij · ln P_ij)
          4. Compute divergence D_j = 1 - E_j
          5. Compute weights W_j = D_j / Σ D_j

        Args:
            criteria_matrix: (n_resources × n_criteria) numpy array.
            criterion_names: Names for each criterion (column).

        Returns:
            EWMResult with per-criterion weights.
        """
        n, m = criteria_matrix.shape
        assert m == len(criterion_names), "Criterion names must match columns"

        # Step 1: Min-max normalization
        col_min = criteria_matrix.min(axis=0)
        col_max = criteria_matrix.max(axis=0)
        col_range = col_max - col_min
        col_range[col_range == 0] = 1.0  # Avoid division by zero

        normalized = (criteria_matrix - col_min) / col_range
        # Shift to avoid log(0)
        normalized = normalized + 1e-10

        # Step 2: Probability matrix
        col_sums = normalized.sum(axis=0)
        col_sums[col_sums == 0] = 1.0
        P = normalized / col_sums

        # Step 3: Entropy
        k = 1.0 / math.log(max(n, 2))  # Normalization constant
        entropy_vals = np.zeros(m)
        for j in range(m):
            entropy_vals[j] = -k * np.sum(P[:, j] * np.log(P[:, j] + 1e-15))

        # Step 4: Divergence
        divergence = 1.0 - entropy_vals

        # Step 5: Weights
        div_sum = divergence.sum()
        if div_sum == 0:
            weights_arr = np.ones(m) / m  # Equal weights fallback
        else:
            weights_arr = divergence / div_sum

        weights = {name: round(float(w), 6) for name, w in zip(criterion_names, weights_arr)}
        entropy_dict = {name: round(float(e), 6) for name, e in zip(criterion_names, entropy_vals)}
        divergence_dict = {name: round(float(d), 6) for name, d in zip(criterion_names, divergence)}

        return EWMResult(
            weights=weights,
            entropy_values=entropy_dict,
            divergence_values=divergence_dict,
        )

    # ─── 4. CRITIC Weighting ─────────────────────────────────────────────────

    def calculate_critic(
        self,
        criteria_matrix: np.ndarray,
        criterion_names: list[str],
    ) -> CRITICResult:
        """
        CRITIC (Criteria Importance Through Intercriteria Correlation).
        Diakoulaki et al. (1995).

        Combines standard deviation (contrast intensity) with
        inter-criteria correlation to determine objective weights.

        Steps:
          1. Normalize decision matrix
          2. Compute σ_j (standard deviation of each criterion)
          3. Compute correlation matrix R
          4. Compute information content:
             C_j = σ_j × Σ_k (1 - r_jk)
          5. Compute weights: W_j = C_j / Σ C_j

        Args:
            criteria_matrix: (n_resources × n_criteria) numpy array.
            criterion_names: Names for each criterion (column).

        Returns:
            CRITICResult with per-criterion weights.
        """
        n, m = criteria_matrix.shape
        assert m == len(criterion_names), "Criterion names must match columns"

        # Step 1: Normalize
        col_min = criteria_matrix.min(axis=0)
        col_max = criteria_matrix.max(axis=0)
        col_range = col_max - col_min
        col_range[col_range == 0] = 1.0
        normalized = (criteria_matrix - col_min) / col_range

        # Step 2: Standard deviations
        std_devs = normalized.std(axis=0, ddof=1)

        # Step 3: Correlation matrix
        if n > 1:
            corr_matrix = np.corrcoef(normalized.T)
            # Handle NaN from zero-variance columns
            corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)
        else:
            corr_matrix = np.eye(m)

        # Step 4: Information content
        info_content = np.zeros(m)
        for j in range(m):
            conflict = sum(1.0 - abs(corr_matrix[j, k]) for k in range(m))
            info_content[j] = std_devs[j] * conflict

        # Step 5: Weights
        info_sum = info_content.sum()
        if info_sum == 0:
            weights_arr = np.ones(m) / m
        else:
            weights_arr = info_content / info_sum

        weights = {name: round(float(w), 6) for name, w in zip(criterion_names, weights_arr)}
        std_dict = {name: round(float(s), 6) for name, s in zip(criterion_names, std_devs)}
        corr_dict = {name: round(float(corr_matrix[i, :].mean()), 6)
                     for i, name in enumerate(criterion_names)}
        info_dict = {name: round(float(c), 6) for name, c in zip(criterion_names, info_content)}

        return CRITICResult(
            weights=weights,
            std_devs=std_dict,
            correlations=corr_dict,
            information_content=info_dict,
        )

    # ─── 5. NetworkX Dependency Graph ─────────────────────────────────────────

    def build_dependency_graph(
        self,
        edges: list[tuple[str, str]],
    ) -> dict[str, float]:
        """
        Build a directed dependency graph from resource relationships
        and compute betweenness centrality for EWM/CRITIC weighting.

        High centrality = resource is a critical dependency hub →
        its risk should be weighted more heavily.

        Args:
            edges: List of (source_id, target_id) dependency tuples.

        Returns:
            Dict mapping resource_id → betweenness centrality score.
        """
        if not HAS_NETWORKX:
            # Fallback: equal centrality for all nodes
            nodes = set()
            for src, tgt in edges:
                nodes.add(src)
                nodes.add(tgt)
            return {n: 1.0 / max(len(nodes), 1) for n in nodes}

        self._dependency_graph = nx.DiGraph()
        self._dependency_graph.add_edges_from(edges)

        centrality = nx.betweenness_centrality(self._dependency_graph)
        return {k: round(v, 6) for k, v in centrality.items()}

    def get_graph_stats(self) -> dict:
        """Get dependency graph statistics."""
        if not HAS_NETWORKX or self._dependency_graph is None:
            return {"nodes": 0, "edges": 0, "connected": False}

        return {
            "nodes": self._dependency_graph.number_of_nodes(),
            "edges": self._dependency_graph.number_of_edges(),
            "connected": nx.is_weakly_connected(self._dependency_graph)
            if self._dependency_graph.number_of_nodes() > 0 else False,
            "density": round(nx.density(self._dependency_graph), 4),
        }

    # ─── 6. Composite Governance Score ────────────────────────────────────────

    def governance_percentage(self, j_score: float) -> float:
        """
        Convert J score to governance percentage.
          0% governed = J=1.0 (worst)
          100% governed = J=0.0 (best)
        """
        return round((1.0 - max(0.0, min(1.0, j_score))) * 100, 2)

    # ─── 7. Fuzzy Logic — Trapezoidal Membership Function ─────────────────────

    @staticmethod
    def trapezoidal_mf(x: float, a: float, b: float, c: float, d: float) -> float:
        """
        Trapezoidal Membership Function (TMF).

        Produces a membership degree µ ∈ [0, 1] for value x:
          µ = 0           if x ≤ a or x ≥ d
          µ = (x-a)/(b-a) if a < x < b  (rising edge)
          µ = 1           if b ≤ x ≤ c  (plateau)
          µ = (d-x)/(d-c) if c < x < d  (falling edge)

        Args:
            x: Input value to fuzzify
            a: Left foot (µ=0 boundary)
            b: Left shoulder (µ=1 start)
            c: Right shoulder (µ=1 end)
            d: Right foot (µ=0 boundary)

        Returns:
            Membership degree µ in [0, 1]
        """
        if x <= a or x >= d:
            return 0.0
        elif a < x < b:
            return (x - a) / (b - a) if (b - a) > 0 else 1.0
        elif b <= x <= c:
            return 1.0
        elif c < x < d:
            return (d - x) / (d - c) if (d - c) > 0 else 1.0
        return 0.0

    def fuzzy_risk_classification(self, risk_score: float) -> dict[str, float]:
        """
        Classify a risk score (0–100) into fuzzy risk categories using
        overlapping trapezoidal membership functions.

        Categories with their (a, b, c, d) parameters:
          LOW:      (0,  0,  15, 35)
          MEDIUM:   (20, 35, 50, 65)
          HIGH:     (50, 65, 75, 85)
          CRITICAL: (75, 85, 100, 100)

        Returns:
            Dict mapping category name → membership degree.
            Sum of memberships may exceed 1.0 due to overlapping regions.
        """
        return {
            "LOW":      self.trapezoidal_mf(risk_score, 0,  0,  15, 35),
            "MEDIUM":   self.trapezoidal_mf(risk_score, 20, 35, 50, 65),
            "HIGH":     self.trapezoidal_mf(risk_score, 50, 65, 75, 85),
            "CRITICAL": self.trapezoidal_mf(risk_score, 75, 85, 100, 100),
        }

    def defuzzify_centroid(self, memberships: dict[str, float]) -> float:
        """
        Defuzzify using centroid method.
        Maps each category to a representative value and computes
        the weighted average.

        Representative values:
          LOW=10, MEDIUM=42, HIGH=70, CRITICAL=90

        Returns:
            Defuzzified crisp risk score.
        """
        centroids = {"LOW": 10.0, "MEDIUM": 42.0, "HIGH": 70.0, "CRITICAL": 90.0}
        numerator = sum(memberships[k] * centroids[k] for k in memberships)
        denominator = sum(memberships.values())
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 4)

    # ─── 8. Combined EWM-CRITIC Weighting ─────────────────────────────────────

    def calculate_combined_weights(
        self,
        matrix: np.ndarray,
        criterion_names: list[str],
        alpha: float = 0.5,
    ) -> dict[str, Any]:
        """
        Combine EWM (entropy) and CRITIC (correlation) weights.

        The combined weight for each criterion j is:
          w_combined_j = α · w_ewm_j + (1-α) · w_critic_j

        Then normalized so Σ w_combined = 1.

        Args:
            matrix: (n_resources × n_criteria) performance matrix
            criterion_names: List of criterion labels
            alpha: Blending parameter (0.0 = pure CRITIC, 1.0 = pure EWM)

        Returns:
            Dict with combined_weights, ewm_weights, critic_weights, alpha.
        """
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha must be in [0,1], got {alpha}")

        ewm_result = self.calculate_ewm(matrix, criterion_names)
        critic_result = self.calculate_critic(matrix, criterion_names)

        combined = {}
        for name in criterion_names:
            w_e = ewm_result.weights.get(name, 0.0)
            w_c = critic_result.weights.get(name, 0.0)
            combined[name] = alpha * w_e + (1 - alpha) * w_c

        # Normalize
        total = sum(combined.values())
        if total > 0:
            combined = {k: round(v / total, 6) for k, v in combined.items()}

        return {
            "combined_weights": combined,
            "ewm_weights": ewm_result.weights,
            "critic_weights": critic_result.weights,
            "alpha": alpha,
        }
