import re

with open("cloudguard/simulator/inject_drift.py", "r") as f:
    content = f.read()

chaos_func = """
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
    
    print("\\n" + "═" * 80)
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
    
    print(f"\\n[Parallel Dispatch] Fired {len(results)} tasks simultaneously into Inference Scheduler.")
    print(f"[Collision Inject] Forced 2 tasks onto: {conflict_target}")
    
    # Assert integrity: Ensure timers were armed
    active_timers = len(gate._pending)
    print(f"[Integrity Check] SovereignGate timers currently armed: {active_timers} / {count}")
    
    print("\\n[Status] Celery is processing tasks in the background. Check celery worker logs!")

"""

# insert it before PROACTIVE MODE
content = content.replace("# ═══════════════════════════════════════════════════════════════════════════════\n# PROACTIVE", chaos_func + "\n# ═══════════════════════════════════════════════════════════════════════════════\n# PROACTIVE")

with open("cloudguard/simulator/inject_drift.py", "w") as f:
    f.write(content)
