"""
REDIS PUB/SUB EVENT BUS — EVENT-DRIVEN SIEM
=============================================
Subsystem 3 — Phase 1 Foundation

The simulator pushes JSON payloads to Redis channel `cloudguard_events`.

Payload Requirements:
  - trace_id: Distributed trace identifier
  - timestamp_tick: Simulation tick when event occurred
  - environment_weights: (w_R, w_C) optimization weights

Log Stream: Emulates a Splunk-style stream containing:
  - VPC Flow Logs
  - CloudTrail Events
  - K8s Audit Logs
  - Cumulative Drifts
  - False Positives (Sahay & Soto, 2026)

Watchdog: The TemporalClock emits HEARTBEAT every 10 ticks.
This module forwards heartbeats to Redis for agent health monitoring.

Redis is OPTIONAL for local development. If Redis is unavailable,
the bus falls back to an in-memory queue (logged to console).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("cloudguard.redis_bus")

# Redis channel name
CHANNEL_NAME = "cloudguard_events"
SIEM_CHANNEL = "cloudguard_siem"

# Try to import redis
try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    try:
        import redis as sync_redis
        HAS_REDIS = True
    except ImportError:
        HAS_REDIS = False
        logger.info("Redis not available — using in-memory event bus")


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT PAYLOAD SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class EventPayload:
    """
    Standardized JSON payload for Redis pub/sub.
    Every event published to `cloudguard_events` uses this format.
    """

    @staticmethod
    def create(
        event_type: str,
        trace_id: Optional[str] = None,
        timestamp_tick: int = 0,
        w_risk: float = 0.6,
        w_cost: float = 0.4,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Create a standardized event payload.

        Args:
            event_type: Type of event (DRIFT, HEARTBEAT, REMEDIATION, etc.)
            trace_id: Distributed trace ID for correlation
            timestamp_tick: Simulation tick number
            w_risk: Risk weight (w_R)
            w_cost: Cost weight (w_C)
            data: Event-specific data

        Returns:
            JSON-serializable dict meeting the Redis payload requirements.
        """
        return {
            "event_id": f"evt-{uuid.uuid4().hex[:8]}",
            "event_type": event_type,
            "trace_id": trace_id or f"trace-{uuid.uuid4().hex[:12]}",
            "timestamp_tick": timestamp_tick,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "environment_weights": {
                "w_R": w_risk,
                "w_C": w_cost,
            },
            "data": data or {},
        }

    @staticmethod
    def heartbeat(tick: int, w_risk: float = 0.6, w_cost: float = 0.4) -> dict:
        """Create a HEARTBEAT payload (emitted every 10 ticks)."""
        return EventPayload.create(
            event_type="HEARTBEAT",
            timestamp_tick=tick,
            w_risk=w_risk,
            w_cost=w_cost,
            data={"status": "alive", "tick": tick},
        )

    @staticmethod
    def drift(
        resource_id: str,
        drift_type: str,
        severity: str,
        tick: int,
        trace_id: Optional[str] = None,
        mutations: Optional[dict] = None,
        cumulative_score: float = 0.0,
        is_false_positive: bool = False,
        w_risk: float = 0.6,
        w_cost: float = 0.4,
    ) -> dict:
        """Create a DRIFT event payload."""
        return EventPayload.create(
            event_type="DRIFT",
            trace_id=trace_id,
            timestamp_tick=tick,
            w_risk=w_risk,
            w_cost=w_cost,
            data={
                "resource_id": resource_id,
                "drift_type": drift_type,
                "severity": severity,
                "mutations": mutations or {},
                "cumulative_drift_score": cumulative_score,
                "is_false_positive": is_false_positive,
            },
        )

    @staticmethod
    def remediation(
        resource_id: str,
        action: str,
        tier: str,
        tick: int,
        success: bool,
        j_before: float = 0.0,
        j_after: float = 0.0,
        trace_id: Optional[str] = None,
    ) -> dict:
        """Create a REMEDIATION event payload."""
        return EventPayload.create(
            event_type="REMEDIATION",
            trace_id=trace_id,
            timestamp_tick=tick,
            data={
                "resource_id": resource_id,
                "action": action,
                "tier": tier,
                "success": success,
                "j_before": j_before,
                "j_after": j_after,
            },
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SIEM LOG EMULATOR
# ═══════════════════════════════════════════════════════════════════════════════

class SIEMLogEmulator:
    """
    Emulates a Splunk-style SIEM log stream.
    Generates VPC Flow, CloudTrail, and K8s Audit log entries
    containing cumulative drift scores and false positive markers.

    Sahay & Soto (2026): Modeling cumulative drifts and false positives
    is essential for measuring real-world SIEM accuracy.
    """

    LOG_TYPES = ["VPC_FLOW", "CLOUDTRAIL", "K8S_AUDIT"]

    @staticmethod
    def vpc_flow_log(
        resource_id: str,
        source_ip: str = "10.0.1.100",
        dest_ip: str = "0.0.0.0",
        port: int = 443,
        action: str = "ACCEPT",
        tick: int = 0,
    ) -> dict:
        """Generate a VPC Flow Log entry."""
        return {
            "log_type": "VPC_FLOW",
            "timestamp_tick": tick,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "resource_id": resource_id,
            "source_ip": source_ip,
            "dest_ip": dest_ip,
            "dest_port": port,
            "protocol": "TCP",
            "action": action,
            "bytes": 1024,
        }

    @staticmethod
    def cloudtrail_event(
        event_name: str,
        resource_id: str,
        user_identity: str = "root",
        source_ip: str = "203.0.113.1",
        is_error: bool = False,
        tick: int = 0,
    ) -> dict:
        """Generate a CloudTrail audit event."""
        return {
            "log_type": "CLOUDTRAIL",
            "timestamp_tick": tick,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_name": event_name,
            "resource_id": resource_id,
            "user_identity": user_identity,
            "source_ip_address": source_ip,
            "event_source": "s3.amazonaws.com",
            "error_code": "AccessDenied" if is_error else None,
            "read_only": event_name.startswith("Get"),
        }

    @staticmethod
    def k8s_audit_log(
        resource_id: str,
        verb: str = "create",
        resource_kind: str = "Pod",
        namespace: str = "default",
        user: str = "system:serviceaccount",
        tick: int = 0,
    ) -> dict:
        """Generate a K8s Audit Log entry."""
        return {
            "log_type": "K8S_AUDIT",
            "timestamp_tick": tick,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "resource_id": resource_id,
            "verb": verb,
            "resource_kind": resource_kind,
            "namespace": namespace,
            "user": user,
            "response_status": 200,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT BUS (Redis + In-Memory Fallback)
# ═══════════════════════════════════════════════════════════════════════════════

# Type for event subscribers
EventSubscriber = Callable[[dict[str, Any]], Any]


class EventBus:
    """
    Redis Pub/Sub event bus with in-memory fallback.

    Publishes events to Redis channel `cloudguard_events`.
    If Redis is unavailable, events are queued in-memory
    and logged for debugging.

    Usage:
        bus = EventBus(redis_url="redis://localhost:6379")
        await bus.connect()

        # Publish an event
        await bus.publish(EventPayload.heartbeat(tick=10))

        # Subscribe to events
        bus.subscribe(my_callback)

        # Process SIEM logs
        bus.emit_siem_log(SIEMLogEmulator.vpc_flow_log(...))
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        channel: str = CHANNEL_NAME,
        max_memory_queue: int = 10000,
    ) -> None:
        self._redis_url = redis_url
        self._channel = channel
        self._redis_client = None
        self._connected = False
        self._subscribers: list[EventSubscriber] = []

        # In-memory fallback queue
        self._memory_queue: deque[dict] = deque(maxlen=max_memory_queue)
        self._siem_queue: deque[dict] = deque(maxlen=max_memory_queue)

        # Stats
        self._published_count: int = 0
        self._failed_count: int = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def published_count(self) -> int:
        return self._published_count

    @property
    def queue_size(self) -> int:
        return len(self._memory_queue)

    async def connect(self) -> bool:
        """
        Connect to Redis. Returns True if connected, False if falling back.
        """
        if not HAS_REDIS:
            logger.info("📡 EventBus: Redis not installed, using in-memory mode")
            return False

        try:
            self._redis_client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await self._redis_client.ping()
            self._connected = True
            logger.info(f"📡 EventBus: Connected to Redis at {self._redis_url}")
            return True
        except Exception as e:
            logger.warning(f"📡 EventBus: Redis unavailable ({e}), using in-memory mode")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis_client:
            await self._redis_client.close()
            self._connected = False
            logger.info("📡 EventBus: Disconnected from Redis")

    def connect_sync(self, redis_url: Optional[str] = None) -> bool:
        """Synchronous connection attempt (for non-async contexts)."""
        url = redis_url or self._redis_url
        if not HAS_REDIS:
            return False
        try:
            client = sync_redis.from_url(url, decode_responses=True, socket_connect_timeout=3)
            client.ping()
            self._connected = True
            logger.info(f"📡 EventBus: Sync connected to Redis at {url}")
            return True
        except Exception as e:
            logger.warning(f"📡 EventBus: Sync Redis unavailable ({e}), in-memory mode")
            return False

    # ── Publishing ────────────────────────────────────────────────────────────

    async def publish(self, payload: dict[str, Any]) -> bool:
        """
        Publish an event payload to Redis (or in-memory queue).
        Returns True if published successfully.
        """
        payload_json = json.dumps(payload, default=str)

        if self._connected and self._redis_client:
            try:
                await self._redis_client.publish(self._channel, payload_json)
                self._published_count += 1
                logger.debug(
                    f"📤 Published {payload.get('event_type', '?')} "
                    f"(tick={payload.get('timestamp_tick', '?')})"
                )
                # Also notify local subscribers
                self._notify_subscribers(payload)
                return True
            except Exception as e:
                logger.error(f"Redis publish failed: {e}")
                self._failed_count += 1

        # Fallback: in-memory queue
        self._memory_queue.append(payload)
        self._published_count += 1
        self._notify_subscribers(payload)
        logger.debug(
            f"📥 Queued (in-memory) {payload.get('event_type', '?')} "
            f"(queue size: {len(self._memory_queue)})"
        )
        return True

    def publish_sync(self, payload: dict[str, Any]) -> bool:
        """Synchronous publish for non-async contexts."""
        self._memory_queue.append(payload)
        self._published_count += 1
        self._notify_subscribers(payload)
        return True

    # ── SIEM Log Stream ───────────────────────────────────────────────────────

    async def emit_siem_log(self, log_entry: dict[str, Any]) -> None:
        """Emit a SIEM log entry to the dedicated SIEM channel."""
        self._siem_queue.append(log_entry)

        if self._connected and self._redis_client:
            try:
                await self._redis_client.publish(
                    SIEM_CHANNEL,
                    json.dumps(log_entry, default=str),
                )
            except Exception:
                pass  # SIEM logs are best-effort

    def emit_siem_log_sync(self, log_entry: dict[str, Any]) -> None:
        """Synchronous SIEM log emission."""
        self._siem_queue.append(log_entry)

    # ── Subscribing ───────────────────────────────────────────────────────────

    def subscribe(self, callback: EventSubscriber) -> None:
        """Register a local subscriber for event notifications."""
        self._subscribers.append(callback)

    def unsubscribe(self, callback: EventSubscriber) -> None:
        """Remove a subscriber."""
        self._subscribers = [s for s in self._subscribers if s is not callback]

    def _notify_subscribers(self, payload: dict[str, Any]) -> None:
        """Notify all local subscribers of a new event."""
        for sub in self._subscribers:
            try:
                sub(payload)
            except Exception as e:
                logger.error(f"Subscriber error: {e}")

    # ── Queue Access ──────────────────────────────────────────────────────────

    def drain_queue(self, max_items: int = 100) -> list[dict]:
        """Drain events from the in-memory queue."""
        items = []
        for _ in range(min(max_items, len(self._memory_queue))):
            items.append(self._memory_queue.popleft())
        return items

    def drain_siem_queue(self, max_items: int = 100) -> list[dict]:
        """Drain SIEM logs from the in-memory queue."""
        items = []
        for _ in range(min(max_items, len(self._siem_queue))):
            items.append(self._siem_queue.popleft())
        return items

    def get_stats(self) -> dict:
        """Get event bus statistics."""
        return {
            "connected": self._connected,
            "channel": self._channel,
            "published_count": self._published_count,
            "failed_count": self._failed_count,
            "memory_queue_size": len(self._memory_queue),
            "siem_queue_size": len(self._siem_queue),
            "subscribers": len(self._subscribers),
        }
