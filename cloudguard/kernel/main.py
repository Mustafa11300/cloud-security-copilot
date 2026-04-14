"""
KERNEL CLI — FIRST-CONTACT SIEM INJECTION
=========================================
Tests the Consultant (Gemini 1.5 Pro) traversing a novel trust relationship breach,
demonstrating the "Dialectical Friction" between the Sentry and the Consultant.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

# Ensure cloudguard is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cloudguard.agents.sentry_node import DriftEventOutput, PolicyViolation
from cloudguard.agents.swarm import create_swarm_personas
from cloudguard.graph.state_machine import KernelOrchestrator
from cloudguard.infra.memory_service import MemoryService

# ── LOGGING SETUP ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="\n%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("kernel_main")


# ── THE PAYLOAD ───────────────────────────────────────────────────────────────
NOVEL_TRUST_PAYLOAD = {
    "trace_id": "NOVA-001-ALPHA",
    "timestamp_tick": 1024,
    "drift_type": "EXTERNAL_OIDC_TRUST_INJECTION",
    "resource_id": "arn:aws:iam::123456789012:role/CloudGuard-B-Admin",
    "severity": "CRITICAL",
    "mutations": {
        "trust_policy": "Added: token.actions.githubusercontent.com:aud",
        "condition": "StringLike: repo:rogue-actor/*:*",
        "risk_profile": "Lateral Movement Opportunity"
    },
    "metadata": {
        "environment": "PROD",
        "data_class": "PII",
        "business_unit": "Core-Banking"
    }
}


# ── EXECUTION SCRIPT ──────────────────────────────────────────────────────────
async def run_scenario(mode: str, scenario: str) -> None:
    print("\n" + "═" * 80)
    print("  CLOUDGUARD-B COGNITIVE OS — FIRST-CONTACT SIEM INJECTION")
    print("  Mode: LIVE LLM (Gemini 1.5 Pro enabled)")
    print("═" * 80)

    # 1. Initialize Memory Service
    mem = MemoryService(bypass_threshold=0.85)

    # 2. Create Swarm Personas (Gemini + Ollama/Stub)
    sentry_p, consultant_p, kernel_mem = create_swarm_personas(gemini_model="gemini-1.5-pro-latest")

    # 3. Create Orchestrator
    orchestrator = KernelOrchestrator(
        memory_service=mem,
        sentry_persona=sentry_p,
        consultant_persona=consultant_p,
        kernel_memory=kernel_mem,
    )

    # 4. Convert Payload to PolicyViolation
    drift = DriftEventOutput(
        resource_id=NOVEL_TRUST_PAYLOAD["resource_id"],
        drift_type=NOVEL_TRUST_PAYLOAD["drift_type"],
        severity=NOVEL_TRUST_PAYLOAD["severity"],
        confidence=0.95,
        triage_reasoning="Critical OIDC trust injection to high-privilege Admin role.",
        raw_logs=[NOVEL_TRUST_PAYLOAD],
    )

    violation = PolicyViolation(
        drift_events=[drift],
        heuristic_available=False,
        batch_size=1,
        confidence=0.95,
    )

    # We provide Cost & Risk approximations to simulate ALE calculation constraints.
    resource_ctx = {
        "drift_type": NOVEL_TRUST_PAYLOAD["drift_type"],
        "resource_type": "IAM_ROLE",
        "resource_id": NOVEL_TRUST_PAYLOAD["resource_id"],
        "provider": "aws",
        "region": "global",
        "monthly_cost_usd": 0.0,
        "total_risk": 2400000.0,  # $2.4M potential breach cost!
        "potential_savings": 0.0,
        "remediation_cost": 0.0,
        "data_classification": NOVEL_TRUST_PAYLOAD["metadata"]["data_class"],
        "impact_zone": "Core-Banking Admin",
    }
    resource_tags = {"Environment": NOVEL_TRUST_PAYLOAD["metadata"]["environment"]}

    print("\n[SIEM Injection] Processing NOVEL_TRUST payload...")
    print(json.dumps(NOVEL_TRUST_PAYLOAD, indent=2))

    # 5. Execute Negotiation Simulation
    print("\n[Orchestrator] Kernel Phase Tracing initiated...")
    kernel_result = await orchestrator.process_violation(
        violation=violation,
        current_j=0.75,  # High J-score starting state (High Risk)
        resource_context=resource_ctx,
        resource_tags=resource_tags,
    )

    # 6. Extract the "Truth Log" Transcript
    print("\n" + "▓" * 80)
    print("  TRUTH LOG: THE DIALECTICAL FRICTION TRANSCRIPT")
    print("▓" * 80)

    history = orchestrator._kernel_memory.get_consultant_context().get("previous_proposals", [])
    
    if not history:
        print("\n[SYSTEM] No negotiation took place. Possibly bypassed.")
    else:
        for phase in kernel_result.phase_history:
            if phase["to"] == "remediation":
                pass

        for p in history:
            role = getattr(p, "agent_role", "unknown").upper()
            cost_d = getattr(p, "expected_cost_delta", 0)
            risk_d = getattr(p, "expected_risk_delta", 0)
            reason = getattr(p, "reasoning", "")
            cmds = getattr(p, "commands", [])

            color = "\033[91m" if role == "CISO" else "\033[94m" if role == "CONTROLLER" else "\033[93m"
            reset = "\033[0m"

            print(f"\n{color}● Agent: {role}{reset}")
            print(f"  ├─ Proposed Impact: Risk Δ={risk_d}, Cost Δ=${cost_d}")
            print(f"  ├─ Reasoning:       {reason}")
            
            if cmds:
                print(f"  └─ Operations:")
                for cmd in cmds:
                    cmd_dict = cmd if isinstance(cmd, dict) else cmd.model_dump()
                    print(f"       > {json.dumps(cmd_dict)}")

    print("\n" + "═" * 80)
    print("  FINAL VERDICT (Synthesis outcome)")
    print("═" * 80)
    if kernel_result.final_decision and kernel_result.final_decision.winning_proposal:
        win = kernel_result.final_decision.winning_proposal
        print(f"\n[ORCHESTRATOR] Selected Decision Status: {kernel_result.final_decision.status.value.upper()}")
        print(f"               J-Score Improved: {kernel_result.j_before:.4f} → {kernel_result.j_after:.4f}")
        print(f"\n[ORCHESTRATOR] Synthesis Reasoning:\n  > {kernel_result.final_decision.reasoning}")
        print(f"\n[ORCHESTRATOR] Final Python Healing Execution Plan:")
        win_cmds = getattr(win, "commands", [])
        for cmd in win_cmds:
            print(f"  - Action: {getattr(cmd, 'action', None)}")
            print(f"    Code Payload:\n{getattr(cmd, 'payload', None)}")
    else:
        print("\n[ORCHESTRATOR] No decisive outcome available.")
    
    print("\n═" * 80)

if __name__ == "__main__":
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="CloudGuard Kernel Runner")
    parser.add_argument("--mode", type=str, choices=["live", "simulated"], default="live")
    parser.add_argument("--scenario", type=str, required=True)
    
    args = parser.parse_args()
    
    asyncio.run(run_scenario(args.mode, args.scenario))
