"""
CLOUDGUARD-B — PHASE 4 DISSIPATION HANDLER & THREAT HORIZON OVERLAY
======================================================================
Handles two responsibilities:

1. DissipationHandler
   ─────────────────
   Monitors the LSTM P-score history for an active Amber Alert.
   If P drops below AMBER_THRESHOLD (0.75), it:
     a. Auto-closes the Alert (sets a dissipation event).
     b. Generates a structured "Dissipation Log" for the War Room:
        "Threat Horizon OMEGA-999 dissipated. Probability dropped from
         [X%] to [Y%]. No action taken."
     c. Emits a FORECAST_SIGNAL with type="Dissipated" to the WebSocket.

2. AttackPathResolver
   ──────────────────
   Given a ForecastResult with a detected recon_pattern, builds a list
   of `transitive_nodes` describing the lateral movement graph:
     Compromised Role → IAM Policy → Targeted S3 Bucket → ...
   Emits a THREAT_HORIZON_OVERLAY event to the War Room frontend so it
   can draw a translucent Orange Attack Path on the topology graph.

Mathematical note on P-threshold:
   AMBER_THRESHOLD = 0.75  (defined in threat_forecaster.py)
   Dissipation is triggered when P < AMBER_THRESHOLD for
   DISSIPATION_COOLDOWN_TICKS consecutive ticks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("cloudguard.dissipation")

# ─── Thresholds ────────────────────────────────────────────────────────────────
AMBER_THRESHOLD          = 0.75   # Must match threat_forecaster.AMBER_THRESHOLD
DISSIPATION_COOLDOWN_TICKS = 3    # P must fall below threshold for N ticks to dissipate
OMEGA_COUNTER_SEED       = 999    # Starting ID for Threat Horizon labels (cosmetic)

# ─── Attack path node types ────────────────────────────────────────────────────
_RECON_CHAIN_GRAPH: dict[str, list[dict[str, str]]] = {
    # IAM Recon → Policy Exploit → S3 Exfiltration
    "DescribeRoles→DescribeRoles→ModifyPolicy": [
        {"node_id": "iam-role-compromised",  "label": "Compromised IAM Role",    "type": "iam_role"},
        {"node_id": "iam-policy-modified",   "label": "Modified IAM Policy",     "type": "iam_policy"},
        {"node_id": "s3-bucket-target",      "label": "Targeted S3 Bucket",      "type": "s3_bucket"},
        {"node_id": "data-plane-exfil",      "label": "Data Exfiltration Vector","type": "data_plane"},
    ],
    # S3 Enumeration → Public Bucket Takeover
    "ListBuckets→ListBuckets→PutBucketPolicy": [
        {"node_id": "s3-enum-origin",        "label": "S3 Enumeration Origin",   "type": "api_call"},
        {"node_id": "s3-bucket-public",      "label": "Targeted Public Bucket",  "type": "s3_bucket"},
        {"node_id": "data-exposed",          "label": "Exposed Data Asset",      "type": "data_asset"},
    ],
    # Lateral Movement via Cross-Account
    "AssumeRole→CreateUser→AttachRolePolicy": [
        {"node_id": "cross-account-pivot",   "label": "Cross-Account AssumeRole","type": "iam_role"},
        {"node_id": "shadow-user-created",   "label": "Shadow User Created",     "type": "iam_user"},
        {"node_id": "policy-attached",       "label": "Privilege Policy Attached","type": "iam_policy"},
        {"node_id": "admin-access-gained",   "label": "Admin Access Gained",     "type": "escalation"},
    ],
    # OIDC Pre-Breach Recon Kill-Chain
    "DescribeRoles→DescribeRoles→DescribeRoles→AssumeRole→CreateRole": [
        {"node_id": "oidc-recon-start",      "label": "OIDC Recon Entry Point",  "type": "api_call"},
        {"node_id": "iam-role-enumerated",   "label": "Enumerated IAM Roles",    "type": "iam_role"},
        {"node_id": "assume-role-pivot",     "label": "AssumeRole Pivot",        "type": "iam_role"},
        {"node_id": "new-role-created",      "label": "Attacker-Controlled Role","type": "iam_role"},
        {"node_id": "oidc-breach-target",    "label": "OIDC Trust Breach Vector","type": "oidc_provider"},
    ],
    # Bulk Data Access (5× GetObject)
    "GetObject→GetObject→GetObject→GetObject→GetObject": [
        {"node_id": "bulk-read-origin",      "label": "Bulk Read Origin",        "type": "api_call"},
        {"node_id": "s3-data-store",         "label": "Bulk-Read S3 Store",      "type": "s3_bucket"},
        {"node_id": "data-exfil-endpoint",   "label": "Exfiltration Endpoint",   "type": "network"},
    ],
    # Short Amber Sequence
    "DescribeRoles→DescribeRoles→DescribeRoles→AssumeRole": [
        {"node_id": "oidc-recon-start",      "label": "OIDC Recon Entry Point",  "type": "api_call"},
        {"node_id": "iam-role-enumerated",   "label": "Enumerated IAM Roles",    "type": "iam_role"},
        {"node_id": "assume-role-target",    "label": "Target Role Identified",  "type": "iam_role"},
    ],
}

# Fallback generic attack path for unknown recon chains
_DEFAULT_ATTACK_PATH = [
    {"node_id": "entry-point",    "label": "Attacker Entry Point",  "type": "api_call"},
    {"node_id": "pivot-resource", "label": "Pivot Resource",        "type": "resource"},
    {"node_id": "target-asset",   "label": "Target Asset",          "type": "data_asset"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AmberAlertRecord:
    """
    Tracks the lifecycle of a single Amber Alert session.
    An alert is 'open' from the moment P ≥ 0.75 until it either:
      - Dissipates (P drops below threshold for N ticks), or
      - Is resolved by human operator action via ValidationQueue.
    """
    alert_id: str = field(default_factory=lambda: f"OMEGA-{OMEGA_COUNTER_SEED}")
    target_resource_id: str = ""
    predicted_drift_type: str = ""
    open_probability: float = 0.0       # P when alert was opened
    current_probability: float = 0.0    # Most recent P value
    peak_probability: float = 0.0       # Highest P observed
    ticks_below_threshold: int = 0      # Consecutive ticks with P < 0.75
    is_open: bool = True
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    transitive_nodes: list[dict] = field(default_factory=list)
    recon_pattern_name: str = ""
    p_history: list[float] = field(default_factory=list)   # Full P trace


@dataclass
class DissipationLog:
    """
    Structured Dissipation Log entry for the War Room narrative.
    Emitted when an Amber Alert auto-closes.
    """
    alert_id: str
    target_resource_id: str
    p_open: float          # Probability when alert was first raised
    p_close: float         # Probability when alert dissipated
    peak_p: float          # Peak probability observed
    recon_pattern: str
    dissipation_reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_war_room_narrative(self) -> str:
        """Human-readable War Room message per narrative spec."""
        return (
            f"Threat Horizon {self.alert_id} dissipated. "
            f"Probability dropped from {self.p_open:.1%} to {self.p_close:.1%}. "
            f"No action taken. "
            f"Peak threat probability: {self.peak_p:.1%}. "
            f"Recon chain '{self.recon_pattern}' no longer progressing. "
            f"[NIST AI RMF — Govern 5.2 — Adaptive Threat Posture]"
        )

    def to_ws_payload(self) -> dict[str, Any]:
        """Build a FORECAST_SIGNAL WebSocket payload for the dissipation event."""
        return {
            "event_type": "FORECAST_SIGNAL",
            "event_id":   f"evt-{uuid.uuid4().hex[:8]}",
            "agent_id":   "dissipation_handler",
            "trace_id":   self.alert_id,
            "data": {
                "target":          self.target_resource_id,
                "probability":     round(self.p_close, 4),
                "type":            "Dissipated",
                "horizon":         "0 ticks",
                "predicted_drift": "none",
                "is_shadow_ai":    False,
                "j_forecast":      0.0,
                "recon_chain":     self.recon_pattern or None,
                "confidence_lo":   0.0,
                "confidence_hi":   0.0,
                # Extended dissipation fields
                "dissipation": {
                    "alert_id":   self.alert_id,
                    "p_open":     round(self.p_open,  4),
                    "p_close":    round(self.p_close, 4),
                    "peak_p":     round(self.peak_p,  4),
                    "narrative":  self.to_war_room_narrative(),
                    "reason":     self.dissipation_reason,
                    "closed_at":  self.timestamp.isoformat(),
                },
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ATTACK PATH RESOLVER
# ═══════════════════════════════════════════════════════════════════════════════

class AttackPathResolver:
    """
    Resolves a recon pattern name into a chain of transitive nodes
    suitable for the Threat Horizon Overlay in the War Room UI.

    The frontend listens for THREAT_HORIZON_OVERLAY events and draws
    translucent Orange edges connecting the resolved topology nodes.

    Node Schema:
        {
            "node_id": str,    — matches topology resource ID if real
            "label":   str,    — human-readable label
            "type":    str,    — iam_role | s3_bucket | iam_policy | network | ...
            "resource_id": str — actual resource to highlight (if any)
        }
    """

    def resolve(
        self,
        recon_pattern_name: str,
        target_resource_id: str = "",
    ) -> list[dict[str, Any]]:
        """
        Return the ordered list of transitive_nodes for a given recon pattern.

        Args:
            recon_pattern_name: The pattern name string (e.g. "DescribeRoles→…")
            target_resource_id: The real resource ID to anchor the last node.

        Returns:
            List of node dicts with node_id, label, type, and resource_id.
        """
        # Look up the template path
        path_template = _RECON_CHAIN_GRAPH.get(
            recon_pattern_name, _DEFAULT_ATTACK_PATH
        )

        # Clone and enrich with real resource ID on the terminal node
        path = [dict(node) for node in path_template]
        if path and target_resource_id:
            path[-1]["resource_id"] = target_resource_id
            path[-1]["node_id"]     = target_resource_id

        return path

    def build_overlay_event(
        self,
        alert_id: str,
        recon_pattern_name: str,
        target_resource_id: str,
        probability: float,
    ) -> dict[str, Any]:
        """
        Build a THREAT_HORIZON_OVERLAY WebSocket event payload.
        This is the trigger for the frontend to draw the orange attack path.

        Payload schema:
            event_type: "THREAT_HORIZON_OVERLAY"
            data:
              alert_id    — OMEGA-NNN identifier
              probability — P score at time of overlay
              color       — "orange" (Amber Alert visual)
              transitive_nodes — ordered list of graph nodes
              recon_pattern    — human-readable chain description
        """
        nodes = self.resolve(recon_pattern_name, target_resource_id)

        return {
            "event_type": "THREAT_HORIZON_OVERLAY",
            "event_id":   f"evt-{uuid.uuid4().hex[:8]}",
            "agent_id":   "threat_forecaster",
            "trace_id":   alert_id,
            "data": {
                "alert_id":        alert_id,
                "target":          target_resource_id,
                "probability":     round(probability, 4),
                "color":           "orange",
                "recon_pattern":   recon_pattern_name,
                "transitive_nodes": nodes,
                "label":           (
                    f"Threat Horizon {alert_id}: "
                    f"High-probability recon sequence detected (P={probability:.1%}). "
                    f"Attack path: {' → '.join(n['label'] for n in nodes)}"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# DISSIPATION HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

class DissipationHandler:
    """
    Phase 4 Auto-Close & Dissipation Logging Engine.

    Lifecycle:
      1. A new Amber Alert fires (P ≥ 0.75) → call open_alert(result).
      2. Each subsequent prediction tick → call update(result).
         • If P ≥ 0.75: update stats, re-emit overlay if pattern changed.
         • If P < 0.75 for N=3 consecutive ticks: auto-close.
      3. On auto-close: generate DissipationLog → emit to War Room.

    The handler also generates the THREAT_HORIZON_OVERLAY event on every
    new Amber Alert or when the recon chain is first detected.

    Usage:
        handler = DissipationHandler(broadcast_fn=my_ws_broadcast)
        # Called by ThreatForecaster / ProactiveSentry
        await handler.open_alert(forecast_result)
        await handler.update(new_forecast_result)
    """

    def __init__(
        self,
        broadcast_fn: Optional[Callable[[dict], Any]] = None,
        cooldown_ticks: int = DISSIPATION_COOLDOWN_TICKS,
    ) -> None:
        self._broadcast_fn  = broadcast_fn
        self._cooldown      = cooldown_ticks
        self._path_resolver = AttackPathResolver()

        # Active alerts: alert_id → AmberAlertRecord
        self._active_alerts: dict[str, AmberAlertRecord] = {}
        # Closed alert archive
        self._dissipation_log: deque[DissipationLog] = deque(maxlen=500)

        # Monotonic OMEGA counter
        self._omega_seq = 0

    # ─── Public API ───────────────────────────────────────────────────────────

    async def open_alert(self, result: "ForecastResult") -> AmberAlertRecord:  # type: ignore[name-defined]
        """
        Register a new Amber Alert from a ForecastResult.
        Emits a THREAT_HORIZON_OVERLAY event with the attack path.

        Args:
            result: ForecastResult with is_amber_alert=True.

        Returns:
            The newly created AmberAlertRecord.
        """
        self._omega_seq += 1
        alert_id = f"OMEGA-{self._omega_seq:03d}"

        nodes = self._path_resolver.resolve(
            result.recon_pattern_name,
            result.target_resource_id,
        )

        record = AmberAlertRecord(
            alert_id           = alert_id,
            target_resource_id = result.target_resource_id,
            predicted_drift_type = result.predicted_drift_type,
            open_probability   = result.probability,
            current_probability= result.probability,
            peak_probability   = result.probability,
            ticks_below_threshold = 0,
            is_open            = True,
            transitive_nodes   = nodes,
            recon_pattern_name = result.recon_pattern_name,
            p_history          = [result.probability],
        )
        self._active_alerts[alert_id] = record

        logger.warning(
            f"🟠 DissipationHandler: Amber Alert OPENED — {alert_id} "
            f"P={result.probability:.2%} on {result.target_resource_id}"
        )

        # Emit attack-path overlay
        overlay = self._path_resolver.build_overlay_event(
            alert_id           = alert_id,
            recon_pattern_name = result.recon_pattern_name,
            target_resource_id = result.target_resource_id,
            probability        = result.probability,
        )
        await self._broadcast(overlay)

        return record

    async def update(
        self,
        result: "ForecastResult",  # type: ignore[name-defined]
        alert_id: Optional[str] = None,
    ) -> Optional[DissipationLog]:
        """
        Update active alerts with the latest prediction probability.
        If P drops below AMBER_THRESHOLD for COOLDOWN_TICKS consecutive
        ticks, auto-close the alert and emit a Dissipation Log.

        Args:
            result:   Latest ForecastResult from ThreatForecaster.predict_tick().
            alert_id: Specific alert to update (if None, updates first open alert).

        Returns:
            DissipationLog if an alert dissipated, else None.
        """
        if not self._active_alerts:
            return None

        # Identify which alert to update
        target_id = alert_id or next(iter(self._active_alerts))
        record = self._active_alerts.get(target_id)
        if not record or not record.is_open:
            return None

        p = result.probability
        record.current_probability = p
        record.peak_probability    = max(record.peak_probability, p)
        record.p_history.append(p)

        if p < AMBER_THRESHOLD:
            record.ticks_below_threshold += 1
            logger.debug(
                f"🔽 {target_id}: P={p:.2%} below threshold "
                f"({record.ticks_below_threshold}/{self._cooldown} ticks)"
            )
        else:
            # P is still high — reset cooldown, update overlay if chain changed
            record.ticks_below_threshold = 0
            if result.recon_pattern_name and result.recon_pattern_name != record.recon_pattern_name:
                record.recon_pattern_name = result.recon_pattern_name
                record.transitive_nodes = self._path_resolver.resolve(
                    result.recon_pattern_name, result.target_resource_id
                )
                overlay = self._path_resolver.build_overlay_event(
                    alert_id           = target_id,
                    recon_pattern_name = result.recon_pattern_name,
                    target_resource_id = result.target_resource_id,
                    probability        = p,
                )
                await self._broadcast(overlay)

        # Auto-close check
        if record.ticks_below_threshold >= self._cooldown:
            return await self._dissipate(record, p)

        return None

    async def force_close(
        self, alert_id: str, reason: str = "Operator closed"
    ) -> Optional[DissipationLog]:
        """
        Manually close an active alert (e.g., after human remediation).
        """
        record = self._active_alerts.get(alert_id)
        if not record or not record.is_open:
            return None
        return await self._dissipate(record, record.current_probability, reason)

    @property
    def active_alert_count(self) -> int:
        return sum(1 for r in self._active_alerts.values() if r.is_open)

    @property
    def dissipation_history(self) -> list[DissipationLog]:
        return list(self._dissipation_log)

    def get_active_alerts(self) -> list[AmberAlertRecord]:
        return [r for r in self._active_alerts.values() if r.is_open]

    # ─── Internal ─────────────────────────────────────────────────────────────

    async def _dissipate(
        self,
        record: AmberAlertRecord,
        final_p: float,
        reason: str = "P-score fell below 0.75 threshold",
    ) -> DissipationLog:
        """Close an alert, build the DissipationLog, broadcast to War Room."""
        record.is_open   = False
        record.closed_at = datetime.now(timezone.utc)

        log = DissipationLog(
            alert_id           = record.alert_id,
            target_resource_id = record.target_resource_id,
            p_open             = record.open_probability,
            p_close            = final_p,
            peak_p             = record.peak_probability,
            recon_pattern      = record.recon_pattern_name,
            dissipation_reason = reason,
        )
        self._dissipation_log.append(log)

        logger.info(
            f"✅ DissipationHandler: Alert DISSIPATED — {record.alert_id}. "
            f"P: {record.open_probability:.2%} → {final_p:.2%}. "
            f"Narrative: {log.to_war_room_narrative()}"
        )

        # Broadcast dissipation to War Room
        payload = log.to_ws_payload()
        await self._broadcast(payload)

        # Also emit a War Room narrative chunk (in-line dissipation log)
        narrative_evt = self._build_narrative_event(log)
        await self._broadcast(narrative_evt)

        # Remove from active alerts dict
        self._active_alerts.pop(record.alert_id, None)

        return log

    def _build_narrative_event(self, log: DissipationLog) -> dict[str, Any]:
        """
        Build a NarrativeChunk-style event for the War Room
        so the dissipation appears in the narrative stream alongside
        other Cognitive Pulse blocks.
        """
        return {
            "event_id":       f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type":     "NarrativeChunk",
            "agent_id":       "dissipation_handler",
            "trace_id":       log.alert_id,
            "w_R": 0.6, "w_C": 0.4, "j_score": 0.0,
            "message_body": {
                "chunk_type":        "dissipation",
                "heading":           f"🟢 Threat Horizon {log.alert_id} — DISSIPATED",
                "body":              log.to_war_room_narrative(),
                "citation":          "[NIST AI RMF — Govern 5.2] [Adaptive Threat Posture]",
                "is_final":          True,
                "countdown_active":  False,
                "seconds_remaining": 0,
                "j_before":          log.p_open,
                "j_after":           log.p_close,
                "j_delta":           round(log.p_close - log.p_open, 4),
                "roi_summary":       None,
                "math_trace":        None,
                "dissipation_meta": {
                    "alert_id":   log.alert_id,
                    "p_open":     round(log.p_open,  4),
                    "p_close":    round(log.p_close, 4),
                    "peak_p":     round(log.peak_p,  4),
                    "reason":     log.dissipation_reason,
                },
            },
        }

    async def _broadcast(self, payload: dict) -> None:
        """Safe broadcast call — no-ops if no broadcaster configured."""
        if self._broadcast_fn:
            try:
                if asyncio.iscoroutinefunction(self._broadcast_fn):
                    await self._broadcast_fn(payload)
                else:
                    self._broadcast_fn(payload)
            except Exception as exc:
                logger.warning(f"DissipationHandler broadcast error: {exc}")
