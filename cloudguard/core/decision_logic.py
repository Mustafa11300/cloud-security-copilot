"""
ACTIVE EDITOR — PARETO SYNTHESIS & J-SCORE EQUILIBRIUM
========================================================
Phase 2 Module 5 — Cognitive Cloud OS

The "Active Editor" that resolves the J-score equilibrium between
competing Security (CISO) and Cost (Controller) proposals.

Implements:
  1. Pareto Optimization: Calculate J-score for competing proposals
  2. Weighting Context: Pull environment weights from resource tags
  3. 1% Floor: NO_ACTION if improvement < 1%
  4. Synthesis: Merge suboptimal proposals into a Pareto-optimal third option

Mathematical Framework:
  J = min Σ (w_R · R_i + w_C · C_i)
  Where w_R and w_C are environment-dependent weights:
    - Production: w_R=0.8, w_C=0.2
    - Development: w_R=0.3, w_C=0.7
    - Staging: w_R=0.5, w_C=0.5

Academic References:
  - Pareto Optimality: Deb et al. (2002) — NSGA-II
  - Multi-Objective Decision: Marler & Arora (2004) — Survey
  - NRL: Negotiable Reinforcement Learning framework
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("cloudguard.decision_logic")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMERATIONS
# ═══════════════════════════════════════════════════════════════════════════════


class DecisionStatus(str, Enum):
    """Outcome status of the Active Editor synthesis."""
    SECURITY_WINS = "security_wins"      # CISO proposal selected
    COST_WINS = "cost_wins"              # Controller proposal selected
    SYNTHESIZED = "synthesized"          # Merged Pareto-optimal proposal
    NO_ACTION = "no_action"              # Improvement < 1% floor
    HEURISTIC_APPLIED = "heuristic"      # H-MEM bypass applied
    ESCALATED = "human_escalation"       # Neither proposal is safe


class EnvironmentTier(str, Enum):
    """Environment classification for weight derivation."""
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════


# Environment-specific default weights
ENVIRONMENT_WEIGHTS: dict[EnvironmentTier, tuple[float, float]] = {
    EnvironmentTier.PRODUCTION: (0.8, 0.2),   # Security-first
    EnvironmentTier.STAGING: (0.5, 0.5),       # Balanced
    EnvironmentTier.DEVELOPMENT: (0.3, 0.7),   # Cost-first
}


@dataclass
class ProposalScore:
    """Scored version of a remediation proposal."""
    proposal_id: str = ""
    agent_role: str = ""
    j_score: float = 0.0
    j_improvement: float = 0.0          # Δ from current J
    j_improvement_pct: float = 0.0      # % improvement
    risk_impact: float = 0.0
    cost_impact: float = 0.0
    weighted_score: float = 0.0         # w_R * risk + w_C * cost
    is_pareto_optimal: bool = False
    raw_proposal: dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesisResult:
    """Result of the Active Editor synthesis."""
    decision_id: str = field(
        default_factory=lambda: f"dec-{uuid.uuid4().hex[:8]}"
    )
    status: DecisionStatus = DecisionStatus.NO_ACTION
    winning_proposal: Optional[dict[str, Any]] = None
    synthesized_proposal: Optional[dict[str, Any]] = None

    # ── Scoring ──────────────────────────────────────────────────────────────
    security_score: Optional[ProposalScore] = None
    cost_score: Optional[ProposalScore] = None
    synthesized_score: Optional[ProposalScore] = None

    # ── Weights Used ─────────────────────────────────────────────────────────
    w_risk: float = 0.6
    w_cost: float = 0.4
    environment: str = "production"

    # ── Audit Trail ──────────────────────────────────────────────────────────
    reasoning: str = ""
    j_before: float = 0.0
    j_after: float = 0.0
    j_improvement_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "status": self.status.value,
            "winning_proposal": self.winning_proposal,
            "synthesized_proposal": self.synthesized_proposal,
            "w_risk": self.w_risk,
            "w_cost": self.w_cost,
            "environment": self.environment,
            "reasoning": self.reasoning,
            "j_before": self.j_before,
            "j_after": self.j_after,
            "j_improvement_pct": self.j_improvement_pct,
            "security_score": {
                "j_score": self.security_score.j_score,
                "j_improvement_pct": self.security_score.j_improvement_pct,
                "weighted_score": self.security_score.weighted_score,
            } if self.security_score else None,
            "cost_score": {
                "j_score": self.cost_score.j_score,
                "j_improvement_pct": self.cost_score.j_improvement_pct,
                "weighted_score": self.cost_score.weighted_score,
            } if self.cost_score else None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ACTIVE EDITOR
# ═══════════════════════════════════════════════════════════════════════════════


class ActiveEditor:
    """
    The Active Editor resolves the J-score equilibrium between
    competing Security (CISO) and Cost (Controller) proposals.

    It implements Pareto-optimal synthesis:
      1. Score both proposals using J = min Σ (w_R · R_i + w_C · C_i)
      2. If neither improves J by > 1%, output NO_ACTION
      3. If both are suboptimal, MERGE them into a Pareto-optimal third
      4. Otherwise, select the winner with the best J-score

    Usage:
        editor = ActiveEditor()
        result = editor.synthesize(
            security_proposal={...},
            cost_proposal={...},
            current_j=0.45,
            resource_tags={"Environment": "production"},
        )
    """

    # 1% Floor — minimum J improvement to justify action
    IMPROVEMENT_FLOOR_PCT = 1.0

    def __init__(self) -> None:
        self._decisions: list[SynthesisResult] = []

    # ─── Weight Derivation ────────────────────────────────────────────────────

    @staticmethod
    def derive_weights(
        resource_tags: Optional[dict[str, str]] = None,
        default_w_risk: float = 0.6,
        default_w_cost: float = 0.4,
    ) -> tuple[float, float, str]:
        """
        Pull environment weights from resource tags.

        Tags checked (case-insensitive):
          - "Environment" / "env" / "Env"

        Args:
            resource_tags: Resource tags dict.
            default_w_risk: Fallback risk weight.
            default_w_cost: Fallback cost weight.

        Returns:
            (w_risk, w_cost, environment_name)
        """
        if not resource_tags:
            return default_w_risk, default_w_cost, "unknown"

        # Look for environment tag
        env_value = (
            resource_tags.get("Environment", "")
            or resource_tags.get("environment", "")
            or resource_tags.get("env", "")
            or resource_tags.get("Env", "")
        ).lower().strip()

        for tier in EnvironmentTier:
            if tier.value in env_value or env_value.startswith(tier.value[:3]):
                w_r, w_c = ENVIRONMENT_WEIGHTS[tier]
                return w_r, w_c, tier.value

        return default_w_risk, default_w_cost, env_value or "unknown"

    # ─── J-Score Calculation ──────────────────────────────────────────────────

    @staticmethod
    def calculate_proposal_j(
        proposal: dict[str, Any],
        current_j: float,
        w_risk: float,
        w_cost: float,
    ) -> ProposalScore:
        """
        Calculate the J-score for a single proposal.

        J_proposal = current_J + Δ where:
          Δ = w_R * risk_delta_normalized + w_C * cost_delta_normalized

        Args:
            proposal: Agent proposal dict with expected_risk_delta, expected_cost_delta.
            current_j: Current J-score before remediation.
            w_risk: Risk weight.
            w_cost: Cost weight.

        Returns:
            ProposalScore with calculated J-score and improvement metrics.
        """
        risk_delta = proposal.get("expected_risk_delta", 0.0)
        cost_delta = proposal.get("expected_cost_delta", 0.0)

        # Normalize deltas to [0, 1] range for J calculation
        # Risk: negative delta = improvement (risk reduced)
        # Cost: negative delta = savings (cost reduced)
        risk_impact = risk_delta / 100.0 if abs(risk_delta) > 0 else 0.0
        cost_impact = cost_delta / 1000.0 if abs(cost_delta) > 0 else 0.0

        # Weighted contribution
        weighted_delta = w_risk * risk_impact + w_cost * cost_impact
        j_new = max(0.0, min(1.0, current_j + weighted_delta))
        j_improvement = current_j - j_new

        # Calculate percentage improvement
        if current_j > 0:
            j_improvement_pct = (j_improvement / current_j) * 100.0
        else:
            j_improvement_pct = 0.0

        return ProposalScore(
            proposal_id=proposal.get("proposal_id", ""),
            agent_role=proposal.get("agent_role", ""),
            j_score=round(j_new, 6),
            j_improvement=round(j_improvement, 6),
            j_improvement_pct=round(j_improvement_pct, 2),
            risk_impact=risk_delta,
            cost_impact=cost_delta,
            weighted_score=round(weighted_delta, 6),
            raw_proposal=proposal,
        )

    # ─── Pareto Dominance Check ───────────────────────────────────────────────

    @staticmethod
    def is_pareto_dominant(
        a: ProposalScore, b: ProposalScore
    ) -> bool:
        """
        Check if proposal A Pareto-dominates proposal B.
        A dominates B if A is at least as good on all objectives
        and strictly better on at least one.
        """
        a_risk_better = a.risk_impact <= b.risk_impact
        a_cost_better = a.cost_impact <= b.cost_impact
        a_strictly_better = (
            a.risk_impact < b.risk_impact or a.cost_impact < b.cost_impact
        )
        return a_risk_better and a_cost_better and a_strictly_better

    # ─── Synthesis (Merge) ────────────────────────────────────────────────────

    @staticmethod
    def _merge_proposals(
        security: dict[str, Any],
        cost: dict[str, Any],
        w_risk: float,
        w_cost: float,
    ) -> dict[str, Any]:
        """
        Merge two suboptimal proposals into a Pareto-optimal third.

        Strategy:
          - Take the security fix action from CISO (security groups, encryption)
          - Take the cost optimization from Controller (spot instances, rightsizing)
          - Blend the expected deltas using the environment weights

        This creates a hybrid proposal that satisfies both objectives.
        """
        # Blend risk/cost deltas weighted by environment context
        blended_risk = (
            w_risk * security.get("expected_risk_delta", 0.0)
            + (1 - w_risk) * cost.get("expected_risk_delta", 0.0)
        )
        blended_cost = (
            w_cost * cost.get("expected_cost_delta", 0.0)
            + (1 - w_cost) * security.get("expected_cost_delta", 0.0)
        )

        # Merge commands: security-critical actions from CISO,
        # cost-optimization from Controller
        security_commands = security.get("commands", [])
        cost_commands = cost.get("commands", [])

        # Deduplicate by action type
        seen_actions = set()
        merged_commands = []
        for cmd in security_commands:
            action = cmd.get("action", "")
            if action not in seen_actions:
                seen_actions.add(action)
                merged_commands.append(cmd)
        for cmd in cost_commands:
            action = cmd.get("action", "")
            if action not in seen_actions:
                seen_actions.add(action)
                merged_commands.append(cmd)

        # Use the higher-tier from both proposals
        sec_tier = security.get("tier", "silver")
        cost_tier = cost.get("tier", "silver")
        tier_order = {"gold": 3, "silver": 2, "bronze": 1}
        final_tier = (
            sec_tier
            if tier_order.get(sec_tier, 0) >= tier_order.get(cost_tier, 0)
            else cost_tier
        )

        return {
            "proposal_id": f"synth-{uuid.uuid4().hex[:8]}",
            "agent_role": "active_editor",
            "commands": merged_commands,
            "expected_risk_delta": round(blended_risk, 4),
            "expected_cost_delta": round(blended_cost, 4),
            "expected_j_delta": round(
                w_risk * (blended_risk / 100.0) + w_cost * (blended_cost / 1000.0),
                6,
            ),
            "tier": final_tier,
            "reasoning": (
                f"Active Editor synthesis: merged CISO's security fix "
                f"({security.get('agent_role', 'ciso')}: "
                f"risk_Δ={security.get('expected_risk_delta', 0):.2f}) "
                f"with Controller's cost optimization "
                f"({cost.get('agent_role', 'controller')}: "
                f"cost_Δ=${cost.get('expected_cost_delta', 0):.2f}). "
                f"Blended: risk_Δ={blended_risk:.2f}, "
                f"cost_Δ=${blended_cost:.2f}."
            ),
            "token_count": (
                security.get("token_count", 0) + cost.get("token_count", 0)
            ),
        }

    # ─── Main Synthesis ───────────────────────────────────────────────────────

    def synthesize(
        self,
        security_proposal: dict[str, Any],
        cost_proposal: dict[str, Any],
        current_j: float,
        resource_tags: Optional[dict[str, str]] = None,
        w_risk_override: Optional[float] = None,
        w_cost_override: Optional[float] = None,
    ) -> SynthesisResult:
        """
        Main synthesis entry point.

        Takes two competing proposals (Security vs. Cost) and resolves
        the J-score equilibrium using Pareto optimization.

        Decision Logic:
          1. Derive weights from resource tags (Prod=0.8R, Dev=0.3R)
          2. Score both proposals
          3. If neither improves J by > 1%, return NO_ACTION
          4. If one dominates the other, select the winner
          5. If both are suboptimal, synthesize a third Pareto-optimal option

        Args:
            security_proposal: CISO agent proposal dict.
            cost_proposal: Controller agent proposal dict.
            current_j: Current J-score.
            resource_tags: Resource tags for weight derivation.
            w_risk_override: Override w_R (ignores tags).
            w_cost_override: Override w_C (ignores tags).

        Returns:
            SynthesisResult with the decision and audit trail.
        """
        result = SynthesisResult(j_before=current_j)

        # Step 1: Derive weights
        if w_risk_override is not None and w_cost_override is not None:
            w_r, w_c = w_risk_override, w_cost_override
            env_name = "override"
        else:
            w_r, w_c, env_name = self.derive_weights(resource_tags)

        result.w_risk = w_r
        result.w_cost = w_c
        result.environment = env_name

        # Step 2: Score both proposals
        sec_score = self.calculate_proposal_j(
            security_proposal, current_j, w_r, w_c
        )
        cost_score = self.calculate_proposal_j(
            cost_proposal, current_j, w_r, w_c
        )
        result.security_score = sec_score
        result.cost_score = cost_score

        # Step 3: 1% Floor check
        sec_improves = sec_score.j_improvement_pct > self.IMPROVEMENT_FLOOR_PCT
        cost_improves = cost_score.j_improvement_pct > self.IMPROVEMENT_FLOOR_PCT

        if not sec_improves and not cost_improves:
            result.status = DecisionStatus.NO_ACTION
            result.reasoning = (
                f"Neither proposal improves J by > {self.IMPROVEMENT_FLOOR_PCT}%. "
                f"Security: {sec_score.j_improvement_pct:.2f}%, "
                f"Cost: {cost_score.j_improvement_pct:.2f}%. "
                f"NO_ACTION — current governance is sufficient."
            )
            result.j_after = current_j
            result.j_improvement_pct = 0.0
            logger.info(f"⚖️ Decision: NO_ACTION (below 1% floor)")
            self._decisions.append(result)
            return result

        # Step 4: Check Pareto dominance
        sec_dominates = self.is_pareto_dominant(sec_score, cost_score)
        cost_dominates = self.is_pareto_dominant(cost_score, sec_score)

        if sec_dominates and sec_improves:
            result.status = DecisionStatus.SECURITY_WINS
            result.winning_proposal = security_proposal
            result.j_after = sec_score.j_score
            result.j_improvement_pct = sec_score.j_improvement_pct
            sec_score.is_pareto_optimal = True
            result.reasoning = (
                f"CISO proposal Pareto-dominates Controller. "
                f"J: {current_j:.4f} → {sec_score.j_score:.4f} "
                f"({sec_score.j_improvement_pct:.2f}% improvement). "
                f"Risk Δ={sec_score.risk_impact:.2f}, "
                f"Cost Δ=${sec_score.cost_impact:.2f}."
            )
            logger.info(
                f"⚖️ Decision: SECURITY_WINS "
                f"(J improvement: {sec_score.j_improvement_pct:.2f}%)"
            )

        elif cost_dominates and cost_improves:
            result.status = DecisionStatus.COST_WINS
            result.winning_proposal = cost_proposal
            result.j_after = cost_score.j_score
            result.j_improvement_pct = cost_score.j_improvement_pct
            cost_score.is_pareto_optimal = True
            result.reasoning = (
                f"Controller proposal Pareto-dominates CISO. "
                f"J: {current_j:.4f} → {cost_score.j_score:.4f} "
                f"({cost_score.j_improvement_pct:.2f}% improvement). "
                f"Risk Δ={cost_score.risk_impact:.2f}, "
                f"Cost Δ=${cost_score.cost_impact:.2f}."
            )
            logger.info(
                f"⚖️ Decision: COST_WINS "
                f"(J improvement: {cost_score.j_improvement_pct:.2f}%)"
            )

        else:
            # Step 5: Neither dominates — SYNTHESIZE a Pareto-optimal third
            merged = self._merge_proposals(
                security_proposal, cost_proposal, w_r, w_c
            )
            merged_score = self.calculate_proposal_j(
                merged, current_j, w_r, w_c
            )
            result.synthesized_score = merged_score

            # Check if synthesized is better than both originals
            if merged_score.j_improvement > max(
                sec_score.j_improvement, cost_score.j_improvement
            ):
                result.status = DecisionStatus.SYNTHESIZED
                result.synthesized_proposal = merged
                result.j_after = merged_score.j_score
                result.j_improvement_pct = merged_score.j_improvement_pct
                merged_score.is_pareto_optimal = True
                result.reasoning = (
                    f"Active Editor synthesized Pareto-optimal proposal. "
                    f"J: {current_j:.4f} → {merged_score.j_score:.4f} "
                    f"({merged_score.j_improvement_pct:.2f}% improvement). "
                    f"Merged CISO security fix with Controller cost optimization."
                )
                logger.info(
                    f"⚖️ Decision: SYNTHESIZED "
                    f"(J improvement: {merged_score.j_improvement_pct:.2f}%)"
                )
            else:
                # Synthesized isn't better — pick the better individual
                if sec_score.j_improvement >= cost_score.j_improvement:
                    result.status = DecisionStatus.SECURITY_WINS
                    result.winning_proposal = security_proposal
                    result.j_after = sec_score.j_score
                    result.j_improvement_pct = sec_score.j_improvement_pct
                    result.reasoning = (
                        f"No Pareto dominance; CISO has better J improvement. "
                        f"J: {current_j:.4f} → {sec_score.j_score:.4f}."
                    )
                else:
                    result.status = DecisionStatus.COST_WINS
                    result.winning_proposal = cost_proposal
                    result.j_after = cost_score.j_score
                    result.j_improvement_pct = cost_score.j_improvement_pct
                    result.reasoning = (
                        f"No Pareto dominance; Controller has better J improvement. "
                        f"J: {current_j:.4f} → {cost_score.j_score:.4f}."
                    )
                logger.info(
                    f"⚖️ Decision: {result.status.value} (synthesis not better)"
                )

        self._decisions.append(result)
        return result

    # ─── History & Stats ──────────────────────────────────────────────────────

    def get_decision_history(self) -> list[dict[str, Any]]:
        """Return all past decisions."""
        return [d.to_dict() for d in self._decisions]

    def get_stats(self) -> dict[str, Any]:
        """Get decision engine statistics."""
        total = len(self._decisions)
        if total == 0:
            return {"total_decisions": 0}

        status_counts = {}
        for d in self._decisions:
            s = d.status.value
            status_counts[s] = status_counts.get(s, 0) + 1

        avg_improvement = (
            sum(d.j_improvement_pct for d in self._decisions) / total
        )

        return {
            "total_decisions": total,
            "status_breakdown": status_counts,
            "avg_j_improvement_pct": round(avg_improvement, 2),
            "no_action_rate": round(
                status_counts.get("no_action", 0) / total * 100, 1
            ),
            "synthesis_rate": round(
                status_counts.get("synthesized", 0) / total * 100, 1
            ),
        }
