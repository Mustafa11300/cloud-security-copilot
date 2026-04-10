"""
LANGGRAPH KERNEL — STATE MACHINE ORCHESTRATOR
===============================================
Phase 2 Module 4 — Cognitive Cloud OS

Core state machine managing the "Kernel-Level" diplomacy and
2-round negotiation limit for drift remediation.

Architecture:
  SentryNode → [Sentry Agent] → [Consultant Agent?] → [Decision Logic] → [Remediation]
                    ↑                                         ↓
                    └─── Self-Correction Loop (on Rollback) ──┘

Key Features:
  1. SwarmState Schema: Tracks drift_details, round_counter, proposals, final_decision
  2. 2-Round Cap: Force transition to DecisionLogic after 2 rounds
  3. Asymmetric Wake: Consultant only entered for non-cached drifts
  4. Self-Correction Loop: On rollback, re-route to Remediation with traceback

Design Decisions:
  - LangGraph is OPTIONAL — falls back to procedural state machine
  - State transitions are fully auditable (every step logged)
  - Implements NRL (Negotiable Reinforcement Learning) via round cap
  - All proposals are structured JSON for deterministic parsing

Academic References:
  - NRL Framework: Negotiable Reinforcement Learning
  - State Machines: Harel (1987) — Statecharts
  - Multi-Agent Systems: Wooldridge (2009) — Introduction to MAS
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from cloudguard.agents.sentry_node import PolicyViolation, SentryNode
from cloudguard.agents.swarm import (
    ConsultantPersona,
    KernelMemory,
    SentryPersona,
    create_swarm_personas,
)
from cloudguard.core.decision_logic import ActiveEditor, DecisionStatus, SynthesisResult
from cloudguard.core.schemas import AgentProposal, EnvironmentWeights
from cloudguard.core.swarm import NegotiationRound, NegotiationStatus, SwarmState
from cloudguard.infra.memory_service import (
    HeuristicProposal,
    MemoryService,
    VictorySummary,
)

logger = logging.getLogger("cloudguard.kernel")

# ── Optional LangGraph import ────────────────────────────────────────────────
try:
    from langgraph.graph import StateGraph, END

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    logger.info("LangGraph not available — using procedural state machine")


# ═══════════════════════════════════════════════════════════════════════════════
# STATE SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════


class KernelPhase(str, Enum):
    """Phases of the kernel state machine."""
    IDLE = "idle"
    TRIAGE = "triage"                    # SentryNode processing
    HEURISTIC_CHECK = "heuristic_check"  # H-MEM pre-check
    SENTRY_PROPOSE = "sentry_propose"    # CISO proposes
    CONSULTANT_PROPOSE = "consultant"    # Controller proposes
    DECISION = "decision"                # ActiveEditor synthesis
    REMEDIATION = "remediation"          # Apply fix
    SELF_CORRECTION = "self_correction"  # Rollback check
    COMPLETED = "completed"              # Done
    FAILED = "failed"                    # Error state


@dataclass
class KernelState:
    """
    Complete state for the LangGraph Kernel.
    Extends SwarmState with kernel-level orchestration fields.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    kernel_id: str = field(
        default_factory=lambda: f"kernel-{uuid.uuid4().hex[:8]}"
    )
    phase: KernelPhase = KernelPhase.IDLE

    # ── Drift Details ─────────────────────────────────────────────────────────
    drift_details: Optional[dict[str, Any]] = None
    policy_violation: Optional[PolicyViolation] = None

    # ── Negotiation ───────────────────────────────────────────────────────────
    round_counter: int = 0
    max_rounds: int = 2  # 2-Round Cap (NRL Framework)
    sentry_proposal: Optional[AgentProposal] = None
    consultant_proposal: Optional[AgentProposal] = None
    final_decision: Optional[SynthesisResult] = None

    # ── H-MEM ─────────────────────────────────────────────────────────────────
    heuristic_proposal: Optional[HeuristicProposal] = None
    heuristic_bypassed: bool = False

    # ── Remediation ───────────────────────────────────────────────────────────
    remediation_result: Optional[dict[str, Any]] = None
    remediation_success: bool = False
    rollback_attempted: bool = False
    retry_count: int = 0
    max_retries: int = 1  # One retry on rollback

    # ── J-Score Tracking ──────────────────────────────────────────────────────
    j_before: float = 0.0
    j_after: float = 0.0
    j_improvement: float = 0.0

    # ── Weights ───────────────────────────────────────────────────────────────
    w_risk: float = 0.6
    w_cost: float = 0.4
    environment: str = "production"
    resource_tags: dict[str, str] = field(default_factory=dict)
    resource_context: dict[str, Any] = field(default_factory=dict)

    # ── Timestamps & Audit ────────────────────────────────────────────────────
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    phase_history: list[dict[str, Any]] = field(default_factory=list)
    error_traceback: str = ""

    # ── Token Budget ──────────────────────────────────────────────────────────
    token_budget: int = 10000
    tokens_consumed: int = 0

    def transition_to(self, new_phase: KernelPhase) -> None:
        """Record a phase transition in the audit trail."""
        self.phase_history.append({
            "from": self.phase.value,
            "to": new_phase.value,
            "round": self.round_counter,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.phase = new_phase
        logger.debug(f"⚙️ Kernel phase: {new_phase.value}")

    def consume_tokens(self, count: int) -> bool:
        """Track token consumption against budget."""
        self.tokens_consumed += count
        if self.tokens_consumed >= self.token_budget:
            logger.warning(
                f"🚫 Token budget exceeded: "
                f"{self.tokens_consumed}/{self.token_budget}"
            )
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Serialize kernel state for logging/API."""
        return {
            "kernel_id": self.kernel_id,
            "phase": self.phase.value,
            "round_counter": self.round_counter,
            "max_rounds": self.max_rounds,
            "j_before": self.j_before,
            "j_after": self.j_after,
            "j_improvement": self.j_improvement,
            "heuristic_bypassed": self.heuristic_bypassed,
            "remediation_success": self.remediation_success,
            "rollback_attempted": self.rollback_attempted,
            "tokens_consumed": self.tokens_consumed,
            "phase_history": self.phase_history,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "final_decision": self.final_decision.to_dict() if self.final_decision else None,
            "error_traceback": self.error_traceback,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# KERNEL ORCHESTRATOR (Procedural State Machine)
# ═══════════════════════════════════════════════════════════════════════════════


class KernelOrchestrator:
    """
    LangGraph-compatible state machine orchestrator for CloudGuard-B.

    Manages the full drift remediation lifecycle:
      1. Receive PolicyViolation from SentryNode
      2. Check H-MEM for heuristic bypass
      3. Run 2-round adversarial negotiation (CISO vs Controller)
      4. Synthesize final decision via ActiveEditor
      5. Apply remediation
      6. Self-correction: rollback if J worsens

    Falls back to procedural execution if LangGraph is not installed.

    Usage:
        orchestrator = KernelOrchestrator(
            memory_service=mem,
            sentry_persona=ciso,
            consultant_persona=controller,
        )

        result = await orchestrator.process_violation(violation)
    """

    def __init__(
        self,
        memory_service: Optional[MemoryService] = None,
        sentry_persona: Optional[SentryPersona] = None,
        consultant_persona: Optional[ConsultantPersona] = None,
        kernel_memory: Optional[KernelMemory] = None,
        active_editor: Optional[ActiveEditor] = None,
        remediation_callback: Optional[Callable] = None,
        j_score_calculator: Optional[Callable] = None,
    ) -> None:
        self._memory = memory_service or MemoryService()
        self._memory.initialize()

        # Create default personas if not provided
        if sentry_persona is None or consultant_persona is None:
            s, c, km = create_swarm_personas()
            self._sentry = sentry_persona or s
            self._consultant = consultant_persona or c
            self._kernel_memory = kernel_memory or km
        else:
            self._sentry = sentry_persona
            self._consultant = consultant_persona
            self._kernel_memory = kernel_memory or KernelMemory()

        self._editor = active_editor or ActiveEditor()
        self._remediation_callback = remediation_callback
        self._j_calculator = j_score_calculator

        # Stats
        self._processed_count = 0
        self._heuristic_bypass_count = 0
        self._rollback_count = 0
        self._history: list[KernelState] = []

    # ─── Main Entry Point ─────────────────────────────────────────────────────

    async def process_violation(
        self,
        violation: PolicyViolation,
        current_j: float = 0.5,
        resource_context: Optional[dict[str, Any]] = None,
        resource_tags: Optional[dict[str, str]] = None,
    ) -> KernelState:
        """
        Process a PolicyViolation through the full kernel pipeline.

        Pipeline:
          1. Initialize state
          2. Check heuristic bypass (H-MEM pre-check)
          3. If non-cached → Run 2-round negotiation
          4. Synthesize via ActiveEditor
          5. Apply remediation
          6. Self-correction check

        Args:
            violation: PolicyViolation from SentryNode.
            current_j: Current J-score.
            resource_context: Context about the affected resource.
            resource_tags: Resource tags for weight derivation.

        Returns:
            Final KernelState with complete audit trail.
        """
        state = KernelState(
            started_at=datetime.now(timezone.utc),
            j_before=current_j,
            policy_violation=violation,
            resource_context=resource_context or {},
            resource_tags=resource_tags or {},
        )

        # Derive weights
        w_r, w_c, env = self._editor.derive_weights(resource_tags)
        state.w_risk = w_r
        state.w_cost = w_c
        state.environment = env

        try:
            # Phase 1: Heuristic Check
            state = await self._heuristic_check(state, violation)

            if state.heuristic_bypassed:
                # H-MEM bypass — skip negotiation
                state = await self._apply_heuristic(state)
            else:
                # Phase 2–3: Negotiation Rounds
                state = await self._run_negotiation(state)

                # Phase 4: Decision
                state = await self._make_decision(state)

            # Phase 5: Remediation
            state = await self._apply_remediation(state)

            # Phase 6: Self-Correction
            state = await self._self_correction(state)

        except Exception as e:
            state.transition_to(KernelPhase.FAILED)
            state.error_traceback = str(e)
            logger.error(f"⚙️ Kernel error: {e}")

        # Finalize
        state.completed_at = datetime.now(timezone.utc)
        if state.phase != KernelPhase.FAILED:
            state.transition_to(KernelPhase.COMPLETED)

        self._processed_count += 1
        self._history.append(state)

        logger.info(
            f"⚙️ Kernel complete: {state.kernel_id} "
            f"({state.phase.value}, "
            f"J: {state.j_before:.4f} → {state.j_after:.4f})"
        )

        return state

    # ─── Pipeline Stages ──────────────────────────────────────────────────────

    async def _heuristic_check(
        self, state: KernelState, violation: PolicyViolation
    ) -> KernelState:
        """Check H-MEM for heuristic bypass opportunity."""
        state.transition_to(KernelPhase.HEURISTIC_CHECK)

        # Check if the Sentry already found a heuristic
        if violation.heuristic_available and violation.heuristic_proposal:
            proposal_data = violation.heuristic_proposal
            if proposal_data.get("can_bypass_round1", False):
                state.heuristic_bypassed = True
                state.heuristic_proposal = HeuristicProposal(
                    **{
                        k: v
                        for k, v in proposal_data.items()
                        if k in HeuristicProposal.__dataclass_fields__
                    }
                )
                self._heuristic_bypass_count += 1
                logger.info(
                    f"⚙️ H-MEM bypass: similarity="
                    f"{proposal_data.get('similarity_score', 0):.2%}"
                )
                return state

        # Query H-MEM directly
        for drift in violation.drift_events:
            proposal = self._memory.query_victory(
                drift_type=drift.drift_type,
                resource_type=state.resource_context.get("resource_type", ""),
            )
            if proposal and proposal.can_bypass_round1:
                state.heuristic_bypassed = True
                state.heuristic_proposal = proposal
                self._heuristic_bypass_count += 1
                logger.info(
                    f"⚙️ H-MEM bypass (direct): "
                    f"similarity={proposal.similarity_score:.2%}"
                )
                return state

        return state

    async def _apply_heuristic(self, state: KernelState) -> KernelState:
        """Apply heuristic proposal directly (bypass negotiation)."""
        hp = state.heuristic_proposal
        if hp is None:
            return state

        # Convert HeuristicProposal to SynthesisResult
        state.final_decision = SynthesisResult(
            status=DecisionStatus.HEURISTIC_APPLIED,
            winning_proposal={
                "proposal_id": hp.proposal_id,
                "agent_role": "heuristic_memory",
                "expected_risk_delta": hp.expected_risk_delta,
                "expected_cost_delta": hp.expected_cost_delta,
                "commands": [],
                "reasoning": hp.reasoning,
            },
            w_risk=state.w_risk,
            w_cost=state.w_cost,
            environment=state.environment,
            reasoning=f"H-MEM bypass applied: {hp.reasoning}",
            j_before=state.j_before,
        )

        return state

    async def _run_negotiation(self, state: KernelState) -> KernelState:
        """
        Run the 2-round adversarial negotiation.

        Asymmetric Wake:
          - CISO (Sentry) always proposes
          - Controller (Consultant) only proposes if drift is non-cached
        """
        # Set up kernel memory context
        if state.policy_violation:
            drift_events = [
                e.to_dict() for e in state.policy_violation.drift_events
            ]
            self._kernel_memory.set_sentry_findings(
                drift_events, state.resource_context
            )

        self._kernel_memory.current_j_score = state.j_before
        self._kernel_memory.environment_weights = EnvironmentWeights(
            w_risk=state.w_risk, w_cost=state.w_cost
        )

        # Create SwarmState for agents
        swarm_state = SwarmState(
            current_j_score=state.j_before,
            weights=EnvironmentWeights(
                w_risk=state.w_risk, w_cost=state.w_cost
            ),
        )

        for round_num in range(1, state.max_rounds + 1):
            state.round_counter = round_num
            self._kernel_memory.round_number = round_num

            # CISO proposes
            state.transition_to(KernelPhase.SENTRY_PROPOSE)
            state.sentry_proposal = self._sentry.propose(
                swarm_state, state.resource_context
            )

            if not state.consume_tokens(state.sentry_proposal.token_count):
                break

            # Controller proposes (asymmetric wake — only if non-cached)
            state.transition_to(KernelPhase.CONSULTANT_PROPOSE)

            # Share CISO findings with Controller via kernel memory
            self._kernel_memory.feedback_from_opponent = (
                state.sentry_proposal.reasoning
            )

            state.consultant_proposal = self._consultant.propose(
                swarm_state, state.resource_context
            )

            if not state.consume_tokens(state.consultant_proposal.token_count):
                break

            # Store proposals for multi-round context
            self._kernel_memory.previous_proposals.append({
                "round": round_num,
                "ciso": {
                    "risk_delta": state.sentry_proposal.expected_risk_delta,
                    "cost_delta": state.sentry_proposal.expected_cost_delta,
                },
                "controller": {
                    "risk_delta": state.consultant_proposal.expected_risk_delta,
                    "cost_delta": state.consultant_proposal.expected_cost_delta,
                },
            })

            logger.info(
                f"⚙️ Round {round_num}/{state.max_rounds}: "
                f"CISO(ΔR={state.sentry_proposal.expected_risk_delta:.2f}) "
                f"vs Controller(ΔC={state.consultant_proposal.expected_cost_delta:.2f})"
            )

        return state

    async def _make_decision(self, state: KernelState) -> KernelState:
        """Synthesize final decision via ActiveEditor."""
        state.transition_to(KernelPhase.DECISION)

        if state.sentry_proposal is None or state.consultant_proposal is None:
            logger.warning("⚙️ Missing proposals — cannot synthesize")
            return state

        # Convert proposals to dicts for ActiveEditor
        sec_dict = {
            "proposal_id": state.sentry_proposal.proposal_id,
            "agent_role": state.sentry_proposal.agent_role,
            "expected_risk_delta": state.sentry_proposal.expected_risk_delta,
            "expected_cost_delta": state.sentry_proposal.expected_cost_delta,
            "expected_j_delta": state.sentry_proposal.expected_j_delta,
            "commands": [
                cmd.model_dump() for cmd in state.sentry_proposal.commands
            ],
            "reasoning": state.sentry_proposal.reasoning,
            "token_count": state.sentry_proposal.token_count,
        }
        cost_dict = {
            "proposal_id": state.consultant_proposal.proposal_id,
            "agent_role": state.consultant_proposal.agent_role,
            "expected_risk_delta": state.consultant_proposal.expected_risk_delta,
            "expected_cost_delta": state.consultant_proposal.expected_cost_delta,
            "expected_j_delta": state.consultant_proposal.expected_j_delta,
            "commands": [
                cmd.model_dump() for cmd in state.consultant_proposal.commands
            ],
            "reasoning": state.consultant_proposal.reasoning,
            "token_count": state.consultant_proposal.token_count,
        }

        state.final_decision = self._editor.synthesize(
            security_proposal=sec_dict,
            cost_proposal=cost_dict,
            current_j=state.j_before,
            resource_tags=state.resource_tags,
            w_risk_override=state.w_risk,
            w_cost_override=state.w_cost,
        )

        logger.info(
            f"⚙️ Decision: {state.final_decision.status.value} "
            f"(ΔJ%={state.final_decision.j_improvement_pct:.2f}%)"
        )

        return state

    async def _apply_remediation(self, state: KernelState) -> KernelState:
        """Apply the final remediation decision."""
        state.transition_to(KernelPhase.REMEDIATION)

        if state.final_decision is None:
            logger.warning("⚙️ No decision to apply")
            return state

        # NO_ACTION — nothing to apply
        if state.final_decision.status == DecisionStatus.NO_ACTION:
            state.j_after = state.j_before
            state.remediation_success = True
            logger.info("⚙️ NO_ACTION — no remediation needed")
            return state

        # Apply via callback if available
        if self._remediation_callback:
            try:
                result = self._remediation_callback(
                    state.final_decision.to_dict()
                )
                if asyncio.iscoroutine(result):
                    result = await result
                state.remediation_result = result
                state.remediation_success = True
            except Exception as e:
                state.remediation_success = False
                state.error_traceback = f"Remediation failed: {e}"
                logger.error(f"⚙️ Remediation error: {e}")
        else:
            # Simulate success (no callback)
            state.remediation_success = True
            state.remediation_result = {"status": "simulated_success"}

        # Calculate new J score
        if self._j_calculator:
            state.j_after = self._j_calculator()
        else:
            # Estimate from decision
            state.j_after = state.final_decision.j_after

        state.j_improvement = state.j_before - state.j_after

        return state

    async def _self_correction(self, state: KernelState) -> KernelState:
        """
        Self-Correction Loop.

        If J worsened after remediation (j_after >= j_before),
        attempt one retry with the error traceback.
        """
        state.transition_to(KernelPhase.SELF_CORRECTION)

        # Check if J improved
        if state.j_after < state.j_before:
            # Fix worked — store victory in H-MEM
            await self._store_victory(state)
            return state

        # J didn't improve — self-correction needed
        if state.retry_count < state.max_retries and not state.rollback_attempted:
            state.rollback_attempted = True
            state.retry_count += 1
            self._rollback_count += 1

            logger.warning(
                f"⚙️ Self-correction: J worsened "
                f"({state.j_before:.4f} → {state.j_after:.4f}). "
                f"Retrying (attempt {state.retry_count}/{state.max_retries})"
            )

            # Re-run negotiation with error context
            state.resource_context["_rollback_error"] = state.error_traceback
            state.resource_context["_previous_j_after"] = state.j_after

            state = await self._run_negotiation(state)
            state = await self._make_decision(state)
            state = await self._apply_remediation(state)

            # Check again
            if state.j_after < state.j_before:
                await self._store_victory(state)
            else:
                logger.warning(
                    "⚙️ Self-correction failed — accepting current state"
                )
        else:
            logger.info("⚙️ J unchanged or worsened, no retry available")

        return state

    async def _store_victory(self, state: KernelState) -> None:
        """Store successful remediation in H-MEM."""
        if state.policy_violation and state.policy_violation.drift_events:
            drift = state.policy_violation.drift_events[0]
            victory = VictorySummary(
                drift_type=drift.drift_type,
                resource_type=state.resource_context.get("resource_type", ""),
                resource_id=drift.resource_id,
                remediation_action=(
                    state.final_decision.winning_proposal.get("commands", [{}])[0].get("action", "unknown")
                    if state.final_decision and state.final_decision.winning_proposal
                    and state.final_decision.winning_proposal.get("commands")
                    else "unknown"
                ),
                j_before=state.j_before,
                j_after=state.j_after,
                risk_delta=state.final_decision.security_score.risk_impact
                if state.final_decision and state.final_decision.security_score
                else 0.0,
                cost_delta=state.final_decision.cost_score.cost_impact
                if state.final_decision and state.final_decision.cost_score
                else 0.0,
                environment=state.environment,
                reasoning=state.final_decision.reasoning
                if state.final_decision
                else "",
            )
            self._memory.store_victory(victory)

    # ─── Stats & History ──────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get kernel orchestrator statistics."""
        return {
            "processed_violations": self._processed_count,
            "heuristic_bypasses": self._heuristic_bypass_count,
            "rollback_attempts": self._rollback_count,
            "memory_stats": self._memory.get_stats(),
            "editor_stats": self._editor.get_stats(),
        }

    def get_history(self) -> list[dict[str, Any]]:
        """Return processing history."""
        return [s.to_dict() for s in self._history]


# ═══════════════════════════════════════════════════════════════════════════════
# LANGGRAPH BUILDER (Optional)
# ═══════════════════════════════════════════════════════════════════════════════


def build_langgraph_kernel(
    orchestrator: KernelOrchestrator,
) -> Optional[Any]:
    """
    Build a LangGraph StateGraph if LangGraph is installed.

    This wraps the procedural KernelOrchestrator into a proper
    LangGraph graph with conditional edges and state management.

    Returns:
        Compiled LangGraph graph, or None if LangGraph is unavailable.
    """
    if not HAS_LANGGRAPH:
        logger.info("⚙️ LangGraph not available — using procedural kernel")
        return None

    # Define the LangGraph state as a TypedDict
    from typing import TypedDict

    class GraphState(TypedDict):
        kernel_state: KernelState
        violation: PolicyViolation
        current_j: float
        resource_context: dict
        resource_tags: dict

    # Node functions
    async def heuristic_node(state: GraphState) -> GraphState:
        ks = state["kernel_state"]
        ks = await orchestrator._heuristic_check(
            ks, state["violation"]
        )
        state["kernel_state"] = ks
        return state

    async def sentry_node(state: GraphState) -> GraphState:
        ks = state["kernel_state"]
        ks = await orchestrator._run_negotiation(ks)
        state["kernel_state"] = ks
        return state

    async def decision_node(state: GraphState) -> GraphState:
        ks = state["kernel_state"]
        ks = await orchestrator._make_decision(ks)
        state["kernel_state"] = ks
        return state

    async def remediation_node(state: GraphState) -> GraphState:
        ks = state["kernel_state"]
        ks = await orchestrator._apply_remediation(ks)
        state["kernel_state"] = ks
        return state

    async def correction_node(state: GraphState) -> GraphState:
        ks = state["kernel_state"]
        ks = await orchestrator._self_correction(ks)
        state["kernel_state"] = ks
        return state

    # Conditional edges
    def should_negotiate(state: GraphState) -> str:
        ks = state["kernel_state"]
        if ks.heuristic_bypassed:
            return "remediation"
        return "negotiation"

    def should_retry(state: GraphState) -> str:
        ks = state["kernel_state"]
        if ks.j_after >= ks.j_before and ks.retry_count < ks.max_retries:
            return "negotiation"
        return END

    # Build graph
    graph = StateGraph(GraphState)
    graph.add_node("heuristic", heuristic_node)
    graph.add_node("negotiation", sentry_node)
    graph.add_node("decision", decision_node)
    graph.add_node("remediation", remediation_node)
    graph.add_node("correction", correction_node)

    graph.set_entry_point("heuristic")
    graph.add_conditional_edges("heuristic", should_negotiate)
    graph.add_edge("negotiation", "decision")
    graph.add_edge("decision", "remediation")
    graph.add_edge("remediation", "correction")
    graph.add_conditional_edges("correction", should_retry)

    compiled = graph.compile()
    logger.info("⚙️ LangGraph kernel compiled successfully")
    return compiled
