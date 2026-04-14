"""
CLOUDGUARD-B — CORE SOVEREIGN TEST
====================================
Simulates a high-stakes OIDC Trust Breach scenario by injecting events
through the REST API → WebSocket pipeline.

This tests:
  1. Temporal Risk Horizon (Past Events + Forecast pills)
  2. J-Score Negotiation (w_R / w_C bar movement)
  3. 10-Second Fast-Pass Countdown
  4. Iron Dome Topology (Stasis Field on locked resource)
  5. NIST Audit Trail (Sovereign Remediation log)

Prerequisites:
  - Backend running: uvicorn cloudguard.app:app --port 8000
  - Frontend running: npm run dev (port 3000)
  - Browser open to http://localhost:3000/dashboard with "WS Connected"

Usage:
  python sovereign_core_test.py
"""

import requests
import time
import sys

API_BASE = "http://localhost:8000"
INJECT_URL = f"{API_BASE}/api/v2/test/inject"


def inject(event_type: str, data: dict, weights: dict = None, agent: str = "test-harness"):
    """Send an event through the injection endpoint."""
    payload = {
        "event_type": event_type,
        "data": data,
        "agent_id": agent,
    }
    if weights:
        payload["environment_weights"] = weights

    resp = requests.post(INJECT_URL, json=payload, timeout=5)
    if resp.status_code != 200:
        print(f"  ❌ FAILED ({resp.status_code}): {resp.text[:200]}")
        return False
    result = resp.json()
    print(f"  ✅ Injected: {result['event_type']} → {result['event_id']}")
    return True


def check_backend():
    """Verify the backend is running."""
    try:
        resp = requests.get(f"{API_BASE}/api/v2/health", timeout=3)
        data = resp.json()
        clients = data.get("war_room", {}).get("active_clients", 0)
        print(f"  Backend: {data['status']}")
        print(f"  WebSocket clients: {clients}")
        if clients == 0:
            print("  ⚠️  No WebSocket clients - open http://localhost:3000/dashboard first!")
        return True
    except Exception as e:
        print(f"  ❌ Backend not reachable: {e}")
        return False


def run_sovereign_core_test():
    """Execute the full OIDC Trust Breach scenario."""

    print("=" * 60)
    print("🛡️  CLOUDGUARD-B — CORE SOVEREIGN TEST")
    print("    Scenario: OIDC Trust Breach on PII Vault")
    print("=" * 60)

    # ── Pre-flight Check ──────────────────────────────────────────────
    print("\n📡 Phase 0: Pre-flight Check")
    if not check_backend():
        print("\n❌ Cannot proceed without backend. Run:")
        print("   uvicorn cloudguard.app:app --port 8000")
        sys.exit(1)

    # ── Phase 1: Topology Sync (Baseline) ─────────────────────────────
    print("\n🌐 Phase 1: Topology Sync — Establishing Crown Jewels")
    print("   → Populates Iron Dome hex grid with target resources")
    inject("TOPOLOGY_SYNC", {
        "resources": [
            {"id": "iam-role-PII-vault",  "resource_id": "iam-role-PII-vault",  "status": "GREEN", "type": "IAM",     "isLocked": False},
            {"id": "ec2-shadow-ai-node",  "resource_id": "ec2-shadow-ai-node",  "status": "GREEN", "type": "Compute", "isLocked": False},
            {"id": "s3-audit-trail",      "resource_id": "s3-audit-trail",      "status": "GREEN", "type": "Storage", "isLocked": False},
            {"id": "lambda-auth-gateway", "resource_id": "lambda-auth-gateway", "status": "GREEN", "type": "Compute", "isLocked": False},
            {"id": "rds-user-profiles",   "resource_id": "rds-user-profiles",   "status": "YELLOW","type": "Database","isLocked": False},
        ]
    })
    time.sleep(2)

    # ── Phase 2: DRIFT Detection ──────────────────────────────────────
    print("\n🔍 Phase 2: Drift Detection — Reconnaissance Spotted")
    print("   → IAM policy change detected on PII Vault")
    inject("DRIFT", {
        "resource_id": "iam-role-PII-vault",
        "drift_type": "IAM_POLICY_CHANGE",
        "severity": "HIGH",
        "cumulative_drift_score": 7.2,
        "is_false_positive": False,
    }, weights={"w_R": 0.70, "w_C": 0.30})
    time.sleep(2)

    # ── Phase 3: Amber Alert (LSTM Forecast) ──────────────────────────
    print("\n📡 Phase 3: Amber Alert — LSTM Predicts OIDC Breach")
    print("   → 93% probability within 5 ticks, Ghost Node manifests")
    inject("FORECAST_SIGNAL", {
        "type": "Amber_Alert",
        "probability": 0.93,
        "target": "iam-role-PII-vault",
        "horizon": "5 ticks",
        "predicted_drift": "OIDC_TRUST_BREACH",
        "is_shadow_ai": True,
        "j_forecast": 0.82,
        "recon_chain": "CloudTrail:AssumeRoleWithWebIdentity → IAM:CreatePolicy → S3:GetObject",
        "confidence_lo": 0.87,
        "confidence_hi": 0.97,
    })
    time.sleep(3)

    # ── Phase 4: Agentic Friction (J-Score Negotiation) ───────────────
    print("\n🧠 Phase 4: Dialectical Negotiation — Sentry vs Controller")
    print("   → Sentry pushes w_R=0.85, Controller argues cost impact")

    # Sentry's opening argument
    inject("NARRATIVE_CHUNK", {
        "chunk_type": "threat",
        "heading": "CRITICAL: OIDC Trust Breach Imminent",
        "body": "Sentry detected IAM policy drift on iam-role-PII-vault. "
                "CloudTrail shows AssumeRoleWithWebIdentity from unknown OIDC provider. "
                "Cumulative drift score: 7.2/10. Recommending immediate lockdown.",
        "citation": "NIST SP 800-207 §4.3 — Zero Trust Architecture",
        "j_before": 0.51,
        "j_after": 0.68,
        "j_delta": 0.17,
    }, weights={"w_R": 0.85, "w_C": 0.15}, agent="sentry-node")
    time.sleep(2)

    # Controller's cost objection
    inject("NARRATIVE_CHUNK", {
        "chunk_type": "argument",
        "heading": "Cost Impact Assessment",
        "body": "Controller: Lockdown of iam-role-PII-vault affects 12 downstream services. "
                "Estimated operational impact: $450/min. Negotiating reduced-scope remediation. "
                "Proposing credential rotation + monitoring instead of full lockdown.",
        "citation": "ROSI Framework §2.1 — Annualized Loss Expectancy",
        "j_before": 0.68,
        "j_after": 0.55,
        "j_delta": -0.13,
    }, weights={"w_R": 0.72, "w_C": 0.28}, agent="controller")
    time.sleep(2)

    # Orchestrator synthesis
    inject("NARRATIVE_CHUNK", {
        "chunk_type": "synthesis",
        "heading": "Pareto Consensus Reached",
        "body": "Orchestrator: J-Score converged at 0.5100. "
                "Sentry risk assessment weighted at 85%. "
                "Approved action: rotate_credentials on PII-vault. "
                "Full lockdown deferred pending Fast-Pass review window.",
        "citation": "J-Function Pareto Optimization §3.2",
        "j_before": 0.55,
        "j_after": 0.51,
        "j_delta": -0.04,
        "is_final": True,
        "roi_summary": {"cost_avoided": 5400, "mttr_reduction_pct": 45},
    }, weights={"w_R": 0.85, "w_C": 0.15}, agent="orchestrator")
    time.sleep(2)

    # ── Phase 5: Fast-Pass Armed (10s Countdown) ─────────────────────
    print("\n⚡ Phase 5: Fast-Pass Armed — 10-Second Countdown")
    print("   → Switch to /dashboard/cost to see the countdown timer!")
    inject("NARRATIVE_CHUNK", {
        "chunk_type": "fast_pass",
        "heading": "AUTONOMOUS REFLEX: Fast-Pass Armed",
        "body": "High-confidence threat (P=0.93). Fast-Pass activated. "
                "Autonomous remediation in 10 seconds unless vetoed.",
        "is_fast_pass": True,
        "countdown_active": True,
        "seconds_remaining": 10,
        "fast_pass_meta": {
            "resource_id": "iam-role-PII-vault",
            "action": "rotate_credentials",
            "probability": 0.93,
            "accelerated_window_s": 10,
        },
    }, weights={"w_R": 0.85, "w_C": 0.15}, agent="orchestrator")
    time.sleep(5)

    print("   ⏱️  5 seconds remaining — veto now at /dashboard/cost or /dashboard/copilot!")
    time.sleep(5)

    # ── Phase 6: Remediation Executed ─────────────────────────────────
    print("\n🛡️  Phase 6: Sovereign Remediation — Credentials Rotated")
    print("   → PII Vault locked, Iron Dome shows Stasis Field")
    inject("REMEDIATION", {
        "resource_id": "iam-role-PII-vault",
        "action": "rotate_credentials",
        "tier": "T1",
        "success": True,
        "j_before": 0.51,
        "j_after": 0.11,
        "isLocked": True,
    }, weights={"w_R": 0.60, "w_C": 0.40}, agent="remediation-protocol")
    time.sleep(2)

    # ── Phase 7: Audit Surgeon Verification ───────────────────────────
    print("\n📋 Phase 7: Audit Surgeon — NIST Compliance Check")
    inject("NARRATIVE_CHUNK", {
        "chunk_type": "exec",
        "heading": "NIST AI RMF 2.1 — Compliance Verified",
        "body": "Audit Surgeon: Credential rotation on iam-role-PII-vault confirmed. "
                "OIDC trust boundary re-established. "
                "12 downstream services reconnected with rotated credentials. "
                "No data exfiltration detected during the 47-second exposure window.",
        "citation": "NIST AI RMF 2.1 §MAP-1.5, GOVERN-1.2",
        "is_final": True,
        "j_before": 0.11,
        "j_after": 0.08,
        "j_delta": -0.03,
    }, agent="audit-surgeon")
    time.sleep(1)

    # ── Phase 8: Post-Incident Topology Sync ──────────────────────────
    print("\n🌐 Phase 8: Topology Sync — Post-Remediation State")
    inject("TOPOLOGY_SYNC", {
        "resources": [
            {"id": "iam-role-PII-vault",  "resource_id": "iam-role-PII-vault",  "status": "GREEN", "type": "IAM",      "isLocked": True},
            {"id": "ec2-shadow-ai-node",  "resource_id": "ec2-shadow-ai-node",  "status": "GREEN", "type": "Compute",  "isLocked": False},
            {"id": "s3-audit-trail",      "resource_id": "s3-audit-trail",      "status": "GREEN", "type": "Storage",  "isLocked": False},
            {"id": "lambda-auth-gateway", "resource_id": "lambda-auth-gateway", "status": "GREEN", "type": "Compute",  "isLocked": False},
            {"id": "rds-user-profiles",   "resource_id": "rds-user-profiles",   "status": "GREEN", "type": "Database", "isLocked": False},
        ]
    })

    # ── Fin ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("✅ CORE SOVEREIGN TEST COMPLETE")
    print("=" * 60)
    print()
    print("🔍 Verify the following on the dashboard:")
    print("   /dashboard          → Past Events shows DRIFT + AMBER + FIXED")
    print("   /dashboard          → Forecast Horizon has Amber_Alert P=93%")
    print("   /dashboard          → Sovereign Remediations: rotate_credentials")
    print("   /dashboard/cost     → Negotiation Trace with threat/argument/synthesis")
    print("   /dashboard/copilot  → Explainability Feed with full narrative chain")
    print("   /dashboard/copilot  → J-Score bar shifted to w_R=85% / w_C=15%")
    print("   /dashboard/findings → Iron Dome updated with PII-vault GREEN+locked")
    print("   /dashboard/logs     → NIST audit trail with FORECAST + SHUTDOWN entries")


if __name__ == "__main__":
    run_sovereign_core_test()
