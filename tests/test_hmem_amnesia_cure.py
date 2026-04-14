#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  H-MEM "AMNESIA CURE" VERIFICATION — SEMANTIC STRIPPER STRESS TEST          ║
║  ═══════════════════════════════════════════════════════════════════════════  ║
║                                                                              ║
║  Test Scenario: Verify the Semantic Stripper (Sanitization Pipeline)         ║
║  transforms volatile infrastructure noise into stable "Security DNA"        ║
║  that produces >0.90 cosine similarity for identical threat patterns.       ║
║                                                                              ║
║  Test Workflow:                                                              ║
║   Step 1: "Victory" Anchor — Store S3_PUBLIC_ACCESS drift (tick=100)        ║
║   Step 2: "Dirty" Twin — Inject same drift with changed metadata           ║
║   Step 3: Sanitization Audit — Assert sanitized strings are identical       ║
║   Step 4: Orchestrator Verdict — Assert heuristic bypass = True            ║
║                                                                              ║
║  Expected Outcome:                                                           ║
║   • similarity_score:  0.33 (before stripper) → >0.90 (after stripper)     ║
║   • heuristic_bypassed: True                                                 ║
║   • round_counter: 0                                                         ║
║   • Phase trace: [heuristic_check] → [remediation] → [completed]           ║
║                                                                              ║
║  Run: .venv/bin/python tests/test_hmem_amnesia_cure.py                      ║
║  Or:  .venv/bin/python -m pytest tests/test_hmem_amnesia_cure.py -v -s      ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

# ── Path Setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Core Imports ──────────────────────────────────────────────────────────────
from cloudguard.agents.sentry_node import DriftEventOutput, PolicyViolation
from cloudguard.agents.swarm import (
    ConsultantPersona,
    KernelMemory,
    SentryPersona,
)
from cloudguard.core.decision_logic import DecisionStatus
from cloudguard.graph.state_machine import (
    KernelOrchestrator,
    KernelPhase,
    KernelState,
)
from cloudguard.infra.memory_service import (
    HeuristicProposal,
    MemoryService,
    VictorySummary,
    sanitize_for_embedding,
    _text_to_vector,
    _cosine_similarity,
)

# ── Logging Setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("hmem_amnesia_cure")


# ═══════════════════════════════════════════════════════════════════════════════
# DRIFT EVENT FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

def make_victory_drift() -> dict:
    """
    Step 1: The "Victory" Anchor.
    S3_PUBLIC_ACCESS drift with timestamp_tick=100, trace_id="ALPHA-123".
    """
    return {
        "event_id": "drift-victory-001",
        "trace_id": "ALPHA-123",
        "resource_id": "prod-bucket-01",
        "drift_type": "public_exposure",
        "severity": "CRITICAL",
        "description": (
            "S3 bucket prod-bucket-01 PublicAccessBlock disabled. "
            "All objects are now publicly readable."
        ),
        "mutations": {
            "public_access_blocked": False,
            "block_public_acls": False,
            "block_public_policy": False,
        },
        "previous_values": {
            "public_access_blocked": True,
            "block_public_acls": True,
            "block_public_policy": True,
        },
        "timestamp_tick": 100,
        "is_false_positive": False,
        "cumulative_drift_score": 95.0,
    }


def make_dirty_twin_drift() -> dict:
    """
    Step 2: The "Dirty" Twin Injection.
    Same S3_PUBLIC_ACCESS drift but with CHANGED volatile metadata:
      - timestamp_tick: 550 (simulation time shift)
      - trace_id: "OMEGA-999" (unique request ID)
      - resource_id: "prod-bucket-99" (different instance)
    """
    return {
        "event_id": "drift-twin-002",
        "trace_id": "OMEGA-999",
        "resource_id": "prod-bucket-99",
        "drift_type": "public_exposure",
        "severity": "CRITICAL",
        "description": (
            "S3 bucket prod-bucket-99 PublicAccessBlock disabled. "
            "All objects are now publicly readable."
        ),
        "mutations": {
            "public_access_blocked": False,
            "block_public_acls": False,
            "block_public_policy": False,
        },
        "previous_values": {
            "public_access_blocked": True,
            "block_public_acls": True,
            "block_public_policy": True,
        },
        "timestamp_tick": 550,
        "is_false_positive": False,
        "cumulative_drift_score": 95.0,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY INTEGRITY REPORT PRINTER
# ═══════════════════════════════════════════════════════════════════════════════

class MemoryIntegrityReport:
    """Collects and prints the Memory Integrity Report."""

    def __init__(self):
        self.sections: list[dict[str, Any]] = []

    def add(self, title: str, data: dict[str, Any]):
        self.sections.append({"title": title, "data": data})

    def print_report(self):
        width = 90
        print(f"\n{'▓' * width}")
        print(f"  🧪 MEMORY INTEGRITY REPORT — H-MEM AMNESIA CURE VERIFICATION")
        print(f"{'▓' * width}")

        for section in self.sections:
            title = section["title"]
            data = section["data"]
            print(f"\n  ┌──── {title} {'─' * max(0, 55 - len(title))}┐")
            for k, v in data.items():
                if isinstance(v, float):
                    print(f"  │  {k:36s}: {v:.6f}")
                elif isinstance(v, bool):
                    icon = "✅" if v else "❌"
                    print(f"  │  {k:36s}: {icon} {v}")
                elif isinstance(v, list):
                    print(f"  │  {k:36s}:")
                    for item in v:
                        if isinstance(item, dict):
                            fr = item.get("from", "")
                            to = item.get("to", "")
                            print(f"  │      [{fr}] → [{to}]")
                        else:
                            print(f"  │      {item}")
                else:
                    print(f"  │  {k:36s}: {v}")
            print(f"  └{'─' * (width - 4)}┘")

        print(f"\n{'▓' * width}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1: THE "VICTORY" ANCHOR
# ═══════════════════════════════════════════════════════════════════════════════

def step_1_victory_anchor(mem: MemoryService, report: MemoryIntegrityReport) -> str:
    """
    Create a DriftEvent for S3_PUBLIC_ACCESS with timestamp_tick=100
    and trace_id="ALPHA-123". Store as a victory in H-MEM.
    """
    print("\n▸ Step 1: The 'Victory' Anchor...")

    victory = VictorySummary(
        drift_type="public_exposure",
        resource_type="S3",
        resource_id="prod-bucket-01",
        remediation_action="block_public_access",
        remediation_tier="gold",
        fix_parameters={
            "BlockPublicAcls": True,
            "BlockPublicPolicy": True,
            "IgnorePublicAcls": True,
            "RestrictPublicBuckets": True,
        },
        j_before=0.50,
        j_after=0.15,
        risk_delta=-66.5,
        cost_delta=0.50,
        environment="production",
        reasoning=(
            "CISO-selected remediation: S3 PublicAccessBlock enabled. "
            "Closes CIS 2.1.2. Immediate risk elimination for 50,000 PII objects."
        ),
        raw_drift=make_victory_drift(),
    )

    victory_id = mem.store_victory(victory)
    print(f"  ✅ Victory stored: {victory_id}")

    report.add("STEP 1: Victory Anchor", {
        "victory_id": victory_id,
        "drift_type": victory.drift_type,
        "resource_type": victory.resource_type,
        "resource_id": victory.resource_id,
        "remediation_action": victory.remediation_action,
        "j_before": victory.j_before,
        "j_after": victory.j_after,
        "j_improvement": victory.j_improvement,
    })

    return victory_id


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2: THE "DIRTY" TWIN INJECTION
# ═══════════════════════════════════════════════════════════════════════════════

def step_2_dirty_twin_injection(report: MemoryIntegrityReport) -> dict:
    """
    Inject a second S3_PUBLIC_ACCESS drift with changed volatile metadata.
    This is the "dirty twin" that the Semantic Stripper must handle.
    """
    print("\n▸ Step 2: The 'Dirty' Twin Injection...")

    dirty_twin = make_dirty_twin_drift()
    print(f"  ✅ Dirty twin injected:")
    print(f"      timestamp_tick: {dirty_twin['timestamp_tick']} (was 100)")
    print(f"      trace_id:      {dirty_twin['trace_id']} (was ALPHA-123)")
    print(f"      resource_id:   {dirty_twin['resource_id']} (was prod-bucket-01)")

    report.add("STEP 2: Dirty Twin Injection", {
        "timestamp_tick": dirty_twin["timestamp_tick"],
        "trace_id": dirty_twin["trace_id"],
        "resource_id": dirty_twin["resource_id"],
        "drift_type": dirty_twin["drift_type"],
        "severity": dirty_twin["severity"],
        "volatile_fields_changed": "timestamp_tick, trace_id, resource_id",
    })

    return dirty_twin


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3: THE SANITIZATION AUDIT
# ═══════════════════════════════════════════════════════════════════════════════

def step_3_sanitization_audit(report: MemoryIntegrityReport) -> tuple[float, float]:
    """
    Capture the output of sanitize_for_embedding() for both events.
    Compute similarity BEFORE and AFTER stripping.
    Assert that sanitized strings are semantically identical.
    """
    print("\n▸ Step 3: The Sanitization Audit...")

    victory_event = make_victory_drift()
    dirty_twin = make_dirty_twin_drift()

    # ── BEFORE: Raw cosine similarity (no stripping) ──────────────────────────
    raw_victory_str = json.dumps(victory_event, sort_keys=True)
    raw_twin_str = json.dumps(dirty_twin, sort_keys=True)

    raw_victory_vec = _text_to_vector(raw_victory_str)
    raw_twin_vec = _text_to_vector(raw_twin_str)
    similarity_before = _cosine_similarity(raw_victory_vec, raw_twin_vec)

    print(f"  📊 RAW similarity (before stripper): {similarity_before:.6f}")

    # ── AFTER: Sanitized cosine similarity (with Semantic Stripper) ───────────
    sanitized_victory = sanitize_for_embedding(victory_event)
    sanitized_twin = sanitize_for_embedding(dirty_twin)

    print(f"\n  📋 Sanitized Victory: '{sanitized_victory}'")
    print(f"  📋 Sanitized Twin:    '{sanitized_twin}'")

    san_victory_vec = _text_to_vector(sanitized_victory)
    san_twin_vec = _text_to_vector(sanitized_twin)
    similarity_after = _cosine_similarity(san_victory_vec, san_twin_vec)

    print(f"\n  📊 SANITIZED similarity (after stripper): {similarity_after:.6f}")

    # ── Verification: sanitized strings should be identical ───────────────────
    strings_identical = sanitized_victory == sanitized_twin
    print(f"  {'✅' if strings_identical else '⚠️'} Sanitized strings identical: {strings_identical}")

    if strings_identical:
        # If strings are identical, similarity is approx 1.0
        assert similarity_after > 0.99, (
            f"Identical strings must yield similarity ≈ 1.0, got {similarity_after}"
        )
    else:
        assert similarity_after > 0.90, (
            f"Sanitized similarity must be >0.90, got {similarity_after:.6f}"
        )

    # ── SNR Jump ──────────────────────────────────────────────────────────────
    snr_jump = similarity_after - similarity_before
    print(f"\n  🚀 SNR Jump: {similarity_before:.4f} → {similarity_after:.4f} (Δ={snr_jump:+.4f})")
    print(f"  ✅ Semantic Stripper VERIFIED: similarity >0.90 achieved")

    report.add("STEP 3: Sanitization Audit", {
        "raw_similarity_before": similarity_before,
        "sanitized_similarity_after": similarity_after,
        "snr_jump_delta": snr_jump,
        "sanitized_strings_identical": strings_identical,
        "sanitized_victory_text": sanitized_victory,
        "sanitized_twin_text": sanitized_twin,
        "threshold_met (>0.90)": similarity_after > 0.90,
    })

    return similarity_before, similarity_after


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: THE ORCHESTRATOR VERDICT
# ═══════════════════════════════════════════════════════════════════════════════

async def step_4_orchestrator_verdict(
    mem: MemoryService,
    report: MemoryIntegrityReport,
) -> KernelState:
    """
    Run the KernelOrchestrator on the dirty twin drift.
    Assert that heuristic_bypassed=True and round_counter=0.
    """
    print("\n▸ Step 4: The Orchestrator Verdict...")

    # Query H-MEM for the dirty twin to get the pre-built proposal
    proposal = mem.query_victory(
        drift_type="public_exposure",
        resource_type="S3",
        raw_logs=[json.dumps(make_dirty_twin_drift())],
    )
    assert proposal is not None, "H-MEM should return a proposal for known drift type"
    assert proposal.can_bypass_round1, (
        f"Proposal must allow bypass (similarity={proposal.similarity_score:.4f}, "
        f"threshold={mem.BYPASS_THRESHOLD})"
    )

    print(f"  📊 H-MEM query result: similarity={proposal.similarity_score:.6f}")
    print(f"  📊 Can bypass Round 1: {proposal.can_bypass_round1}")

    # Create the Orchestrator
    orchestrator = KernelOrchestrator(
        memory_service=mem,
        sentry_persona=SentryPersona(),
        consultant_persona=ConsultantPersona(gemini_api_key=None),
    )

    # Build the dirty twin violation with pre-loaded heuristic
    second_drift = DriftEventOutput(
        resource_id="prod-bucket-99",
        drift_type="public_exposure",
        severity="CRITICAL",
        confidence=0.9,
        triage_reasoning="Identical S3 public access drift (dirty twin, tick=550)",
    )

    second_violation = PolicyViolation(
        drift_events=[second_drift],
        heuristic_available=proposal.can_bypass_round1,
        heuristic_proposal=proposal.to_dict() if proposal.can_bypass_round1 else None,
        batch_size=1,
        confidence=0.9,
    )

    resource_ctx = {
        "resource_type": "S3",
        "resource_id": "prod-bucket-99",
        "provider": "aws",
        "region": "us-east-1",
        "monthly_cost_usd": 45.00,
        "total_risk": 95.0,
        "potential_savings": 0.0,
        "remediation_cost": 0.50,
        "data_classification": "PII",
        "object_count": 50000,
    }
    resource_tags = {"Environment": "production"}

    # Run the Orchestrator
    kernel_result = await orchestrator.process_violation(
        violation=second_violation,
        current_j=0.50,
        resource_context=resource_ctx,
        resource_tags=resource_tags,
    )

    # ── Assertions ────────────────────────────────────────────────────────────
    assert kernel_result.heuristic_bypassed is True, (
        f"Expected heuristic_bypassed=True, got {kernel_result.heuristic_bypassed}"
    )
    assert kernel_result.round_counter == 0, (
        f"Expected round_counter=0 (bypass = no negotiation), got {kernel_result.round_counter}"
    )

    print(f"  ✅ HEURISTIC_BYPASSED: {kernel_result.heuristic_bypassed}")
    print(f"  ✅ ROUND_COUNTER: {kernel_result.round_counter}")
    print(f"  ✅ PHASE: {kernel_result.phase.value}")

    # Extract the phase trace
    phase_trace = [
        f"[{t['from']}] → [{t['to']}]"
        for t in kernel_result.phase_history
    ]
    print(f"  📋 KERNEL_PHASE_TRACE: {' → '.join(t['to'] for t in kernel_result.phase_history)}")

    report.add("STEP 4: Orchestrator Verdict", {
        "kernel_id": kernel_result.kernel_id,
        "heuristic_bypassed": kernel_result.heuristic_bypassed,
        "round_counter": kernel_result.round_counter,
        "phase": kernel_result.phase.value,
        "j_before": kernel_result.j_before,
        "j_after": kernel_result.j_after,
        "j_improvement": kernel_result.j_improvement,
        "tokens_consumed": kernel_result.tokens_consumed,
        "phase_trace": kernel_result.phase_history,
    })

    # Verify we have the "Fast Path" trace
    if kernel_result.final_decision:
        report.add("STEP 4: Final Decision", {
            "decision_status": kernel_result.final_decision.status.value,
            "remediation_action": (
                kernel_result.final_decision.winning_proposal.get(
                    "reasoning", "N/A"
                )[:100]
                if kernel_result.final_decision.winning_proposal
                else "N/A"
            ),
        })

    return kernel_result


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_amnesia_cure_test():
    """Execute the full H-MEM Amnesia Cure Verification sequence."""
    width = 90
    print(f"\n{'█' * width}")
    print(f"  🧪 H-MEM 'AMNESIA CURE' VERIFICATION — SEMANTIC STRIPPER STRESS TEST")
    print(f"  CloudGuard-B Phase 2 — Heuristic Reasoning Validation")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'█' * width}")

    report = MemoryIntegrityReport()
    start = time.monotonic()

    # ── Initialize H-MEM ──────────────────────────────────────────────────────
    mem = MemoryService()
    initialized = mem.initialize()
    print(f"\n  🧠 H-MEM backend: {'ChromaDB' if initialized else 'in-memory cosine similarity'}")

    # ── Step 1: Victory Anchor ────────────────────────────────────────────────
    victory_id = step_1_victory_anchor(mem, report)

    # ── Step 2: Dirty Twin Injection ──────────────────────────────────────────
    dirty_twin = step_2_dirty_twin_injection(report)

    # ── Step 3: Sanitization Audit ────────────────────────────────────────────
    sim_before, sim_after = step_3_sanitization_audit(report)

    # ── Step 4: Orchestrator Verdict ──────────────────────────────────────────
    kernel_result = await step_4_orchestrator_verdict(mem, report)

    elapsed = time.monotonic() - start

    # ── Print the full Memory Integrity Report ────────────────────────────────
    report.add("FINAL SUMMARY", {
        "similarity_before_stripper": sim_before,
        "similarity_after_stripper": sim_after,
        "snr_improvement": sim_after - sim_before,
        "heuristic_bypassed": kernel_result.heuristic_bypassed,
        "round_counter": kernel_result.round_counter,
        "fast_path_achieved": kernel_result.heuristic_bypassed and kernel_result.round_counter == 0,
        "total_elapsed_seconds": elapsed,
    })

    report.print_report()

    # ── Final Pass/Fail ───────────────────────────────────────────────────────
    all_passed = (
        sim_after > 0.90
        and kernel_result.heuristic_bypassed is True
        and kernel_result.round_counter == 0
    )

    print(f"  ⏱️  Total elapsed: {elapsed:.2f}s")
    if all_passed:
        print(f"  🎯 ALL ASSERTIONS PASSED — AMNESIA CURE VERIFIED ✅")
        print(f"      Similarity: {sim_before:.4f} → {sim_after:.4f}")
        print(f"      Bypass: ENABLED | Rounds: 0 | Fast Path: YES")
    else:
        print(f"  ❌ TEST FAILED")
        if sim_after <= 0.90:
            print(f"      Similarity {sim_after:.4f} <= 0.90 threshold")
        if not kernel_result.heuristic_bypassed:
            print(f"      Heuristic bypass not triggered")
        if kernel_result.round_counter != 0:
            print(f"      Round counter {kernel_result.round_counter} != 0")

    print()
    return all_passed


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    success = asyncio.run(run_amnesia_cure_test())
    sys.exit(0 if success else 1)
