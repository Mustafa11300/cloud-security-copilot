# tests/test_copilot.py
from unittest.mock import patch, MagicMock
from agent.copilot import run_copilot

@patch("agent.copilot.call_nova", return_value="Mocked security summary")
@patch("agent.copilot.TOOL_REGISTRY", {
    "get_critical_findings": lambda: "2 critical S3 buckets found",
    "get_high_findings": lambda: "5 open security groups",
    "get_top_risks": lambda: "IAM over-permissioned roles",
})
def test_run_copilot_returns_expected_shape(mock_nova):
    result = run_copilot("show me critical risks")
    assert "response" in result
    assert "tools_used" in result
    assert result["response"] == "Mocked security summary"