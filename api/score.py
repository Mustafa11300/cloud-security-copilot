"""
SCORE API — ES-FREE VERSION
============================
Returns a realistic static security posture snapshot.
Elasticsearch has been removed; no external DB required.
"""
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


MOCK_SCORE = {
    "security_score": 72,
    "cost_health_score": 68,
    "monthly_waste_usd": 1240.50,
    "total_findings": 47,
    "critical_count": 3,
    "high_count": 11,
    "last_scan": "2026-04-14T05:00:00Z",
}

MOCK_TREND = [
    {"date": "2026-04-08", "security_score": 61, "cost_health_score": 60},
    {"date": "2026-04-09", "security_score": 64, "cost_health_score": 62},
    {"date": "2026-04-10", "security_score": 67, "cost_health_score": 64},
    {"date": "2026-04-11", "security_score": 65, "cost_health_score": 63},
    {"date": "2026-04-12", "security_score": 70, "cost_health_score": 66},
    {"date": "2026-04-13", "security_score": 71, "cost_health_score": 67},
    {"date": "2026-04-14", "security_score": 72, "cost_health_score": 68},
]


@router.get("/")
def get_score():
    return MOCK_SCORE


@router.get("/trend")
def get_trend(days: int = 7):
    return MOCK_TREND[-days:]


@router.post("/scan")
async def run_scan():
    """Simulate a scan run — no real AWS/ES ops."""
    return {
        "status": "success",
        "message": "Scan completed (demo mode — Elasticsearch removed)",
        "security_score": MOCK_SCORE["security_score"],
        "total_findings": MOCK_SCORE["total_findings"],
        "monthly_waste_usd": MOCK_SCORE["monthly_waste_usd"],
        "scanned_at": _now_iso(),
    }
