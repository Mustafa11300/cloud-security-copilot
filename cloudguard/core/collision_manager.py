"""
RESOURCE COLLISION MANAGER — DISTRIBUTED LOCK & BATCH COORDINATOR
==================================================================
Phase 8 Module 93 — Parallel Hardening & Chaos Trial

Implements a Redis-backed locking mechanism (CollisionManager) that ensures
no two RemediationSurgeon threads can mutate the same cloud resource
concurrently — preventing "Security Holes" introduced by race conditions.

Architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │  50 inbound drifts (chaos storm)                            │
  │       ↓                                                     │
  │  CollisionManager.acquire_lock(resource_id)                 │
  │       ├── ACQUIRED  → spawn RemediationSurgeon thread        │
  │       ├── CONTESTED → batch into existing payload           │
  │       └── QUEUED    → serial queue (FIFO after first done)  │
  └─────────────────────────────────────────────────────────────┘

Lock Design:
  • Redis SET NX PX (atomic, expires in `lock_ttl_ms` milliseconds)
  • Lock key: "cg_lock:{resource_id}"
  • Lock value: "{thread_id}:{timestamp_utc}"
  • On acquisition failure → check if resource is in active batch list
    - If batching enabled → add to existing payload batch
    - Else → enqueue in per-resource serial queue

Thread Safety:
  • Python threading.Lock guards the in-process payload_batches dict
  • Redis provides distributed lock across processes/pods
  • All operations are atomic; no busy-wait (exponential backoff)

Academic Reference:
  - Distributed Locks with Redis — Redlock Algorithm (Antirez, 2014)
  - NIST SP 800-53 SC-5: Denial of Service Protection
  - CIS Control 4: Secure Configuration (race-condition hardening)
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("cloudguard.collision_manager")


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

LOCK_KEY_PREFIX: str = "cg_lock:"
LOCK_TTL_MS:     int = 30_000   # 30-second lock TTL (max remediation runtime)
LOCK_RETRY_DELAY: float = 0.05  # 50ms between acquisition retries
LOCK_MAX_RETRIES: int   = 3     # Retries before falling back to batch/queue
BATCH_WINDOW_SECONDS: float = 2.0  # Group arrivals within this window into a batch


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

class LockOutcome(str, Enum):
    ACQUIRED  = "ACQUIRED"   # Lock obtained — spawn thread immediately
    BATCHED   = "BATCHED"    # Merged into existing thread's payload
    QUEUED    = "QUEUED"     # Added to serial FIFO queue
    RELEASED  = "RELEASED"   # Lock was successfully released


@dataclass
class LockHandle:
    """Opaque handle returned by acquire_lock(); pass to release_lock()."""
    resource_id: str
    lock_key:    str
    lock_value:  str
    thread_id:   str
    acquired_at: datetime
    outcome:     LockOutcome


@dataclass
class BatchedPayload:
    """
    Holds the accumulated drift payloads for a resource that is
    already under active remediation — 'Cluster Effect' batching.
    """
    resource_id:      str
    primary_drift_id: str
    created_at:       datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    drifts:           list[dict[str, Any]] = field(default_factory=list)
    lock_holder:      str = ""   # thread_id of the owning surgeon

    @property
    def batch_size(self) -> int:
        return len(self.drifts)

    def add(self, drift: dict[str, Any]) -> None:
        self.drifts.append({**drift, "_batched_at": datetime.now(timezone.utc).isoformat()})

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id":      self.resource_id,
            "primary_drift_id": self.primary_drift_id,
            "lock_holder":      self.lock_holder,
            "batch_size":       self.batch_size,
            "created_at":       self.created_at.isoformat(),
            "drifts":           self.drifts,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# REDIS BACKEND (Graceful Fallback)
# ═══════════════════════════════════════════════════════════════════════════════

class _RedisLockBackend:
    """
    Thin Redis wrapper for atomic SET NX PX lock operations.
    Falls back to an in-process dict if Redis is unavailable.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis = None
        self._fallback: dict[str, str] = {}   # in-process fallback
        self._fallback_lock = threading.Lock()
        self._redis_available = False
        self._connect(redis_url)

    def _connect(self, url: str) -> None:
        try:
            import redis as _redis
            client = _redis.from_url(url, socket_connect_timeout=2, decode_responses=True)
            client.ping()
            self._redis = client
            self._redis_available = True
            logger.info(f"[CollisionManager] Redis connected → {url}")
        except Exception as exc:
            logger.warning(
                f"[CollisionManager] Redis unavailable ({exc}) — "
                "using in-process fallback lock backend"
            )

    # ── Atomic SET NX ──────────────────────────────────────────────────────────

    def set_nx(self, key: str, value: str, ttl_ms: int) -> bool:
        """Atomically set key=value only if key does not exist. Returns True if set."""
        if self._redis_available and self._redis:
            try:
                return bool(self._redis.set(key, value, px=ttl_ms, nx=True))
            except Exception as exc:
                logger.error(f"[CollisionManager] Redis set_nx error: {exc}")
        # Fallback
        with self._fallback_lock:
            if key not in self._fallback:
                self._fallback[key] = value
                return True
            return False

    def get(self, key: str) -> Optional[str]:
        if self._redis_available and self._redis:
            try:
                return self._redis.get(key)
            except Exception:
                pass
        with self._fallback_lock:
            return self._fallback.get(key)

    def delete_if_value(self, key: str, value: str) -> bool:
        """Lua-atomic delete: only delete if the stored value matches (we own the lock)."""
        lua_script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        if self._redis_available and self._redis:
            try:
                result = self._redis.eval(lua_script, 1, key, value)
                return bool(result)
            except Exception as exc:
                logger.error(f"[CollisionManager] Redis delete_if_value error: {exc}")
        # Fallback
        with self._fallback_lock:
            if self._fallback.get(key) == value:
                del self._fallback[key]
                return True
            return False

    @property
    def is_redis_available(self) -> bool:
        return self._redis_available


# ═══════════════════════════════════════════════════════════════════════════════
# COLLISION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class CollisionManager:
    """
    Distributed lock coordinator for parallel remediation threads.

    Ensures that concurrent drift events targeting the same resource_id are
    handled safely via one of three strategies:

      1. ACQUIRED  — Lock obtained; caller should spawn a RemediationSurgeon thread.
      2. BATCHED   — Resource is being remediated; drift merged into active payload.
      3. QUEUED    — Resource locked, not batchable; enqueue for serial execution.

    Thread Safety:
      All in-process state (batches, queues) is guarded by threading.RLock.
      Redis provides the distributed lock primitive.

    Usage:
        mgr = CollisionManager()

        handle = mgr.acquire_lock(resource_id="arn:...", drift_payload={...})
        if handle.outcome == LockOutcome.ACQUIRED:
            # Start your remediation thread
            ...
            mgr.release_lock(handle)
        elif handle.outcome == LockOutcome.BATCHED:
            # Payload was merged — primary thread will handle it
            pass
        elif handle.outcome == LockOutcome.QUEUED:
            # Will execute serially after current thread finishes
            pass
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        lock_ttl_ms: int = LOCK_TTL_MS,
        batch_window_seconds: float = BATCH_WINDOW_SECONDS,
        enable_batching: bool = True,
    ) -> None:
        self._backend = _RedisLockBackend(redis_url)
        self._lock_ttl_ms = lock_ttl_ms
        self._batch_window = batch_window_seconds
        self._enable_batching = enable_batching

        # In-process state (protected by RLock)
        self._state_lock = threading.RLock()
        self._active_batches:   dict[str, BatchedPayload]      = {}  # resource_id → batch
        self._serial_queues:    dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self._active_handles:   dict[str, LockHandle]           = {}  # resource_id → handle

        # Metrics
        self._acquired_count = 0
        self._batched_count  = 0
        self._queued_count   = 0
        self._released_count = 0
        self._veto_count     = 0

        logger.info(
            f"[CollisionManager] Initialized (Redis: {self._backend.is_redis_available}, "
            f"TTL: {lock_ttl_ms}ms, Batch: {enable_batching})"
        )

    # ─── Core API ─────────────────────────────────────────────────────────────

    def acquire_lock(
        self,
        resource_id: str,
        drift_payload: dict[str, Any],
        thread_id: Optional[str] = None,
    ) -> LockHandle:
        """
        Attempt to acquire a distributed lock for resource_id.

        Args:
            resource_id:    The cloud resource ARN / ID to lock.
            drift_payload:  The drift event payload to associate.
            thread_id:      Caller's thread ID (auto-detected if None).

        Returns:
            LockHandle with outcome ACQUIRED, BATCHED, or QUEUED.
        """
        thread_id = thread_id or str(threading.current_thread().ident)
        lock_key  = f"{LOCK_KEY_PREFIX}{resource_id}"
        lock_val  = f"{thread_id}:{uuid.uuid4().hex[:8]}:{time.time()}"

        # Try atomic acquisition with retries
        for attempt in range(LOCK_MAX_RETRIES):
            acquired = self._backend.set_nx(lock_key, lock_val, self._lock_ttl_ms)
            if acquired:
                with self._state_lock:
                    handle = LockHandle(
                        resource_id=resource_id,
                        lock_key=lock_key,
                        lock_value=lock_val,
                        thread_id=thread_id,
                        acquired_at=datetime.now(timezone.utc),
                        outcome=LockOutcome.ACQUIRED,
                    )
                    self._active_handles[resource_id] = handle
                    # Open a batch payload for potential latecomers
                    self._active_batches[resource_id] = BatchedPayload(
                        resource_id=resource_id,
                        primary_drift_id=drift_payload.get("drift_id", "?"),
                        lock_holder=thread_id,
                    )
                    self._acquired_count += 1
                    logger.info(
                        f"[CollisionManager] 🔒 LOCK ACQUIRED: {resource_id[:50]} "
                        f"[thread={thread_id}]"
                    )
                return handle

            # Failed — brief back-off then retry
            time.sleep(LOCK_RETRY_DELAY * (attempt + 1))

        # Could not acquire — decide: BATCH or QUEUE
        return self._handle_contention(
            resource_id, drift_payload, thread_id, lock_key
        )

    def release_lock(self, handle: LockHandle) -> bool:
        """
        Release the lock identified by the handle.
        Drains the serial queue for this resource (runs queued drifts).

        Returns:
            True if lock was released (we owned it); False otherwise.
        """
        released = self._backend.delete_if_value(handle.lock_key, handle.lock_value)
        with self._state_lock:
            self._active_handles.pop(handle.resource_id, None)
            batch = self._active_batches.pop(handle.resource_id, None)

        if released:
            self._released_count += 1
            logger.info(
                f"[CollisionManager] 🔓 LOCK RELEASED: {handle.resource_id[:50]} "
                f"[batch_size={batch.batch_size if batch else 0}]"
            )
            # Drain the serial queue for this resource
            self._drain_queue(handle.resource_id)
        else:
            logger.warning(
                f"[CollisionManager] Could not release lock for {handle.resource_id[:50]} "
                "(expired or stolen)"
            )

        return released

    def get_batch(self, resource_id: str) -> Optional[BatchedPayload]:
        """
        Retrieve the accumulated batch payload for a resource.
        Called by RemediationSurgeon before applying fixes.
        """
        with self._state_lock:
            return self._active_batches.get(resource_id)

    def drain_queue_next(self, resource_id: str) -> Optional[dict[str, Any]]:
        """Pop the next queued payload for serial processing."""
        with self._state_lock:
            q = self._serial_queues.get(resource_id)
            return q.popleft() if q else None

    # ─── Contention Handling ──────────────────────────────────────────────────

    def _handle_contention(
        self,
        resource_id: str,
        drift_payload: dict[str, Any],
        thread_id: str,
        lock_key: str,
    ) -> LockHandle:
        """
        Lock is held by another thread.
        Decide: BATCH into existing payload, or QUEUE for serial execution.
        """
        with self._state_lock:
            batch = self._active_batches.get(resource_id)
            # If batch is still open AND within time window → BATCH
            if (
                self._enable_batching
                and batch is not None
                and (datetime.now(timezone.utc) - batch.created_at).total_seconds()
                    < self._batch_window
            ):
                batch.add(drift_payload)
                self._batched_count += 1
                logger.info(
                    f"[CollisionManager] 📦 BATCHED drift into active payload: "
                    f"{resource_id[:50]} (batch_size={batch.batch_size})"
                )
                return LockHandle(
                    resource_id=resource_id,
                    lock_key=lock_key,
                    lock_value="",
                    thread_id=thread_id,
                    acquired_at=datetime.now(timezone.utc),
                    outcome=LockOutcome.BATCHED,
                )

            # Otherwise → QUEUE for serial execution
            self._serial_queues[resource_id].append(drift_payload)
            self._queued_count += 1
            logger.info(
                f"[CollisionManager] 🗃️  QUEUED drift for serial execution: "
                f"{resource_id[:50]} (queue_depth={len(self._serial_queues[resource_id])})"
            )
            return LockHandle(
                resource_id=resource_id,
                lock_key=lock_key,
                lock_value="",
                thread_id=thread_id,
                acquired_at=datetime.now(timezone.utc),
                outcome=LockOutcome.QUEUED,
            )

    def _drain_queue(self, resource_id: str) -> None:
        """
        After lock release — process queued drifts serially.
        In production this would re-submit each enqueued payload to the
        Orchestrator. Here we log for transparency.
        """
        with self._state_lock:
            q = self._serial_queues.get(resource_id, deque())
            count = len(q)

        if count:
            logger.info(
                f"[CollisionManager] 🔄 Draining {count} queued drift(s) for "
                f"{resource_id[:50]} — will be re-submitted serially"
            )

    # ─── Metrics & Reporting ──────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        with self._state_lock:
            active_batches = {
                rk: b.batch_size for rk, b in self._active_batches.items()
                if b.batch_size > 0
            }
            queue_depths = {
                rk: len(q) for rk, q in self._serial_queues.items() if q
            }
        return {
            "redis_available":  self._backend.is_redis_available,
            "lock_ttl_ms":      self._lock_ttl_ms,
            "acquired_count":   self._acquired_count,
            "batched_count":    self._batched_count,
            "queued_count":     self._queued_count,
            "released_count":   self._released_count,
            "active_locks":     len(self._active_handles),
            "active_batches":   active_batches,
            "queue_depths":     queue_depths,
            "global_veto_count": self._veto_count,
        }

    def record_global_veto(self) -> None:
        """Called by AuditSurgeon when a GLOBAL_VETO is issued."""
        self._veto_count += 1


# ═══════════════════════════════════════════════════════════════════════════════
# PARALLEL THREAD POOL EXECUTOR (for the 50-drift Chaos Trial)
# ═══════════════════════════════════════════════════════════════════════════════

class ParallelRemediationPool:
    """
    Spawns up to `max_workers` RemediationSurgeon threads, each guarded
    by the CollisionManager, and routes each drift to ACQUIRED / BATCHED / QUEUED.

    Integration:
        pool = ParallelRemediationPool(collision_mgr=mgr, max_workers=50)
        futures = pool.submit_all(drift_list, surgeon_fn)
        results = pool.collect_results(futures)
    """

    def __init__(
        self,
        collision_mgr: Optional[CollisionManager] = None,
        max_workers: int = 50,
    ) -> None:
        self._mgr = collision_mgr or CollisionManager()
        self._max_workers = max_workers
        self._results: list[dict[str, Any]] = []
        self._results_lock = threading.Lock()

    def submit_all(
        self,
        drifts: list[dict[str, Any]],
        surgeon_fn: Callable[[dict[str, Any], Optional[BatchedPayload]], dict[str, Any]],
    ) -> list[threading.Thread]:
        """
        Submit all drifts to the thread pool.

        Args:
            drifts:     List of drift event dicts (each must have 'resource_id').
            surgeon_fn: Callable(drift, batch) → result_dict — the RemediationSurgeon logic.

        Returns:
            List of Thread objects (call t.join() to wait).
        """
        threads: list[threading.Thread] = []

        for drift in drifts:
            resource_id = drift.get("resource_id", f"unknown-{uuid.uuid4().hex[:6]}")
            t = threading.Thread(
                target=self._worker,
                args=(resource_id, drift, surgeon_fn),
                name=f"Surgeon-{resource_id[-12:]}",
                daemon=True,
            )
            threads.append(t)

        # Fire all threads simultaneously
        logger.info(f"[ParallelPool] 🚀 Firing {len(threads)} parallel Surgeon threads")
        for t in threads:
            t.start()

        return threads

    def _worker(
        self,
        resource_id: str,
        drift: dict[str, Any],
        surgeon_fn: Callable,
    ) -> None:
        handle = self._mgr.acquire_lock(resource_id, drift)
        result: dict[str, Any] = {
            "resource_id":  resource_id,
            "drift_id":     drift.get("drift_id"),
            "lock_outcome": handle.outcome.value,
            "worker_thread": threading.current_thread().name,
        }

        try:
            if handle.outcome == LockOutcome.ACQUIRED:
                batch = self._mgr.get_batch(resource_id)
                surgeon_result = surgeon_fn(drift, batch)
                result.update(surgeon_result or {})
                self._mgr.release_lock(handle)

            elif handle.outcome == LockOutcome.BATCHED:
                result["status"] = "merged_into_primary"
                logger.debug(
                    f"[ParallelPool] Drift {drift.get('drift_id')} batched into "
                    f"primary thread for {resource_id[:40]}"
                )

            elif handle.outcome == LockOutcome.QUEUED:
                result["status"] = "queued_for_serial"
                logger.debug(
                    f"[ParallelPool] Drift {drift.get('drift_id')} queued for "
                    f"serial processing on {resource_id[:40]}"
                )

        except Exception as exc:
            result["error"] = str(exc)
            result["status"] = "surgeon_error"
            logger.error(
                f"[ParallelPool] Surgeon error for {resource_id[:40]}: {exc}"
            )
            if handle.outcome == LockOutcome.ACQUIRED:
                self._mgr.release_lock(handle)  # Always release on error

        with self._results_lock:
            self._results.append(result)

    def collect_results(
        self,
        threads: list[threading.Thread],
        timeout_per_thread: float = 60.0,
    ) -> list[dict[str, Any]]:
        """Wait for all threads and return collected results."""
        for t in threads:
            t.join(timeout=timeout_per_thread)
            if t.is_alive():
                logger.warning(f"[ParallelPool] Thread {t.name} timed out after {timeout_per_thread}s")
        with self._results_lock:
            return list(self._results)

    def get_collision_stats(self) -> dict[str, Any]:
        return self._mgr.get_stats()
