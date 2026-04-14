"""
PHASE 7 INFERENCE SCHEDULER — CELERY/REDIS ASYNC SCALING
=========================================================

High-throughput scheduler for decoupling Swarm reasoning from the simulator's
telemetry stream.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from cloudguard.api.narrative_engine import PREDICTIVE_FAST_PASS_THRESHOLD

logger = logging.getLogger("cloudguard.scheduler")

try:
    from celery import Celery

    HAS_CELERY = True
except ImportError:
    Celery = None  # type: ignore[assignment]
    HAS_CELERY = False


PRIORITY_CRITICAL = "P1_CRITICAL"
PRIORITY_STOCHASTIC = "P2_STOCHASTIC"
PRIORITY_OPTIMIZATION = "P3_OPTIMIZATION"


@dataclass
class ScheduledInference:
    sentry_task_id: Optional[str]
    consultant_task_id: Optional[str]
    priority: str
    queue: str
    gate_seconds: int
    batched: bool = False
    batch_size: int = 1


class InferenceScheduler:
    """Celery-backed inference scheduler for Sentry/Consultant task dispatch."""

    def __init__(
        self,
        broker_url: Optional[str] = None,
        result_backend: Optional[str] = None,
        non_blocking: bool = True,
        app_name: str = "cloudguard_scheduler",
    ) -> None:
        self._broker_url = broker_url or os.getenv("CLOUDGUARD_CELERY_BROKER_URL", "redis://localhost:6379/0")
        self._result_backend = result_backend or os.getenv("CLOUDGUARD_CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
        self.non_blocking = non_blocking
        self.enabled = HAS_CELERY

        self._app = None
        if not self.enabled:
            logger.warning("[Scheduler] Celery is not installed; scheduler disabled")
            return

        self._app = Celery(app_name, broker=self._broker_url, backend=self._result_backend)
        self._app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            task_default_exchange="cloudguard",
            task_default_routing_key="cloudguard.optimization",
            task_acks_late=True,
            worker_prefetch_multiplier=1,
            task_default_retry_delay=2,
            task_routes={
                "cloudguard.core.tasks.sentry_reasoning_task": {"queue": "cloudguard.critical"},
                "cloudguard.core.tasks.consultant_reasoning_task": {"queue": "cloudguard.optimization"},
                "cloudguard.core.tasks.batch_reasoning_task": {"queue": "cloudguard.stochastic"},
            },
            task_queues={
                "cloudguard.critical": {"routing_key": "cloudguard.critical"},
                "cloudguard.stochastic": {"routing_key": "cloudguard.stochastic"},
                "cloudguard.optimization": {"routing_key": "cloudguard.optimization"},
            },
        )

        logger.info(
            "[Scheduler] Initialized (broker=%s, backend=%s, non_blocking=%s)",
            self._broker_url,
            self._result_backend,
            self.non_blocking,
        )

    @property
    def app(self):
        return self._app

    def classify_priority(
        self,
        *,
        j_impact: float,
        probability: float,
        severity: str,
    ) -> tuple[str, str]:
        """
        Risk-weighted queue tiering.

        P1: CRITICAL if J-impact > 0.5 or critical severity.
        P2: STOCHASTIC if Amber probability in [0.75, 0.90].
        P3: OPTIMIZATION for lower-priority drifts.
        """
        sev = (severity or "").upper()
        if j_impact > 0.5 or sev == "CRITICAL":
            return PRIORITY_CRITICAL, "cloudguard.critical"

        if 0.75 <= probability < 0.90:
            return PRIORITY_STOCHASTIC, "cloudguard.stochastic"

        return PRIORITY_OPTIMIZATION, "cloudguard.optimization"

    @staticmethod
    def sovereign_gate_window_seconds(probability: float) -> int:
        """UI handshake: preserve 10s/60s gate semantics while queued."""
        if probability >= PREDICTIVE_FAST_PASS_THRESHOLD:
            return 10
        return 60

    def dispatch_reasoning(
        self,
        *,
        sentry_context: dict[str, Any],
        consultant_context: dict[str, Any],
        resource_context: dict[str, Any],
        swarm_state: dict[str, Any],
        j_impact: float,
        probability: float,
        severity: str,
        cluster_signals: Optional[list[dict[str, Any]]] = None,
    ) -> ScheduledInference:
        """Dispatch Sentry + Consultant reasoning as async tasks."""
        priority, queue = self.classify_priority(
            j_impact=j_impact,
            probability=probability,
            severity=severity,
        )
        gate_seconds = self.sovereign_gate_window_seconds(probability)

        if not self.enabled or self._app is None:
            return ScheduledInference(
                sentry_task_id=None,
                consultant_task_id=None,
                priority=priority,
                queue=queue,
                gate_seconds=gate_seconds,
            )

        # Cluster Effect integration: collapse concurrent shadow signals into one job.
        if cluster_signals and len(cluster_signals) >= 2:
            async_result = self._app.send_task(
                "cloudguard.core.tasks.batch_reasoning_task",
                kwargs={
                    "signals": cluster_signals,
                    "resource_context": resource_context,
                    "swarm_state": swarm_state,
                },
                queue="cloudguard.stochastic",
                routing_key="cloudguard.stochastic",
                priority=8,
            )
            return ScheduledInference(
                sentry_task_id=async_result.id,
                consultant_task_id=None,
                priority=PRIORITY_STOCHASTIC,
                queue="cloudguard.stochastic",
                gate_seconds=gate_seconds,
                batched=True,
                batch_size=len(cluster_signals),
            )

        sentry_result = self._app.send_task(
            "cloudguard.core.tasks.sentry_reasoning_task",
            kwargs={
                "sentry_context": sentry_context,
                "resource_context": resource_context,
                "swarm_state": swarm_state,
            },
            queue=queue,
            routing_key=queue,
            priority=9 if priority == PRIORITY_CRITICAL else 5,
        )

        consultant_result = self._app.send_task(
            "cloudguard.core.tasks.consultant_reasoning_task",
            kwargs={
                "consultant_context": consultant_context,
                "resource_context": resource_context,
                "swarm_state": swarm_state,
            },
            queue=queue,
            routing_key=queue,
            priority=8 if priority == PRIORITY_CRITICAL else 4,
        )

        return ScheduledInference(
            sentry_task_id=sentry_result.id,
            consultant_task_id=consultant_result.id,
            priority=priority,
            queue=queue,
            gate_seconds=gate_seconds,
        )

    def collect_task(self, task_id: str, timeout_s: float = 20.0) -> dict[str, Any]:
        """Collect a Celery task result from backend."""
        if not self.enabled or self._app is None:
            raise RuntimeError("Scheduler is disabled")
        result = self._app.AsyncResult(task_id)
        payload = result.get(timeout=timeout_s)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected task result payload type: {type(payload)!r}")
        return payload

celery = InferenceScheduler().app

