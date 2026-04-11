"""
AMBER SEQUENCE GENERATOR
=========================
Phase 4 — Proactive Simulation Engine

Generates the 20-tick "Amber Sequence" used by --mode proactive in inject_drift.py.

Tick Layout
-----------
Ticks 1-5  : LOW-signal breadcrumbs (IAM:GetPolicy, Lambda:ListFunctions, ...)
Ticks 6-10 : MEDIUM-signal breadcrumbs (VPC:DescribeFlowLogs, STS:GetCallerIdentity, ...)
Ticks 11-15: HIGH-signal recon (assume-role chains, DescribeRoles ×3, CreateRole, ...)
Tick  16   : OIDC_TRUST_BREACH trigger (the actual breach event)
Ticks 17-20: Post-breach noise (lateral movement attempts, data access probes)

Academic Reference
------------------
- Kill Chain: Hutchins et al. (2011) — Intelligence-Driven Computer Network Defense
- Cyber Recon: MITRE ATT&CK® T1526 (Cloud Service Discovery),
  T1078.004 (Valid Accounts: Cloud Accounts)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

# ── Breadcrumb event templates ────────────────────────────────────────────────
# Each entry:  (event_name, drift_type, severity, api_volume, cpu_delta, gpu_util)

_LOW_BREADCRUMBS: list[tuple[str, str, str, float, float, float]] = [
    ("IAM:GetPolicy",          "iam_policy_change",    "LOW",    12.0,  2.1, 0.0),
    ("IAM:ListPolicies",       "iam_policy_change",    "LOW",    18.0,  3.0, 0.0),
    ("Lambda:ListFunctions",   "resource_created",     "LOW",     8.0,  1.5, 0.0),
    ("EC2:DescribeInstances",  "resource_created",     "LOW",    22.0,  2.8, 0.0),
    ("S3:ListBuckets",         "public_exposure",      "LOW",     6.0,  1.2, 0.0),
]

_MEDIUM_BREADCRUMBS: list[tuple[str, str, str, float, float, float]] = [
    ("VPC:DescribeFlowLogs",         "network_rule_change",  "MEDIUM",  35.0,  8.0, 0.0),
    ("STS:GetCallerIdentity",        "iam_policy_change",    "MEDIUM",  28.0,  5.5, 0.0),
    ("CloudTrail:LookupEvents",      "iam_policy_change",    "MEDIUM",  41.0, 12.0, 0.0),
    ("EC2:DescribeSecurityGroups",   "network_rule_change",  "MEDIUM",  19.0,  4.0, 0.0),
    ("IAM:GetAccountAuthorizationDetails", "iam_policy_change", "MEDIUM", 55.0, 14.0, 0.0),
]

_HIGH_RECON: list[tuple[str, str, str, float, float, float]] = [
    ("IAM:DescribeRoles",          "DescribeRoles",      "HIGH",  72.0, 25.0, 0.0),
    ("IAM:DescribeRoles",          "DescribeRoles",      "HIGH",  88.0, 31.0, 0.0),
    ("IAM:DescribeRoles",          "DescribeRoles",      "HIGH", 104.0, 38.0, 0.0),
    ("STS:AssumeRole",             "AssumeRole",         "HIGH",  60.0, 42.0, 0.0),
    ("IAM:CreateRole",             "CreateRole",         "HIGH",  45.0, 30.0, 0.0),
]

_BREACH_EVENT: tuple[str, str, str, float, float, float] = (
    "OIDC_TRUST_BREACH",
    "oidc_trust_breach",
    "CRITICAL",
    200.0,
    65.0,
    0.0,
)

_POST_BREACH: list[tuple[str, str, str, float, float, float]] = [
    ("IAM:AttachRolePolicy",   "permission_escalation", "CRITICAL", 180.0, 55.0, 0.0),
    ("STS:AssumeRole",         "lateral_movement",      "CRITICAL", 160.0, 48.0, 0.0),
    ("S3:GetObject",           "data_exfiltration",     "CRITICAL", 350.0, 30.0, 0.0),
    ("S3:GetObject",           "data_exfiltration",     "CRITICAL", 412.0, 28.0, 0.0),
]


def _make_event(
    tick: int,
    resource_id: str,
    event_name: str,
    drift_type: str,
    severity: str,
    api_volume: float,
    cpu_delta: float,
    gpu_utilization: float,
    phase: str,
    mutations: dict[str, Any] | None = None,
    tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a single simulated telemetry event dict compatible with the truth_log schema."""
    return {
        "event_id":       f"amr-{uuid.uuid4().hex[:8]}",
        "event_type":     drift_type,
        "timestamp_tick": tick,
        "timestamp_utc":  datetime.now(timezone.utc).isoformat(),
        "amber_phase":    phase,           # breadcrumb | breach | post_breach
        "data": {
            "resource_id":      resource_id,
            "drift_type":       drift_type,
            "event_name":       event_name,
            "severity":         severity,
            "api_volume":       api_volume,
            "cpu_delta":        cpu_delta,
            "gpu_utilization":  gpu_utilization,
            "network_bytes_out": cpu_delta * 1024 * 40,  # proportional estimate
            "mutations":        mutations or {},
            "tags":             tags or {},
            "sequence_hint":    f"Tick {tick}/20 — {phase}",
        },
    }


class AmberSequenceGenerator:
    """
    Generates the full 20-tick Amber Sequence for proactive reconnaissance
    simulation. Encodes ground-truth attack kill-chain ordering:

      Phase A (ticks 1-5):   LOW breadcrumbs  — silently fingerprinting env
      Phase B (ticks 6-10):  MEDIUM recon     — VPC/flow-log enumeration
      Phase C (ticks 11-15): HIGH recon chain — DescribeRoles³ + AssumeRole
      Phase D (tick 16):     BREACH           — OIDC_TRUST_BREACH trigger
      Phase E (ticks 17-20): POST-BREACH      — lateral move + data exfil

    The LSTM ThreatForecaster, trained on this sequence, should fire an
    Amber Alert (P ≥ 0.75) by tick 13-14 — *before* the breach materialises.

    Usage
    -----
    gen = AmberSequenceGenerator(resource_id="arn:aws:iam::123:role/prod-deploy")
    ticks = gen.generate()          # list[dict] — 20 events
    for evt in ticks:
        print(evt["amber_phase"], evt["timestamp_tick"])
    """

    # Tick numbers (1-indexed)
    BREACH_TICK = 16
    TOTAL_TICKS = 20

    def __init__(
        self,
        resource_id: str = "arn:aws:iam::123456789012:role/prod-cicd-deploy",
        tags: dict[str, str] | None = None,
    ) -> None:
        self._resource_id = resource_id
        self._tags = tags or {"Environment": "PROD", "data_class": "PII"}

    def generate(self) -> list[dict[str, Any]]:
        """
        Produce the ordered 20-tick sequence.

        Returns
        -------
        list[dict]
            Ordered list of raw event dicts ready for Redis publish or
            direct ingestion into ThreatForecaster.ingest_event().
        """
        ticks: list[dict[str, Any]] = []

        # ── Ticks 1-5: LOW breadcrumbs ────────────────────────────────────────
        for i, (ev, dt, sev, api, cpu, gpu) in enumerate(_LOW_BREADCRUMBS, start=1):
            ticks.append(_make_event(
                tick=i,
                resource_id=self._resource_id,
                event_name=ev, drift_type=dt, severity=sev,
                api_volume=api, cpu_delta=cpu, gpu_utilization=gpu,
                phase="breadcrumb_low",
                tags=self._tags,
            ))

        # ── Ticks 6-10: MEDIUM breadcrumbs ────────────────────────────────────
        for i, (ev, dt, sev, api, cpu, gpu) in enumerate(_MEDIUM_BREADCRUMBS, start=6):
            ticks.append(_make_event(
                tick=i,
                resource_id=self._resource_id,
                event_name=ev, drift_type=dt, severity=sev,
                api_volume=api, cpu_delta=cpu, gpu_utilization=gpu,
                phase="breadcrumb_medium",
                tags=self._tags,
            ))

        # ── Ticks 11-15: HIGH recon ────────────────────────────────────────────
        for i, (ev, dt, sev, api, cpu, gpu) in enumerate(_HIGH_RECON, start=11):
            mutations: dict[str, Any] = {}
            if ev == "IAM:DescribeRoles":
                mutations = {"roles_enumerated": True, "target_privilege_level": "ADMIN"}
            elif ev == "STS:AssumeRole":
                mutations = {"new_account_id": "987654321098", "cross_account": True}
            elif ev == "IAM:CreateRole":
                mutations = {
                    "trust_policy": "Added: token.actions.githubusercontent.com:aud",
                    "condition": "StringLike: repo:rogue-actor/*:*",
                }
            ticks.append(_make_event(
                tick=i,
                resource_id=self._resource_id,
                event_name=ev, drift_type=dt, severity=sev,
                api_volume=api, cpu_delta=cpu, gpu_utilization=gpu,
                phase="breadcrumb_high",
                mutations=mutations,
                tags=self._tags,
            ))

        # ── Tick 16: OIDC TRUST BREACH ────────────────────────────────────────
        ev, dt, sev, api, cpu, gpu = _BREACH_EVENT
        ticks.append(_make_event(
            tick=self.BREACH_TICK,
            resource_id=self._resource_id,
            event_name=ev, drift_type=dt, severity=sev,
            api_volume=api, cpu_delta=cpu, gpu_utilization=gpu,
            phase="breach",
            mutations={
                "trust_policy": "Added: token.actions.githubusercontent.com:aud",
                "condition":    "StringLike: repo:rogue-actor/*:*",
                "risk_profile": "Lateral Movement Opportunity",
            },
            tags=self._tags,
        ))

        # ── Ticks 17-20: Post-breach ───────────────────────────────────────────
        for i, (ev, dt, sev, api, cpu, gpu) in enumerate(_POST_BREACH, start=17):
            ticks.append(_make_event(
                tick=i,
                resource_id=self._resource_id,
                event_name=ev, drift_type=dt, severity=sev,
                api_volume=api, cpu_delta=cpu, gpu_utilization=gpu,
                phase="post_breach",
                mutations={"exfil_attempt": True} if "GetObject" in ev else {},
                tags=self._tags,
            ))

        assert len(ticks) == self.TOTAL_TICKS, (
            f"Expected {self.TOTAL_TICKS} ticks, got {len(ticks)}"
        )
        return ticks

    def generate_training_corpus(
        self,
        num_sequences: int = 50,
    ) -> list[tuple[list[dict[str, Any]], str]]:
        """
        Generate multiple labeled sequences for LSTM training.

        Returns
        -------
        list[(events, label)]
            Where label is the drift_type string of the breach event.
        """
        import random
        rng = random.Random(42)
        corpus: list[tuple[list[dict[str, Any]], str]] = []

        for _ in range(num_sequences):
            # Vary the resource ID to simulate different targets
            rid = (
                f"arn:aws:iam::{rng.randint(100000000000, 999999999999)}"
                f":role/{rng.choice(['prod-cicd', 'staging-deploy', 'data-pipeline'])}"
            )
            gen = AmberSequenceGenerator(resource_id=rid)
            seq = gen.generate()
            # Label = the drift type of the breach tick
            label = seq[self.BREACH_TICK - 1]["data"]["drift_type"]
            corpus.append((seq, label))

        return corpus
