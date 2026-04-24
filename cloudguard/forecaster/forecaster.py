"""
FORECASTER MODULE — Phase 4 Entry Point
========================================
Thin orchestration wrapper that:
  1. Pulls the last 100 events from Redis truth_log (LRANGE)
  2. Feeds them into ThreatForecaster's sliding window
  3. Runs predict_tick() → ForecastResult
  4. Emits FORECAST_SIGNAL / AMBER_ALERT to the War Room WS

This is the "standalone" runner — importable by inject_drift.py --mode proactive
or launchable directly:

    python -m cloudguard.forecaster.forecaster

Academic note on the sliding-window design
------------------------------------------
Redis LRANGE returns events in insertion order (oldest→newest). We take the
last WINDOW_SIZE entries so the LSTM sees the *most recent* temporal context,
which is the correct causal ordering for sequential anomaly detection.

Shadow AI Fast-Path (Phase 5 preview)
--------------------------------------
If P(shadow_ai_spawn) ≥ 0.90 (PREDICTIVE_FASTPASS_THRESHOLD),
the SovereignGate shutdown timer drops from 60 s → 10 s ("Predictive Fast-Pass").
This avoids the full SLA window for a near-certain high-cost GPU threat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger("cloudguard.forecaster.runner")

# ── Constants ─────────────────────────────────────────────────────────────────

REDIS_TRUTH_LOG_KEY      = os.getenv("REDIS_TRUTH_LOG_KEY", "cloudguard:truth_log")
REDIS_CHANNEL            = os.getenv("REDIS_CHANNEL", "cloudguard_events")
REDIS_URL                = os.getenv("REDIS_URL", "redis://default:uOnxudpatLQBllCvLmbzXIesXnmcTizm@redis.railway.internal:6379")
TICK_INTERVAL_SECONDS    = float(os.getenv("FORECASTER_TICK_INTERVAL", "5"))
SLIDING_WINDOW_SIZE      = 100

# Phase 5 threshold: P ≥ this → execute shutdown in 10 s
PREDICTIVE_FASTPASS_THRESHOLD = 0.90
STANDARD_SHUTDOWN_TIMEOUT    = 60   # seconds (sovereign gate default)
FASTPASS_SHUTDOWN_TIMEOUT    = 10   # seconds (predictive fast-pass)


# ═══════════════════════════════════════════════════════════════════════════════
# REDIS TRUTH LOG READER
# ═══════════════════════════════════════════════════════════════════════════════

async def pull_truth_log(
    redis_url: str = REDIS_URL,
    key: str = REDIS_TRUTH_LOG_KEY,
    window: int = SLIDING_WINDOW_SIZE,
) -> list[dict[str, Any]]:
    """
    Pull the last `window` events from the Redis truth_log list.

    The truth_log is a Redis LIST (LPUSH'd so newest is at index 0).
    We read LRANGE key 0 window-1 and reverse to get oldest-first ordering
    for the LSTM temporal sequence.

    Falls back gracefully to [] if Redis is unavailable.
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        await client.ping()

        raw_entries = await client.lrange(key, 0, window - 1)
        await client.aclose()

        events: list[dict[str, Any]] = []
        for entry in reversed(raw_entries):   # oldest → newest
            try:
                events.append(json.loads(entry))
            except json.JSONDecodeError:
                pass

        logger.info(
            f"📥 truth_log: pulled {len(events)}/{window} events "
            f"from Redis key '{key}'"
        )
        return events

    except ImportError:
        logger.warning("redis.asyncio not installed — running forecaster on empty window")
        return []
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}) — running on empty window")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# SOVEREIGN GATE — Shadow AI Shutdown Timer
# ═══════════════════════════════════════════════════════════════════════════════

class SovereignGate:
    """
    Phase 5 preview: Controls the shutdown timer for unauthorised GPU workloads.

    Standard behaviour
    ------------------
    Wait STANDARD_SHUTDOWN_TIMEOUT (60 s) before executing resource kill to
    allow human review / false-positive cancellation.

    Predictive Fast-Pass
    --------------------
    If the LSTM emits P(shadow_ai_spawn) ≥ PREDICTIVE_FASTPASS_THRESHOLD (0.90),
    the timer collapses to FASTPASS_SHUTDOWN_TIMEOUT (10 s).

    Rationale: A 90 %+ confidence GPU spin-up with no Cost-Center tag has
    an expected loss of ~$18 000/hr at p100 rates. The 50 s time saving
    translates to ~$250 in direct cost avoidance per incident. The low
    false-positive rate at 90 % calibration makes the aggressive timer
    risk-acceptable.

    Architect's Answer (Collaborator Query):
        YES — implement Predictive Fast-Pass for P ≥ 0.90.
        The 60-second full wait should only apply for P ∈ [0.75, 0.90).
    """

    def __init__(
        self,
        on_execute: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._on_execute = on_execute or self._default_execute
        self._pending: dict[str, asyncio.Task] = {}

    @staticmethod
    async def _default_execute(resource_id: str) -> None:
        logger.warning(
            f"🔴 SOVEREIGN GATE: Executing shutdown for resource {resource_id}"
        )

    async def arm(
        self,
        resource_id: str,
        shadow_ai_probability: float,
    ) -> dict[str, Any]:
        """
        Arm the shutdown timer for a resource.

        Parameters
        ----------
        resource_id : str
        shadow_ai_probability : float
            P(shadow_ai_spawn) from LSTM — governs timer selection.

        Returns
        -------
        dict with timer_seconds and fast_pass flag.
        """
        if resource_id in self._pending:
            logger.debug(f"⏱️  Gate already armed for {resource_id} — skipping")
            return {"status": "already_armed", "resource_id": resource_id}

        fast_pass = shadow_ai_probability >= PREDICTIVE_FASTPASS_THRESHOLD
        timer_s = FASTPASS_SHUTDOWN_TIMEOUT if fast_pass else STANDARD_SHUTDOWN_TIMEOUT

        logger.warning(
            f"⚡ SovereignGate {'FAST-PASS' if fast_pass else 'STANDARD'} armed: "
            f"{resource_id} — P={shadow_ai_probability:.0%} — {timer_s}s timer"
        )

        task = asyncio.create_task(self._countdown(resource_id, timer_s))
        self._pending[resource_id] = task

        return {
            "status": "armed",
            "resource_id": resource_id,
            "timer_seconds": timer_s,
            "fast_pass": fast_pass,
            "probability": round(shadow_ai_probability, 4),
        }

    async def _countdown(self, resource_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._on_execute(resource_id)
        except asyncio.CancelledError:
            logger.info(f"🛑 SovereignGate cancelled for {resource_id}")
        finally:
            self._pending.pop(resource_id, None)

    def cancel(self, resource_id: str) -> bool:
        """Cancel a pending shutdown (human intervention cancel window)."""
        task = self._pending.pop(resource_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"✅ SovereignGate cancelled for {resource_id}")
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN FORECASTER RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

class ForecasterRunner:
    """
    Phase 4 production forecaster entry-point.

    Wires together:
      - RedisReader   → pulls last 100 truth_log events
      - ThreatForecaster → sliding window + LSTM + Shadow AI + Recon
      - SovereignGate → timer-based shutdown with Predictive Fast-Pass
      - WebSocket emitter (via cloudguard.api.streamer)
    """

    def __init__(
        self,
        redis_url: str = REDIS_URL,
        truth_log_key: str = REDIS_TRUTH_LOG_KEY,
        tick_interval: float = TICK_INTERVAL_SECONDS,
        current_j_getter: Optional[Callable[[], float]] = None,
    ) -> None:
        from cloudguard.forecaster.threat_forecaster import ThreatForecaster
        self._forecaster = ThreatForecaster(window_size=SLIDING_WINDOW_SIZE)
        self._sovereign_gate = SovereignGate()
        self._redis_url = redis_url
        self._truth_log_key = truth_log_key
        self._tick_interval = tick_interval
        self._current_j_getter = current_j_getter or (lambda: 0.5)

        # pre-train LSTM on synthetic recon patterns
        losses = self._forecaster.train_on_recon_patterns(num_synthetic=50)
        logger.info(
            f"🧠 LSTM pre-trained — final loss: {losses[-1]:.4f}"
        )

    async def run_once(self) -> dict[str, Any]:
        """
        Single execution cycle:
          1. Pull truth_log from Redis
          2. Feed events into sliding window
          3. Run LSTM prediction
          4. Handle Amber Alert / SovereignGate

        Returns the ForecastResult dict.
        """
        events = await pull_truth_log(
            redis_url=self._redis_url,
            key=self._truth_log_key,
            window=SLIDING_WINDOW_SIZE,
        )

        # Ingest into sliding window (replaces existing window content)
        self._forecaster.processor.clear()
        for evt in events:
            self._forecaster.ingest_event(evt)

        current_j = self._current_j_getter()
        result = self._forecaster.predict_tick(current_j=current_j)

        if result.is_amber_alert:
            await self._forecaster.emit_amber_alert(result)

            # Shadow AI → arm SovereignGate
            if result.is_shadow_ai and result.shadow_ai_details:
                rid = result.shadow_ai_details.get("resource_id", result.target_resource_id)
                shadow_p = result.shadow_ai_details.get("confidence", result.probability)
                await self._sovereign_gate.arm(
                    resource_id=rid,
                    shadow_ai_probability=shadow_p,
                )

        return result.to_dict()

    async def run_loop(self) -> None:
        """Continuous prediction loop at TICK_INTERVAL_SECONDS cadence."""
        logger.info(
            f"🔮 ForecasterRunner started "
            f"(tick_interval={self._tick_interval}s, "
            f"redis={self._redis_url})"
        )
        while True:
            try:
                await self.run_once()
            except Exception as exc:
                logger.error(f"Forecaster tick error: {exc}")
            await asyncio.sleep(self._tick_interval)


# ─── CLI entry-point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    runner = ForecasterRunner()
    try:
        asyncio.run(runner.run_loop())
    except KeyboardInterrupt:
        sys.exit(0)
