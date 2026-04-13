"""
PHASE 7 ASYNC TASKS — SENTRY/CONSULTANT REASONING
==================================================

Celery task endpoints for non-blocking swarm inference execution.
"""

from __future__ import annotations

import logging
import random
import time
from functools import wraps
from typing import Any, Callable

from cloudguard.agents.swarm import create_swarm_personas
from cloudguard.core.schemas import AgentProposal, EnvironmentWeights
from cloudguard.core.swarm import SwarmState

logger = logging.getLogger("cloudguard.scheduler.tasks")


def _is_rate_limit_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    if "ratelimit" in name or "rate limit" in message:
        return True
    if "429" in message:
        return True
    if "resourceexhausted" in name:
        return True
    return False


def retry_on_rate_limit(max_attempts: int = 4, base_delay: float = 2.0) -> Callable:
    """Decorator implementing exponential backoff for 429/rate limit failures."""

    def _decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def _wrapped(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    attempt += 1
                    if not _is_rate_limit_error(exc) or attempt >= max_attempts:
                        raise

                    delay = base_delay * (2 ** (attempt - 1))
                    # Add a tiny jitter to avoid synchronized worker retries.
                    delay += random.uniform(0.0, 0.25)
                    logger.warning(
                        "[SchedulerTasks] Rate limit detected (attempt %s/%s). Retrying in %.2fs",
                        attempt,
                        max_attempts,
                        delay,
                    )
                    time.sleep(delay)

        return _wrapped

    return _decorator


def _build_swarm_state(payload: dict[str, Any]) -> SwarmState:
    weights = payload.get("weights") or {"w_risk": 0.6, "w_cost": 0.4}
    return SwarmState(
        current_j_score=payload.get("current_j_score", 0.5),
        weights=EnvironmentWeights(
            w_risk=weights.get("w_risk", 0.6),
            w_cost=weights.get("w_cost", 0.4),
        ),
        drift_event_id=payload.get("drift_event_id", ""),
    )


def _proposal_to_dict(proposal: AgentProposal) -> dict[str, Any]:
    return proposal.model_dump(mode="json")


@retry_on_rate_limit(max_attempts=4, base_delay=2.0)
def _run_sentry_reasoning(
    sentry_context: dict[str, Any],
    resource_context: dict[str, Any],
    swarm_state_payload: dict[str, Any],
) -> dict[str, Any]:
    sentry, _, kernel_memory = create_swarm_personas()
    if sentry_context:
        kernel_memory.drift_summary = sentry_context.get("drift_summary", "")
        kernel_memory.severity_assessment = sentry_context.get("severity_assessment", "")
        kernel_memory.compliance_gaps = list(sentry_context.get("compliance_gaps", []))
        kernel_memory.resource_context = resource_context
        sentry.set_kernel_memory(kernel_memory)

    proposal = sentry.propose(_build_swarm_state(swarm_state_payload), resource_context)
    return {"proposal": _proposal_to_dict(proposal), "agent": "sentry"}


@retry_on_rate_limit(max_attempts=4, base_delay=2.0)
def _run_consultant_reasoning(
    consultant_context: dict[str, Any],
    resource_context: dict[str, Any],
    swarm_state_payload: dict[str, Any],
) -> dict[str, Any]:
    _, consultant, kernel_memory = create_swarm_personas()
    if consultant_context:
        kernel_memory.drift_summary = consultant_context.get("drift_summary", "")
        kernel_memory.severity_assessment = consultant_context.get("max_severity", "")
        kernel_memory.resource_context = resource_context
        consultant.set_kernel_memory(kernel_memory)

    proposal = consultant.propose(_build_swarm_state(swarm_state_payload), resource_context)
    return {"proposal": _proposal_to_dict(proposal), "agent": "consultant"}


@retry_on_rate_limit(max_attempts=4, base_delay=2.0)
def _run_batch_reasoning(
    signals: list[dict[str, Any]],
    resource_context: dict[str, Any],
    swarm_state_payload: dict[str, Any],
) -> dict[str, Any]:
    # Batch job is represented as a single consultant-style summary proposal.
    _, consultant, kernel_memory = create_swarm_personas()
    kernel_memory.drift_summary = (
        f"Cluster batch with {len(signals)} concurrent stochastic signals"
    )
    kernel_memory.resource_context = resource_context
    consultant.set_kernel_memory(kernel_memory)

    state = _build_swarm_state(swarm_state_payload)
    proposal = consultant.propose(state, resource_context)
    payload = _proposal_to_dict(proposal)
    payload["reasoning"] = (
        f"Batch-clustered reasoning across {len(signals)} signals. "
        f"{payload.get('reasoning', '')}"
    )
    return {
        "proposal": payload,
        "agent": "batch_consultant",
        "clustered": True,
        "cluster_size": len(signals),
    }


try:
    from cloudguard.core.scheduler import InferenceScheduler

    _scheduler = InferenceScheduler()
    _celery_app = _scheduler.app
except Exception:
    _scheduler = None
    _celery_app = None


if _celery_app:
    @_celery_app.task(name="cloudguard.core.tasks.sentry_reasoning_task")
    def sentry_reasoning_task(
        sentry_context: dict[str, Any],
        resource_context: dict[str, Any],
        swarm_state: dict[str, Any],
    ) -> dict[str, Any]:
        return _run_sentry_reasoning(sentry_context, resource_context, swarm_state)


    @_celery_app.task(name="cloudguard.core.tasks.consultant_reasoning_task")
    def consultant_reasoning_task(
        consultant_context: dict[str, Any],
        resource_context: dict[str, Any],
        swarm_state: dict[str, Any],
    ) -> dict[str, Any]:
        return _run_consultant_reasoning(consultant_context, resource_context, swarm_state)


    @_celery_app.task(name="cloudguard.core.tasks.batch_reasoning_task")
    def batch_reasoning_task(
        signals: list[dict[str, Any]],
        resource_context: dict[str, Any],
        swarm_state: dict[str, Any],
    ) -> dict[str, Any]:
        return _run_batch_reasoning(signals, resource_context, swarm_state)
