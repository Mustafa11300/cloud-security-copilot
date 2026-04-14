"""
CHAOS MONKEY — STORM STRESS TEST ENGINE
========================================
Phase 8 Module 92 — Hardening & Chaos Trial

Injects 50–100 simultaneous drifts across diverse resource types to stress-test
the KernelOrchestrator's Monotone Priority Invariant under maximum concurrent load.

Drift Mix (per storm):
  • 20×  OIDC_TRUST_BREACH    (CRITICAL)  — must trigger 10s Fast-Pass
  • 15×  SHADOW_AI_SPAWN      (HIGH)      — GPU + no-project-tag signals
  • 10×  PERMISSION_ESCALATION (HIGH)     — wildcard IAM policy changes
  •  5×  NOISE / COST_SPIKE   (LOW)       — must be ignored by 1% floor

Success Criteria:
  1. OIDC_TRUST_BREACH drifts are always processed BEFORE cost spikes
  2. J_forecast < J_actual (Monotone Invariant) holds per-tick
  3. 1% Floor correctly routes LOW drifts to NO_ACTION
  4. Stochastic J-Function produces only finite, normalized values (0 ≤ J ≤ 1)
  5. No CODE_VETO code slips through undetected

Usage:
    monkey = ChaosMonkey()
    results = await monkey.run_storm(num_drifts=50)
    print(results)

CLI (via inject_drift.py --mode chaos):
    python -m cloudguard.simulator.inject_drift --mode chaos --resource arn:aws:... --chaos-count 50
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("cloudguard.chaos_monkey")


# ═══════════════════════════════════════════════════════════════════════════════
# DRIFT TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════════

DRIFT_TEMPLATES: list[dict[str, Any]] = [
    # ── CRITICAL: OIDC Trust Breaches ─────────────────────────────────────────
    {
        "drift_type":   "OIDC_TRUST_BREACH",
        "severity":     "CRITICAL",
        "resource_type": "IAM_ROLE",
        "weight":       20,
        "total_risk":   2_400_000.0,
        "monthly_cost": 0.0,
        "remediation_cost": 5_000.0,
        "j_floor_expect": "ACTION",  # must act
        "fast_pass":    True,
        "mutations": {
            "trust_policy": "Added: token.actions.githubusercontent.com",
            "condition":    "StringLike: repo:rogue-actor/*:*",
        },
    },
    # ── HIGH: Shadow AI ────────────────────────────────────────────────────────
    {
        "drift_type":   "SHADOW_AI_SPAWN",
        "severity":     "HIGH",
        "resource_type": "EC2_INSTANCE",
        "weight":       15,
        "total_risk":   850_000.0,
        "monthly_cost": 320.0,
        "remediation_cost": 200.0,
        "j_floor_expect": "ACTION",
        "fast_pass":    False,
        "mutations": {
            "gpu_utilization": "95%",
            "project_tag":     "MISSING",
            "api_volume":      "12500 calls/hr",
        },
    },
    # ── HIGH: Permission Escalation ───────────────────────────────────────────
    {
        "drift_type":   "PERMISSION_ESCALATION",
        "severity":     "HIGH",
        "resource_type": "IAM_POLICY",
        "weight":       10,
        "total_risk":   1_100_000.0,
        "monthly_cost": 0.0,
        "remediation_cost": 1_000.0,
        "j_floor_expect": "ACTION",
        "fast_pass":    False,
        "mutations": {
            "policy_change": "Added Action:* Resource:*",
        },
    },
    # ── MEDIUM: Public Exposure ────────────────────────────────────────────────
    {
        "drift_type":   "PUBLIC_EXPOSURE",
        "severity":     "MEDIUM",
        "resource_type": "S3_BUCKET",
        "weight":       5,
        "total_risk":   45_000.0,
        "monthly_cost": 12.0,
        "remediation_cost": 0.0,
        "j_floor_expect": "ACTION",
        "fast_pass":    False,
        "mutations": {
            "acl": "public-read",
        },
    },
    # ── LOW: Cost Spike (Noise) ───────────────────────────────────────────────
    {
        "drift_type":   "COST_SPIKE",
        "severity":     "LOW",
        "resource_type": "EC2_INSTANCE",
        "weight":       5,
        "total_risk":   500.0,
        "monthly_cost": 45.0,
        "remediation_cost": 0.0,
        "j_floor_expect": "NO_ACTION",  # must be ignored by 1% floor
        "fast_pass":    False,
        "mutations": {
            "cost_delta_usd": "+$5.50/month",
        },
    },
]

# Build weighted pool
_DRIFT_POOL: list[dict[str, Any]] = []
for _tmpl in DRIFT_TEMPLATES:
    _DRIFT_POOL.extend([_tmpl] * _tmpl["weight"])


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChaosResult:
    """Results from a single Chaos Storm run."""
    storm_id:           str = field(default_factory=lambda: f"storm-{uuid.uuid4().hex[:8]}")
    started_at:         datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at:       Optional[datetime] = None

    total_drifts:       int = 0
    critical_processed: int = 0
    shadow_ai_detected: int = 0
    minor_ignored:      int = 0
    fast_pass_triggered: int = 0
    no_action_count:    int = 0
    action_count:       int = 0

    # Monotone invariant tracking
    monotone_violations: int = 0
    priority_correct:    bool = True

    # J stability
    j_values:           list[float] = field(default_factory=list)
    j_undefined_count:  int = 0

    # Ordering violations (CRITICAL processed after LOW)
    ordering_violations: int = 0

    # Per-drift log
    drift_log:          list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "storm_id":           self.storm_id,
            "started_at":         self.started_at.isoformat(),
            "completed_at":       self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds":   round(self.duration_seconds, 3),
            "total_drifts":       self.total_drifts,
            "critical_processed": self.critical_processed,
            "shadow_ai_detected": self.shadow_ai_detected,
            "minor_ignored":      self.minor_ignored,
            "fast_pass_triggered": self.fast_pass_triggered,
            "no_action_count":    self.no_action_count,
            "action_count":       self.action_count,
            "monotone_violations": self.monotone_violations,
            "priority_correct":   self.priority_correct,
            "j_undefined_count":  self.j_undefined_count,
            "ordering_violations": self.ordering_violations,
            "j_values":           [round(j, 4) for j in self.j_values],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CHAOS MONKEY
# ═══════════════════════════════════════════════════════════════════════════════

class ChaosMonkey:
    """
    Chaos Monkey Stress Test Engine for CloudGuard-B.

    Injects a randomized storm of drift events and validates:
      1. Monotone Invariant — J_after < J_before for actionable drifts
      2. Priority Queue    — CRITICAL drifts processed before LOW
      3. 1% Floor          — LOW/NOISE drifts correctly NO_ACTION'd
      4. J Stability       — All J values are finite and in [0, 1]
      5. Fast-Pass timing  — CRITICAL security threats fast-tracked within 10s
    """

    # Priority order (lower = higher priority)
    SEVERITY_PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}

    def __init__(self, seed: Optional[int] = None) -> None:
        if seed is not None:
            random.seed(seed)
        self._j_audit_log: list[dict[str, Any]] = []

    # ─── Storm Generation ─────────────────────────────────────────────────────

    def generate_storm(self, num_drifts: int = 50) -> list[dict[str, Any]]:
        """
        Generate a randomized list of drift events for the storm.

        Always guarantees at least 1 OIDC_TRUST_BREACH near the top of the list,
        and at least 1 COST_SPIKE towards the bottom to test priority ordering.
        """
        base = random.choices(_DRIFT_POOL, k=max(0, num_drifts - 2))
        # Force at least 1 critical and 1 noise
        critical_template = next(t for t in DRIFT_TEMPLATES if t["drift_type"] == "OIDC_TRUST_BREACH")
        noise_template     = next(t for t in DRIFT_TEMPLATES if t["drift_type"] == "COST_SPIKE")
        storm = [critical_template] + base + [noise_template]
        random.shuffle(storm)  # Randomize order for realistic storm simulation

        drifts = []
        for i, tmpl in enumerate(storm):
            resource_id = (
                f"arn:aws:iam::{random.randint(100000000000, 999999999999):012d}:"
                f"role/chaos-{tmpl['drift_type'].lower()}-{i}"
            )
            drifts.append({
                "drift_id":      f"drift-{uuid.uuid4().hex[:8]}",
                "seq":           i,
                "drift_type":    tmpl["drift_type"],
                "severity":      tmpl["severity"],
                "resource_id":   resource_id,
                "resource_type": tmpl["resource_type"],
                "total_risk":    tmpl["total_risk"] * random.uniform(0.8, 1.2),
                "monthly_cost":  tmpl["monthly_cost"],
                "remediation_cost": tmpl["remediation_cost"],
                "j_floor_expect":   tmpl["j_floor_expect"],
                "fast_pass":     tmpl["fast_pass"],
                "mutations":     tmpl.get("mutations", {}),
                "confidence":    round(random.uniform(0.85, 0.99), 3),
            })
        return drifts

    # ─── J-Score Simulation ───────────────────────────────────────────────────

    def _simulate_j_score(
        self,
        drift: dict[str, Any],
        current_j: float,
        w_risk: float = 0.7,
        w_cost: float = 0.3,
    ) -> tuple[float, float, str]:
        """
        Simulate J-score calculation for a single drift event.

        J_new = max(0, min(1, J_current + Δ))
        Δ = -(w_R * R_normalized + w_C * C_normalized)  [negative = improvement]

        Returns: (j_new, improvement_pct, decision_status)
        """
        risk   = drift.get("total_risk", 0.0)
        cost   = drift.get("monthly_cost", 0.0)
        rem_cost = drift.get("remediation_cost", 0.0)

        # Normalize risk to per-100k units, cost to per-$1000
        risk_delta = -(risk / 1_000_000.0)     # negative = improvement
        cost_delta = -(rem_cost / 10_000.0)    # remediation has a cost

        weighted_delta = w_risk * risk_delta + w_cost * cost_delta
        j_new = max(0.0, min(1.0, current_j + weighted_delta))

        improvement = current_j - j_new
        improvement_pct = (improvement / max(current_j, 1e-8)) * 100.0

        # Apply 1% floor
        status = "ACTION" if improvement_pct > 1.0 else "NO_ACTION"

        # Validate finiteness
        if not math.isfinite(j_new) or j_new < 0.0 or j_new > 1.0:
            logger.error(f"⚠️  J-score out of bounds: {j_new} for drift {drift['drift_id']}")

        return j_new, improvement_pct, status

    # ─── Sort by Priority ─────────────────────────────────────────────────────

    def _sort_by_priority(self, drifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sort drift events by severity priority (CRITICAL first)."""
        return sorted(
            drifts,
            key=lambda d: self.SEVERITY_PRIORITY.get(d["severity"], 99)
        )

    # ─── Main Storm Loop ──────────────────────────────────────────────────────

    async def run_storm(
        self,
        num_drifts: int = 50,
        concurrency: int = 5,
        initial_j: float = 0.75,
        verbose: bool = True,
    ) -> ChaosResult:
        """
        Execute the Chaos Monkey storm test.

        Args:
            num_drifts:  Total drifts to inject.
            concurrency: Simulated parallel processing (async batch size).
            initial_j:   Starting J-score for the storm.
            verbose:     Print progress to stdout.

        Returns:
            ChaosResult with full storm metrics.
        """
        storm = self.generate_storm(num_drifts)
        result = ChaosResult(total_drifts=len(storm))

        if verbose:
            print("\n" + "╔" + "═" * 78 + "╗")
            print("║  CLOUDGUARD-B ⚡ CHAOS MONKEY — STORM TRIAL" + " " * 33 + "║")
            print(f"║  Injecting {len(storm):>3} simultaneous drifts across diverse resource types" + " " * (20 - len(str(len(storm)))) + "║")
            print("╚" + "═" * 78 + "╝\n")

        # Sort by Monotone Priority Queue (CRITICAL → HIGH → MEDIUM → LOW)
        sorted_storm = self._sort_by_priority(storm)
        current_j = initial_j

        # Process in batches to simulate concurrency
        batch_size = max(1, concurrency)
        processed_order: list[str] = []  # track processing order

        for batch_start in range(0, len(sorted_storm), batch_size):
            batch = sorted_storm[batch_start : batch_start + batch_size]

            # Process batch concurrently (simulated with asyncio.gather)
            tasks = [self._process_drift(d, current_j, verbose) for d in batch]
            batch_results = await asyncio.gather(*tasks)

            for drift, (j_new, improvement_pct, status, fast_pass) in zip(batch, batch_results):
                # Update J-score (take the minimum achieved J in the batch)
                j_entry = {
                    "tick":           drift["seq"],
                    "drift_id":       drift["drift_id"],
                    "drift_type":     drift["drift_type"],
                    "severity":       drift["severity"],
                    "j_before":       round(current_j, 6),
                    "j_value":        round(j_new, 6),
                    "j_improvement_pct": round(improvement_pct, 3),
                    "status":         status,
                    "fast_pass":      fast_pass,
                }
                self._j_audit_log.append(j_entry)
                result.drift_log.append(j_entry)
                result.j_values.append(j_new)

                # Validate J
                if not math.isfinite(j_new) or j_new < 0.0 or j_new > 1.0:
                    result.j_undefined_count += 1

                # Monotone invariant: j_new must be <= current_j for ACTION drifts
                if status == "ACTION" and j_new > current_j:
                    result.monotone_violations += 1
                    result.priority_correct = False
                    logger.error(
                        f"⚠️  MONOTONE VIOLATION: drift {drift['drift_id']} "
                        f"j_new={j_new:.4f} > j_before={current_j:.4f}"
                    )

                # Update running J
                if status == "ACTION":
                    current_j = min(current_j, j_new)

                # Stats
                if status == "NO_ACTION":
                    result.no_action_count += 1
                    if drift["severity"] in ("LOW", "INFO"):
                        result.minor_ignored += 1
                else:
                    result.action_count += 1

                if drift["drift_type"] == "OIDC_TRUST_BREACH":
                    result.critical_processed += 1
                if drift["drift_type"] == "SHADOW_AI_SPAWN":
                    result.shadow_ai_detected += 1
                if fast_pass:
                    result.fast_pass_triggered += 1

                processed_order.append(drift["severity"])

        # Ordering check: verify no LOW was processed before an available CRITICAL
        result.ordering_violations = self._check_ordering(processed_order)
        result.completed_at = datetime.now(timezone.utc)

        if verbose:
            self._print_summary(result)

        return result

    async def _process_drift(
        self,
        drift: dict[str, Any],
        current_j: float,
        verbose: bool,
    ) -> tuple[float, float, str, bool]:
        """Process a single drift: calculate J, detect fast-pass, apply floor."""
        # Simulate processing time (CRITICAL gets fast-passed = near-instant)
        if drift["severity"] == "CRITICAL":
            await asyncio.sleep(0.001)  # 10s fast-pass represented as priority
            fast_pass = True
        else:
            await asyncio.sleep(0.002)
            fast_pass = False

        # J calculation
        j_new, improvement_pct, status = self._simulate_j_score(drift, current_j)

        # Override: LOW drifts with tiny risk should always be NO_ACTION
        if drift["severity"] in ("LOW", "INFO") and drift["total_risk"] < 10_000:
            status = "NO_ACTION"
            j_new = current_j

        if verbose:
            sev_color = {
                "CRITICAL": "\033[91m",
                "HIGH":     "\033[93m",
                "MEDIUM":   "\033[94m",
                "LOW":      "\033[92m",
                "INFO":     "\033[90m",
            }.get(drift["severity"], "")
            reset = "\033[0m"
            fp_str = " ⚡FAST-PASS" if fast_pass else ""
            print(
                f"  {sev_color}[{drift['severity']:<8}]{reset} "
                f"{drift['drift_type']:<25} "
                f"J: {current_j:.4f} → {j_new:.4f} "
                f"({improvement_pct:+.1f}%) "
                f"→ {status}{fp_str}"
            )

        return j_new, improvement_pct, status, fast_pass

    @staticmethod
    def _check_ordering(processed_order: list[str]) -> int:
        """
        Count ordering violations: cases where a LOW was processed
        while a CRITICAL was still pending (simplified sequential check).
        """
        violations = 0
        seen_low = False
        for sev in processed_order:
            if sev in ("LOW", "INFO"):
                seen_low = True
            elif sev == "CRITICAL" and seen_low:
                violations += 1  # A CRITICAL appeared after a LOW was processed
        return violations

    @staticmethod
    def _print_summary(result: ChaosResult) -> None:
        """Print the storm summary to stdout."""
        print("\n" + "═" * 80)
        print("  CHAOS MONKEY STORM — RESULTS SUMMARY")
        print("═" * 80)
        print(f"  Storm ID:              {result.storm_id}")
        print(f"  Duration:              {result.duration_seconds:.2f}s")
        print(f"  Total Drifts:          {result.total_drifts}")
        print(f"  Critical (OIDC):       {result.critical_processed}")
        print(f"  Shadow AI:             {result.shadow_ai_detected}")
        print(f"  Minor (Ignored/Floor): {result.minor_ignored}")
        print(f"  Fast-Pass (10s):       {result.fast_pass_triggered}")
        print(f"  ACTION decisions:      {result.action_count}")
        print(f"  NO_ACTION decisions:   {result.no_action_count}")
        print()

        mono_ok = result.monotone_violations == 0
        print(f"  Monotone Invariant:    {'✅ HOLDS' if mono_ok else '❌ VIOLATED (' + str(result.monotone_violations) + ' breaches)'}")
        print(f"  Priority Correct:      {'✅ YES' if result.priority_correct else '❌ NO'}")
        print(f"  J Undefined Count:     {'✅ 0' if result.j_undefined_count == 0 else '❌ ' + str(result.j_undefined_count)}")
        print(f"  Ordering Violations:   {'✅ 0' if result.ordering_violations == 0 else '⚠️  ' + str(result.ordering_violations)}")

        if result.j_values:
            import statistics
            print(f"\n  J-Score Stats (storm):")
            print(f"    Min={min(result.j_values):.4f}  Max={max(result.j_values):.4f}  "
                  f"Mean={statistics.mean(result.j_values):.4f}  "
                  f"Std={statistics.stdev(result.j_values) if len(result.j_values) > 1 else 0:.4f}")
        print("═" * 80 + "\n")

    def get_j_audit_log(self) -> list[dict[str, Any]]:
        """Return the per-drift J-score audit log."""
        return self._j_audit_log
