"""
CLOUDGUARD-B — WAR ROOM WebSocket STREAMING ENGINE
====================================================
Phase 3 — Real-Time Agentic Visibility Layer

WebSocket endpoint: /ws/war-room

Architecture:
  ┌─────────────────────┐      Redis PubSub      ┌──────────────────────┐
  │  cloudguard_events  │ ──── DRIFT/REMEDIATION ─▶│                      │
  │  kernel_traces      │ ──── NEGOTIATION/TRACE  ─▶│  Broadcaster Task    │
  └─────────────────────┘                          │  (background)        │
                                                   └──────────┬───────────┘
                                                              │ transform → UIEvent
                                                              │ buffer → last 50
                                                              ▼
                                                   ┌──────────────────────┐
                                                   │  Active WS Clients   │
                                                   │  /ws/war-room        │
                                                   └──────────────────────┘

Message Types Emitted:
  DRIFT              — Security drift detected on a resource
  REMEDIATION        — Fix applied (success/failure)
  NEGOTIATION        — w_R ↕ w_C weight tug-of-war
  TICKER_UPDATE      — J-Score equilibrium change (w_R + w_C + J_total)
  TOPOLOGY_SYNC      — Full 345-resource Green/Yellow/Red status snapshot
  HEARTBEAT          — Connection keepalive ping
  SWARM_COOLING_DOWN — Gemini 429 quota exceeded
  BUFFER_REPLAY      — Last-50 events sent to a newly connected client

Usage:
  # Attach to existing FastAPI app:
  from cloudguard.api.streamer import war_room_router, lifespan
  app.include_router(war_room_router)

  # Stand-alone dev mode:
  uvicorn cloudguard.api.streamer:app --reload --port 8765
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi import APIRouter

logger = logging.getLogger("cloudguard.war_room")

# ─── Redis channel names ───────────────────────────────────────────────────────
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379")
CH_WORLD         = "cloudguard_events"   # Phase 1 world-state
CH_KERNEL        = "kernel_traces"       # Phase 2 swarm reasoning traces

# ─── J-Score weights kept in module state ─────────────────────────────────────
_w_risk: float = 0.6
_w_cost: float = 0.4
_j_score: float = 0.5   # last known equilibrium

# ─── Last-50 event replay buffer ──────────────────────────────────────────────
EVENT_BUFFER: deque[dict] = deque(maxlen=50)

# ─── Active WebSocket connections ─────────────────────────────────────────────
CLIENTS: set[WebSocket] = set()

# ─── Heartbeat interval ───────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 15   # seconds

# ─── Topology: resource_id → status (Green/Yellow/Red) ───────────────────────
TOPOLOGY: dict[str, str] = {}


# ═══════════════════════════════════════════════════════════════════════════════
# PAYLOAD TRANSFORMER  (raw Redis → UI-Ready JSON)
# ═══════════════════════════════════════════════════════════════════════════════

_EVENT_TYPE_MAP: dict[str, str] = {
    "DRIFT":                "Drift",
    "REMEDIATION":          "Remediation",
    "NEGOTIATION":          "Negotiation",
    "HEARTBEAT":            "Heartbeat",
    "TICKER_UPDATE":          "TickerUpdate",
    "TOPOLOGY_SYNC":          "TopologySync",
    "SWARM_COOLING_DOWN":     "SwarmCoolingDown",
    "FORECAST_SIGNAL":        "ForecastSignal",
    "NARRATIVE_CHUNK":        "NarrativeChunk",
    "NarrativeChunk":         "NarrativeChunk",
    # Phase 4: Threat Horizon Overlay (attack path visualization)
    "THREAT_HORIZON_OVERLAY": "ThreatHorizonOverlay",
}


def _build_ui_event(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Transform a raw Redis / in-memory event payload into a UI-Ready JSON object.

    Schema guaranteed:
        tick_timestamp  — simulation tick or wall-clock ISO string
        event_type      — human-readable type label
        agent_id        — originating agent (or 'system')
        message_body    — dict with event-specific detail

    Additionally adds:
        w_R, w_C, j_score  — latest equilibrium values (always present)
    """
    raw_type = raw.get("event_type", "UNKNOWN")
    data     = raw.get("data", {})
    weights  = raw.get("environment_weights", {})

    # Update module-level J-score snapshot when weights change
    global _w_risk, _w_cost, _j_score
    if weights:
        _w_risk  = weights.get("w_R", _w_risk)
        _w_cost  = weights.get("w_C", _w_cost)

    # Build message_body per event type
    if raw_type == "DRIFT":
        message_body = {
            "resource_id":           data.get("resource_id", "unknown"),
            "drift_type":            data.get("drift_type", "UNKNOWN"),
            "severity":              data.get("severity", "LOW"),
            "cumulative_drift_score": data.get("cumulative_drift_score", 0.0),
            "is_false_positive":     data.get("is_false_positive", False),
        }
        _update_topology(data.get("resource_id"), data.get("severity", "LOW"))

    elif raw_type == "REMEDIATION":
        j_before = data.get("j_before", _j_score)
        j_after  = data.get("j_after",  _j_score)
        _j_score = j_after
        message_body = {
            "resource_id": data.get("resource_id", "unknown"),
            "action":      data.get("action", "unknown"),
            "tier":        data.get("tier", "T0"),
            "success":     data.get("success", False),
            "j_before":    j_before,
            "j_after":     j_after,
            "j_delta":     round(j_after - j_before, 6),
        }
        if data.get("success"):
            _update_topology(data.get("resource_id"), "GREEN")

    elif raw_type == "TICKER_UPDATE":
        # Weights shifted — emit Pareto-front tug-of-war detail
        _j_score = data.get("j_score", _j_score)
        message_body = {
            "w_R":            _w_risk,
            "w_C":            _w_cost,
            "j_score":        _j_score,
            "j_percentage":   round((1.0 - _j_score) * 100, 2),
            "pareto_summary": data.get("pareto_summary", []),
            "trigger":        data.get("trigger", "weight_update"),
        }

    elif raw_type == "TOPOLOGY_SYNC":
        message_body = {
            "resources": data.get("resources", _snapshot_topology()),
            "green_count":  data.get("green_count",  _count_topology("GREEN")),
            "yellow_count": data.get("yellow_count", _count_topology("YELLOW")),
            "red_count":    data.get("red_count",    _count_topology("RED")),
            "total":        len(TOPOLOGY),
        }

    elif raw_type == "SWARM_COOLING_DOWN":
        message_body = {
            "reason":        data.get("reason", "Gemini 429 quota hit"),
            "retry_after_s": data.get("retry_after_s", 60),
            "agent_id":      data.get("agent_id", "swarm"),
        }

    elif raw_type == "FORECAST_SIGNAL":
        # Phase 4: Proactive Intelligence — Amber Alert from ThreatForecaster
        signal_type = data.get("type", "Advisory")
        dissipation = data.get("dissipation")

        message_body = {
            "target":          data.get("target", "unknown"),
            "probability":     data.get("probability", 0.0),
            "type":            signal_type,
            "horizon":         data.get("horizon", "5 ticks"),
            "predicted_drift": data.get("predicted_drift", "UNKNOWN"),
            "is_shadow_ai":    data.get("is_shadow_ai", False),
            "j_forecast":      data.get("j_forecast", 0.0),
            "recon_chain":     data.get("recon_chain"),
            "confidence_lo":   data.get("confidence_lo", 0.0),
            "confidence_hi":   data.get("confidence_hi", 0.0),
            # Phase 4 extended fields
            "dissipation":     dissipation,   # Non-null only on Dissipated signals
        }

        target = data.get("target")
        if target:
            if signal_type == "Amber_Alert":
                # Mark target resource as AMBER/CRITICAL in topology
                _update_topology(target, "CRITICAL")
            elif signal_type == "Dissipated":
                # Amber Alert dissipated — return target to YELLOW (watch state)
                TOPOLOGY[target] = "YELLOW"
                logger.info(
                    f"🟢 Topology: {target} returned to YELLOW after dissipation "
                    f"(was CRITICAL, P dropped below 0.75)"
                )

    elif raw_type == "THREAT_HORIZON_OVERLAY":
        # Phase 4: Frontend attack-path visualization overlay
        # Passes transitive_nodes to the War Room UI to draw orange edges
        message_body = {
            "alert_id":         data.get("alert_id", ""),
            "target":           data.get("target", "unknown"),
            "probability":      data.get("probability", 0.0),
            "color":            data.get("color", "orange"),
            "recon_pattern":    data.get("recon_pattern", ""),
            "transitive_nodes": data.get("transitive_nodes", []),
            "label":            data.get("label", ""),
            "timestamp":        data.get("timestamp", ""),
        }
        # Mark all transitive node resource_ids in topology as AMBER
        for node in data.get("transitive_nodes", []):
            rid = node.get("resource_id") or node.get("node_id")
            if rid and rid not in ("entry-point", "pivot-resource", "target-asset"):
                if TOPOLOGY.get(rid) not in ("RED", "CRITICAL"):
                    TOPOLOGY[rid] = "AMBER"
        logger.info(
            f"🟠 ThreatHorizonOverlay: {data.get('alert_id')} — "
            f"{len(data.get('transitive_nodes', []))} attack-path nodes painted orange"
        )

    elif raw_type in ("NARRATIVE_CHUNK", "NarrativeChunk"):
        # Preserve the full NarrativeChunk structure for Friction HUD + Liaison Console
        message_body = {
            "chunk_type":        data.get("chunk_type", "narrative"),
            "heading":           data.get("heading", ""),
            "body":              data.get("body", ""),
            "citation":          data.get("citation", ""),
            "is_final":          data.get("is_final", False),
            "countdown_active":  data.get("countdown_active", False),
            "seconds_remaining": data.get("seconds_remaining", 0),
            "j_before":          data.get("j_before", _j_score),
            "j_after":           data.get("j_after", _j_score),
            "j_delta":           data.get("j_delta", 0.0),
            "roi_summary":       data.get("roi_summary"),
            "math_trace":        data.get("math_trace"),
            "is_fast_pass":      data.get("is_fast_pass", False),
            "fast_pass_meta":    data.get("fast_pass_meta"),
        }

    elif raw_type == "HEARTBEAT":
        message_body = {
            "status": data.get("status", "alive"),
            "tick":   data.get("tick", raw.get("timestamp_tick", 0)),
        }

    else:
        # Catch-all: pass data through as-is (kernel traces, negotiations, etc.)
        message_body = data if data else {"raw": raw_type}

    return {
        "event_id":      raw.get("event_id", f"evt-{uuid.uuid4().hex[:8]}"),
        "tick_timestamp": raw.get("timestamp_tick", raw.get("timestamp_utc",
                          datetime.now(timezone.utc).isoformat())),
        "event_type":    _EVENT_TYPE_MAP.get(raw_type, raw_type),
        "agent_id":      raw.get("agent_id", data.get("agent_id", "system")),
        "trace_id":      raw.get("trace_id", ""),
        "message_body":  message_body,
        "w_R":           _w_risk,
        "w_C":           _w_cost,
        "j_score":       round(_j_score, 6),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TOPOLOGY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

_SEVERITY_TO_STATUS = {
    "CRITICAL": "RED",
    "HIGH":     "RED",
    "MEDIUM":   "YELLOW",
    "LOW":      "YELLOW",
    "GREEN":    "GREEN",   # remediation success
}


def _update_topology(resource_id: Optional[str], severity: str) -> None:
    """Map a drift severity to a topology status and trigger a TOPOLOGY_SYNC."""
    if not resource_id:
        return
    status = _SEVERITY_TO_STATUS.get(severity.upper(), "YELLOW")
    TOPOLOGY[resource_id] = status


def _snapshot_topology() -> list[dict]:
    """Serialize current topology to a list of {resource_id, status} records."""
    return [{"resource_id": rid, "status": st} for rid, st in TOPOLOGY.items()]


def _count_topology(status: str) -> int:
    return sum(1 for s in TOPOLOGY.values() if s == status)


def build_topology_sync_message() -> dict:
    """Build a full TOPOLOGY_SYNC payload."""
    return _build_ui_event({
        "event_type": "TOPOLOGY_SYNC",
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
        "data": {
            "resources":    _snapshot_topology(),
            "green_count":  _count_topology("GREEN"),
            "yellow_count": _count_topology("YELLOW"),
            "red_count":    _count_topology("RED"),
        },
    })


# ═══════════════════════════════════════════════════════════════════════════════
# J-SCORE TICKER  (weight-change detection)
# ═══════════════════════════════════════════════════════════════════════════════

def build_ticker_update(
    w_risk: float = 0.6,
    w_cost: float = 0.4,
    j_score: float = 0.5,
    trigger: str = "weight_update",
    pareto_summary: Optional[list] = None,
) -> dict:
    """
    Construct a TICKER_UPDATE UI event.

    Called whenever MathEngine updates w_R or w_C (the Pareto tug-of-war).
    The UI uses this to animate the Negotiation graph:
      - w_R spikes  → CISO (Sentry) flagged a risk
      - w_C moves   → Controller proposes cost-optimized fix
      - J drops     → equilibrium found by Active Editor
    """
    global _w_risk, _w_cost, _j_score
    _w_risk  = w_risk
    _w_cost  = w_cost
    _j_score = j_score

    return _build_ui_event({
        "event_type": "TICKER_UPDATE",
        "event_id":   f"evt-{uuid.uuid4().hex[:8]}",
        "environment_weights": {"w_R": w_risk, "w_C": w_cost},
        "data": {
            "j_score":        j_score,
            "trigger":        trigger,
            "pareto_summary": pareto_summary or [],
        },
    })


# ═══════════════════════════════════════════════════════════════════════════════
# BROADCASTER  (Redis → Clients)
# ═══════════════════════════════════════════════════════════════════════════════

async def _broadcast(event: dict) -> None:
    """Push a UI-event to all active WebSocket clients. Prune dead connections."""
    dead: set[WebSocket] = set()
    msg = json.dumps(event, default=str)
    for ws in CLIENTS:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    CLIENTS.difference_update(dead)

    # Buffer the event for late-joiners
    EVENT_BUFFER.append(event)


async def _redis_broadcaster(redis_url: str) -> None:
    """
    Subscribe to Redis channels and forward messages to WebSocket clients.
    Falls back to a silent no-op if Redis is unavailable.
    """
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("⚠️  redis.asyncio not installed — broadcaster in no-op mode")
        return

    while True:   # reconnect loop
        try:
            client = aioredis.from_url(redis_url, decode_responses=True,
                                       socket_connect_timeout=5)
            await client.ping()
            logger.info(f"📡 Broadcaster connected to Redis at {redis_url}")

            pubsub = client.pubsub()
            await pubsub.subscribe(CH_WORLD, CH_KERNEL)

            async for raw_msg in pubsub.listen():
                if raw_msg["type"] not in ("message", "pmessage"):
                    continue

                channel = raw_msg.get("channel", "")
                try:
                    payload = json.loads(raw_msg["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.debug(f"Non-JSON on {channel}: {raw_msg['data'][:120]}")
                    continue

                # Rate-limit guard: broadcast SWARM_COOLING_DOWN
                if payload.get("event_type") == "RATE_LIMIT_429":
                    event = _build_ui_event({
                        "event_type": "SWARM_COOLING_DOWN",
                        "event_id":   f"evt-{uuid.uuid4().hex[:8]}",
                        "data": {
                            "reason":        "Gemini API quota exhausted (HTTP 429)",
                            "retry_after_s": payload.get("retry_after", 60),
                            "agent_id":      payload.get("agent_id", "swarm"),
                        },
                    })
                    await _broadcast(event)
                    continue

                # Topology change detection: only emit TOPOLOGY_SYNC when status changes
                if payload.get("event_type") == "DRIFT":
                    data = payload.get("data", {})
                    rid  = data.get("resource_id")
                    sev  = data.get("severity", "LOW")
                    old  = TOPOLOGY.get(rid)
                    new  = _SEVERITY_TO_STATUS.get(sev.upper(), "YELLOW")
                    if old != new:
                        _update_topology(rid, sev)
                        await _broadcast(build_topology_sync_message())

                # Emit the primary event
                ui_event = _build_ui_event(payload)
                await _broadcast(ui_event)

                # If weights changed → emit TICKER_UPDATE
                weights = payload.get("environment_weights", {})
                if weights and (
                    abs(weights.get("w_R", _w_risk) - _w_risk) > 1e-6 or
                    abs(weights.get("w_C", _w_cost) - _w_cost) > 1e-6
                ):
                    ticker = build_ticker_update(
                        w_risk=weights["w_R"],
                        w_cost=weights["w_C"],
                        j_score=_j_score,
                        trigger=payload.get("event_type", "weight_update"),
                    )
                    await _broadcast(ticker)

        except asyncio.CancelledError:
            logger.info("📡 Broadcaster task cancelled — shutting down")
            return
        except Exception as exc:
            logger.warning(f"📡 Redis connection lost ({exc}) — retrying in 5s …")
            await asyncio.sleep(5)


async def _heartbeat_loop() -> None:
    """Send a HEARTBEAT to all connected clients every HEARTBEAT_INTERVAL seconds."""
    tick = 0
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if CLIENTS:
            hb = _build_ui_event({
                "event_type": "HEARTBEAT",
                "event_id":   f"evt-{uuid.uuid4().hex[:8]}",
                "data":       {"status": "alive", "tick": tick, "client_count": len(CLIENTS)},
            })
            await _broadcast(hb)
        tick += 1


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI LIFESPAN  (background tasks)
# ═══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start broadcaster + heartbeat + auto-stepper background tasks on app startup."""
    from cloudguard.api.auto_stepper import run_auto_stepper

    tasks = [
        asyncio.create_task(_redis_broadcaster(REDIS_URL), name="redis_broadcaster"),
        asyncio.create_task(_heartbeat_loop(),              name="ws_heartbeat"),
        asyncio.create_task(run_auto_stepper(),             name="auto_stepper"),
    ]
    logger.info("🚀 War Room streaming engine started (with auto-stepper)")
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("🛑 War Room streaming engine stopped")


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════════

war_room_router = APIRouter(tags=["War Room (WebSocket)"])


@war_room_router.websocket("/ws/war-room")
async def war_room_ws(websocket: WebSocket):
    """
    WebSocket endpoint: /ws/war-room

    On connect:
      1. Accepts the connection and registers the client.
      2. Sends a BUFFER_REPLAY of the last 50 events so the UI is never blank.
      3. Streams live events as they arrive.

    On disconnect / error:
      Gracefully removes the client without crashing other connections.
    """
    await websocket.accept()
    CLIENTS.add(websocket)
    client_id = id(websocket)
    logger.info(f"🔌 Client connected: {client_id}  (total: {len(CLIENTS)})")

    # ── Send replay buffer to new client ────────────────────────────────────
    if EVENT_BUFFER:
        replay = {
            "event_id":      f"evt-{uuid.uuid4().hex[:8]}",
            "tick_timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type":    "BufferReplay",
            "agent_id":      "system",
            "trace_id":      "",
            "message_body":  {
                "events": list(EVENT_BUFFER),
                "count":  len(EVENT_BUFFER),
            },
            "w_R":     _w_risk,
            "w_C":     _w_cost,
            "j_score": round(_j_score, 6),
        }
        try:
            await websocket.send_text(json.dumps(replay, default=str))
        except Exception:
            pass

    # ── Send current topology snapshot ──────────────────────────────────────
    if TOPOLOGY:
        try:
            await websocket.send_text(
                json.dumps(build_topology_sync_message(), default=str)
            )
        except Exception:
            pass

    # ── Keep-alive: receive pings from client ────────────────────────────────
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Echo pong for client-initiated pings
                if data == "ping":
                    await websocket.send_text(json.dumps({
                        "event_type": "Heartbeat",
                        "message_body": {"status": "pong"},
                        "w_R": _w_risk, "w_C": _w_cost, "j_score": round(_j_score, 6),
                    }))
            except asyncio.TimeoutError:
                # No message from client in 30 s — that's fine, we send heartbeats
                pass

    except WebSocketDisconnect:
        logger.info(f"🔌 Client disconnected: {client_id}")
    except Exception as exc:
        logger.warning(f"⚠️  WS error for {client_id}: {exc}")
    finally:
        CLIENTS.discard(websocket)
        logger.info(f"📊 Remaining clients: {len(CLIENTS)}")


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API  (for injecting events from within the Python process)
# ═══════════════════════════════════════════════════════════════════════════════

async def emit_event(raw_payload: dict[str, Any]) -> None:
    """
    Inject an event into the War Room from inside the Python process
    (e.g., from the swarm agents when Redis is not available).

    Usage in swarm.py / sentry_node.py:
        from cloudguard.api.streamer import emit_event
        await emit_event(EventPayload.drift(resource_id=..., ...))
    """
    ui_event = _build_ui_event(raw_payload)
    await _broadcast(ui_event)

    # Topology auto-sync on DRIFT
    if raw_payload.get("event_type") == "DRIFT":
        data = raw_payload.get("data", {})
        rid, sev = data.get("resource_id"), data.get("severity", "LOW")
        if rid and TOPOLOGY.get(rid) != _SEVERITY_TO_STATUS.get(sev.upper(), "YELLOW"):
            _update_topology(rid, sev)
            await _broadcast(build_topology_sync_message())


async def emit_ticker(
    w_risk: float,
    w_cost: float,
    j_score: float,
    trigger: str = "math_engine_update",
    pareto_summary: Optional[list] = None,
) -> None:
    """
    Emit a J-Score TICKER_UPDATE event.  Call this from MathEngine callbacks.

    The Pareto Tug-of-War visualization fires from here:
      - CISO flags risk  → emit_ticker(w_risk↑, w_cost↓, ...)
      - Controller fixes → emit_ticker(w_risk↓, w_cost↑, ...)
      - Editor commits   → emit_ticker(w_risk, w_cost, j_score↓)
    """
    ticker = build_ticker_update(
        w_risk=w_risk, w_cost=w_cost,
        j_score=j_score, trigger=trigger,
        pareto_summary=pareto_summary or [],
    )
    await _broadcast(ticker)


# ═══════════════════════════════════════════════════════════════════════════════
# STAND-ALONE DEV APP
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="CloudGuard-B — War Room Streamer",
    description="Real-time WebSocket bridge: Redis → Agentic UI",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(war_room_router)


@app.get("/ws/status", tags=["War Room (WebSocket)"])
def ws_status() -> dict:
    """Quick health check: returns live client count and buffer state."""
    return {
        "status":           "running",
        "active_clients":   len(CLIENTS),
        "buffer_size":      len(EVENT_BUFFER),
        "topology_resources": len(TOPOLOGY),
        "redis_url":        REDIS_URL,
        "w_R":              _w_risk,
        "w_C":              _w_cost,
        "j_score":          round(_j_score, 6),
        "j_percentage":     round((1.0 - _j_score) * 100, 2),
        "channels":         [CH_WORLD, CH_KERNEL],
    }


@war_room_router.get("/ws/war-room/test-emit", tags=["War Room (WebSocket)"])
async def test_emit() -> dict:
    """
    Developer utility: inject a synthetic DRIFT + TICKER_UPDATE to verify
    the pipeline without needing a live simulation.
    """
    import random, time

    resource_ids = [f"res-{i:03d}" for i in range(1, 346)]
    rid          = random.choice(resource_ids)
    severity     = random.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    tick         = int(time.time()) % 10000
    new_w_risk   = round(random.uniform(0.45, 0.75), 3)
    new_w_cost   = round(1.0 - new_w_risk, 3)
    new_j        = round(random.uniform(0.25, 0.75), 4)

    drift_payload = {
        "event_type":          "DRIFT",
        "event_id":            f"evt-{uuid.uuid4().hex[:8]}",
        "trace_id":            f"trace-{uuid.uuid4().hex[:12]}",
        "timestamp_tick":      tick,
        "environment_weights": {"w_R": new_w_risk, "w_C": new_w_cost},
        "data": {
            "resource_id":           rid,
            "drift_type":            "IAM_POLICY_CHANGE",
            "severity":              severity,
            "cumulative_drift_score": round(random.uniform(0.1, 9.9), 2),
            "is_false_positive":     random.random() < 0.15,
        },
    }
    await emit_event(drift_payload)
    await emit_ticker(new_w_risk, new_w_cost, new_j, trigger="test_emit")

    return {
        "emitted": ["DRIFT", "TOPOLOGY_SYNC", "TICKER_UPDATE"],
        "resource_id": rid,
        "severity":    severity,
        "w_R":         new_w_risk,
        "w_C":         new_w_cost,
        "j_score":     new_j,
        "active_clients": len(CLIENTS),
    }


# ─── Attach to existing app ───────────────────────────────────────────────────
# In cloudguard/app.py, add:
#
#   from cloudguard.api.streamer import war_room_router, lifespan
#   app.router.lifespan_context = lifespan
#   app.include_router(war_room_router)
#
# Or run this file alone for quick dev testing:
#   uvicorn cloudguard.api.streamer:app --reload --port 8765
