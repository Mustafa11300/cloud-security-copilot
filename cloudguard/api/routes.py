"""
CLOUDGUARD-B FASTAPI ENDPOINTS
================================
Phase 1 Foundation API

Exposes the SimulationEngine, MathEngine, and StateBranchManager
via REST endpoints for local development and VS Code debugging.

Endpoints:
  POST /api/v2/simulation/init      — Initialize simulation
  POST /api/v2/simulation/step      — Advance one tick
  POST /api/v2/simulation/step/{n}  — Advance N ticks
  GET  /api/v2/simulation/metrics   — Get metrics
  GET  /api/v2/simulation/resources — Resource summary
  GET  /api/v2/simulation/j-history — J score history

  POST /api/v2/math/j               — Calculate J equilibrium
  POST /api/v2/math/rosi             — Calculate ROSI
  POST /api/v2/math/ale              — Calculate ALE
  POST /api/v2/math/ewm              — Calculate EWM weights
  POST /api/v2/math/critic           — Calculate CRITIC weights

  GET  /api/v2/branches              — List branches
  POST /api/v2/branches              — Create branch
  POST /api/v2/branches/{id}/rollback — Rollback branch
  POST /api/v2/branches/{id}/merge    — Merge to trunk

  GET  /api/v2/events                — Drain event queue
  GET  /api/v2/events/siem           — Drain SIEM queue
  GET  /api/v2/events/stats          — Event bus stats
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
from cloudguard.simulation.engine import SimulationEngine

logger = logging.getLogger("cloudguard.api.v2")

# ── Global Engine Instance ────────────────────────────────────────────────────
_engine: Optional[SimulationEngine] = None
_math = MathEngine()


def get_engine() -> SimulationEngine:
    """Get or create the global simulation engine."""
    global _engine
    if _engine is None:
        _engine = SimulationEngine(seed=42)
    return _engine


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class InitRequest(BaseModel):
    seed: int = 42
    w_risk: float = 0.6
    w_cost: float = 0.4


class StepRequest(BaseModel):
    n_ticks: int = Field(default=1, ge=1, le=1000)


class JRequest(BaseModel):
    resources: list[dict] = Field(
        description="List of {resource_id, risk_score, monthly_cost_usd}"
    )
    w_risk: float = 0.6
    w_cost: float = 0.4


class ROSIRequest(BaseModel):
    ale_before: float
    ale_after: float
    remediation_cost: float


class ALERequest(BaseModel):
    asset_value: float
    exposure_factor: float
    annual_rate_of_occurrence: float


class MatrixRequest(BaseModel):
    matrix: list[list[float]] = Field(
        description="2D matrix (n_resources × n_criteria)"
    )
    criterion_names: list[str]


class BranchCreateRequest(BaseModel):
    name: str = Field(description="Branch name: branch_a or branch_b")
    parent: Optional[str] = None


class BranchRollbackRequest(BaseModel):
    reason: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

simulation_router = APIRouter(prefix="/api/v2/simulation", tags=["Simulation"])


@simulation_router.post("/init")
def init_simulation(req: InitRequest) -> dict:
    """Initialize the simulation with the given parameters."""
    global _engine
    _engine = SimulationEngine(seed=req.seed, w_risk=req.w_risk, w_cost=req.w_cost)
    return _engine.initialize()


@simulation_router.post("/step")
def step_simulation() -> dict:
    """Advance the simulation by one tick."""
    engine = get_engine()
    if not engine._initialized:
        engine.initialize()
    report = engine.step()
    return report.to_dict()


@simulation_router.post("/step/{n_ticks}")
def step_n_simulation(n_ticks: int) -> dict:
    """Advance the simulation by N ticks."""
    if n_ticks < 1 or n_ticks > 1000:
        raise HTTPException(400, "n_ticks must be between 1 and 1000")

    engine = get_engine()
    if not engine._initialized:
        engine.initialize()

    reports = []
    for _ in range(n_ticks):
        report = engine.step()
        reports.append(report.to_dict())

    return {
        "ticks_processed": n_ticks,
        "first_tick": reports[0] if reports else {},
        "last_tick": reports[-1] if reports else {},
        "j_start": reports[0]["j_percentage"] if reports else 0,
        "j_end": reports[-1]["j_percentage"] if reports else 0,
    }


@simulation_router.get("/metrics")
def get_metrics() -> dict:
    """Get comprehensive simulation metrics."""
    engine = get_engine()
    if not engine._initialized:
        return {"status": "not_initialized", "hint": "POST /api/v2/simulation/init first"}
    return engine.get_metrics()


@simulation_router.get("/resources")
def get_resources() -> dict:
    """Get resource summary by provider and type."""
    engine = get_engine()
    if not engine._initialized:
        return {"status": "not_initialized"}
    return engine.get_resources_summary()


@simulation_router.get("/j-history")
def get_j_history() -> dict:
    """Get the full J score history."""
    engine = get_engine()
    return {
        "j_history": engine.get_j_history(),
        "length": len(engine.get_j_history()),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MATH ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

math_router = APIRouter(prefix="/api/v2/math", tags=["Math Engine"])


@math_router.post("/j")
def calculate_j(req: JRequest) -> dict:
    """Calculate J equilibrium for given resources."""
    resources = [
        ResourceRiskCost(
            resource_id=r.get("resource_id", f"res-{i}"),
            risk_score=r.get("risk_score", 0),
            monthly_cost_usd=r.get("monthly_cost_usd", 0),
        )
        for i, r in enumerate(req.resources)
    ]
    result = _math.calculate_j(resources, w_risk=req.w_risk, w_cost=req.w_cost)
    return {
        "j_score": result.j_score,
        "j_percentage": result.j_percentage,
        "w_risk": result.w_risk,
        "w_cost": result.w_cost,
        "per_resource": result.per_resource,
        "pareto_front": result.pareto_front,
    }


@math_router.post("/rosi")
def calculate_rosi(req: ROSIRequest) -> dict:
    """Calculate Return on Security Investment."""
    result = _math.calculate_rosi(
        ale_before=req.ale_before,
        ale_after=req.ale_after,
        remediation_cost=req.remediation_cost,
    )
    return {
        "rosi": result.rosi,
        "ale_before": result.ale_before,
        "ale_after": result.ale_after,
        "remediation_cost": result.remediation_cost,
        "time_to_breakeven_months": result.time_to_breakeven_months,
        "is_positive_roi": result.is_positive,
    }


@math_router.post("/ale")
def calculate_ale(req: ALERequest) -> dict:
    """Calculate Annualized Loss Expectancy."""
    ale = _math.calculate_ale(
        asset_value=req.asset_value,
        exposure_factor=req.exposure_factor,
        annual_rate_of_occurrence=req.annual_rate_of_occurrence,
    )
    sle = req.asset_value * req.exposure_factor
    return {
        "ale": ale,
        "sle": round(sle, 2),
        "asset_value": req.asset_value,
        "exposure_factor": req.exposure_factor,
        "aro": req.annual_rate_of_occurrence,
    }


@math_router.post("/ewm")
def calculate_ewm(req: MatrixRequest) -> dict:
    """Calculate Entropy Weight Method weights."""
    matrix = np.array(req.matrix)
    if matrix.shape[1] != len(req.criterion_names):
        raise HTTPException(400, "Matrix columns must match criterion_names length")

    result = _math.calculate_ewm(matrix, req.criterion_names)
    return {
        "weights": result.weights,
        "entropy_values": result.entropy_values,
        "divergence_values": result.divergence_values,
    }


@math_router.post("/critic")
def calculate_critic(req: MatrixRequest) -> dict:
    """Calculate CRITIC weights."""
    matrix = np.array(req.matrix)
    if matrix.shape[1] != len(req.criterion_names):
        raise HTTPException(400, "Matrix columns must match criterion_names length")

    result = _math.calculate_critic(matrix, req.criterion_names)
    return {
        "weights": result.weights,
        "std_devs": result.std_devs,
        "correlations": result.correlations,
        "information_content": result.information_content,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BRANCHES ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

branches_router = APIRouter(prefix="/api/v2/branches", tags=["Branches"])


@branches_router.get("")
def list_branches() -> dict:
    """List all branches."""
    engine = get_engine()
    return {
        "branches": engine.branch_mgr.get_all_branches_info(),
        "active_count": engine.branch_mgr.active_branch_count,
        "max_allowed": 3,
    }


@branches_router.post("")
def create_branch(req: BranchCreateRequest) -> dict:
    """Create a new experiment branch."""
    engine = get_engine()
    if not engine._initialized:
        raise HTTPException(400, "Simulation not initialized")

    branch_id = engine.branch_mgr.create_branch(
        name=req.name, parent=req.parent
    )
    if branch_id is None:
        raise HTTPException(400, "Cannot create branch (max 3 or invalid name)")

    info = engine.branch_mgr.get_branch_info(branch_id)
    return {"created": True, "branch": info}


@branches_router.post("/{branch_id}/rollback")
def rollback_branch(branch_id: str, req: BranchRollbackRequest) -> dict:
    """Roll back a branch to parent state."""
    engine = get_engine()
    success = engine.branch_mgr.rollback(branch_id, reason=req.reason)
    if not success:
        raise HTTPException(400, f"Rollback failed for branch {branch_id}")
    return {"rolled_back": True, "branch": engine.branch_mgr.get_branch_info(branch_id)}


@branches_router.post("/{branch_id}/merge")
def merge_branch(branch_id: str) -> dict:
    """Merge a successful branch to trunk."""
    engine = get_engine()
    success = engine.branch_mgr.merge_to_trunk(branch_id)
    if not success:
        raise HTTPException(400, f"Merge failed for branch {branch_id}")
    return {"merged": True, "trunk": engine.branch_mgr.get_branch_info(engine.branch_mgr.trunk_id)}


# ═══════════════════════════════════════════════════════════════════════════════
# EVENTS ROUTER
# ═══════════════════════════════════════════════════════════════════════════════

events_router = APIRouter(prefix="/api/v2/events", tags=["Events"])


@events_router.get("")
def drain_events(max_items: int = 50) -> dict:
    """Drain events from the in-memory queue."""
    engine = get_engine()
    events = engine.event_bus.drain_queue(max_items)
    return {"events": events, "count": len(events)}


@events_router.get("/siem")
def drain_siem(max_items: int = 50) -> dict:
    """Drain SIEM logs from the queue."""
    engine = get_engine()
    logs = engine.event_bus.drain_siem_queue(max_items)
    return {"siem_logs": logs, "count": len(logs)}


@events_router.get("/stats")
def event_stats() -> dict:
    """Get event bus statistics."""
    engine = get_engine()
    return engine.event_bus.get_stats()


# ── Test Injection Router ────────────────────────────────────────────────────
test_router = APIRouter(prefix="/api/v2/test", tags=["Test Injection"])


class InjectEventRequest(BaseModel):
    """Payload for injecting a raw event into the War Room WebSocket stream."""
    event_type: str = Field(..., description="e.g. DRIFT, REMEDIATION, FORECAST_SIGNAL, NARRATIVE_CHUNK")
    data: dict = Field(default_factory=dict, description="Event data payload")
    environment_weights: dict = Field(default_factory=dict, description="Optional w_R/w_C override")
    event_id: str = Field(default="", description="Optional event ID (auto-generated if empty)")
    agent_id: str = Field(default="test-harness", description="Agent that produced this event")


@test_router.post("/inject")
async def inject_event(req: InjectEventRequest) -> dict:
    """
    Inject a synthetic event into the War Room WebSocket stream.

    This bypasses the simulation engine and broadcasts directly to all
    connected frontend clients. Useful for testing specific UI scenarios
    like Amber Alerts, Fast-Pass countdowns, and remediation triggers.
    """
    import uuid as _uuid
    from cloudguard.api.streamer import emit_event, emit_ticker

    raw_payload = {
        "event_type": req.event_type,
        "event_id": req.event_id or f"evt-test-{_uuid.uuid4().hex[:8]}",
        "agent_id": req.agent_id,
        "data": req.data,
    }
    if req.environment_weights:
        raw_payload["environment_weights"] = req.environment_weights

    await emit_event(raw_payload)

    # If weights were provided, also emit a TICKER_UPDATE
    if req.environment_weights:
        await emit_ticker(
            w_risk=req.environment_weights.get("w_R", 0.6),
            w_cost=req.environment_weights.get("w_C", 0.4),
            j_score=req.data.get("j_score", 0.5),
            trigger=f"test_inject_{req.event_type}",
        )

    return {
        "status": "injected",
        "event_type": req.event_type,
        "event_id": raw_payload["event_id"],
    }
