"""
ELASTICSEARCH QUERIES — REMOVED
=================================
Elasticsearch has been removed. These functions now return empty/mock data
so agent/tools.py continues to import without crashing but falls back
to its "no data" messaging gracefully.
"""

def get_findings_by_severity(severity: str = None) -> list:
    return []

def get_cost_waste_summary() -> dict:
    return {"waste_findings": [], "count": 0}

def get_risk_trend(days: int = 7) -> list:
    return []

def get_top_risky_resources(limit: int = 10) -> list:
    return []

def get_findings_by_resource_type() -> dict:
    return {}
