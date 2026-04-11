"""
CLOUDGUARD-B — PHASE 5 NARRATIVE ENGINE
=========================================
"The Vocal Sovereign" — Cognitive Pulse Streamer & HITL Approval Gate

This module is the "Vocal Cords" of the CloudGuard-B brain. It translates
the raw quantitative output of the Adversarial Swarm into a structured,
human-readable narrative — streamed block-by-block ("Cognitive Pulse") to
the War Room WebSocket, synchronized with the machine's reasoning speed.

Architecture:
                    ┌──────────────────────┐
                    │   SentryNode (CISO)  │   T+0s  → THREAT block
                    └──────────────────────┘
                              │
                    ┌──────────────────────┐
                    │  ConsultantNode (ROI)│   T+15s → ARGUMENT block
                    └──────────────────────┘
                              │
                    ┌──────────────────────┐
                    │  ActiveEditor (Synth)│   T+30s → SYNTHESIS block
                    └──────────────────────┘
                              │
                    ┌──────────────────────┐
                    │  SovereignCountdown  │   T+30..60s — 60-second gate
                    │  ├─ T+50: CRITICAL   │
                    │  └─ T+60: AUTO-EXEC  │
                    └──────────────────────┘

WebSocket Message Extensions (added to Phase 3 schema):
    chunk_type        — "threat" | "argument" | "synthesis" | "countdown" | "veto" | "exec"
    is_final          — True on the last chunk of a narrative sequence
    countdown_active  — True from T+30 onward (triggers UI timer)
    seconds_remaining — Count from 60 → 0

ALE / ROSI / Labor ROI:
    ale_reduction_usd — Risk avoided (ALE_before - ALE_after)
    labor_savings_usd — 4 h × L3 Engineer @ $150/hr = $600 per auto-fix
    rosi              — (ale_reduction - remediation_cost) / remediation_cost

Deep Audit (math_trace):
    entropy_weights   — Shannon EWM per resource criterion
    pareto_front      — Pareto-optimal {risk_norm, cost_norm} coordinates
    j_components      — Per-resource J contributions

Usage:
    from cloudguard.api.narrative_engine import NarrativeEngine, SovereignGate
    engine = NarrativeEngine()

    # Stream narrative async-gen to WebSocket
    async for chunk in engine.stream_narrative(swarm_context):
        await ws.send_text(json.dumps(chunk))

    # Start the 60-second Sovereign Gate
    gate = SovereignGate(on_auto_execute=my_callback)
    await gate.arm(decision_id="dec-abc123", proposal=synthesis_result)
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Optional

logger = logging.getLogger("cloudguard.narrative_engine")

# ─── Labor cost constants ──────────────────────────────────────────────────────
L3_HOURLY_RATE_USD = 150.0   # Senior/L3 cloud engineer hourly rate
L3_HOURS_PER_FIX   = 4.0     # Estimated manual remediation effort

# ─── Sovereign timing ─────────────────────────────────────────────────────────
SOVEREIGN_WINDOW_S    = 60    # Total HITL window
CRITICAL_ALERT_S      = 50    # T+50 → CRITICAL_COUNTDOWN pulse
INTER_BLOCK_DELAY_S   = 15.0  # Delay between narrative blocks (T+0, T+15, T+30)

# ─── Predictive Fast-Pass (Sovereign Gate) ────────────────────────────────────
# If P ≥ 0.90 for Shadow AI, reduce review window from 60s → 10s
PREDICTIVE_FAST_PASS_THRESHOLD = 0.90
PREDICTIVE_FAST_PASS_WINDOW_S  = 10    # Accelerated review window
FAST_PASS_WASTE_SAVINGS_USD     = 250.0 # Estimated operational waste saved per fast-pass

# ─── Citation tags ────────────────────────────────────────────────────────────
CITATIONS = {
    "public_exposure":        "[CIS 2.1.2]",
    "encryption_removed":     "[CIS 2.1.1]",
    "permission_escalation":  "[NIST AC-6]",
    "network_rule_change":    "[CIS 5.2]",
    "iam_policy_change":      "[NIST IA-2]",
    "backup_disabled":        "[CIS 2.2.1]",
    "mfa_disabled":           "[NIST IA-3]",
    "default":                "[NIST AI RMF 1.0]",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SwarmContext:
    """
    All inputs the NarrativeEngine needs to build the Technical Story.
    Populate from the swarm negotiation result before streaming.
    """
    # Identity
    decision_id: str = field(default_factory=lambda: f"dec-{uuid.uuid4().hex[:8]}")
    resource_id:  str = ""
    drift_type:   str = ""
    severity:     str = "MEDIUM"
    environment:  str = "production"

    # Agent reasoning
    sentry_reasoning:     str = ""     # CISO rationale (raw)
    consultant_reasoning: str = ""     # Controller rationale (raw)
    synthesis_reasoning:  str = ""     # ActiveEditor synthesis (raw)
    decision_status:      str = "synthesized"

    # J-Score algebra
    j_before: float = 0.5
    j_after:  float = 0.4
    w_risk:   float = 0.6
    w_cost:   float = 0.4

    # Economics
    ale_before:        float = 0.0
    ale_after:         float = 0.0
    remediation_cost:  float = 0.0
    resource_cost_usd: float = 0.0
    compliance_gaps:   list[str] = field(default_factory=list)

    # Deep-audit payload (math_trace)
    entropy_weights: dict[str, float] = field(default_factory=dict)
    pareto_front:    list[dict]       = field(default_factory=list)
    j_components:    list[dict]       = field(default_factory=list)

    # Remediation command (for Sovereign Gate)
    proposed_action: str = "remediate"
    tier:            str = "silver"

    # ── Phase 4 Predictive Integration ───────────────────────────────────────
    # Forecast P-score from ThreatForecaster (drives Fast-Pass logic)
    forecast_probability: float = 0.0      # LSTM P ∈ [0, 1]; 0.0 = no forecast
    is_shadow_ai_forecast: bool = False    # True if forecast is for Shadow AI
    forecast_alert_id:    str   = ""       # OMEGA-NNN from DissipationHandler


@dataclass
class NarrativeChunk:
    """Single streaming block sent to the War Room WebSocket."""
    chunk_id:         str
    decision_id:      str
    chunk_type:       str          # threat | argument | synthesis | countdown | veto | exec
    heading:          str
    body:             str          # The actual narrative prose
    citation:         str          # [CIS x.x] / [NIST ...] tag
    is_final:         bool
    countdown_active: bool
    seconds_remaining: int
    # Economic payload (non-null on synthesis chunk)
    roi_summary:      Optional[dict]  = None
    # Deep audit (hidden behind UI toggle)
    math_trace:       Optional[dict]  = None
    # J-Score snapshot
    j_before:         float = 0.0
    j_after:          float = 0.0
    w_risk:           float = 0.6
    w_cost:           float = 0.4

    def to_ws_dict(self) -> dict[str, Any]:
        """Serialize to the extended War Room WebSocket schema."""
        return {
            # ── Phase 3 base schema fields ─────────────────────────────────
            "event_id":        self.chunk_id,
            "tick_timestamp":  datetime.now(timezone.utc).isoformat(),
            "event_type":      "NarrativeChunk",
            "agent_id":        {
                "threat":     "sentry_node",
                "argument":   "consultant_node",
                "synthesis":  "active_editor",
                "countdown":  "sovereign_gate",
                "veto":       "human_operator",
                "exec":       "remediation_surgeon",
            }.get(self.chunk_type, "system"),
            "trace_id":        self.decision_id,
            "w_R":             self.w_risk,
            "w_C":             self.w_cost,
            "j_score":         self.j_before,
            # ── Phase 5 extended fields ────────────────────────────────────
            "message_body": {
                "chunk_type":        self.chunk_type,
                "heading":           self.heading,
                "body":              self.body,
                "citation":          self.citation,
                "is_final":          self.is_final,
                "countdown_active":  self.countdown_active,
                "seconds_remaining": self.seconds_remaining,
                "j_before":          self.j_before,
                "j_after":           self.j_after,
                "j_delta":           round(self.j_after - self.j_before, 6),
                "j_improvement_pct": round(
                    (self.j_before - self.j_after) / max(self.j_before, 1e-9) * 100, 2
                ),
                "roi_summary":  self.roi_summary,
                "math_trace":   self.math_trace,
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ROI / LABOR WRAPPER
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_roi_summary(ctx: SwarmContext) -> dict[str, Any]:
    """
    Calculate the economic impact of the remediation.

    Components:
      ale_reduction_usd — directly avoided annualized loss
      labor_savings_usd — 4 h × L3 @ $150 = $600 avoided manual work
      rosi              — (ale_reduction - remediation_cost) / remediation_cost
      breakeven_months  — months to recover investment from monthly savings
    """
    ale_reduction = max(0.0, ctx.ale_before - ctx.ale_after)
    labor_savings  = L3_HOURS_PER_FIX * L3_HOURLY_RATE_USD

    if ctx.remediation_cost > 0:
        rosi = (ale_reduction + labor_savings - ctx.remediation_cost) / ctx.remediation_cost
        monthly_savings = (ale_reduction / 12.0) + labor_savings
        breakeven = (
            round(ctx.remediation_cost / monthly_savings, 1)
            if monthly_savings > 0 else float("inf")
        )
    else:
        rosi = float("inf") if ale_reduction + labor_savings > 0 else 0.0
        breakeven = 0.0

    return {
        "ale_before_usd":     round(ctx.ale_before,     2),
        "ale_after_usd":      round(ctx.ale_after,      2),
        "ale_reduction_usd":  round(ale_reduction,      2),
        "labor_savings_usd":  round(labor_savings,      2),
        "remediation_cost_usd": round(ctx.remediation_cost, 2),
        "rosi":               round(rosi, 4) if rosi != float("inf") else "∞",
        "breakeven_months":   breakeven,
        "total_value_created": round(ale_reduction + labor_savings, 2),
        "l3_hours_saved":     L3_HOURS_PER_FIX,
        "l3_hourly_rate_usd": L3_HOURLY_RATE_USD,
    }


def _compute_math_trace(ctx: SwarmContext) -> dict[str, Any]:
    """
    Build the deep-audit math_trace payload.
    Contains Shannon entropy weights, Pareto front, and J components —
    hidden behind the UI 'Deep Dive' toggle for auditors.
    """
    # Shannon Entropy for EWM weights (if not pre-computed, derive from w_R/w_C)
    entropy_weights = ctx.entropy_weights or {
        "risk":  round(ctx.w_risk, 6),
        "cost":  round(ctx.w_cost, 6),
    }

    # Compute entropy of the weight distribution itself
    weights_vec = [v for v in entropy_weights.values() if v > 0]
    k = 1.0 / math.log(max(len(weights_vec), 2))
    shannon_entropy = round(
        -k * sum(p * math.log(p + 1e-15) for p in weights_vec), 6
    )

    return {
        "ewm": {
            "method":          "Shannon Entropy Weight Method (Shannon, 1948)",
            "weights":         entropy_weights,
            "shannon_entropy": shannon_entropy,
            "interpretation":  (
                "Lower entropy → more discriminating criterion → higher EWM weight. "
                f"Current entropy H={shannon_entropy:.4f} "
                f"({'high' if shannon_entropy > 0.7 else 'moderate' if shannon_entropy > 0.3 else 'low'} "
                f"information content)."
            ),
        },
        "pareto_front":  ctx.pareto_front or [
            {"resource_id": ctx.resource_id or "target",
             "risk_norm":   round(1.0 - ctx.j_after, 4),
             "cost_norm":   round(ctx.w_cost * ctx.j_after, 4)}
        ],
        "j_components":  ctx.j_components or [
            {
                "resource_id":   ctx.resource_id or "target",
                "risk_raw":      round(ctx.ale_before / max(ctx.ale_before, 1e-9) * 100, 2),
                "cost_raw":      ctx.resource_cost_usd,
                "j_contribution": round(
                    ctx.w_risk * (1.0 - ctx.j_before) + ctx.w_cost * ctx.j_before, 6
                ),
            }
        ],
        "equilibrium":   {
            "formula":   "J = min Σᵢ (w_R · R̂ᵢ + w_C · Ĉᵢ)",
            "j_before":  ctx.j_before,
            "j_after":   ctx.j_after,
            "j_delta":   round(ctx.j_after - ctx.j_before, 6),
            "w_R":       ctx.w_risk,
            "w_C":       ctx.w_cost,
            "reference": "NSGA-II, Deb et al. (2002)",
        },
        "critic": {
            "method":      "CRITIC (Diakoulaki et al., 1995)",
            "description": (
                "C_j = σ_j × Σ_k (1 - r_jk). "
                "Higher conflict between risk and cost criteria → higher CRITIC weight."
            ),
            "conflict_score": round(abs(ctx.w_risk - ctx.w_cost), 4),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NARRATIVE BUILDER — per block
# ═══════════════════════════════════════════════════════════════════════════════

def _get_citation(drift_type: str, gaps: list[str]) -> str:
    """Resolve the primary compliance citation for a drift type."""
    if gaps:
        return gaps[0]   # Already formatted by KernelMemory
    return CITATIONS.get(drift_type.lower(), CITATIONS["default"])


def _build_threat_block(ctx: SwarmContext) -> NarrativeChunk:
    """
    T+0s — The Sentry's (CISO) Threat Assessment.
    Typewriter stream target: ~3–4 sentences, citation-tagged.
    """
    citation = _get_citation(ctx.drift_type, ctx.compliance_gaps)
    severity_color = {
        "CRITICAL": "CRITICAL ⛔",
        "HIGH":     "HIGH 🔴",
        "MEDIUM":   "MEDIUM 🟡",
        "LOW":      "LOW 🟢",
    }.get(ctx.severity.upper(), ctx.severity)

    sentry_text = ctx.sentry_reasoning or (
        f"Drift type '{ctx.drift_type}' detected on resource {ctx.resource_id}. "
        f"Assessed severity: {severity_color}. "
        f"This represents a direct violation of {citation}. "
        f"If unaddressed, the attack surface permits lateral movement and privilege escalation. "
        f"Immediate threat vector: unauthorized access to regulated data. "
        f"Zero-tolerance posture mandated [NIST SP 800-207 Zero Trust]."
    )

    return NarrativeChunk(
        chunk_id         = f"chunk-{uuid.uuid4().hex[:8]}",
        decision_id      = ctx.decision_id,
        chunk_type       = "threat",
        heading          = f"⚔️ Sentry Assessment — {ctx.severity} Drift Detected",
        body             = sentry_text,
        citation         = citation,
        is_final         = False,
        countdown_active = False,
        seconds_remaining= SOVEREIGN_WINDOW_S,
        j_before         = ctx.j_before,
        j_after          = ctx.j_before,   # No change yet
        w_risk           = ctx.w_risk,
        w_cost           = ctx.w_cost,
    )


def _build_argument_block(ctx: SwarmContext) -> NarrativeChunk:
    """
    T+15s — The Consultant's (Controller) ROI Counter-Argument.
    Focused on ROSI, ALE reduction, cost optimization.
    """
    roi = _compute_roi_summary(ctx)
    ale_text = (
        f"${roi['ale_before_usd']:,.0f} → ${roi['ale_after_usd']:,.0f}"
        if roi['ale_before_usd'] > 0
        else "estimated"
    )
    rosi_text = (
        f"{roi['rosi']:.2f}x" if roi['rosi'] != "∞" else "∞ (zero-cost fix)"
    )

    consultant_text = ctx.consultant_reasoning or (
        f"Economic analysis for resource {ctx.resource_id}. "
        f"Annualized Loss Expectancy (ALE): {ale_text}. "
        f"ALE Reduction: ${roi['ale_reduction_usd']:,.0f}. "
        f"Avoided L3 Engineer labor: {roi['l3_hours_saved']}h × "
        f"${roi['l3_hourly_rate_usd']:.0f}/hr = ${roi['labor_savings_usd']:,.0f}. "
        f"Return on Security Investment (ROSI): {rosi_text}. "
        f"Break-even: {roi['breakeven_months']} month(s). "
        f"Total value created: ${roi['total_value_created']:,.0f}. "
        f"Recommended tier: {ctx.tier.upper()} — minimum viable fix. "
        f"[Gordon & Loeb (2002) Information Security Economics]"
    )

    return NarrativeChunk(
        chunk_id         = f"chunk-{uuid.uuid4().hex[:8]}",
        decision_id      = ctx.decision_id,
        chunk_type       = "argument",
        heading          = "💰 Consultant Counter-Argument — ROI & Cost Model",
        body             = consultant_text,
        citation         = "[Gordon & Loeb (2002)] [NIST AI RMF 1.0]",
        is_final         = False,
        countdown_active = False,
        seconds_remaining= SOVEREIGN_WINDOW_S - int(INTER_BLOCK_DELAY_S),
        roi_summary      = roi,
        j_before         = ctx.j_before,
        j_after          = ctx.j_before,
        w_risk           = ctx.w_risk,
        w_cost           = ctx.w_cost,
    )


def _build_synthesis_block(ctx: SwarmContext) -> NarrativeChunk:
    """
    T+30s — The Orchestrator's Synthesis & finalized J Score.
    Triggers the 60-second countdown. Contains full math_trace.

    Phase 4 Update — J_forecast formula:
      J_forecast = min Σ (w_R · P · R_i + w_C · C_i)
      The AI's 'Pre-Crime' proposal is strictly proportional to the
      certainty of the threat (LSTM probability P). If P is low,
      the weighted risk term is dampened, preventing over-investment
      in unlikely threats.
    """
    math_trace = _compute_math_trace(ctx)
    roi        = _compute_roi_summary(ctx)

    # ── Phase 4: J_forecast with probability weighting ───────────────────────
    P = ctx.forecast_probability  # LSTM prediction probability (0 if no forecast)
    j_forecast_str = ""
    if P > 0.0:
        # J_forecast = min Σ (w_R · P · R_i + w_C · C_i)
        # Simplified single-resource: R_i ≈ (j_before), C_i ≈ w_cost * j_before
        j_forecast = (ctx.w_risk * P * ctx.j_before) + (ctx.w_cost * ctx.j_before)
        j_forecast_str = (
            f"Predictive J-Forecast (Pre-Crime): "
            f"J_fc = w_R·P·R + w_C·C = "
            f"{ctx.w_risk:.2f}·{P:.2f}·{ctx.j_before:.4f} + "
            f"{ctx.w_cost:.2f}·{ctx.j_before:.4f} = {j_forecast:.4f}. "
            f"LSTM threat certainty P={P:.1%} governs remediation proportionality. "
        )
        # Update math_trace with J_forecast
        math_trace["equilibrium"]["j_forecast"] = round(j_forecast, 6)
        math_trace["equilibrium"]["p_forecast"]  = round(P, 4)
        math_trace["equilibrium"]["formula_forecast"] = (
            "J_forecast = min Σ (w_R · P · R_i + w_C · C_i)"
        )

    status_label = {
        "synthesized":    "Active Editor synthesized a Pareto-optimal path",
        "security_wins":  "Sentry's security proposal selected (Pareto-dominant)",
        "cost_wins":      "Controller's cost proposal selected (Pareto-dominant)",
        "no_action":      "No action — J improvement below 1% floor",
        "human_escalation": "Escalated to human operator — no safe proposal",
    }.get(ctx.decision_status, ctx.decision_status)

    synthesis_text = ctx.synthesis_reasoning or (
        f"Orchestrator Synthesis — {status_label}. "
        f"Equilibrium Function J = min Σ (w_R·R̂ᵢ + w_C·Ĉᵢ). "
        f"{j_forecast_str}"
        f"Weights: w_R={ctx.w_risk:.3f} (risk), w_C={ctx.w_cost:.3f} (cost). "
        f"J-Score: {ctx.j_before:.4f} → {ctx.j_after:.4f} "
        f"(Δ = {ctx.j_after - ctx.j_before:+.4f}, "
        f"{(ctx.j_before - ctx.j_after) / max(ctx.j_before, 1e-9) * 100:.1f}% improvement). "
        f"Remedy: {ctx.proposed_action} [{ctx.tier.upper()} tier]. "
        f"Pareto front: {len(math_trace['pareto_front'])} non-dominated solution(s). "
        f"Autonomous execution begins in {SOVEREIGN_WINDOW_S}s unless vetoed. "
        f"[NSGA-II, Deb et al. (2002)] [NIST AI RMF 1.0 — Govern 1.1]"
    )

    # Determine effective countdown (Fast-Pass may shorten it)
    effective_window = SOVEREIGN_WINDOW_S
    if P >= PREDICTIVE_FAST_PASS_THRESHOLD and ctx.is_shadow_ai_forecast:
        effective_window = PREDICTIVE_FAST_PASS_WINDOW_S

    return NarrativeChunk(
        chunk_id          = f"chunk-{uuid.uuid4().hex[:8]}",
        decision_id       = ctx.decision_id,
        chunk_type        = "synthesis",
        heading           = (
            f"⚖️ Active Editor — J={ctx.j_after:.4f}  "
            f"({(ctx.j_before - ctx.j_after) / max(ctx.j_before, 1e-9) * 100:.1f}% governed)"
            + (f" ⚡ FAST-PASS (P={P:.0%})" if P >= PREDICTIVE_FAST_PASS_THRESHOLD and ctx.is_shadow_ai_forecast else "")
        ),
        body              = synthesis_text,
        citation          = "[NSGA-II, Deb (2002)] [NIST AI RMF] [CIS Benchmark v8.0]",
        is_final          = True,
        countdown_active  = True,
        seconds_remaining = effective_window,
        roi_summary       = roi,
        math_trace        = math_trace,
        j_before          = ctx.j_before,
        j_after           = ctx.j_after,
        w_risk            = ctx.w_risk,
        w_cost            = ctx.w_cost,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# NARRATIVE ENGINE  (async streaming generator)
# ═══════════════════════════════════════════════════════════════════════════════

class NarrativeEngine:
    """
    The Cognitive Pulse Streamer.

    Streams the Technical Story block-by-block to the War Room WebSocket
    at human reading speed (T+0, T+15, T+30), synchronizing the machine's
    reasoning cadence with human comprehension bandwidth.

    Usage:
        engine = NarrativeEngine()
        async for chunk_dict in engine.stream_narrative(ctx):
            await ws.send_text(json.dumps(chunk_dict))
    """

    async def stream_narrative(
        self,
        ctx: SwarmContext,
        inter_block_delay: float = INTER_BLOCK_DELAY_S,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Async generator yielding War Room WebSocket dicts.

        Timing:
          T+0s  → THREAT  block  (Sentry CISO assessment)
          T+15s → ARGUMENT block (Consultant ROI model)
          T+30s → SYNTHESIS block (Orchestrator + countdown armed)

        Args:
            ctx: SwarmContext with all agent reasoning and J-score data.
            inter_block_delay: Seconds between blocks (default 15).
        """
        logger.info(
            f"🎙️ NarrativeEngine: streaming for decision {ctx.decision_id} "
            f"({ctx.severity} drift on {ctx.resource_id})"
        )

        # ── T+0s : THREAT ────────────────────────────────────────────────────
        threat = _build_threat_block(ctx)
        logger.debug(f"  → Emitting THREAT chunk {threat.chunk_id}")
        yield threat.to_ws_dict()

        await asyncio.sleep(inter_block_delay)  # T+0 → T+15

        # ── T+15s : ARGUMENT ─────────────────────────────────────────────────
        argument = _build_argument_block(ctx)
        logger.debug(f"  → Emitting ARGUMENT chunk {argument.chunk_id}")
        yield argument.to_ws_dict()

        await asyncio.sleep(inter_block_delay)  # T+15 → T+30

        # ── T+30s : SYNTHESIS (countdown armed) ──────────────────────────────
        synthesis = _build_synthesis_block(ctx)
        logger.debug(f"  → Emitting SYNTHESIS chunk {synthesis.chunk_id}")
        yield synthesis.to_ws_dict()

        logger.info(
            f"🎙️ NarrativeEngine: narrative complete for {ctx.decision_id}. "
            f"Sovereign Gate now active."
        )

    async def stream_one_shot(
        self, ctx: SwarmContext
    ) -> list[dict[str, Any]]:
        """
        Non-streaming version: collect all chunks into a list.
        Used when you need the full narrative without async consumers.
        """
        chunks = []
        async for chunk in self.stream_narrative(ctx, inter_block_delay=0.0):
            chunks.append(chunk)
        return chunks


# ═══════════════════════════════════════════════════════════════════════════════
# SOVEREIGN GATE  — 60-second HITL Approval Window
# ═══════════════════════════════════════════════════════════════════════════════

class SovereignGate:
    """
    The 60-Second Human-in-the-Loop (HITL) Approval Gate.

    After the Orchestrator synthesizes a remediation path, this gate:
      T+0..50s  — countdown events broadcast every second
      T+50s     — CRITICAL_COUNTDOWN pulse (UI turns red, optional sound)
      T+60s     — If no VETO received → auto-execute remediation
                  If VETO received    → log and abort

    Integrates with the War Room WebSocket broadcaster via asyncio.Queue.

    Usage:
        gate = SovereignGate(broadcast_fn=my_broadcast)
        await gate.arm(ctx)             # returns immediately, gate runs in bg
        gate.veto("human reason")       # can be called anytime before T+60
    """

    def __init__(
        self,
        broadcast_fn: Optional[Callable[[dict], Any]] = None,
        on_auto_execute: Optional[Callable[[SwarmContext], Any]] = None,
        on_veto:         Optional[Callable[[str], Any]] = None,
        window_seconds:  int = SOVEREIGN_WINDOW_S,
        alert_at_second: int = CRITICAL_ALERT_S,
    ) -> None:
        self._broadcast_fn    = broadcast_fn        # async fn(dict) → None
        self._on_auto_execute = on_auto_execute     # async fn(SwarmContext) → None
        self._on_veto         = on_veto             # async fn(reason:str) → None
        self._window_s        = window_seconds
        self._alert_s         = alert_at_second

        self._active_ctx:  Optional[SwarmContext] = None
        self._veto_event:  Optional[asyncio.Event] = None
        self._veto_reason: str = ""
        self._task:        Optional[asyncio.Task]  = None

        # ── Phase 4: Predictive Fast-Pass state ──────────────────────────────
        self._fast_pass_triggered: bool = False
        self._fast_pass_original_window: int = window_seconds

    # ── Public interface ──────────────────────────────────────────────────────

    async def arm(self, ctx: SwarmContext) -> None:
        """
        Arm the gate for the given SwarmContext.
        Starts the countdown background task and returns immediately.

        Phase 4 — Predictive Fast-Pass:
          If ctx.forecast_probability ≥ 0.90 AND ctx.is_shadow_ai_forecast,
          the review window is immediately shortened from 60s → 10s.
        """
        if self._task and not self._task.done():
            logger.warning(
                f"⏳ SovereignGate: previous gate still active for "
                f"{self._active_ctx.decision_id if self._active_ctx else '?'}, cancelling."
            )
            self._task.cancel()

        self._active_ctx           = ctx
        self._veto_event           = asyncio.Event()
        self._veto_reason          = ""
        self._fast_pass_triggered  = False

        # ── Predictive Fast-Pass: check before arming ─────────────────────
        effective_window = self._fast_pass_original_window
        if (
            ctx.forecast_probability >= PREDICTIVE_FAST_PASS_THRESHOLD
            and ctx.is_shadow_ai_forecast
        ):
            effective_window = PREDICTIVE_FAST_PASS_WINDOW_S
            self._fast_pass_triggered = True
            self._window_s = PREDICTIVE_FAST_PASS_WINDOW_S
            # alert at T+8 for the shortened window
            self._alert_s  = max(self._alert_s, PREDICTIVE_FAST_PASS_WINDOW_S - 2)
            logger.warning(
                f"⚡ SovereignGate FAST-PASS: P={ctx.forecast_probability:.2%} "
                f"≥ {PREDICTIVE_FAST_PASS_THRESHOLD:.0%} Shadow AI. "
                f"Window reduced {self._fast_pass_original_window}s → {PREDICTIVE_FAST_PASS_WINDOW_S}s. "
                f"Estimated operational waste avoided: ${FAST_PASS_WASTE_SAVINGS_USD:.0f}."
            )
        else:
            self._window_s = self._fast_pass_original_window
            self._alert_s  = CRITICAL_ALERT_S

        self._task = asyncio.create_task(
            self._countdown_loop(ctx),
            name=f"sovereign_gate_{ctx.decision_id}",
        )
        logger.info(
            f"⏳ SovereignGate ARMED: {ctx.decision_id}  "
            f"({self._window_s}s window, alert at T+{self._alert_s}s, "
            f"fast_pass={self._fast_pass_triggered})"
        )

    def veto(self, reason: str = "Human operator override") -> None:
        """
        Veto the pending execution. Thread-safe — can be called from WS handler.
        """
        self._veto_reason = reason
        if self._veto_event:
            # Schedule the event set on the event loop (thread-safe)
            try:
                loop = asyncio.get_event_loop()
                loop.call_soon_threadsafe(self._veto_event.set)
            except RuntimeError:
                if self._veto_event:
                    self._veto_event.set()
        logger.info(f"🛑 SovereignGate VETO received: '{reason}'")

    @property
    def is_active(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Countdown loop ────────────────────────────────────────────────────────

    async def _countdown_loop(self, ctx: SwarmContext) -> None:
        """
        Background coroutine: ticks every second, emits events, handles veto/auto.

        Phase 4 — Predictive Fast-Pass:
          If fast_pass was triggered at arm(), the loop runs for only
          PREDICTIVE_FAST_PASS_WINDOW_S (10s) instead of 60s.
          A Fast-Pass audit entry is emitted at T+0 of the shortened loop.
        """
        # Emit Fast-Pass audit event at the start of a fast-pass gate
        if self._fast_pass_triggered:
            await self._emit_fast_pass_event(ctx)

        for elapsed in range(self._window_s + 1):
            remaining = self._window_s - elapsed

            # ── Check for veto ─────────────────────────────────────────────
            if self._veto_event and self._veto_event.is_set():
                await self._emit_veto(ctx, remaining)
                return

            # ── CRITICAL alert (T+50 normal, T+8 fast-pass) ───────────────
            if elapsed == self._alert_s:
                await self._emit_critical_alert(ctx, remaining)

            # ── Regular countdown tick ─────────────────────────────────────
            elif remaining % 5 == 0 or remaining <= 10:
                await self._emit_tick(ctx, remaining)

            if elapsed < self._window_s:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(asyncio.ensure_future(
                            self._veto_event.wait()
                        )),
                        timeout=1.0,
                    )
                    # Veto was set while waiting
                    await self._emit_veto(ctx, remaining - 1)
                    return
                except asyncio.TimeoutError:
                    pass  # Normal: no veto this second
                except asyncio.CancelledError:
                    return

        # ── Auto-execute (T+60 normal, T+10 fast-pass) ────────────────────
        await self._emit_auto_execute(ctx)

    async def _broadcast(self, payload: dict) -> None:
        """Safe broadcast call — no-ops if no broadcaster configured."""
        if self._broadcast_fn:
            try:
                if asyncio.iscoroutinefunction(self._broadcast_fn):
                    await self._broadcast_fn(payload)
                else:
                    self._broadcast_fn(payload)
            except Exception as exc:
                logger.warning(f"SovereignGate broadcast error: {exc}")

    # ── Event builders ────────────────────────────────────────────────────────

    def _make_countdown_event(
        self,
        ctx: SwarmContext,
        seconds_remaining: int,
        subtype: str,
        heading: str,
        body: str,
        is_critical: bool = False,
    ) -> dict:
        return {
            "event_id":       f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type":     "NarrativeChunk",
            "agent_id":       "sovereign_gate",
            "trace_id":       ctx.decision_id,
            "w_R": ctx.w_risk, "w_C": ctx.w_cost, "j_score": ctx.j_before,
            "message_body": {
                "chunk_type":        "countdown",
                "countdown_subtype": subtype,
                "heading":           heading,
                "body":              body,
                "citation":          "[NIST AI RMF — Govern 1.1] [Sovereign Autonomy SLA]",
                "is_final":          False,
                "countdown_active":  True,
                "is_critical_alert": is_critical,
                "seconds_remaining": seconds_remaining,
                "j_before":          ctx.j_before,
                "j_after":           ctx.j_after,
                "j_delta":           round(ctx.j_after - ctx.j_before, 6),
                "roi_summary":       None,
                "math_trace":        None,
            },
        }

    async def _emit_fast_pass_event(self, ctx: SwarmContext) -> None:
        """
        Phase 4 — Predictive Fast-Pass Audit Event.
        Emitted at the start of a shortened (10s) sovereign window.
        Logs: 'Predictive Fast-Pass triggered: High-confidence Shadow AI
               (P=X). Accelerating remediation to save estimated $250 in
               operational waste.'
        """
        P = ctx.forecast_probability
        evt = {
            "event_id":       f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type":     "NarrativeChunk",
            "agent_id":       "sovereign_gate",
            "trace_id":       ctx.decision_id,
            "w_R": ctx.w_risk, "w_C": ctx.w_cost, "j_score": ctx.j_before,
            "message_body": {
                "chunk_type":        "fast_pass",
                "countdown_subtype": "predictive_fast_pass",
                "heading":           (
                    f"⚡ PREDICTIVE FAST-PASS — High-Confidence Shadow AI (P={P:.0%})"
                ),
                "body": (
                    f"Predictive Fast-Pass triggered: High-confidence Shadow AI "
                    f"(P={P:.4f}). "
                    f"LSTM forecast probability ≥ {PREDICTIVE_FAST_PASS_THRESHOLD:.0%} threshold. "
                    f"Human review window accelerated: "
                    f"{self._fast_pass_original_window}s → {PREDICTIVE_FAST_PASS_WINDOW_S}s. "
                    f"Accelerating remediation to save estimated "
                    f"${FAST_PASS_WASTE_SAVINGS_USD:.0f} in operational waste. "
                    f"Decision: {ctx.decision_id}. "
                    f"Resource: {ctx.resource_id}. "
                    f"Forecast alert: {ctx.forecast_alert_id}. "
                    f"[NIST AI RMF — Govern 1.1 — Adaptive Governance]"
                ),
                "citation":         "[NIST AI RMF — Govern 1.1] [Predictive Remediation SLA]",
                "is_final":         False,
                "countdown_active": True,
                "is_critical_alert": False,
                "is_fast_pass":      True,
                "seconds_remaining": PREDICTIVE_FAST_PASS_WINDOW_S,
                "j_before":         ctx.j_before,
                "j_after":          ctx.j_after,
                "j_delta":          round(ctx.j_after - ctx.j_before, 6),
                "fast_pass_meta": {
                    "forecast_probability":  round(P, 4),
                    "threshold":             PREDICTIVE_FAST_PASS_THRESHOLD,
                    "original_window_s":     self._fast_pass_original_window,
                    "accelerated_window_s":  PREDICTIVE_FAST_PASS_WINDOW_S,
                    "waste_savings_usd":     FAST_PASS_WASTE_SAVINGS_USD,
                    "forecast_alert_id":     ctx.forecast_alert_id,
                },
                "roi_summary":  None,
                "math_trace":   None,
            },
        }
        logger.warning(
            f"⚡ SovereignGate FAST-PASS AUDIT: {ctx.decision_id} — "
            f"P={P:.2%}, window={PREDICTIVE_FAST_PASS_WINDOW_S}s, "
            f"waste_saved=${FAST_PASS_WASTE_SAVINGS_USD:.0f}"
        )
        await self._broadcast(evt)

    async def _emit_tick(self, ctx: SwarmContext, remaining: int) -> None:
        fp_note = f" [⚡ Fast-Pass active]" if self._fast_pass_triggered else ""
        evt = self._make_countdown_event(
            ctx, remaining, "tick",
            heading = f"⏱ Sovereign Gate — {remaining}s remaining{fp_note}",
            body    = (
                f"Awaiting human veto for decision {ctx.decision_id}. "
                f"Proposed action: {ctx.proposed_action} on {ctx.resource_id}. "
                f"Auto-execution in {remaining}s."
                + (f" [Predictive Fast-Pass: P={ctx.forecast_probability:.0%}]" if self._fast_pass_triggered else "")
            ),
        )
        await self._broadcast(evt)

    async def _emit_critical_alert(self, ctx: SwarmContext, remaining: int) -> None:
        evt = self._make_countdown_event(
            ctx, remaining, "critical_alert",
            heading    = f"🚨 CRITICAL ALERT — {remaining}s to Auto-Execution",
            body       = (
                f"FINAL WARNING. The Sovereign Engine will autonomously execute "
                f"'{ctx.proposed_action}' on resource {ctx.resource_id} in {remaining}s. "
                f"Send VETO message to abort. Governance burden of proof satisfied: "
                f"J improvement of {(ctx.j_before - ctx.j_after) / max(ctx.j_before, 1e-9) * 100:.1f}% "
                f"demonstrated over {self._alert_s}s of streamed reasoning. "
                f"[NIST AI RMF — Govern 1.1]"
            ),
            is_critical = True,
        )
        logger.warning(
            f"🚨 SovereignGate CRITICAL ALERT for {ctx.decision_id}: "
            f"{remaining}s remaining"
        )
        await self._broadcast(evt)

    async def _emit_veto(self, ctx: SwarmContext, remaining: int) -> None:
        evt = {
            "event_id":       f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type":     "NarrativeChunk",
            "agent_id":       "human_operator",
            "trace_id":       ctx.decision_id,
            "w_R": ctx.w_risk, "w_C": ctx.w_cost, "j_score": ctx.j_before,
            "message_body": {
                "chunk_type":        "veto",
                "countdown_subtype": "veto",
                "heading":           "✋ VETO RECEIVED — Autonomous Execution Aborted",
                "body": (
                    f"Human operator vetoed decision {ctx.decision_id} with {remaining}s remaining. "
                    f"Reason: '{self._veto_reason}'. "
                    f"Resource {ctx.resource_id} returns to negotiation queue. "
                    f"Sovereignty boundary honored. [NIST AI RMF — Govern 6.2]"
                ),
                "citation":          "[NIST AI RMF — Govern 6.2]",
                "is_final":          True,
                "countdown_active":  False,
                "seconds_remaining": remaining,
                "j_before": ctx.j_before, "j_after": ctx.j_before,
                "j_delta": 0.0,
                "veto_reason":   self._veto_reason,
                "roi_summary":   None,
                "math_trace":    None,
            },
        }
        await self._broadcast(evt)
        if self._on_veto:
            try:
                if asyncio.iscoroutinefunction(self._on_veto):
                    await self._on_veto(self._veto_reason)
                else:
                    self._on_veto(self._veto_reason)
            except Exception as exc:
                logger.error(f"on_veto callback error: {exc}")

    async def _emit_auto_execute(self, ctx: SwarmContext) -> None:
        evt = {
            "event_id":       f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type":     "NarrativeChunk",
            "agent_id":       "remediation_surgeon",
            "trace_id":       ctx.decision_id,
            "w_R": ctx.w_risk, "w_C": ctx.w_cost, "j_score": ctx.j_after,
            "message_body": {
                "chunk_type":        "exec",
                "countdown_subtype": "auto_execute",
                "heading":           "⚡ AUTONOMOUS EXECUTION — Sovereign Directive Activated",
                "body": (
                    f"60-second window elapsed. No VETO received. "
                    f"Autonomous execution triggered for decision {ctx.decision_id}. "
                    f"Action: {ctx.proposed_action} on {ctx.resource_id} "
                    f"[{ctx.tier.upper()} tier]. "
                    f"J-Score: {ctx.j_before:.4f} → {ctx.j_after:.4f}. "
                    f"Audit log: 'Autonomous execution due to human latency. "
                    f"10-second audible/visual warning provided at T+50s.' "
                    f"[NIST AI RMF — Manage 4.1]"
                ),
                "citation":          "[NIST AI RMF — Manage 4.1]",
                "is_final":          True,
                "countdown_active":  False,
                "seconds_remaining": 0,
                "j_before": ctx.j_before, "j_after": ctx.j_after,
                "j_delta":  round(ctx.j_after - ctx.j_before, 6),
                "roi_summary":  _compute_roi_summary(ctx),
                "math_trace":   None,
            },
        }
        logger.info(
            f"⚡ SovereignGate AUTO-EXECUTE: {ctx.decision_id} — "
            f"'{ctx.proposed_action}' on {ctx.resource_id}. "
            f"Audit: 10s visual warning provided at T+50s."
        )
        await self._broadcast(evt)
        if self._on_auto_execute:
            try:
                if asyncio.iscoroutinefunction(self._on_auto_execute):
                    await self._on_auto_execute(ctx)
                else:
                    self._on_auto_execute(ctx)
            except Exception as exc:
                logger.error(f"on_auto_execute callback error: {exc}")


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FACTORY  — wire into streamer.py
# ═══════════════════════════════════════════════════════════════════════════════

def build_swarm_context(
    decision_result: dict[str, Any],
    kernel_memory_ctx: Optional[dict[str, Any]] = None,
    resource_context:  Optional[dict[str, Any]] = None,
) -> SwarmContext:
    """
    Build a SwarmContext from the output dicts of ActiveEditor.synthesize()
    and KernelMemory, ready to feed into NarrativeEngine.

    Args:
        decision_result:  SynthesisResult.to_dict() output.
        kernel_memory_ctx: KernelMemory.get_sentry_context() output.
        resource_context: Raw resource dict (monthly_cost_usd, etc.).

    Returns:
        SwarmContext ready for streaming.
    """
    km = kernel_memory_ctx or {}
    rc = resource_context  or {}

    # Derive ALE from resource value × drift severity heuristics
    asset_value = rc.get("asset_value_usd", rc.get("monthly_cost_usd", 500.0) * 12)
    sev_exposure = {
        "CRITICAL": 0.9, "HIGH": 0.6, "MEDIUM": 0.3, "LOW": 0.1
    }
    sev   = km.get("severity_assessment", "MEDIUM").upper()
    exp_f = sev_exposure.get(sev, 0.3)
    ale_before = asset_value * exp_f * 1.5   # ARO assumption: 1.5 incidents/year
    ale_after  = ale_before  * (1.0 - 0.7)   # 70% risk reduction post-fix

    drift_type  = ""
    affected    = km.get("affected_resources", [])
    if affected:
        drift_type = affected[0].get("drift_type", "")

    return SwarmContext(
        decision_id       = decision_result.get("decision_id", f"dec-{uuid.uuid4().hex[:8]}"),
        resource_id       = rc.get("resource_id",  affected[0].get("resource_id", "") if affected else ""),
        drift_type        = drift_type,
        severity          = sev,
        environment       = decision_result.get("environment", "production"),
        sentry_reasoning  = "",   # filled in from agent proposals if available
        consultant_reasoning = "",
        synthesis_reasoning  = decision_result.get("reasoning", ""),
        decision_status   = decision_result.get("status", "synthesized"),
        j_before          = decision_result.get("j_before", 0.5),
        j_after           = decision_result.get("j_after",  0.4),
        w_risk            = decision_result.get("w_risk",   0.6),
        w_cost            = decision_result.get("w_cost",   0.4),
        ale_before        = ale_before,
        ale_after         = ale_after,
        remediation_cost  = rc.get("remediation_cost", 50.0),
        resource_cost_usd = rc.get("monthly_cost_usd",  0.0),
        compliance_gaps   = km.get("compliance_gaps", []),
        proposed_action   = (
            (decision_result.get("winning_proposal") or
             decision_result.get("synthesized_proposal") or {}).get("commands", [{}])[0]
            .get("action", "remediate")
            if (decision_result.get("winning_proposal") or
                decision_result.get("synthesized_proposal")) else "remediate"
        ),
        tier              = (
            (decision_result.get("winning_proposal") or
             decision_result.get("synthesized_proposal") or {}).get("tier", "silver")
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# NARRATIVE BATCHING — "CLUSTER EFFECT"  (Phase 8 Parallel Hardening)
# ═══════════════════════════════════════════════════════════════════════════════

# How close two Shadow_AI_Forecast signals must be (seconds) to be clustered
CLUSTER_WINDOW_SECONDS:   float = 8.0
# Minimum signals in window to emit a Cluster Block instead of individual ones
CLUSTER_MIN_SIGNALS:      int   = 2

@dataclass
class SignalEvent:
    """A single Shadow_AI_Forecast signal arriving from the chaos storm."""
    signal_id:      str
    resource_id:    str
    drift_type:     str
    severity:       str
    forecast_prob:  float
    arrived_at:     datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context:        dict[str, Any] = field(default_factory=dict)


@dataclass
class ClusterBlock:
    """
    A single 'Sovereign Reflex Cluster Block' synthesized for the War Room
    when multiple Shadow_AI_Forecast signals arrive within CLUSTER_WINDOW_SECONDS.

    Instead of flooding the War Room with 50 individual narrative streams,
    NarrativeBatcher synthesizes ONE Cluster Block:
      - Lists all clustered resources
      - Aggregates mean probability
      - Proposes a coordinated multi-resource remediation
    """
    cluster_id:       str = field(default_factory=lambda: f"cblk-{uuid.uuid4().hex[:8]}")
    formed_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signals:          list[SignalEvent] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.signals)

    @property
    def mean_probability(self) -> float:
        if not self.signals:
            return 0.0
        return sum(s.forecast_prob for s in self.signals) / len(self.signals)

    @property
    def max_severity(self) -> str:
        order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        found = set(s.severity.upper() for s in self.signals)
        for sev in order:
            if sev in found:
                return sev
        return "INFO"

    @property
    def affected_resources(self) -> list[str]:
        return [s.resource_id for s in self.signals]

    def to_ws_dict(self) -> dict[str, Any]:
        """Serialize to War Room WebSocket schema — 'cluster' chunk_type."""
        resource_list = "\n".join(
            f"  [{i+1}] {s.resource_id[:60]}  P={s.forecast_prob:.0%}  {s.severity}"
            for i, s in enumerate(self.signals[:20])
        )
        body = (
            f"⚡ SOVEREIGN REFLEX CLUSTER — {self.size} concurrent Shadow AI signals "
            f"detected within {CLUSTER_WINDOW_SECONDS:.0f}s window.\n\n"
            f"Mean confidence: P={self.mean_probability:.2%}  "
            f"Max severity: {self.max_severity}\n\n"
            f"Affected resources:\n{resource_list}\n\n"
            f"The Narrative Engine has synthesized a coordinated Cluster Block "
            f"instead of {self.size} individual War Room streams. "
            f"All {self.size} resources are queued for parallel remediation "
            f"under CollisionManager lock discipline. "
            f"[NIST AI RMF — Govern 1.1] [CIS Control 6 — Maintenance]"
        )
        return {
            "event_id":       f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": self.formed_at.isoformat(),
            "event_type":     "NarrativeChunk",
            "agent_id":       "narrative_batcher",
            "trace_id":       self.cluster_id,
            "w_R":            0.6, "w_C": 0.4,
            "j_score":        0.0,
            "message_body": {
                "chunk_type":          "cluster",
                "heading":             (
                    f"🌩️  SOVEREIGN REFLEX CLUSTER — {self.size} simultaneous "
                    f"Shadow AI signals (P={self.mean_probability:.0%})"
                ),
                "body":                body,
                "citation":            "[NIST AI RMF — Govern 1.1] [Phase 8 Parallel Hardening]",
                "is_final":            True,
                "countdown_active":    False,
                "seconds_remaining":   0,
                "cluster_meta": {
                    "cluster_id":         self.cluster_id,
                    "signal_count":       self.size,
                    "mean_probability":   round(self.mean_probability, 4),
                    "max_severity":       self.max_severity,
                    "window_seconds":     CLUSTER_WINDOW_SECONDS,
                    "affected_resources": self.affected_resources[:50],
                    "formed_at":          self.formed_at.isoformat(),
                },
                "roi_summary":  None,
                "math_trace":   None,
            },
        }


class NarrativeBatcher:
    """
    Phase 8 — Narrative Batching Engine ("Cluster Effect").

    Monitors incoming Shadow_AI_Forecast signals. When multiple signals
    arrive within CLUSTER_WINDOW_SECONDS, it:
      1. Buffers them into a ClusterBlock instead of individual narratives
      2. Emits ONE 'Sovereign Reflex Cluster Block' to the War Room
      3. Returns individual contexts only after the cluster is closed

    Thread-safe: uses threading.RLock for all mutable state.

    Usage:
        batcher = NarrativeBatcher(broadcast_fn=ws.send_text)

        # Called for each arriving signal (from chaos storm thread pool)
        result = batcher.ingest_signal(signal)
        if result == "clustered":
            pass  # narrative handled by cluster block
        else:
            # result is a ClusterBlock (freshly flushed) or "solo"
            await engine.stream_narrative(individual_ctx)
    """

    def __init__(
        self,
        broadcast_fn: Optional[Callable[[dict], Any]] = None,
        cluster_window: float = CLUSTER_WINDOW_SECONDS,
        min_signals:    int   = CLUSTER_MIN_SIGNALS,
    ) -> None:
        self._broadcast_fn    = broadcast_fn
        self._cluster_window  = cluster_window
        self._min_signals     = min_signals
        self._state_lock      = threading.RLock()

        # Current open cluster
        self._current_cluster: Optional[ClusterBlock] = None
        self._last_signal_at:  Optional[datetime]     = None

        # History
        self._emitted_clusters: list[ClusterBlock] = []
        self._solo_count: int = 0

        logger.info(
            f"[NarrativeBatcher] Initialized (window={cluster_window}s, "
            f"min_signals={min_signals})"
        )

    def ingest_signal(
        self,
        signal: SignalEvent,
        force_flush: bool = False,
    ) -> str:
        """
        Ingest a single Shadow_AI_Forecast signal.

        Returns:
            "clustered"              — merged into open cluster, no immediate emit
            "solo"                   — below min_signals, caller should stream individually
            "<cluster_id>"           — cluster was flushed (the id of the emitted block)
        """
        now = signal.arrived_at
        with self._state_lock:
            # Is there an open cluster AND the new signal arrived within the window?
            if (
                self._current_cluster is not None
                and self._last_signal_at is not None
                and (now - self._last_signal_at).total_seconds() <= self._cluster_window
            ):
                # Merge into open cluster
                self._current_cluster.signals.append(signal)
                self._last_signal_at = now
                logger.debug(
                    f"[NarrativeBatcher] Signal {signal.signal_id} merged into "
                    f"cluster {self._current_cluster.cluster_id} "
                    f"(size={self._current_cluster.size})"
                )
                return "clustered"

            # No open cluster OR window expired — we may need to flush the old one
            old_cluster = self._current_cluster
            if old_cluster is not None and old_cluster.size >= self._min_signals:
                self._flush_cluster(old_cluster)
                flushed_id = old_cluster.cluster_id
            else:
                flushed_id = None

            # Open a new cluster with this signal
            self._current_cluster = ClusterBlock(signals=[signal])
            self._last_signal_at  = now

            if flushed_id:
                return flushed_id

            # New cluster started — not enough signals yet → return "clustered"
            return "clustered"

    def flush(self) -> Optional[ClusterBlock]:
        """
        Force-flush the current open cluster.
        Call this after the chaos storm completes to emit any remaining signals.
        Returns the flushed ClusterBlock, or None if below min_signals.
        """
        with self._state_lock:
            cluster = self._current_cluster
            self._current_cluster = None
            self._last_signal_at  = None

        if cluster is None:
            return None

        if cluster.size >= self._min_signals:
            self._flush_cluster(cluster)
            return cluster

        # Too small → treat each as solo
        self._solo_count += cluster.size
        logger.info(
            f"[NarrativeBatcher] Cluster below min_signals ({cluster.size} < "
            f"{self._min_signals}) — treating as {cluster.size} solo signal(s)"
        )
        return None

    def _flush_cluster(self, cluster: ClusterBlock) -> None:
        """Emit the cluster block to the broadcast function and record it."""
        payload = cluster.to_ws_dict()
        logger.warning(
            f"[NarrativeBatcher] 🌩️  CLUSTER BLOCK EMITTED {cluster.cluster_id}: "
            f"{cluster.size} signals, P={cluster.mean_probability:.0%}, "
            f"severity={cluster.max_severity}"
        )
        if self._broadcast_fn:
            try:
                self._broadcast_fn(payload)
            except Exception as exc:
                logger.error(f"[NarrativeBatcher] Broadcast error: {exc}")
        self._emitted_clusters.append(cluster)

    def get_stats(self) -> dict[str, Any]:
        with self._state_lock:
            pending_size = self._current_cluster.size if self._current_cluster else 0
        return {
            "clusters_emitted":   len(self._emitted_clusters),
            "solo_signals":       self._solo_count,
            "pending_cluster_sz": pending_size,
            "cluster_window_s":   self._cluster_window,
            "min_signals":        self._min_signals,
            "total_clustered":    sum(c.size for c in self._emitted_clusters),
        }

    def get_emitted_clusters(self) -> list[dict[str, Any]]:
        return [c.to_ws_dict() for c in self._emitted_clusters]
