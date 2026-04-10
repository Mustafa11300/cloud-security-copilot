import asyncio, traceback, sys

OUT = open("verify_results.txt", "w", encoding="utf-8")
def log(msg):
    OUT.write(msg + "\n")
    OUT.flush()

async def main():
    log("=== PHASE 2 BRAIN VERIFICATION ===")
    
    try:
        from cloudguard.infra.memory_service import MemoryService, VictorySummary
        m = MemoryService()
        m.initialize()
        v = VictorySummary(drift_type="public_exposure", resource_type="S3",
                           resource_id="res-001", remediation_action="block_public_access",
                           j_before=0.45, j_after=0.32, risk_delta=-25.0, cost_delta=5.0)
        m.store_victory(v)
        p = m.query_victory("public_exposure", "S3")
        log(f"M3 H-MEM: OK (sim={p.similarity_score:.2%})" if p else "M3: OK (stored)")
    except Exception as e:
        log(f"M3 FAIL: {e}\n{traceback.format_exc()}")

    try:
        from cloudguard.core.decision_logic import ActiveEditor
        ed = ActiveEditor()
        r = ed.synthesize(
            security_proposal={"proposal_id":"s1","agent_role":"ciso","expected_risk_delta":-30,"expected_cost_delta":15,"commands":[]},
            cost_proposal={"proposal_id":"c1","agent_role":"controller","expected_risk_delta":-5,"expected_cost_delta":-20,"commands":[]},
            current_j=0.45, resource_tags={"Environment":"production"},
        )
        log(f"M5 DecisionLogic: OK (status={r.status.value}, dJ%={r.j_improvement_pct:.2f}%)")
    except Exception as e:
        log(f"M5 FAIL: {e}\n{traceback.format_exc()}")

    try:
        from cloudguard.agents.sentry_node import SentryNode
        from cloudguard.infra.redis_bus import EventPayload
        sentry = SentryNode(memory_service=m, use_ollama=False)
        events = [
            EventPayload.drift("res-001", "public_exposure", "HIGH", 1, mutations={"public_access_blocked": False}),
            EventPayload.drift("res-001", "public_exposure", "HIGH", 1, mutations={"public_access_blocked": False}),
            EventPayload.drift("res-003", "tag_removed", "LOW", 1, is_false_positive=True),
        ]
        violations = await sentry.process_batch(events, 1000)
        log(f"M1 SentryNode: OK ({len(violations)} violations from {len(events)} events)")
    except Exception as e:
        log(f"M1 FAIL: {e}\n{traceback.format_exc()}")

    try:
        from cloudguard.agents.swarm import create_swarm_personas
        from cloudguard.core.schemas import EnvironmentWeights
        from cloudguard.core.swarm import SwarmState
        sp, cp, km = create_swarm_personas()
        state = SwarmState(current_j_score=0.45, weights=EnvironmentWeights(w_risk=0.6, w_cost=0.4))
        ctx = {"total_risk": 45.0, "remediation_cost": 100.0, "potential_savings": 200.0}
        ciso = sp.propose(state, ctx)
        ctrl = cp.propose(state, ctx)
        log(f"M2 Personas: OK (CISO dR={ciso.expected_risk_delta:.1f}, CTRL dC={ctrl.expected_cost_delta:.1f})")
    except Exception as e:
        log(f"M2 FAIL: {e}\n{traceback.format_exc()}")

    try:
        from cloudguard.graph.state_machine import KernelOrchestrator
        from cloudguard.agents.sentry_node import DriftEventOutput, PolicyViolation
        orch = KernelOrchestrator(memory_service=m, sentry_persona=sp, consultant_persona=cp, kernel_memory=km)
        drift = DriftEventOutput(resource_id="res-k01", drift_type="public_exposure", severity="HIGH", confidence=0.9)
        viol = PolicyViolation(drift_events=[drift], batch_size=1, total_raw_events=1, confidence=0.9)
        ks = await orch.process_violation(viol, current_j=0.45,
            resource_context={"total_risk":45,"remediation_cost":100,"potential_savings":200},
            resource_tags={"Environment":"production"})
        log(f"M4 Kernel: OK (phase={ks.phase.value}, J:{ks.j_before:.4f}->{ks.j_after:.4f}, rounds={ks.round_counter})")
    except Exception as e:
        log(f"M4 FAIL: {e}\n{traceback.format_exc()}")

    log("\n=== DONE ===")
    OUT.close()

asyncio.run(main())
