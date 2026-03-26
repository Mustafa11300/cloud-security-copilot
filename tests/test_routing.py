# tests/test_routing.py
from agent.copilot import select_tools

def test_cost_query_routes_correctly():
    tools = select_tools("what's causing cost waste?")
    assert "get_cost_waste" in tools

def test_critical_query_routes_correctly():
    tools = select_tools("show me critical findings")
    assert "get_critical_findings" in tools

def test_unknown_query_uses_defaults():
    tools = select_tools("what is the meaning of life")
    assert tools == ["get_critical_findings", "get_high_findings", "get_top_risks"]