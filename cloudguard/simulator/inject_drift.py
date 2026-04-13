import argparse
import asyncio
import json
import logging
import os
import sys
import time
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



# ═══════════════════════════════════════════════════════════════════════════════
# CHAOS MODE — Full-Spectrum Phase 8 Stress Test
# ═══════════════════════════════════════════════════════════════════════════════

async def inject_chaos(
    count: int = 50,
    conflict_target: str = "iam-role-PII-vault",
    verbose: bool = False,
) -> None:
    import uuid
    import random
    from cloudguard.core.scheduler import InferenceScheduler
    from cloudguard.simulator.chaos_monkey import SovereignGate
    
    print("\n" + "═" * 80)
    print("  CLOUDGUARD-B ⚡ CHAOS MODE — FULL-SPECTRUM STRESS TEST")
    print(f"  Count: {count} | Conflict Target: {conflict_target}")
    print("═" * 80)

    scheduler = InferenceScheduler()
    if not scheduler._app:
        print("[!] Inference Scheduler (Celery) NOT ENABLED. Exiting.")
        return

    # 1. Mix Generation (OIDC=10, SHADOW=10, MINOR=30)
    req_oidc = 10
    req_shadow = 10
    req_minor = max(0, count - req_oidc - req_shadow)

    drifts = []
    
    for i in range(req_oidc):
        drifts.append({
            "drift_id": f"oidc-{uuid.uuid4().hex[:8]}",
            "drift_type": "OIDC_TRUST_BREACH",
            "severity": "CRITICAL",
            "resource_id": f"iam-role-oidc-breach-{i:02d}",
            "j_impact": 0.8,
            "probability": 0.85
        })

    for i in range(req_shadow):
        drifts.append({
            "drift_id": f"shadow-{uuid.uuid4().hex[:8]}",
            "drift_type": "SHADOW_AI_SPAWN",
            "severity": "HIGH",
            "resource_id": f"ec2-shadow-ai-{i:02d}",
            "j_impact": 0.6,
            "probability": 0.95  # fast pass!
        })

    # Collision Injection: Ensure at least 2 events target --resource-conflict-target
    for i in range(req_minor):
        res = conflict_target if i < 2 else f"minor-cfg-{uuid.uuid4().hex[:4]}"
        drifts.append({
            "drift_id": f"minor-{uuid.uuid4().hex[:8]}",
            "drift_type": "MINOR_CONFIGURATION_DRIFT",
            "severity": "LOW",
            "resource_id": res,
            "j_impact": 0.1,
            "probability": 0.2
        })

    random.shuffle(drifts)

    # 2. SovereignGate Timers
    gate = SovereignGate()

    # 3. Parallel Dispatch
    async def _fire(d):
        p = d["probability"]
        
        # Arm SovereignGate for this task
        timer_res = f"{d['resource_id']}::{d['drift_id']}"
        await gate.arm(timer_res, p)
        
        if verbose:
            print(f"[Dispatch] {d['drift_type']} -> {d['resource_id']} (Gate Armed: {gate._pending.get(timer_res) is not None})")
            
        scheduler.dispatch_reasoning(
            sentry_context={"drift_summary": f"Chaos drift: {d['drift_type']}"},
            consultant_context={"max_severity": d["severity"]},
            resource_context={"resource_id": d["resource_id"], "drift_type": d["drift_type"]},
            swarm_state={"drift_event_id": d["drift_id"]},
            j_impact=d["j_impact"],
            probability=p,
            severity=d["severity"]
        )
        return True

    results = await asyncio.gather(*[_fire(d) for d in drifts])
    
    print(f"\n[Parallel Dispatch] Fired {len(results)} tasks simultaneously into Inference Scheduler.")
    print(f"[Collision Inject] Forced 2 tasks onto: {conflict_target}")
    
    # Assert integrity: Ensure timers were armed
    active_timers = len(gate._pending)
    print(f"[Integrity Check] SovereignGate timers currently armed: {active_timers} / {count}")
    
    print("\n[Status] Celery is processing tasks in the background. Check celery worker logs!")


# ═══════════════════════════════════════════════════════════════════════════════
# PROACTIVE MODE — 20-tick Amber Sequence Injection
# ═══════════════════════════════════════════════════════════════════════════════

async def inject_proactive(
    resource_id: str,
    tick_delay: float = 0.4,
    redis_url: str = "redis://localhost:6379",
) -> None:
    """
    --mode proactive

    Injects the 20-tick Amber Sequence into the CloudGuard-B pipeline:
      - Ticks 1-5  : LOW breadcrumbs  (IAM:GetPolicy, S3:ListBuckets, …)
      - Ticks 6-10 : MEDIUM recon     (VPC:DescribeFlowLogs, CloudTrail:LookupEvents, …)
      - Ticks 11-15: HIGH recon chain  (DescribeRoles×3, AssumeRole, CreateRole)
      - Tick  16   : OIDC_TRUST_BREACH (the actual breach event)
      - Ticks 17-20: POST-BREACH       (lateral movement + data exfil probes)

    For each tick:
      1. Publishes the event to Redis `cloudguard_events` channel
      2. Feeds the event into ThreatForecaster's sliding window
      3. Runs predict_tick() → prints P, predicted drift, Amber Alert status
    """
    from cloudguard.simulator.amber_sequence_generator import AmberSequenceGenerator
    from cloudguard.forecaster.threat_forecaster import ThreatForecaster

    print("\n" + "═" * 80)
    print("  CLOUDGUARD-B ⚡ PROACTIVE MODE — 20-TICK AMBER SEQUENCE")
    print(f"  Resource: {resource_id}")
    print("═" * 80)

    gen = AmberSequenceGenerator(resource_id=resource_id)
    ticks = gen.generate()

    forecaster = ThreatForecaster(window_size=100)
    # Prime the LSTM with synthetic recon training
    losses = forecaster.train_on_recon_patterns(num_synthetic=50)
    print(f"\n[LSTM] Pre-trained — final loss: {losses[-1]:.4f}\n")

    # Optional Redis client (graceful fallback)
    redis_client = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(
            redis_url, decode_responses=True, socket_connect_timeout=3
        )
        await redis_client.ping()
        print(f"[Redis] Connected → {redis_url}\n")
    except Exception as exc:
        print(f"[Redis] Unavailable ({exc}) — proceeding in offline mode\n")

    # ─── Tick loop ────────────────────────────────────────────────────────────
    phase_colors = {
        "breadcrumb_low":    "\033[92m",   # green
        "breadcrumb_medium": "\033[93m",   # yellow
        "breadcrumb_high":   "\033[33m",   # dark-yellow
        "breach":            "\033[91m",   # red
        "post_breach":       "\033[95m",   # magenta
    }
    reset = "\033[0m"

    for evt in ticks:
        tick_num  = evt["timestamp_tick"]
        phase     = evt["amber_phase"]
        drift_t   = evt["data"]["drift_type"]
        severity  = evt["data"]["severity"]
        color     = phase_colors.get(phase, "")

        # 1. Publish to Redis
        if redis_client:
            try:
                await redis_client.publish("cloudguard_events", json.dumps(evt))
            except Exception:
                pass

        # 2. Ingest into forecaster
        forecaster.ingest_event(evt)

        # 3. Predict
        result = forecaster.predict_tick(current_j=0.5)

        # Publish ForecastSignal payloads so the War Room UI receives
        # proactive advisory/amber events in real time.
        if redis_client:
            try:
                await redis_client.publish(
                    "cloudguard_events",
                    json.dumps(result.to_ws_payload()),
                )
            except Exception:
                pass

        amber_flag = "🚨 AMBER ALERT" if result.is_amber_alert else "   advisory  "
        shadow_flag = " 👁️  SHADOW-AI" if result.is_shadow_ai else ""
        recon_flag  = f" 🔍 RECON:{result.recon_pattern_name}" if result.recon_pattern_detected else ""

        print(
            f"{color}[Tick {tick_num:02d}/20] phase={phase:<18} "
            f"drift={drift_t:<24} sev={severity:<8}{reset}\n"
            f"          {amber_flag}  P={result.probability:.2%}  "
            f"predicted={result.predicted_drift_type}"
            f"  horizon={result.horizon_ticks}t"
            f"{shadow_flag}{recon_flag}"
        )

        if result.is_amber_alert:
            print(
                f"          └─ J_forecast={result.j_forecast:.4f}  "
                f"CI=[{result.confidence_interval[0]:.2%}, "
                f"{result.confidence_interval[1]:.2%}]"
            )
            # Emit STOCHASTIC_THREAT signal
            logger.warning(
                f"🔔 STOCHASTIC_THREAT signal emitted for "
                f"{result.target_resource_id or resource_id}"
            )

        time.sleep(tick_delay)

    if redis_client:
        await redis_client.aclose()

    print("\n" + "═" * 80)
    print("  AMBER SEQUENCE COMPLETE — 20 ticks replayed")
    print(f"  Amber Alerts fired: {forecaster.get_stats()['amber_alerts_fired']}")
    print(f"  Recon patterns:     {forecaster.get_stats()['recon_patterns_found']}")
    print(f"  Shadow AI detect:   {forecaster.get_stats()['shadow_ai_detections']}")
    print("═" * 80 + "\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="CloudGuard-B Drift Simulator",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "proactive", "chaos"],
        default="single",
        help="'single' injects one drift; 'proactive' runs Amber sequence; 'chaos' triggers Phase 8 stress test",
    )
    parser.add_argument("--count", type=int, default=50, help="Number of simultaneous drifts to inject (Default: 50)")
    parser.add_argument("--chaos-factor", type=float, default=1.0, help="Chaos factor")
    parser.add_argument("--resource-conflict-target", default="iam-role-PII-vault", help="Resource ID to force a collision")
    parser.add_argument("--type", default="OIDC_TRUST_BREACH",
                        help="Drift type (single mode only)")
    parser.add_argument("--resource", required=False,
                        help="Resource ID / ARN to target")
    parser.add_argument("--severity", default="CRITICAL",
                        help="Severity (single mode only)")
    parser.add_argument("--verbose", action="store_true", default=False)
    parser.add_argument("--tick-delay", type=float, default=0.4,
                        help="Sleep seconds between ticks in proactive mode")
    parser.add_argument("--redis-url", default="redis://localhost:6379")
    args = parser.parse_args()

    if args.mode == "chaos":
        asyncio.run(
            inject_chaos(
                count=args.count,
                conflict_target=args.resource_conflict_target,
                verbose=args.verbose,
            )
        )
    elif args.mode == "proactive":
        asyncio.run(
            inject_proactive(
                resource_id=args.resource,
                tick_delay=args.tick_delay,
                redis_url=args.redis_url,
            )
        )
    else:
        asyncio.run(
            inject_drift(args.type, args.resource, args.severity, args.verbose)
        )
