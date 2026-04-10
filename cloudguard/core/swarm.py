"""
DIALECTICAL SWARM HANDSHAKE — MEDIATED DIALOGUE
=================================================
Subsystem 6 — Phase 1 Foundation

Architecture for Mediated Conversation via an Orchestrator (LangGraph logic).

Personas:
  - CISO (Ollama/Llama 3): Focus on Zero-Trust, MTTR, Risk reduction
  - Controller (Gemini 1.5 Pro): Focus on Fiscal Efficiency and ROI
  - Orchestrator: The judge finding the Pareto Front

Decision #11: Global Token Budget with hard ceiling per drift event.
Decision #12: Mathematical Deltas in state (price/risk deltas only).
Decision #16: Zero-Shot → Default to "Alarm" (Security-First).

This module defines the interfaces and state schemas for Phase 2.
Actual LLM integration happens in Phase 2 (The Swarm).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from cloudguard.core.schemas import (
    AgentProposal,
    EnvironmentWeights,
    RemediationCommand,
)

logger = logging.getLogger("cloudguard.swarm")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMERATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class AgentRole(str, Enum):
    """Swarm agent roles."""
    CISO = "ciso"                    # Ollama/Llama 3 — Security focus
    CONTROLLER = "controller"        # Gemini 1.5 Pro — Cost/ROI focus
    ORCHESTRATOR = "orchestrator"    # Judge — Pareto Front finder


class NegotiationStatus(str, Enum):
    """Status of a dialectical negotiation round."""
    PENDING = "pending"
    PROPOSING = "proposing"
    DEBATING = "debating"
    CONSENSUS = "consensus"
    DEADLOCK = "deadlock"
    BUDGET_EXCEEDED = "budget_exceeded"
    HUMAN_ESCALATION = "human_escalation"


# ═══════════════════════════════════════════════════════════════════════════════
# STATE SCHEMA (Decision #12: Mathematical Deltas)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SwarmState:
    """
    State object for the dialectical swarm.
    Decision #12: Stores price/risk DELTAS only (not full transcripts).
    Full transcripts go to local audit log to keep LLM context focused.
    """

    negotiation_id: str = field(
        default_factory=lambda: f"neg-{uuid.uuid4().hex[:8]}"
    )
    drift_event_id: str = ""
    status: NegotiationStatus = NegotiationStatus.PENDING

    # ── Mathematical Deltas (Decision #12) ────────────────────────────────────
    current_j_score: float = 0.0
    target_j_score: float = 0.0
    risk_delta: float = 0.0          # Proposed risk change
    cost_delta: float = 0.0          # Proposed cost change (USD)
    j_delta: float = 0.0             # Proposed J score change

    # ── Weights ───────────────────────────────────────────────────────────────
    weights: EnvironmentWeights = field(
        default_factory=EnvironmentWeights
    )

    # ── Token Budget (Decision #11) ───────────────────────────────────────────
    token_budget: int = 10000        # Hard ceiling per drift event
    tokens_consumed: int = 0
    budget_exceeded: bool = False

    # ── Proposals ─────────────────────────────────────────────────────────────
    ciso_proposal: Optional[AgentProposal] = None
    controller_proposal: Optional[AgentProposal] = None
    selected_proposal: Optional[AgentProposal] = None

    # ── Negotiation History (deltas only, not transcripts) ────────────────────
    rounds: list[NegotiationRound] = field(default_factory=list)
    max_rounds: int = 5

    # ── Timestamps ────────────────────────────────────────────────────────────
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def consume_tokens(self, count: int) -> bool:
        """
        Consume tokens from the budget.
        Decision #11: Returns False and locks if budget exceeded.
        """
        self.tokens_consumed += count
        if self.tokens_consumed >= self.token_budget:
            self.budget_exceeded = True
            self.status = NegotiationStatus.BUDGET_EXCEEDED
            logger.warning(
                f"🚫 Token budget exceeded: {self.tokens_consumed}/{self.token_budget}"
            )
            return False
        return True


@dataclass
class NegotiationRound:
    """A single round of dialectical debate between agents."""
    round_number: int
    ciso_risk_delta: float = 0.0
    ciso_cost_delta: float = 0.0
    controller_risk_delta: float = 0.0
    controller_cost_delta: float = 0.0
    orchestrator_verdict: str = ""
    j_before: float = 0.0
    j_after: float = 0.0
    tokens_used: int = 0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT INTERFACES (Phase 2 will implement with LLMs)
# ═══════════════════════════════════════════════════════════════════════════════

class BaseSwarmAgent:
    """
    Abstract base for swarm agents.
    Phase 2 will implement with actual LLM calls (Ollama, Gemini).
    Phase 1 provides deterministic stub implementations for testing.
    """

    def __init__(self, role: AgentRole) -> None:
        self.role = role
        self.agent_id = f"{role.value}-{uuid.uuid4().hex[:6]}"

    def propose(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """
        Generate a remediation proposal based on the current state.
        Overridden by concrete agent implementations.
        """
        raise NotImplementedError(
            f"{self.role.value} agent must implement propose()"
        )


class CISOAgent(BaseSwarmAgent):
    """
    CISO Agent — Security-First Persona
    Ollama/Llama 3 in Phase 2.
    Focuses on: Zero-Trust, MTTR reduction, Risk minimization.
    Decision #16: Defaults to "Alarm" — security-first.
    """

    def __init__(self) -> None:
        super().__init__(AgentRole.CISO)

    def propose(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """
        CISO stub: proposes maximum risk reduction.
        In Phase 2, this calls Ollama/Llama 3.
        """
        # Security-first: reduce all risk, accept higher cost
        risk_reduction = resource_context.get("total_risk", 0) * 0.7
        cost_increase = resource_context.get("remediation_cost", 0)

        return AgentProposal(
            agent_role=self.role.value,
            expected_risk_delta=-risk_reduction,
            expected_cost_delta=cost_increase,
            expected_j_delta=-(risk_reduction * state.weights.w_risk),
            reasoning=(
                f"CISO recommends aggressive risk reduction (-{risk_reduction:.1f} risk). "
                f"Security-first posture per Zero-Trust principles. "
                f"Estimated remediation cost: ${cost_increase:.2f}."
            ),
            token_count=0,  # Stub — no LLM tokens used
        )


class ControllerAgent(BaseSwarmAgent):
    """
    Controller Agent — Fiscal Efficiency Persona
    Gemini 1.5 Pro in Phase 2.
    Focuses on: ROI optimization, cost minimization.
    """

    def __init__(self) -> None:
        super().__init__(AgentRole.CONTROLLER)

    def propose(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """
        Controller stub: proposes cost-efficient remediation.
        In Phase 2, this calls Gemini 1.5 Pro.
        """
        # Cost-first: accept moderate risk, minimize cost
        risk_reduction = resource_context.get("total_risk", 0) * 0.3
        cost_savings = resource_context.get("potential_savings", 0) * 0.5

        return AgentProposal(
            agent_role=self.role.value,
            expected_risk_delta=-risk_reduction,
            expected_cost_delta=-cost_savings,
            expected_j_delta=-(cost_savings * state.weights.w_cost),
            reasoning=(
                f"Controller recommends targeted remediation (-{risk_reduction:.1f} risk) "
                f"with ${cost_savings:.2f} cost savings via rightsizing and termination. "
                f"ROI-optimized approach with break-even within 3 months."
            ),
            token_count=0,
        )


class OrchestratorAgent(BaseSwarmAgent):
    """
    Orchestrator — The Pareto Front Judge
    Evaluates CISO and Controller proposals, finds the equilibrium.
    """

    def __init__(self) -> None:
        super().__init__(AgentRole.ORCHESTRATOR)

    def select_proposal(
        self,
        state: SwarmState,
        ciso_proposal: AgentProposal,
        controller_proposal: AgentProposal,
    ) -> AgentProposal:
        """
        Select the winning proposal by comparing J-score deltas.

        The Orchestrator picks the proposal that minimizes J
        (best trade-off between risk and cost on the Pareto Front).
        """
        # Compare J deltas — lower (more negative) is better
        ciso_j = ciso_proposal.expected_j_delta
        ctrl_j = controller_proposal.expected_j_delta

        if ciso_j <= ctrl_j:
            winner = ciso_proposal
            loser_role = "controller"
        else:
            winner = controller_proposal
            loser_role = "ciso"

        logger.info(
            f"🏛️ Orchestrator verdict: {winner.agent_role} wins "
            f"(J_delta={winner.expected_j_delta:.4f} vs {loser_role})"
        )
        return winner

    def negotiate(
        self,
        state: SwarmState,
        ciso: CISOAgent,
        controller: ControllerAgent,
        resource_context: dict[str, Any],
    ) -> SwarmState:
        """
        Run a full dialectical negotiation round.

        1. Both agents propose
        2. Orchestrator selects winner
        3. Record the round
        4. Check token budget
        """
        state.started_at = datetime.now(timezone.utc)
        state.status = NegotiationStatus.PROPOSING

        # Get proposals
        ciso_prop = ciso.propose(state, resource_context)
        ctrl_prop = controller.propose(state, resource_context)

        state.ciso_proposal = ciso_prop
        state.controller_proposal = ctrl_prop

        # Update token consumption
        total_tokens = ciso_prop.token_count + ctrl_prop.token_count
        if not state.consume_tokens(total_tokens):
            # Budget exceeded — lock and alert
            state.completed_at = datetime.now(timezone.utc)
            return state

        state.status = NegotiationStatus.DEBATING

        # Orchestrator selects
        winner = self.select_proposal(state, ciso_prop, ctrl_prop)
        state.selected_proposal = winner

        # Record the round
        round_record = NegotiationRound(
            round_number=len(state.rounds) + 1,
            ciso_risk_delta=ciso_prop.expected_risk_delta,
            ciso_cost_delta=ciso_prop.expected_cost_delta,
            controller_risk_delta=ctrl_prop.expected_risk_delta,
            controller_cost_delta=ctrl_prop.expected_cost_delta,
            orchestrator_verdict=f"{winner.agent_role} selected",
            j_before=state.current_j_score,
            j_after=state.current_j_score + winner.expected_j_delta,
            tokens_used=total_tokens,
        )
        state.rounds.append(round_record)

        state.status = NegotiationStatus.CONSENSUS
        state.completed_at = datetime.now(timezone.utc)

        logger.info(
            f"✅ Negotiation complete: {winner.agent_role} proposal selected "
            f"(J: {state.current_j_score:.4f} → {round_record.j_after:.4f})"
        )

        return state
