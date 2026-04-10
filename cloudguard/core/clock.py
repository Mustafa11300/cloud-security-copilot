"""
TEMPORAL CLOCK & SUB-TICK BURST MODE
=====================================
Subsystem 2 — Phase 1 Foundation

Implements a dual-mode simulation clock:

Standard Mode:
  1 tick = 1 hour (FinOps / Telemetry measurement)

Burst Mode:
  Upon a DriftEvent on the Redis bus, accelerate to 1-minute "Sub-Ticks."
  MANDATORY for measuring the 6.9-minute MTTR benchmark
  (Self-Healing Infrastructure, 2026).

Watchdog:
  Emits a HEARTBEAT event to Redis every 10 ticks to monitor agent health.

Decision #13: "Patient" 10-second aggregation window for drift events.

Threading Model:
  The clock runs as a Python async coroutine, publishing ticks to
  registered callbacks. It does NOT depend on Redis directly — the
  event bus layer subscribes to clock events and publishes to Redis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("cloudguard.clock")


class ClockMode(str, Enum):
    """Clock operating mode."""
    STANDARD = "standard"   # 1 tick = 1 hour
    BURST = "burst"         # 1 tick = 1 minute (60x acceleration)


@dataclass
class TickEvent:
    """Published every tick to all registered listeners."""
    tick_number: int
    mode: ClockMode
    elapsed_sim_minutes: float     # Total simulated minutes elapsed
    elapsed_sim_hours: float       # Total simulated hours elapsed
    wall_clock_seconds: float      # Real-world seconds elapsed
    is_heartbeat: bool             # True every 10 ticks
    burst_ticks_remaining: int     # Sub-ticks left in burst mode (0 if standard)
    metadata: dict[str, Any] = field(default_factory=dict)


# Type alias for tick callbacks
TickCallback = Callable[[TickEvent], Any]


class TemporalClock:
    """
    Dual-mode simulation clock with burst acceleration.

    Usage:
        clock = TemporalClock()
        clock.register_callback(my_tick_handler)

        # Start standard mode (async)
        await clock.start()

        # Trigger burst mode (e.g., on drift detection)
        clock.enter_burst_mode(duration_ticks=420)  # 420 ticks × 1min = 7 hours

        # Query state
        print(clock.current_tick)
        print(clock.mode)

    MTTR Measurement:
        When a drift event is detected, call enter_burst_mode().
        The clock accelerates to 1-minute ticks so the 6.9-minute
        MTTR benchmark can be measured with tick-level granularity.
        After the burst window expires, the clock reverts to Standard mode.
    """

    # ── Configuration ─────────────────────────────────────────────────────────

    STANDARD_TICK_MINUTES: int = 60       # 1 tick = 1 hour in standard mode
    BURST_TICK_MINUTES: int = 1           # 1 tick = 1 minute in burst mode
    HEARTBEAT_INTERVAL: int = 10          # Emit HEARTBEAT every N ticks
    DRIFT_AGGREGATION_WINDOW_SEC: float = 10.0  # Decision #13: Patient window

    # Real-world delay between ticks (controls simulation speed)
    STANDARD_TICK_DELAY_SEC: float = 1.0  # 1 second real time per standard tick
    BURST_TICK_DELAY_SEC: float = 0.1     # 100ms real time per burst tick

    def __init__(self) -> None:
        self._tick: int = 0
        self._mode: ClockMode = ClockMode.STANDARD
        self._callbacks: list[TickCallback] = []
        self._running: bool = False
        self._start_time: float = 0.0
        self._total_sim_minutes: float = 0.0
        self._burst_ticks_remaining: int = 0
        self._burst_drift_id: Optional[str] = None
        self._pending_drifts: list[dict] = []
        self._drift_window_start: Optional[float] = None
        self._lock = asyncio.Lock()

        # MTTR tracking
        self._mttr_start_tick: Optional[int] = None
        self._mttr_measurements: list[float] = []

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_tick(self) -> int:
        """Current tick number (monotonically increasing)."""
        return self._tick

    @property
    def mode(self) -> ClockMode:
        """Current clock mode (STANDARD or BURST)."""
        return self._mode

    @property
    def is_running(self) -> bool:
        """Whether the clock is actively ticking."""
        return self._running

    @property
    def elapsed_sim_hours(self) -> float:
        """Total simulated hours elapsed since clock start."""
        return self._total_sim_minutes / 60.0

    @property
    def elapsed_sim_minutes(self) -> float:
        """Total simulated minutes elapsed since clock start."""
        return self._total_sim_minutes

    @property
    def mttr_measurements(self) -> list[float]:
        """All MTTR measurements in simulated minutes."""
        return self._mttr_measurements.copy()

    @property
    def average_mttr(self) -> float:
        """Average MTTR across all measurements (in simulated minutes)."""
        if not self._mttr_measurements:
            return 0.0
        return sum(self._mttr_measurements) / len(self._mttr_measurements)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def register_callback(self, callback: TickCallback) -> None:
        """Register a callback to be invoked on every tick."""
        self._callbacks.append(callback)
        logger.info(f"Registered clock callback: {callback.__name__ if hasattr(callback, '__name__') else callback}")

    def unregister_callback(self, callback: TickCallback) -> None:
        """Remove a previously registered callback."""
        self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    # ── Clock Control ─────────────────────────────────────────────────────────

    async def start(self, max_ticks: Optional[int] = None) -> None:
        """
        Start the temporal clock.

        Args:
            max_ticks: Maximum number of ticks before auto-stopping.
                       None = run indefinitely until stop() is called.
        """
        if self._running:
            logger.warning("Clock is already running")
            return

        self._running = True
        self._start_time = time.monotonic()
        logger.info(f"⏰ Clock started in {self._mode.value} mode")

        try:
            while self._running:
                if max_ticks is not None and self._tick >= max_ticks:
                    logger.info(f"Clock reached max_ticks={max_ticks}, stopping")
                    break

                await self._advance_tick()

                # Determine delay based on mode
                delay = (
                    self.BURST_TICK_DELAY_SEC
                    if self._mode == ClockMode.BURST
                    else self.STANDARD_TICK_DELAY_SEC
                )
                await asyncio.sleep(delay)
        finally:
            self._running = False
            logger.info(f"⏰ Clock stopped at tick {self._tick}")

    def stop(self) -> None:
        """Stop the clock after the current tick completes."""
        self._running = False

    def reset(self) -> None:
        """Reset the clock to initial state."""
        self._tick = 0
        self._mode = ClockMode.STANDARD
        self._running = False
        self._total_sim_minutes = 0.0
        self._burst_ticks_remaining = 0
        self._mttr_start_tick = None
        self._mttr_measurements.clear()
        self._pending_drifts.clear()
        self._drift_window_start = None
        logger.info("⏰ Clock reset to initial state")

    # ── Manual tick (for synchronous testing) ─────────────────────────────────

    def tick_sync(self) -> TickEvent:
        """
        Manually advance one tick (synchronous).
        Useful for testing without running the async event loop.
        """
        if self._start_time == 0.0:
            self._start_time = time.monotonic()

        return self._advance_tick_sync()

    # ── Burst Mode ────────────────────────────────────────────────────────────

    def enter_burst_mode(
        self,
        duration_ticks: int = 420,
        drift_id: Optional[str] = None,
    ) -> None:
        """
        Enter Burst Mode (Sub-Tick acceleration).

        Standard → Burst: 1-hour ticks become 1-minute ticks.
        This is mandatory for measuring the 6.9-minute MTTR benchmark.

        Args:
            duration_ticks: Number of burst sub-ticks before reverting.
                           Default 420 (= 7 simulated hours at 1min/tick).
            drift_id: ID of the drift event that triggered burst mode.
        """
        self._mode = ClockMode.BURST
        self._burst_ticks_remaining = duration_ticks
        self._burst_drift_id = drift_id
        self._mttr_start_tick = self._tick
        logger.info(
            f"🔥 BURST MODE activated: {duration_ticks} sub-ticks "
            f"(drift_id={drift_id})"
        )

    def exit_burst_mode(self, remediation_successful: bool = True) -> Optional[float]:
        """
        Exit Burst Mode and return to Standard.

        If remediation was successful, records the MTTR measurement.

        Returns:
            MTTR in simulated minutes if remediation_successful, else None.
        """
        mttr = None
        if self._mttr_start_tick is not None and remediation_successful:
            ticks_elapsed = self._tick - self._mttr_start_tick
            mttr = float(ticks_elapsed * self.BURST_TICK_MINUTES)
            self._mttr_measurements.append(mttr)
            logger.info(f"📊 MTTR measured: {mttr:.1f} simulated minutes")

        self._mode = ClockMode.STANDARD
        self._burst_ticks_remaining = 0
        self._burst_drift_id = None
        self._mttr_start_tick = None
        logger.info("⏰ Returned to STANDARD mode")
        return mttr

    # ── Drift Aggregation (Decision #13: Patient Window) ──────────────────────

    def queue_drift(self, drift_data: dict) -> bool:
        """
        Queue a drift event for aggregation.
        Drift events within DRIFT_AGGREGATION_WINDOW_SEC are aggregated
        into a single consolidated signal before triggering burst mode.

        Returns:
            True if this drift triggered burst mode after aggregation.
        """
        now = time.monotonic()

        if self._drift_window_start is None:
            # Start a new aggregation window
            self._drift_window_start = now
            self._pending_drifts = [drift_data]
            logger.debug(f"Drift aggregation window opened (10s patient mode)")
            return False

        self._pending_drifts.append(drift_data)

        # Check if aggregation window has elapsed
        if now - self._drift_window_start >= self.DRIFT_AGGREGATION_WINDOW_SEC:
            # Flush aggregated drifts
            n = len(self._pending_drifts)
            logger.info(
                f"🔔 Aggregated {n} drift events over {self.DRIFT_AGGREGATION_WINDOW_SEC}s window"
            )
            self._pending_drifts.clear()
            self._drift_window_start = None

            # Trigger burst mode with consolidated signal
            self.enter_burst_mode(
                duration_ticks=420,
                drift_id=drift_data.get("event_id", "aggregated"),
            )
            return True

        return False

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _advance_tick(self) -> TickEvent:
        """Advance one tick and notify all callbacks (async)."""
        async with self._lock:
            event = self._build_tick_event()
            self._tick += 1

            # Notify callbacks
            for cb in self._callbacks:
                try:
                    result = cb(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(f"Tick callback error: {e}")

            # Handle burst mode decrement
            self._handle_burst_decrement()

            return event

    def _advance_tick_sync(self) -> TickEvent:
        """Advance one tick synchronously (for testing)."""
        event = self._build_tick_event()
        self._tick += 1

        for cb in self._callbacks:
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    logger.warning(f"Async callback {cb} cannot be awaited in sync mode")
            except Exception as e:
                logger.error(f"Tick callback error: {e}")

        self._handle_burst_decrement()
        return event

    def _build_tick_event(self) -> TickEvent:
        """Construct the TickEvent for the current tick."""
        # Calculate simulated time advancement
        if self._mode == ClockMode.BURST:
            tick_minutes = self.BURST_TICK_MINUTES
        else:
            tick_minutes = self.STANDARD_TICK_MINUTES

        self._total_sim_minutes += tick_minutes

        is_heartbeat = (self._tick % self.HEARTBEAT_INTERVAL == 0) and self._tick > 0

        if is_heartbeat:
            logger.info(f"💓 HEARTBEAT tick={self._tick} sim_hours={self.elapsed_sim_hours:.1f}")

        return TickEvent(
            tick_number=self._tick,
            mode=self._mode,
            elapsed_sim_minutes=self._total_sim_minutes,
            elapsed_sim_hours=self._total_sim_minutes / 60.0,
            wall_clock_seconds=time.monotonic() - self._start_time,
            is_heartbeat=is_heartbeat,
            burst_ticks_remaining=self._burst_ticks_remaining,
            metadata={
                "burst_drift_id": self._burst_drift_id,
                "pending_drifts": len(self._pending_drifts),
            },
        )

    def _handle_burst_decrement(self) -> None:
        """Decrement burst counter and exit if expired."""
        if self._mode == ClockMode.BURST:
            self._burst_ticks_remaining -= 1
            if self._burst_ticks_remaining <= 0:
                logger.info("⏰ Burst window expired, reverting to STANDARD")
                self.exit_burst_mode(remediation_successful=False)
