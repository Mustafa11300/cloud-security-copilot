"""
SENTRY NODE — ASYMMETRIC TRIAGE & WINDOWED AGGREGATION
========================================================
Phase 2 Module 1 — Cognitive Cloud OS

The high-frequency gatekeeper for CloudGuard-B. Filters Redis noise
before waking the swarm agents using:

  1. Redis Integration: Subscribe to `cloudguard_events` channel
  2. Windowed Aggregation: 10-second debounce buffer
  3. NLU Triage (Ollama): De-duplicate, filter ghost spikes, categorize
  4. H-MEM Pre-Check: Query MemoryService for heuristic matches
  5. Output: Emit PolicyViolation signal only for confirmed drifts

Architecture:
  Redis Events → [10s Window] → [NLU Triage] → [H-MEM Check] → PolicyViolation

Design Decisions:
  - Ollama/Llama 3 is OPTIONAL — falls back to rule-based triage
  - Ghost Spikes: telemetry jitter with no policy impact (filtered)
  - DriftEvent schema used for structured output
  - Only confirmed drifts wake the swarm (asymmetric wake pattern)

Academic References:
  - Sahay & Soto (2026): False positive modeling in SIEM correlation
  - Event-Driven Architecture: Michelson (2006) — Event-Driven SOA
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger("cloudguard.sentry")

# ── Optional Ollama import ────────────────────────────────────────────────────
try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    logger.info("httpx not available — Ollama NLU triage will use rule-based fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class DriftEventOutput:
    """
    Structured output from the Sentry's NLU triage.
    Follows the DriftEvent JSON schema for downstream processing.
    """

    event_id: str = field(
        default_factory=lambda: f"sentry-{uuid.uuid4().hex[:8]}"
    )
    resource_id: str = ""
    drift_type: str = ""
    severity: str = "MEDIUM"
    raw_logs: list[dict[str, Any]] = field(default_factory=list)
    is_ghost_spike: bool = False
    is_duplicate: bool = False
    confidence: float = 0.0
    triage_reasoning: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "resource_id": self.resource_id,
            "drift_type": self.drift_type,
            "severity": self.severity,
            "raw_log_count": len(self.raw_logs),
            "is_ghost_spike": self.is_ghost_spike,
            "is_duplicate": self.is_duplicate,
            "confidence": self.confidence,
            "triage_reasoning": self.triage_reasoning,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class PolicyViolation:
    """
    Signal emitted to the LangGraph Orchestrator when a true drift
    is confirmed after triage and H-MEM pre-check.
    """

    violation_id: str = field(
        default_factory=lambda: f"pv-{uuid.uuid4().hex[:8]}"
    )
    drift_events: list[DriftEventOutput] = field(default_factory=list)
    heuristic_available: bool = False
    heuristic_proposal: Optional[dict[str, Any]] = None
    batch_size: int = 0
    window_duration_ms: float = 0.0
    total_raw_events: int = 0
    filtered_count: int = 0  # Ghost spikes + duplicates removed
    confidence: float = 0.0
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "drift_events": [e.to_dict() for e in self.drift_events],
            "heuristic_available": self.heuristic_available,
            "heuristic_proposal": self.heuristic_proposal,
            "batch_size": self.batch_size,
            "window_duration_ms": self.window_duration_ms,
            "total_raw_events": self.total_raw_events,
            "filtered_count": self.filtered_count,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# TRIAGE ENGINE (Rule-Based Fallback)
# ═══════════════════════════════════════════════════════════════════════════════

# Drift types with known policy impact
POLICY_IMPACT_DRIFTS = {
    "permission_escalation",
    "public_exposure",
    "encryption_removed",
    "network_rule_change",
    "iam_policy_change",
    "backup_disabled",
}

# Telemetry-only drifts (potential ghost spikes)
TELEMETRY_DRIFTS = {
    "resource_created",
    "resource_deleted",
    "tag_removed",
    "cost_spike",
}

# Severity hierarchy for deduplication
SEVERITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}


def _event_fingerprint(event: dict[str, Any]) -> str:
    """
    Generate a fingerprint for an event to detect duplicates.
    Based on resource_id + drift_type + key mutations.
    """
    data = event.get("data", event)
    key_parts = [
        str(data.get("resource_id", "")),
        str(data.get("drift_type", "")),
        json.dumps(sorted(data.get("mutations", {}).keys())),
    ]
    raw = "|".join(key_parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _is_ghost_spike(event: dict[str, Any]) -> bool:
    """
    Detect 'Ghost Spikes' — telemetry jitter with no policy impact.

    Ghost spike criteria:
      1. Drift type is telemetry-only (not in POLICY_IMPACT_DRIFTS)
      2. No mutations affecting security posture
      3. Marked as false positive
    """
    data = event.get("data", event)
    drift_type = data.get("drift_type", "")
    is_fp = data.get("is_false_positive", False)
    mutations = data.get("mutations", {})

    # Explicitly marked as false positive
    if is_fp:
        return True

    # Telemetry-only drift with no security mutations
    if drift_type in TELEMETRY_DRIFTS:
        security_keys = {
            "encryption_enabled",
            "public_access_blocked",
            "mfa_enabled",
            "has_admin_policy",
            "overly_permissive",
            "publicly_accessible",
        }
        has_security_mutation = any(k in security_keys for k in mutations)
        if not has_security_mutation:
            return True

    return False


def _rule_based_triage(
    batch: list[dict[str, Any]],
) -> list[DriftEventOutput]:
    """
    Rule-based triage fallback when Ollama is not available.

    Steps:
      1. De-duplicate identical alerts by fingerprint
      2. Filter out ghost spikes
      3. Categorize valid drifts into DriftEventOutput
    """
    seen_fingerprints: dict[str, dict[str, Any]] = {}
    results: list[DriftEventOutput] = []
    ghost_count = 0
    dup_count = 0

    for event in batch:
        fp = _event_fingerprint(event)
        data = event.get("data", event)

        # De-duplication: keep the highest severity version
        if fp in seen_fingerprints:
            existing = seen_fingerprints[fp]
            existing_sev = SEVERITY_ORDER.get(
                existing.get("data", existing).get("severity", "LOW"), 0
            )
            new_sev = SEVERITY_ORDER.get(
                data.get("severity", "LOW"), 0
            )
            if new_sev > existing_sev:
                seen_fingerprints[fp] = event
            dup_count += 1
            continue

        seen_fingerprints[fp] = event

    # Process deduplicated events
    for fp, event in seen_fingerprints.items():
        data = event.get("data", event)

        # Ghost spike filter
        if _is_ghost_spike(event):
            ghost_count += 1
            results.append(
                DriftEventOutput(
                    resource_id=data.get("resource_id", ""),
                    drift_type=data.get("drift_type", ""),
                    severity=data.get("severity", "LOW"),
                    raw_logs=[data],
                    is_ghost_spike=True,
                    confidence=0.0,
                    triage_reasoning="Filtered: ghost spike (telemetry jitter, no policy impact)",
                )
            )
            continue

        # Valid drift
        drift_type = data.get("drift_type", "unknown")
        severity = data.get("severity", "MEDIUM")
        confidence = 0.9 if drift_type in POLICY_IMPACT_DRIFTS else 0.6

        results.append(
            DriftEventOutput(
                resource_id=data.get("resource_id", ""),
                drift_type=drift_type,
                severity=severity,
                raw_logs=[data],
                is_ghost_spike=False,
                is_duplicate=False,
                confidence=confidence,
                triage_reasoning=(
                    f"Rule-based triage: {drift_type} ({severity}) "
                    f"on {data.get('resource_id', 'unknown')}. "
                    f"Policy impact: {'YES' if drift_type in POLICY_IMPACT_DRIFTS else 'UNKNOWN'}."
                ),
            )
        )

    if ghost_count > 0 or dup_count > 0:
        logger.info(
            f"🛡️ Triage: filtered {ghost_count} ghost spikes, "
            f"{dup_count} duplicates from {len(batch)} events"
        )

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA NLU TRIAGE
# ═══════════════════════════════════════════════════════════════════════════════

# System prompt for Ollama/Llama 3 triage
TRIAGE_SYSTEM_PROMPT = """You are the CloudGuard Sentry, a high-precision security triage system.

Given a batch of cloud security events, you must:
1. DE-DUPLICATE: Identify identical alerts and merge them, keeping the highest severity.
2. FILTER GHOST SPIKES: Remove telemetry jitter that has NO policy impact. Ghost spikes are:
   - Tag changes without security implications
   - Resource creation/deletion that doesn't affect security posture
   - Cost fluctuations within normal variance (< 20%)
   - Events marked as false positives
3. CATEGORIZE: For each valid drift, output a JSON object with:
   - resource_id: The affected resource
   - drift_type: Category (permission_escalation, public_exposure, encryption_removed, etc.)
   - severity: CRITICAL/HIGH/MEDIUM/LOW
   - confidence: 0.0-1.0 confidence that this is a real drift
   - reasoning: Why this is a valid drift

OUTPUT FORMAT: Return a JSON array of valid drift events only. Exclude ghost spikes.
Be extremely precise — false positives waste expensive swarm computation.
"""


async def _ollama_triage(
    batch: list[dict[str, Any]],
    ollama_base_url: str = "http://localhost:11434",
    model: str = "llama3:8b",
) -> list[DriftEventOutput]:
    """
    NLU-based triage using Ollama/Llama 3.

    Sends the batch to a local Ollama instance for intelligent de-duplication,
    ghost spike filtering, and drift categorization.
    """
    if not HAS_HTTPX:
        logger.warning("httpx not available, falling back to rule-based triage")
        return _rule_based_triage(batch)

    # Prepare the batch as a compact JSON string
    batch_text = json.dumps(
        [
            {
                "resource_id": e.get("data", e).get("resource_id", ""),
                "drift_type": e.get("data", e).get("drift_type", ""),
                "severity": e.get("data", e).get("severity", ""),
                "mutations": e.get("data", e).get("mutations", {}),
                "is_false_positive": e.get("data", e).get("is_false_positive", False),
                "tick": e.get("timestamp_tick", 0),
            }
            for e in batch
        ],
        indent=2,
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Triage the following {len(batch)} events:\n\n{batch_text}",
            },
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,  # Low temperature for precise triage
            "num_predict": 2048,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{ollama_base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        content = result.get("message", {}).get("content", "")
        parsed = json.loads(content)

        # Token count for budget tracking
        token_count = (
            result.get("prompt_eval_count", 0)
            + result.get("eval_count", 0)
        )

        # Build DriftEventOutput from LLM response
        events = parsed if isinstance(parsed, list) else parsed.get("events", [])
        outputs = []
        for item in events:
            outputs.append(
                DriftEventOutput(
                    resource_id=item.get("resource_id", ""),
                    drift_type=item.get("drift_type", ""),
                    severity=item.get("severity", "MEDIUM"),
                    raw_logs=[item],
                    confidence=item.get("confidence", 0.7),
                    triage_reasoning=item.get(
                        "reasoning",
                        f"NLU triage: {item.get('drift_type', 'unknown')} confirmed",
                    ),
                )
            )

        logger.info(
            f"🛡️ Ollama triage: {len(batch)} → {len(outputs)} valid drifts "
            f"(tokens={token_count})"
        )
        return outputs

    except Exception as e:
        logger.warning(
            f"🛡️ Ollama triage failed ({e}), falling back to rule-based"
        )
        return _rule_based_triage(batch)


# ═══════════════════════════════════════════════════════════════════════════════
# SENTRY NODE
# ═══════════════════════════════════════════════════════════════════════════════


class SentryNode:
    """
    High-frequency gatekeeper for CloudGuard-B.

    Implements Asymmetric Triage with Windowed Aggregation:
      1. Collects events in a 10-second debounce window
      2. At window end, runs NLU triage (Ollama or rule-based)
      3. Checks H-MEM for heuristic matches
      4. Emits PolicyViolation only for confirmed drifts

    Usage:
        sentry = SentryNode(memory_service=mem_svc)

        # Register violation handler
        sentry.on_violation(my_handler)

        # Start listening (async)
        await sentry.start()

        # Or process events manually
        violations = await sentry.process_batch(events)
    """

    DEFAULT_WINDOW_SECONDS = 10.0

    def __init__(
        self,
        memory_service: Optional[Any] = None,  # MemoryService from Module 3
        window_seconds: float = 10.0,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3:8b",
        use_ollama: bool = True,
        redis_channel: str = "cloudguard_events",
    ) -> None:
        self._memory_service = memory_service
        self._window_seconds = window_seconds
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model
        self._use_ollama = use_ollama
        self._redis_channel = redis_channel

        # Window buffer
        self._buffer: list[dict[str, Any]] = []
        self._window_start: Optional[float] = None
        self._window_timer: Optional[asyncio.Task] = None

        # Violation handlers
        self._violation_handlers: list[Callable] = []

        # Stats
        self._total_events_received = 0
        self._total_events_filtered = 0
        self._total_violations_emitted = 0
        self._total_windows_processed = 0
        self._total_heuristic_hits = 0

        # Running state
        self._running = False
        self._subscriber_task: Optional[asyncio.Task] = None

    # ─── Event Ingestion ──────────────────────────────────────────────────────

    async def ingest_event(self, event: dict[str, Any]) -> None:
        """
        Ingest a single event into the debounce window.

        If this is the first event in a new window, start the timer.
        All subsequent events within the window are buffered.
        """
        self._total_events_received += 1
        self._buffer.append(event)

        # Start window timer on first event
        if self._window_start is None:
            self._window_start = time.monotonic()
            self._window_timer = asyncio.create_task(
                self._window_timeout()
            )
            logger.debug(
                f"🛡️ Window started (will flush in {self._window_seconds}s)"
            )

    async def _window_timeout(self) -> None:
        """Wait for the window duration, then flush the buffer."""
        await asyncio.sleep(self._window_seconds)
        await self._flush_window()

    async def _flush_window(self) -> None:
        """Process the buffered events and emit violations."""
        if not self._buffer:
            self._window_start = None
            return

        batch = self._buffer.copy()
        self._buffer.clear()
        self._window_start = None
        self._total_windows_processed += 1

        window_duration = self._window_seconds * 1000  # ms

        logger.info(
            f"🛡️ Window flush: {len(batch)} events "
            f"(window #{self._total_windows_processed})"
        )

        # Process the batch
        violations = await self.process_batch(batch, window_duration)

        # Emit violations to handlers
        for violation in violations:
            await self._emit_violation(violation)

    # ─── Batch Processing ─────────────────────────────────────────────────────

    async def process_batch(
        self,
        batch: list[dict[str, Any]],
        window_duration_ms: float = 0.0,
    ) -> list[PolicyViolation]:
        """
        Process a batch of events through the triage pipeline.

        Pipeline:
          1. NLU Triage (Ollama or rule-based)
          2. Filter ghost spikes and duplicates
          3. H-MEM pre-check for each valid drift
          4. Build PolicyViolation signals

        Args:
            batch: List of raw event payloads.
            window_duration_ms: Duration of the collection window.

        Returns:
            List of PolicyViolation signals for confirmed drifts.
        """
        if not batch:
            return []

        # Step 1: NLU Triage
        if self._use_ollama:
            triaged = await _ollama_triage(
                batch, self._ollama_url, self._ollama_model
            )
        else:
            triaged = _rule_based_triage(batch)

        # Step 2: Filter out ghost spikes and duplicates
        valid_drifts = [
            e for e in triaged
            if not e.is_ghost_spike and not e.is_duplicate
        ]
        filtered_count = len(triaged) - len(valid_drifts)
        self._total_events_filtered += filtered_count

        if not valid_drifts:
            logger.info(
                f"🛡️ All {len(batch)} events filtered "
                f"(ghost spikes / duplicates)"
            )
            return []

        # Step 3: H-MEM pre-check for each valid drift
        violations = []
        for drift in valid_drifts:
            heuristic_proposal = None
            heuristic_available = False

            if self._memory_service is not None:
                try:
                    proposal = self._memory_service.query_victory(
                        drift_type=drift.drift_type,
                        resource_type="",
                        raw_logs=[json.dumps(log) for log in drift.raw_logs],
                    )
                    if proposal is not None:
                        heuristic_available = True
                        heuristic_proposal = proposal.to_dict()
                        self._total_heuristic_hits += 1
                        logger.info(
                            f"🧠 H-MEM hit for {drift.drift_type}: "
                            f"similarity={proposal.similarity_score:.2%}, "
                            f"bypass={'YES' if proposal.can_bypass_round1 else 'NO'}"
                        )
                except Exception as e:
                    logger.warning(f"H-MEM query failed: {e}")

            # Step 4: Build PolicyViolation
            violation = PolicyViolation(
                drift_events=[drift],
                heuristic_available=heuristic_available,
                heuristic_proposal=heuristic_proposal,
                batch_size=1,
                window_duration_ms=window_duration_ms,
                total_raw_events=len(batch),
                filtered_count=filtered_count,
                confidence=drift.confidence,
            )
            violations.append(violation)

        self._total_violations_emitted += len(violations)
        logger.info(
            f"🛡️ Emitting {len(violations)} PolicyViolation signals "
            f"(from {len(batch)} raw events)"
        )

        return violations

    # ─── Violation Handlers ───────────────────────────────────────────────────

    def on_violation(self, handler: Callable) -> None:
        """Register a handler for PolicyViolation signals."""
        self._violation_handlers.append(handler)

    async def _emit_violation(self, violation: PolicyViolation) -> None:
        """Emit a PolicyViolation to all registered handlers."""
        for handler in self._violation_handlers:
            try:
                result = handler(violation)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Violation handler error: {e}")

    # ─── Redis Subscription ───────────────────────────────────────────────────

    async def start(self, redis_url: str = "redis://localhost:6379") -> None:
        """
        Start the Sentry Node — subscribe to Redis and begin processing.

        Falls back to manual ingestion if Redis is not available.
        """
        self._running = True
        logger.info(
            f"🛡️ SentryNode started "
            f"(window={self._window_seconds}s, "
            f"ollama={'ON' if self._use_ollama else 'OFF'})"
        )

        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await client.ping()

            pubsub = client.pubsub()
            await pubsub.subscribe(self._redis_channel)

            logger.info(
                f"🛡️ Subscribed to Redis channel: {self._redis_channel}"
            )

            async for message in pubsub.listen():
                if not self._running:
                    break
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        await self.ingest_event(event)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in Redis event")

            await pubsub.unsubscribe(self._redis_channel)
            await client.close()

        except ImportError:
            logger.info(
                "🛡️ Redis not available — SentryNode in manual mode. "
                "Use ingest_event() to feed events."
            )
        except Exception as e:
            logger.warning(
                f"🛡️ Redis connection failed ({e}) — "
                f"SentryNode in manual mode."
            )

    async def stop(self) -> None:
        """Stop the Sentry Node."""
        self._running = False
        if self._window_timer and not self._window_timer.done():
            self._window_timer.cancel()
        # Flush remaining buffer
        await self._flush_window()
        logger.info("🛡️ SentryNode stopped")

    # ─── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get Sentry Node statistics."""
        return {
            "running": self._running,
            "window_seconds": self._window_seconds,
            "use_ollama": self._use_ollama,
            "buffer_size": len(self._buffer),
            "total_events_received": self._total_events_received,
            "total_events_filtered": self._total_events_filtered,
            "total_violations_emitted": self._total_violations_emitted,
            "total_windows_processed": self._total_windows_processed,
            "total_heuristic_hits": self._total_heuristic_hits,
            "filter_rate": (
                round(
                    self._total_events_filtered
                    / max(self._total_events_received, 1)
                    * 100,
                    1,
                )
            ),
        }
