"""
SIMULATION ENGINE — MAIN ORCHESTRATOR
=======================================
Phase 1 Foundation — The Research-Valid Core

Wires together ALL Phase 1 subsystems into a running simulation:
  1. UniversalResource Schema (core/schemas.py)
  2. TemporalClock (core/clock.py)
  3. Redis EventBus (infra/redis_bus.py)
  4. StateBranchManager (infra/branch_manager.py)
  5. MathEngine (core/math_engine.py)
  6. Swarm Interfaces (core/swarm.py)
  7. Remediation Protocol (core/remediation.py)
  8. Telemetry Generator (simulation/telemetry.py)

The SimulationEngine is the single entry point for running experiments.
It manages the world state, processes drift events, coordinates agents,
and tracks MTTR/J-score metrics.

Usage:
    engine = SimulationEngine(seed=42)
    engine.initialize()

    # Run N ticks
    for _ in range(100):
        report = engine.step()

    # Get metrics
    print(engine.get_metrics())
"""

from __future__ import annotations

import logging
import random as stdlib_random
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from cloudguard.core.clock import ClockMode, TemporalClock, TickEvent
from cloudguard.core.math_engine import (
    JEquilibriumResult,
    MathEngine,
    ResourceRiskCost,
)
from cloudguard.core.remediation import (
    COMMAND_REGISTRY,
    BlockPublicAccess,
    FailedFixesLog,
    HealingCommand,
)
from cloudguard.core.schemas import (
    CloudProvider,
    DriftEvent,
    DriftType,
    EnvironmentWeights,
    RemediationTier,
    Severity,
    UniversalResource,
)
from cloudguard.core.swarm import (
    CISOAgent,
    ControllerAgent,
    OrchestratorAgent,
    SwarmState,
)
from cloudguard.infra.branch_manager import StateBranchManager
from cloudguard.infra.redis_bus import EventBus, EventPayload, SIEMLogEmulator
from cloudguard.simulation.telemetry import (
    TimeSeriesGenerator,
    WorldStateGenerator,
)

logger = logging.getLogger("cloudguard.engine")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class StepReport:
    """Report generated after each simulation step."""

    def __init__(self) -> None:
        self.tick: int = 0
        self.mode: ClockMode = ClockMode.STANDARD
        self.j_score: float = 0.0
        self.j_percentage: float = 0.0
        self.total_risk: float = 0.0
        self.total_cost: float = 0.0
        self.resource_count: int = 0
        self.compliant_count: int = 0
        self.non_compliant_count: int = 0
        self.drift_events: list[dict] = []
        self.remediations: list[dict] = []
        self.siem_logs: list[dict] = []
        self.is_heartbeat: bool = False
        self.mttr_current: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "mode": self.mode.value,
            "j_score": round(self.j_score, 4),
            "j_percentage": round(self.j_percentage, 2),
            "total_risk": round(self.total_risk, 2),
            "total_cost_usd": round(self.total_cost, 2),
            "resource_count": self.resource_count,
            "compliant": self.compliant_count,
            "non_compliant": self.non_compliant_count,
            "drift_events": len(self.drift_events),
            "remediations": len(self.remediations),
            "siem_logs": len(self.siem_logs),
            "is_heartbeat": self.is_heartbeat,
            "mttr_current": self.mttr_current,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class SimulationEngine:
    """
    Main simulation orchestrator.

    Coordinates all Phase 1 subsystems to run a complete
    cloud governance simulation:
      - Generates world state with 40% wasteful baseline
      - Runs temporal clock (standard + burst mode)
      - Injects drift events
      - Calculates J equilibrium
      - Triggers agent debate (swarm)
      - Executes remediations (command pattern)
      - Tracks MTTR against 6.9-minute benchmark
      - Manages branch state for A/B testing

    Usage:
        engine = SimulationEngine(seed=42)
        engine.initialize()

        # Step through the simulation
        for i in range(100):
            report = engine.step()
            print(f"Tick {report.tick}: J={report.j_percentage}% Governed")

        # Get final metrics
        metrics = engine.get_metrics()
    """

    # Drift injection probability per tick
    DRIFT_PROBABILITY: float = 0.05  # 5% chance per standard tick

    def __init__(
        self,
        seed: int = 42,
        w_risk: float = 0.6,
        w_cost: float = 0.4,
        redis_url: str = "redis://localhost:6379",
        postgres_dsn: Optional[str] = None,
    ) -> None:
        self._seed = seed
        self._rng = np.random.default_rng(seed)
        self._weights = EnvironmentWeights(w_risk=w_risk, w_cost=w_cost)

        # ── Subsystems ────────────────────────────────────────────────────────
        self.clock = TemporalClock()
        self.math = MathEngine()
        self.event_bus = EventBus(redis_url=redis_url)
        self.branch_mgr = StateBranchManager(postgres_dsn=postgres_dsn)
        self.failed_fixes = FailedFixesLog()
        self.ts_gen = TimeSeriesGenerator(seed)
        self.world_gen = WorldStateGenerator(seed)

        # ── Swarm Agents (Phase 1: deterministic stubs) ───────────────────────
        self.ciso = CISOAgent()
        self.controller = ControllerAgent()
        self.orchestrator = OrchestratorAgent()

        # ── State ─────────────────────────────────────────────────────────────
        self._resources: list[UniversalResource] = []
        self._trust_links: list = []
        self._initialized: bool = False
        self._j_history: list[float] = []
        self._step_reports: list[StepReport] = []
        self._drift_events_total: int = 0
        self._remediations_total: int = 0
        self._remediations_successful: int = 0

        # Register clock callback
        self.clock.register_callback(self._on_tick)

    # ── Initialization ────────────────────────────────────────────────────────

    def initialize(self) -> dict[str, Any]:
        """
        Initialize the simulation world state.

        1. Generate resources with 40% wasteful baseline
        2. Build dependency graph
        3. Calculate initial J score
        4. Initialize trunk branch
        5. Connect event bus

        Returns:
            Initialization report dict.
        """
        logger.info("🚀 Initializing CloudGuard-B Simulation Engine...")

        # 1. Generate world state
        self._resources, self._trust_links = self.world_gen.generate()
        logger.info(f"   Generated {len(self._resources)} resources, {len(self._trust_links)} trust links")

        # 2. Build dependency graph from trust links
        edges = [
            (link.source_resource_id, link.target_resource_id)
            for link in self._trust_links
        ]
        centrality = self.math.build_dependency_graph(edges)

        # Apply centrality to resources
        for res in self._resources:
            if res.resource_id in centrality:
                res.properties["centrality"] = centrality[res.resource_id]

        # 3. Calculate initial J score
        j_result = self._calculate_j()
        self._j_history.append(j_result.j_score)
        logger.info(
            f"   Initial J score: {j_result.j_score:.4f} "
            f"({j_result.j_percentage:.1f}% Governed)"
        )

        # 4. Initialize trunk
        resource_dicts = [r.to_simulation_dict() for r in self._resources]
        self.branch_mgr.initialize_trunk(resource_dicts, j_score=j_result.j_score)

        # 5. Event bus (best-effort connection)
        self.event_bus.connect_sync()

        self._initialized = True

        # Count wasteful resources
        wasteful_count = sum(1 for r in self._resources if not r.is_compliant)
        total = len(self._resources)
        waste_pct = (wasteful_count / total * 100) if total else 0

        report = {
            "status": "initialized",
            "total_resources": total,
            "wasteful_resources": wasteful_count,
            "wasteful_percentage": round(waste_pct, 1),
            "trust_links": len(self._trust_links),
            "j_score": round(j_result.j_score, 4),
            "j_percentage": round(j_result.j_percentage, 2),
            "graph_stats": self.math.get_graph_stats(),
            "providers": {
                "aws": sum(1 for r in self._resources if r.provider == CloudProvider.AWS),
                "azure": sum(1 for r in self._resources if r.provider == CloudProvider.AZURE),
            },
            "event_bus": self.event_bus.get_stats(),
        }

        logger.info(f"✅ Simulation initialized: {waste_pct:.0f}% wasteful baseline")
        return report

    # ── Stepping ──────────────────────────────────────────────────────────────

    def step(self) -> StepReport:
        """
        Advance the simulation by one tick.

        Each step:
          1. Advance the clock
          2. Potentially inject drift events
          3. Generate SIEM logs
          4. If drift detected → trigger burst mode + swarm debate
          5. Calculate new J score
          6. Self-correction check

        Returns:
            StepReport with tick metrics.
        """
        if not self._initialized:
            raise RuntimeError("SimulationEngine not initialized. Call initialize() first.")

        # Advance clock (synchronous mode)
        tick_event = self.clock.tick_sync()
        report = StepReport()
        report.tick = tick_event.tick_number
        report.mode = tick_event.mode
        report.is_heartbeat = tick_event.is_heartbeat

        # Heartbeat → publish
        if tick_event.is_heartbeat:
            payload = EventPayload.heartbeat(
                tick=tick_event.tick_number,
                w_risk=self._weights.w_risk,
                w_cost=self._weights.w_cost,
            )
            self.event_bus.publish_sync(payload)

        # Drift injection (only in standard mode)
        if tick_event.mode == ClockMode.STANDARD:
            if self._rng.random() < self.DRIFT_PROBABILITY:
                drift = self._inject_drift(tick_event.tick_number)
                if drift:
                    report.drift_events.append(drift)
                    self._drift_events_total += 1

                    # Trigger burst mode for MTTR measurement
                    self.clock.enter_burst_mode(
                        duration_ticks=420,
                        drift_id=drift.get("event_id"),
                    )

                    # Run swarm debate
                    remediation_result = self._run_swarm_debate(drift)
                    if remediation_result:
                        report.remediations.append(remediation_result)

        # Generate SIEM logs
        siem_log = SIEMLogEmulator.vpc_flow_log(
            resource_id=self._resources[0].resource_id if self._resources else "unknown",
            tick=tick_event.tick_number,
        )
        self.event_bus.emit_siem_log_sync(siem_log)
        report.siem_logs.append(siem_log)

        # Calculate J
        j_result = self._calculate_j()
        report.j_score = j_result.j_score
        report.j_percentage = j_result.j_percentage
        self._j_history.append(j_result.j_score)

        # Resource stats
        report.resource_count = len(self._resources)
        report.total_risk = sum(r.risk_score for r in self._resources)
        report.total_cost = sum(r.monthly_cost_usd for r in self._resources)
        report.compliant_count = sum(1 for r in self._resources if r.is_compliant)
        report.non_compliant_count = report.resource_count - report.compliant_count
        report.mttr_current = self.clock.average_mttr

        self._step_reports.append(report)
        return report

    # ── Internal Operations ───────────────────────────────────────────────────

    def _calculate_j(self) -> JEquilibriumResult:
        """Calculate J equilibrium across all resources."""
        risk_cost_vectors = [
            ResourceRiskCost(
                resource_id=r.resource_id,
                risk_score=r.risk_score,
                monthly_cost_usd=r.monthly_cost_usd,
                centrality=r.properties.get("centrality", 0.0),
            )
            for r in self._resources
        ]

        return self.math.calculate_j(
            risk_cost_vectors,
            w_risk=self._weights.w_risk,
            w_cost=self._weights.w_cost,
        )

    def _inject_drift(self, tick: int) -> Optional[dict]:
        """Inject a random drift event into a resource."""
        if not self._resources:
            return None

        # Pick a random resource
        idx = int(self._rng.integers(0, len(self._resources)))
        resource = self._resources[idx]

        # Random drift type (use stdlib random to avoid numpy.str_ type issue)
        drift_types = list(DriftType)
        drift_type = stdlib_random.choice(drift_types)

        # Generate mutations based on drift type
        mutations = self._generate_drift_mutations(drift_type, resource)

        # Is this a false positive? (Sahay & Soto, 2026)
        is_fp = bool(self._rng.random() < 0.15)  # 15% false positive rate

        drift = DriftEvent(
            resource_id=resource.resource_id,
            drift_type=drift_type,
            severity=self._drift_severity(drift_type),
            description=f"Drift detected on {resource.name}: {drift_type.value}",
            mutations=mutations,
            previous_values={k: resource.properties.get(k) for k in mutations},
            timestamp_tick=tick,
            is_false_positive=is_fp,
            cumulative_drift_score=resource.risk_score + 10.0,
            environment_weights=self._weights,
        )

        # Apply to resource (unless false positive)
        if not is_fp:
            resource.apply_drift(drift)

        # Publish to Redis
        payload = EventPayload.drift(
            resource_id=resource.resource_id,
            drift_type=drift_type.value,
            severity=drift.severity.value,
            tick=tick,
            trace_id=drift.trace_id,
            mutations=mutations,
            cumulative_score=drift.cumulative_drift_score,
            is_false_positive=is_fp,
            w_risk=self._weights.w_risk,
            w_cost=self._weights.w_cost,
        )
        self.event_bus.publish_sync(payload)

        logger.info(
            f"🔔 Drift injected: {drift_type.value} on {resource.name} "
            f"(tick={tick}, fp={is_fp})"
        )

        return drift.model_dump(mode="json")

    def _generate_drift_mutations(
        self, drift_type: DriftType, resource: UniversalResource
    ) -> dict[str, Any]:
        """Generate property mutations for a specific drift type."""
        mutations = {
            DriftType.PUBLIC_EXPOSURE: {"public_access_blocked": False},
            DriftType.ENCRYPTION_REMOVED: {"encryption_enabled": False},
            DriftType.PERMISSION_ESCALATION: {"has_admin_policy": True},
            DriftType.NETWORK_RULE_CHANGE: {
                "inbound_rules": [{"port": 22, "protocol": "tcp", "source": "0.0.0.0/0"}]
            },
            DriftType.IAM_POLICY_CHANGE: {"overly_permissive": True},
            DriftType.TAG_REMOVED: {"has_purpose_tag": False},
            DriftType.BACKUP_DISABLED: {"backup_enabled": False},
            DriftType.COST_SPIKE: {},  # Handled via cost increase
            DriftType.RESOURCE_CREATED: {},
            DriftType.RESOURCE_DELETED: {"state": "terminated"},
        }
        return mutations.get(drift_type, {})

    def _drift_severity(self, drift_type: DriftType) -> Severity:
        """Map drift types to severity levels."""
        critical = {DriftType.PUBLIC_EXPOSURE, DriftType.PERMISSION_ESCALATION}
        high = {DriftType.ENCRYPTION_REMOVED, DriftType.NETWORK_RULE_CHANGE}
        medium = {DriftType.IAM_POLICY_CHANGE, DriftType.TAG_REMOVED, DriftType.BACKUP_DISABLED}

        if drift_type in critical:
            return Severity.CRITICAL
        elif drift_type in high:
            return Severity.HIGH
        elif drift_type in medium:
            return Severity.MEDIUM
        return Severity.LOW

    def _run_swarm_debate(self, drift: dict) -> Optional[dict]:
        """
        Run a swarm debate to determine remediation for a drift event.
        """
        # Build context
        resource_id = drift.get("resource_id", "")
        resource = next(
            (r for r in self._resources if r.resource_id == resource_id),
            None,
        )
        if resource is None:
            return None

        context = {
            "resource_id": resource_id,
            "resource_type": resource.resource_type.value,
            "total_risk": resource.risk_score,
            "monthly_cost": resource.monthly_cost_usd,
            "remediation_cost": resource.monthly_cost_usd * 0.1,
            "potential_savings": resource.monthly_cost_usd * 0.3,
        }

        # Initialize swarm state
        j_current = self._j_history[-1] if self._j_history else 1.0
        state = SwarmState(
            drift_event_id=drift.get("event_id", ""),
            current_j_score=j_current,
        )

        # Run negotiation (Phase 1: deterministic)
        state = self.orchestrator.negotiate(
            state, self.ciso, self.controller, context
        )

        if state.selected_proposal:
            self._remediations_total += 1

            # Apply ROSI calculation
            rosi = self.math.calculate_rosi(
                ale_before=resource.risk_score * 1000,
                ale_after=max(0, resource.risk_score - 30) * 1000,
                remediation_cost=context["remediation_cost"],
            )

            result = {
                "negotiation_id": state.negotiation_id,
                "selected_agent": state.selected_proposal.agent_role,
                "risk_delta": state.selected_proposal.expected_risk_delta,
                "cost_delta": state.selected_proposal.expected_cost_delta,
                "j_delta": state.selected_proposal.expected_j_delta,
                "rosi": rosi.rosi,
                "breakeven_months": rosi.time_to_breakeven_months,
                "status": state.status.value,
            }

            # Publish remediation event
            payload = EventPayload.remediation(
                resource_id=resource_id,
                action="swarm_remediation",
                tier="silver",
                tick=self.clock.current_tick,
                success=True,
                j_before=j_current,
                j_after=j_current + (state.selected_proposal.expected_j_delta or 0),
            )
            self.event_bus.publish_sync(payload)

            self._remediations_successful += 1
            return result

        return None

    # ── Tick Callback ─────────────────────────────────────────────────────────

    def _on_tick(self, event: TickEvent) -> None:
        """Callback invoked by the TemporalClock on each tick."""
        # Update telemetry for compute resources (simplified)
        if event.tick_number % 10 == 0:  # Every 10 ticks
            for res in self._resources:
                if res.resource_type.value in ("EC2", "AZURE_VM", "EKS_POD"):
                    noise = float(self._rng.normal(0, 2))
                    res.cpu_utilization = max(0, min(100, res.cpu_utilization + noise))

    # ── Metrics ───────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict[str, Any]:
        """
        Get comprehensive simulation metrics.
        Includes J history, MTTR, ROSI, and compliance stats.
        """
        if not self._step_reports:
            return {"status": "no_data"}

        latest = self._step_reports[-1]

        # Compliance breakdown
        compliant = sum(1 for r in self._resources if r.is_compliant)
        total = len(self._resources)
        compliance_pct = (compliant / total * 100) if total else 0

        # Cost analysis
        total_cost = sum(r.monthly_cost_usd for r in self._resources)
        wasteful_cost = sum(
            r.monthly_cost_usd
            for r in self._resources
            if not r.is_compliant and r.cpu_utilization < 5
        )
        waste_pct = (wasteful_cost / total_cost * 100) if total_cost else 0

        return {
            "simulation": {
                "total_ticks": self.clock.current_tick,
                "elapsed_sim_hours": round(self.clock.elapsed_sim_hours, 1),
                "current_mode": self.clock.mode.value,
            },
            "governance": {
                "j_score": round(latest.j_score, 4),
                "j_percentage": round(latest.j_percentage, 2),
                "j_history_length": len(self._j_history),
                "j_trend": "improving" if len(self._j_history) > 1 and self._j_history[-1] < self._j_history[-2] else "stable",
            },
            "compliance": {
                "compliant_resources": compliant,
                "non_compliant_resources": total - compliant,
                "compliance_percentage": round(compliance_pct, 1),
            },
            "economics": {
                "total_monthly_cost_usd": round(total_cost, 2),
                "wasteful_cost_usd": round(wasteful_cost, 2),
                "waste_percentage": round(waste_pct, 1),
                "potential_annual_savings": round(wasteful_cost * 12, 2),
            },
            "drift_events": {
                "total": self._drift_events_total,
            },
            "remediations": {
                "total": self._remediations_total,
                "successful": self._remediations_successful,
                "success_rate": round(
                    self._remediations_successful / max(self._remediations_total, 1) * 100, 1
                ),
                "failed_fixes": self.failed_fixes.total_failures,
            },
            "mttr": {
                "average_minutes": round(self.clock.average_mttr, 2),
                "measurements": len(self.clock.mttr_measurements),
                "benchmark_6_9_min": self.clock.average_mttr <= 6.9 if self.clock.mttr_measurements else None,
            },
            "branches": {
                "active": self.branch_mgr.active_branch_count,
                "info": self.branch_mgr.get_all_branches_info(),
            },
            "event_bus": self.event_bus.get_stats(),
            "weights": {
                "w_risk": self._weights.w_risk,
                "w_cost": self._weights.w_cost,
            },
        }

    def get_j_history(self) -> list[float]:
        """Get the full J score history."""
        return self._j_history.copy()

    def get_resources_summary(self) -> dict[str, Any]:
        """Get a summary of all resources by provider and type."""
        by_provider: dict[str, int] = {}
        by_type: dict[str, int] = {}
        by_risk: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        for r in self._resources:
            by_provider[r.provider.value] = by_provider.get(r.provider.value, 0) + 1
            by_type[r.resource_type.value] = by_type.get(r.resource_type.value, 0) + 1

            if r.risk_score >= 80:
                by_risk["critical"] += 1
            elif r.risk_score >= 50:
                by_risk["high"] += 1
            elif r.risk_score >= 20:
                by_risk["medium"] += 1
            else:
                by_risk["low"] += 1

        return {
            "total": len(self._resources),
            "by_provider": by_provider,
            "by_type": by_type,
            "by_risk_tier": by_risk,
        }
