"""
SCORE API
Endpoints that return the overall security posture score.
"""
from fastapi import APIRouter
from elastic.queries import get_findings_by_severity, get_risk_trend
from elastic.client import es

router = APIRouter()

@router.get("/")
def get_score():
    """
    Returns the current security posture score + cost health score.
    This is what the big ScoreCard components on the dashboard display.
    """
    # Get latest scan snapshot from Elasticsearch
    try:
        result = es.search(
            index="scan-history",
            body={
                "sort": [{"timestamp": "desc"}],
                "size": 1
            }
        )
        if result["hits"]["hits"]:
            latest = result["hits"]["hits"][0]["_source"]
            return {
                "security_score":    latest.get("security_score", 0),
                "cost_health_score": latest.get("cost_health_score", 0),
                "monthly_waste":     latest.get("monthly_waste_usd", 0),
                "total_findings":    latest.get("total_findings", 0),
                "critical_count":    latest.get("critical_count", 0),
                "high_count":        latest.get("high_count", 0),
                "last_scan":         latest.get("timestamp", "N/A")
            }
    except Exception as e:
        print(f"Score fetch error: {e}")

    return {
        "security_score": 0,
        "cost_health_score": 0,
        "monthly_waste": 0,
        "total_findings": 0,
        "critical_count": 0,
        "high_count": 0,
        "last_scan": "No scans yet — run bootstrap.py first"
    }

@router.get("/trend")
def get_trend(days: int = 7):
    """Returns score history for the drift/trend line chart."""
    return get_risk_trend(days)
@router.post("/scan")
async def run_scan():
    """
    Fast scan — re-runs rules on EXISTING indexed resources.
    No data generation, no full re-index. Just rules + snapshot.
    Takes ~2-3 seconds instead of 15-20 seconds.
    """
    try:
        from elastic.client import es
        from engine.rules import scan_all_resources
        from engine.scorer import generate_posture_report
        from elastic.indexer import index_findings, index_scan_snapshot

        print("⚡ Fast scan triggered...")

        # Step 1: Fetch existing resources from ES (no generation)
        result = es.search(
            index="cloud-resources",
            body={"query": {"match_all": {}}, "size": 500}
        )
        resources = [h["_source"] for h in result["hits"]["hits"]]
        print(f"   Loaded {len(resources)} existing resources")

        # Step 2: Run rules on existing resources
        findings_result = scan_all_resources(resources)

        # Step 3: Clear old findings and index new ones
        es.delete_by_query(
            index="security-findings",
            body={"query": {"match_all": {}}}
        )
        index_findings(findings_result["all_findings"])

        # Step 4: Save new snapshot (for trend chart)
        report = generate_posture_report(resources, findings_result)
        index_scan_snapshot(report)

        print("✅ Fast scan complete!")

        return {
            "status":         "success",
            "message":        "Scan completed",
            "security_score": report["security"]["security_score"],
            "total_findings": report["finding_count"],
            "monthly_waste":  report["cost"]["total_monthly_waste_usd"],
            "scanned_at":     report["generated_at"],
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}