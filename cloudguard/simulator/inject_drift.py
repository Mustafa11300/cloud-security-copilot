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
logger = logging.getLogger("simulator.inject_drift")

async def inject_drift(drift_type: str, resource_id: str, severity: str, verbose: bool = False):
    print("\n" + "═" * 80)
    print(f"  CLOUDGUARD-B SIMULATOR — NOVEL DRIFT INJECTION")
    print(f"  Type: {drift_type} | Resource: {resource_id} | Verbose: {verbose}")
    print("═" * 80)

    # 1. Initialize Memory Service
    mem = MemoryService(bypass_threshold=0.85)

    # 2. Create Swarm Personas (Gemini 2.5 Flash + Ollama/Stub)
    sentry_p, consultant_p, kernel_mem = create_swarm_personas()

    # 3. Create Orchestrator
    orchestrator = KernelOrchestrator(
        memory_service=mem,
        sentry_persona=sentry_p,
        consultant_persona=consultant_p,
        kernel_memory=kernel_mem,
    )

    novel_payload = {
        "trace_id": "X-CROSS-CLOUD-IDENT-999",
        "timestamp_tick": 1025,
        "drift_type": drift_type,
        "resource_id": resource_id,
        "severity": severity,
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

    drift = DriftEventOutput(
        resource_id=novel_payload["resource_id"],
        drift_type=novel_payload["drift_type"],
        severity=novel_payload["severity"],
        confidence=0.95,
        triage_reasoning="Critical OIDC trust injection detected.",
        raw_logs=[novel_payload],
    )

    violation = PolicyViolation(
        drift_events=[drift],
        heuristic_available=False,
        batch_size=1,
        confidence=0.95,
    )

    resource_ctx = {
        "resource_type": "IAM_ROLE",
        "drift_type": drift_type,
        "resource_id": resource_id,
        "provider": "aws",
        "region": "global",
        "monthly_cost_usd": 0.0,
        "total_risk": 2400000.0,
        "potential_savings": 0.0,
        "remediation_cost": 5000.0, # Impact if CI/CD breaks
        "data_classification": novel_payload["metadata"]["data_class"],
    }
    
    # 4. Generate topology image (Phase 3 vision test stub)
    import base64
    b64_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    with open("topology.png", "wb") as f:
        f.write(base64.b64decode(b64_png))

    print("\n[Simulator] Processing payload...")
    kernel_result = await orchestrator.process_violation(
        violation=violation,
        current_j=0.75,
        resource_context=resource_ctx,
        resource_tags={"Environment": "PROD"},
    )

    print("\n" + "▓" * 80)
    print("  TRUTH LOG: THE DIALECTICAL FRICTION TRANSCRIPT")
    print("▓" * 80)

    history = orchestrator._kernel_memory.get_consultant_context().get("previous_proposals", [])
    
    if not history:
        print("\n[SYSTEM] No negotiation took place. Possibly bypassed.")
    else:
        for p in history:
            role = p.get("agent_role", getattr(p, "agent_role", "unknown"))
            role_upper = getattr(role, "value", str(role)).upper()
            
            # Since p could be a dict or a Pydantic AgentProposal
            if hasattr(p, "model_dump"):
                p = p.model_dump()
            
            cost_d = p.get("expected_cost_delta", 0)
            risk_d = p.get("expected_risk_delta", 0)
            reason = p.get("reasoning", "")
            cmds = p.get("commands", [])

            color = "\033[91m" if role_upper == "CISO" else "\033[94m" if role_upper == "CONTROLLER" else "\033[93m"
            reset = "\033[0m"

            print(f"\n{color}● Agent: {role_upper}{reset}")
            print(f"  ├─ Proposed Impact: Risk Δ={risk_d}, Cost Δ=${cost_d}")
            print(f"  ├─ Reasoning:       {reason}")
            
            if cmds:
                print(f"  └─ Operations:")
                for cmd in cmds:
                    cmd_dict = cmd if isinstance(cmd, dict) else getattr(cmd, "model_dump", lambda: cmd)()
                    print(f"       > {json.dumps(cmd_dict, default=str)}")
                    
                    if verbose and role_upper == "CONTROLLER":
                         print(f"\n       [VERBOSE TRACE] RAW Action Output:")
                         print(f"       {cmd_dict.get('payload', 'None')}")

    print("\n" + "═" * 80)
    print("  FINAL VERDICT (Synthesis outcome)")
    print("═" * 80)
    if kernel_result.final_decision and kernel_result.final_decision.winning_proposal:
        win = kernel_result.final_decision.winning_proposal
        print(f"\n[ORCHESTRATOR] Selected Decision Status: {kernel_result.final_decision.status.value.upper()}")
        print(f"               J-Score Improved: {kernel_result.j_before:.4f} → {kernel_result.j_after:.4f}")
        print(f"\n[ORCHESTRATOR] Synthesis Reasoning:\n  > {kernel_result.final_decision.reasoning}")
        print(f"\n[ORCHESTRATOR] Final Python Healing Execution Plan:")
        
        # Handle dict or Pydantic object
        win_dict = win if isinstance(win, dict) else win.model_dump()
        for cmd in win_dict.get("commands", []):
            print(f"  - Action: {cmd.get('action')}")
            print(f"    Code Payload:\n{cmd.get('python_code', 'None')}")
    else:
        print("\n[ORCHESTRATOR] No decisive outcome available.")
    
    print("\n═" * 80)


if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument("--severity", required=True)
    parser.add_argument("--verbose", action="store_true", default=False)
    args = parser.parse_args()
    
    asyncio.run(inject_drift(args.type, args.resource, args.severity, args.verbose))
