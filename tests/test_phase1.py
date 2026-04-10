"""
CloudGuard-B Phase 1 — Test Suite
===================================
Comprehensive tests for ALL 8 subsystems.

Run with:
  cd cloud-security-copilot
  python -m pytest tests/test_phase1.py -v
"""

import json
import math

import numpy as np
import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# 1. UNIVERSAL SCHEMA TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUniversalSchema:
    """Tests for Subsystem 1: Universal Resource Schema."""

    def test_create_aws_ec2_resource(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
            region="us-east-1",
            name="test-ec2",
            properties={"instance_type": "t3.micro", "state": "running"},
            monthly_cost_usd=10.0,
            risk_score=25.0,
        )
        assert res.provider == CloudProvider.AWS
        assert res.resource_type == ResourceType.EC2
        assert res.risk_score == 25.0
        assert res.is_compliant is True

    def test_create_azure_blob_resource(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AZURE,
            resource_type=ResourceType.AZURE_BLOB,
            region="eastus",
            name="test-blob",
            properties={"container_access": "private"},
        )
        assert res.provider == CloudProvider.AZURE
        assert res.resource_type == ResourceType.AZURE_BLOB

    def test_oidc_trust_link(self):
        from cloudguard.core.schemas import CloudProvider, OIDCTrustLink
        link = OIDCTrustLink(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-123",
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-456",
            oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLE",
            allowed_audiences=["api://AzureADTokenExchange"],
        )
        assert link.validate_trust() is True
        assert link.is_expired() is False

    def test_oidc_trust_no_audience_invalid(self):
        from cloudguard.core.schemas import CloudProvider, OIDCTrustLink
        link = OIDCTrustLink(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-123",
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-456",
            oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com",
            allowed_audiences=[],  # Empty = overly permissive
        )
        assert link.validate_trust() is False

    def test_drift_event_application(self):
        from cloudguard.core.schemas import (
            CloudProvider, DriftEvent, DriftType, ResourceType, UniversalResource
        )
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.S3,
            properties={"public_access_blocked": True},
            is_compliant=True,
        )
        drift = DriftEvent(
            resource_id=res.resource_id,
            drift_type=DriftType.PUBLIC_EXPOSURE,
            mutations={"public_access_blocked": False},
        )
        res.apply_drift(drift)
        assert res.is_compliant is False
        assert res.properties["public_access_blocked"] is False
        assert len(res.drift_history) == 1

    def test_environment_weights_validation(self):
        from cloudguard.core.schemas import EnvironmentWeights
        w = EnvironmentWeights(w_risk=0.7, w_cost=0.3)
        assert w.w_risk == 0.7
        assert w.w_cost == 0.3

    def test_environment_weights_invalid(self):
        from cloudguard.core.schemas import EnvironmentWeights
        with pytest.raises(Exception):
            EnvironmentWeights(w_risk=0.7, w_cost=0.5)

    def test_serialization_roundtrip(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
            name="test",
            properties={"key": "value"},
            monthly_cost_usd=50.0,
        )
        data = res.to_simulation_dict()
        assert isinstance(data, dict)
        assert data["provider"] == "aws"
        assert data["monthly_cost_usd"] == 50.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TEMPORAL CLOCK TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemporalClock:
    """Tests for Subsystem 2: Temporal Clock."""

    def test_standard_mode_ticking(self):
        from cloudguard.core.clock import ClockMode, TemporalClock
        clock = TemporalClock()
        event = clock.tick_sync()
        assert event.tick_number == 0
        assert event.mode == ClockMode.STANDARD
        assert event.elapsed_sim_minutes == 60  # 1 tick = 60 min

    def test_burst_mode_activation(self):
        from cloudguard.core.clock import ClockMode, TemporalClock
        clock = TemporalClock()
        clock.enter_burst_mode(duration_ticks=10)
        assert clock.mode == ClockMode.BURST

        event = clock.tick_sync()
        assert event.mode == ClockMode.BURST
        assert event.elapsed_sim_minutes == 1  # 1 tick = 1 min in burst

    def test_burst_mode_exit(self):
        from cloudguard.core.clock import ClockMode, TemporalClock
        clock = TemporalClock()
        clock.enter_burst_mode(duration_ticks=3)

        # Tick through burst
        for _ in range(4):
            clock.tick_sync()

        # Should have reverted to standard
        assert clock.mode == ClockMode.STANDARD

    def test_heartbeat_every_10_ticks(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        heartbeats = []
        for _ in range(25):
            event = clock.tick_sync()
            if event.is_heartbeat:
                heartbeats.append(event.tick_number)

        # Ticks 10 and 20 should be heartbeats
        assert 10 in heartbeats
        assert 20 in heartbeats

    def test_mttr_measurement(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        clock.enter_burst_mode(duration_ticks=100, drift_id="test-drift")

        # Simulate 7 burst ticks (= 7 simulated minutes)
        for _ in range(7):
            clock.tick_sync()

        mttr = clock.exit_burst_mode(remediation_successful=True)
        assert mttr == 7.0  # 7 burst ticks × 1 min
        assert len(clock.mttr_measurements) == 1

    def test_clock_reset(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        for _ in range(10):
            clock.tick_sync()
        clock.reset()
        assert clock.current_tick == 0
        assert clock.elapsed_sim_minutes == 0

    def test_callback_registration(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        ticks_received = []

        def my_callback(event):
            ticks_received.append(event.tick_number)

        clock.register_callback(my_callback)
        clock.tick_sync()
        clock.tick_sync()
        assert len(ticks_received) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REDIS EVENT BUS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBus:
    """Tests for Subsystem 3: Redis Pub/Sub Event Bus."""

    def test_event_payload_creation(self):
        from cloudguard.infra.redis_bus import EventPayload
        payload = EventPayload.create(
            event_type="TEST",
            timestamp_tick=5,
            w_risk=0.7,
            w_cost=0.3,
            data={"key": "value"},
        )
        assert payload["event_type"] == "TEST"
        assert payload["timestamp_tick"] == 5
        assert payload["environment_weights"]["w_R"] == 0.7
        assert payload["environment_weights"]["w_C"] == 0.3
        assert "trace_id" in payload
        assert "event_id" in payload

    def test_heartbeat_payload(self):
        from cloudguard.infra.redis_bus import EventPayload
        hb = EventPayload.heartbeat(tick=10)
        assert hb["event_type"] == "HEARTBEAT"
        assert hb["data"]["tick"] == 10

    def test_drift_payload(self):
        from cloudguard.infra.redis_bus import EventPayload
        drift = EventPayload.drift(
            resource_id="s3-test",
            drift_type="public_exposure",
            severity="CRITICAL",
            tick=42,
            is_false_positive=True,
        )
        assert drift["event_type"] == "DRIFT"
        assert drift["data"]["resource_id"] == "s3-test"
        assert drift["data"]["is_false_positive"] is True

    def test_in_memory_event_bus(self):
        from cloudguard.infra.redis_bus import EventBus, EventPayload
        bus = EventBus()
        payload = EventPayload.heartbeat(tick=1)
        bus.publish_sync(payload)
        assert bus.published_count == 1
        assert bus.queue_size == 1

    def test_event_bus_drain(self):
        from cloudguard.infra.redis_bus import EventBus, EventPayload
        bus = EventBus()
        for i in range(5):
            bus.publish_sync(EventPayload.heartbeat(tick=i))
        events = bus.drain_queue(3)
        assert len(events) == 3
        assert bus.queue_size == 2

    def test_event_bus_subscriber(self):
        from cloudguard.infra.redis_bus import EventBus, EventPayload
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))
        bus.publish_sync(EventPayload.heartbeat(tick=1))
        assert len(received) == 1

    def test_siem_log_emulator(self):
        from cloudguard.infra.redis_bus import SIEMLogEmulator
        vpc = SIEMLogEmulator.vpc_flow_log("res-1", tick=10)
        assert vpc["log_type"] == "VPC_FLOW"

        ct = SIEMLogEmulator.cloudtrail_event("PutObject", "s3-1", tick=10)
        assert ct["log_type"] == "CLOUDTRAIL"

        k8s = SIEMLogEmulator.k8s_audit_log("pod-1", verb="create", tick=10)
        assert k8s["log_type"] == "K8S_AUDIT"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STATE BRANCH MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateBranchManager:
    """Tests for Subsystem 4: Isolated Branching & Rollback."""

    def test_initialize_trunk(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        resources = [{"resource_id": f"res-{i}", "risk": i * 10} for i in range(5)]
        trunk_id = mgr.initialize_trunk(resources, j_score=0.85)
        assert trunk_id is not None
        assert mgr.active_branch_count == 1

    def test_create_branch(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        resources = [{"resource_id": "res-1"}]
        mgr.initialize_trunk(resources)
        branch_id = mgr.create_branch("branch_a")
        assert branch_id is not None
        assert mgr.active_branch_count == 2

    def test_max_3_branches(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "r1"}])
        mgr.create_branch("branch_a")
        mgr.create_branch("branch_b")
        # 4th branch should fail
        result = mgr.create_branch("branch_a")
        assert result is None

    def test_branch_isolation(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "res-1", "value": "original"}])
        branch_id = mgr.create_branch("branch_a")
        # Modify branch
        mgr.update_resource(branch_id, "res-1", {"value": "modified"})
        # Trunk should be unchanged
        trunk_res = mgr.get_resources(mgr.trunk_id)
        assert trunk_res[0]["value"] == "original"
        # Branch should be modified
        branch_res = mgr.get_resources(branch_id)
        assert branch_res[0]["value"] == "modified"

    def test_rollback(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "res-1", "value": "v1"}], j_score=0.5)
        branch_id = mgr.create_branch("branch_a")
        mgr.update_resource(branch_id, "res-1", {"value": "v2"})

        success = mgr.rollback(branch_id, reason="J_new >= J_old")
        assert success is True

        # After rollback, branch state should match trunk
        branch_res = mgr.get_resources(branch_id)
        assert branch_res[0]["value"] == "v1"

    def test_self_correction_logic_gate(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        # J_new >= J_old → should rollback
        assert mgr.should_rollback("any", j_old=0.5, j_new=0.6) is True
        assert mgr.should_rollback("any", j_old=0.5, j_new=0.5) is True
        assert mgr.should_rollback("any", j_old=0.5, j_new=0.4) is False

    def test_cannot_rollback_trunk(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "r1"}])
        assert mgr.rollback(mgr.trunk_id) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MATH ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMathEngine:
    """Tests for Subsystem 5: Governance & ROI Math Engine."""

    def test_j_equilibrium_basic(self):
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        resources = [
            ResourceRiskCost("r1", risk_score=80, monthly_cost_usd=100),
            ResourceRiskCost("r2", risk_score=20, monthly_cost_usd=50),
            ResourceRiskCost("r3", risk_score=50, monthly_cost_usd=75),
        ]
        result = engine.calculate_j(resources, w_risk=0.6, w_cost=0.4)
        assert 0 <= result.j_score <= 1
        assert 0 <= result.j_percentage <= 100
        assert len(result.per_resource) == 3

    def test_j_empty_resources(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        result = engine.calculate_j([], w_risk=0.6, w_cost=0.4)
        assert result.j_score == 0.0
        assert result.j_percentage == 100.0

    def test_j_weights_must_sum_to_one(self):
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        with pytest.raises(ValueError):
            engine.calculate_j(
                [ResourceRiskCost("r1", 50, 50)],
                w_risk=0.5, w_cost=0.6,
            )

    def test_rosi_positive(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        result = engine.calculate_rosi(
            ale_before=50000,
            ale_after=5000,
            remediation_cost=10000,
        )
        assert result.rosi > 0
        assert result.is_positive is True
        assert result.time_to_breakeven_months > 0

    def test_rosi_negative(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        result = engine.calculate_rosi(
            ale_before=10000,
            ale_after=9000,
            remediation_cost=5000,
        )
        assert result.rosi < 0
        assert result.is_positive is False

    def test_ale_calculation(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        ale = engine.calculate_ale(
            asset_value=1_000_000,
            exposure_factor=0.25,
            annual_rate_of_occurrence=0.1,
        )
        assert ale == 25000.0  # 1M × 0.25 × 0.1 = 25K

    def test_ewm_weights(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        matrix = np.array([
            [10, 20, 30],
            [40, 50, 60],
            [70, 80, 90],
            [25, 35, 45],
        ])
        names = ["risk", "cost", "impact"]
        result = engine.calculate_ewm(matrix, names)
        assert len(result.weights) == 3
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_critic_weights(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        matrix = np.array([
            [10, 80, 5],
            [20, 60, 10],
            [70, 30, 50],
            [40, 50, 25],
        ])
        names = ["risk", "cost", "impact"]
        result = engine.calculate_critic(matrix, names)
        assert len(result.weights) == 3
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_pareto_front(self):
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        resources = [
            ResourceRiskCost("r1", risk_score=10, monthly_cost_usd=100),  # Low risk, high cost
            ResourceRiskCost("r2", risk_score=90, monthly_cost_usd=10),   # High risk, low cost
            ResourceRiskCost("r3", risk_score=50, monthly_cost_usd=50),   # Middle
        ]
        result = engine.calculate_j(resources, w_risk=0.5, w_cost=0.5)
        assert len(result.pareto_front) > 0

    def test_self_correction_gate(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        assert engine.should_rollback(j_old=0.5, j_new=0.6) is True
        assert engine.should_rollback(j_old=0.5, j_new=0.4) is False

    def test_governance_percentage(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        assert engine.governance_percentage(0.0) == 100.0
        assert engine.governance_percentage(1.0) == 0.0
        assert engine.governance_percentage(0.5) == 50.0

    def test_dependency_graph(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        edges = [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]
        centrality = engine.build_dependency_graph(edges)
        assert len(centrality) == 4
        stats = engine.get_graph_stats()
        assert stats["nodes"] == 4
        assert stats["edges"] == 4


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SWARM HANDSHAKE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSwarmHandshake:
    """Tests for Subsystem 6: Dialectical Swarm."""

    def test_ciso_proposes_risk_reduction(self):
        from cloudguard.core.swarm import CISOAgent, SwarmState
        ciso = CISOAgent()
        state = SwarmState(current_j_score=0.7)
        context = {"total_risk": 80, "remediation_cost": 100}
        proposal = ciso.propose(state, context)
        assert proposal.agent_role == "ciso"
        assert proposal.expected_risk_delta < 0

    def test_controller_proposes_cost_savings(self):
        from cloudguard.core.swarm import ControllerAgent, SwarmState
        ctrl = ControllerAgent()
        state = SwarmState(current_j_score=0.7)
        context = {"total_risk": 80, "potential_savings": 200}
        proposal = ctrl.propose(state, context)
        assert proposal.agent_role == "controller"
        assert proposal.expected_cost_delta <= 0

    def test_orchestrator_selects_winner(self):
        from cloudguard.core.swarm import (
            CISOAgent, ControllerAgent, OrchestratorAgent, SwarmState,
        )
        orch = OrchestratorAgent()
        ciso = CISOAgent()
        ctrl = ControllerAgent()
        state = SwarmState(current_j_score=0.7)
        context = {"total_risk": 80, "remediation_cost": 50, "potential_savings": 200}

        state = orch.negotiate(state, ciso, ctrl, context)
        assert state.selected_proposal is not None
        assert state.status.value == "consensus"

    def test_token_budget_enforcement(self):
        from cloudguard.core.swarm import SwarmState
        state = SwarmState(token_budget=100, tokens_consumed=0)
        assert state.consume_tokens(50) is True
        assert state.consume_tokens(60) is False
        assert state.budget_exceeded is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. REMEDIATION PROTOCOL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRemediationProtocol:
    """Tests for Subsystem 7: Command Pattern Remediation."""

    def _make_resource(self, **props):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        return UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.S3,
            properties=props,
            risk_score=90.0,
        )

    def test_block_public_access(self):
        from cloudguard.core.remediation import BlockPublicAccess, RemediationTier
        from cloudguard.core.schemas import RemediationTier as RT
        res = self._make_resource(public_access_blocked=False)
        cmd = BlockPublicAccess(res, tier=RT.SILVER)
        success = cmd.execute_with_retry()
        assert success is True
        assert res.properties["public_access_blocked"] is True

    def test_command_undo(self):
        from cloudguard.core.remediation import BlockPublicAccess
        from cloudguard.core.schemas import RemediationTier
        res = self._make_resource(public_access_blocked=False, encryption_enabled=False)
        cmd = BlockPublicAccess(res, tier=RemediationTier.SILVER)
        cmd._previous_state = res.properties.copy()
        cmd.execute()
        assert res.properties["public_access_blocked"] is True
        cmd.undo()
        assert res.properties["public_access_blocked"] is False

    def test_failed_fixes_log(self):
        from cloudguard.core.remediation import FailedFixesLog, BlockPublicAccess
        from cloudguard.core.schemas import RemediationTier
        log = FailedFixesLog()
        res = self._make_resource(public_access_blocked=False)
        cmd = BlockPublicAccess(res, tier=RemediationTier.BRONZE)
        cmd._is_failed = True
        cmd._failure_reason = "test failure"
        log.record_failure(cmd)
        assert log.total_failures == 1
        assert log.has_failed_before("BlockPublicAccess", res.resource_id)

    def test_command_registry(self):
        from cloudguard.core.remediation import COMMAND_REGISTRY
        assert "block_public_access" in COMMAND_REGISTRY
        assert "enable_encryption" in COMMAND_REGISTRY
        assert "restrict_network_access" in COMMAND_REGISTRY
        assert len(COMMAND_REGISTRY) >= 7


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TELEMETRY GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetryGenerator:
    """Tests for Subsystem 8: Telemetry & Waste Baseline."""

    def test_time_series_generation(self):
        from cloudguard.simulation.telemetry import TimeSeriesGenerator
        gen = TimeSeriesGenerator(seed=42)
        series = gen.generate(n_ticks=720, base_level=50.0)
        assert len(series) == 720
        assert series.min() >= 0
        assert series.max() <= 100

    def test_seasonality_present(self):
        from cloudguard.simulation.telemetry import TimeSeriesGenerator
        gen = TimeSeriesGenerator(seed=42)
        series = gen.generate(n_ticks=168, base_level=50.0, seasonality_24h=20.0, noise_std=0.1)
        # Series should oscillate around 50 with 24h period
        assert series.std() > 5  # Significant variation from seasonality

    def test_world_state_generation(self):
        from cloudguard.simulation.telemetry import WorldStateGenerator
        gen = WorldStateGenerator(seed=42)
        resources, trust_links = gen.generate()
        assert len(resources) > 300
        assert len(trust_links) > 0

        # Check provider distribution
        aws_count = sum(1 for r in resources if r.provider.value == "aws")
        azure_count = sum(1 for r in resources if r.provider.value == "azure")
        assert aws_count > 200
        assert azure_count > 20

    def test_wasteful_baseline(self):
        from cloudguard.simulation.telemetry import WorldStateGenerator
        gen = WorldStateGenerator(seed=42)
        resources, _ = gen.generate(wasteful_pct=0.40)
        non_compliant = sum(1 for r in resources if not r.is_compliant)
        total = len(resources)
        waste_pct = non_compliant / total
        # Should be roughly 40% (±15% due to randomness)
        assert 0.20 < waste_pct < 0.60

    def test_cross_cloud_trust_links(self):
        from cloudguard.simulation.telemetry import WorldStateGenerator
        gen = WorldStateGenerator(seed=42)
        _, trust_links = gen.generate()
        # Should have Lambda→Blob and EKS→AKS links
        aws_to_azure = [
            l for l in trust_links
            if l.source_provider.value == "aws" and l.target_provider.value == "azure"
        ]
        assert len(aws_to_azure) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SIMULATION ENGINE (INTEGRATION)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimulationEngine:
    """Integration tests for the complete SimulationEngine."""

    def test_initialization(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        report = engine.initialize()
        assert report["status"] == "initialized"
        assert report["total_resources"] > 300
        assert report["j_percentage"] > 0
        assert report["wasteful_percentage"] > 20

    def test_step_advances_tick(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        engine.initialize()
        report = engine.step()
        assert report.tick == 0
        report2 = engine.step()
        assert report2.tick == 1

    def test_metrics_after_steps(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        engine.initialize()
        for _ in range(5):
            engine.step()
        metrics = engine.get_metrics()
        assert metrics["simulation"]["total_ticks"] == 5
        assert "governance" in metrics
        assert "economics" in metrics
        assert "mttr" in metrics

    def test_uninitialised_step_raises(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        with pytest.raises(RuntimeError):
            engine.step()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
