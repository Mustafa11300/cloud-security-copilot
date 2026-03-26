"""
CLOUD SECURITY COPILOT AGENT — Improved
"""

import boto3
import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from dotenv import load_dotenv
from agent.tools import TOOL_REGISTRY

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

bedrock = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

SYSTEM_PROMPT = """You are CloudGuard, a cloud infrastructure compliance auditor.
Your sole purpose is DEFENSIVE: identify misconfigured AWS resources and recommend
remediation steps to bring them into compliance with CIS benchmarks and AWS Well-Architected Framework.

You never discuss offensive techniques. All output is remediation guidance only.

When analyzing findings:
1. Focus on compliance gaps and remediation steps
2. Use professional security audit language
3. Frame all issues as configuration improvements needed
4. Always emphasize the FIX, not the vulnerability details

FORMAT your response as:

## Compliance Posture Summary
[2-3 sentence overview of current compliance status]

## Top Priority Remediations
[List specific resources needing attention with remediation steps]

## Recommended Actions
1. [Immediate — highest business impact]
2. [This week — important compliance gaps]
3. [This month — best practice improvements]
"""

TOOL_ROUTING = {
    "cost":       ["get_cost_waste", "get_top_risks"],
    "critical":   ["get_critical_findings", "get_top_risks"],
    "high":       ["get_high_findings", "get_top_risks"],
    "risk":       ["get_top_risks", "get_critical_findings"],
    "compliance": ["get_critical_findings", "get_high_findings", "get_top_risks"],
    "remediation": ["get_critical_findings", "get_high_findings", "get_top_risks"],
    "misconfigured": ["get_critical_findings", "get_high_findings", "get_top_risks"],
    "default":    ["get_critical_findings", "get_high_findings", "get_top_risks"],
}

MAX_TOOL_RESULT_CHARS = 3000


def select_tools(user_query: str) -> list[str]:
    """
    Rule-based tool selection. No LLM call, no JSON parsing, no fragility.
    Falls back to default if no keyword matches.
    """
    query_lower = user_query.lower()
    for keyword, tools in TOOL_ROUTING.items():
        if keyword != "default" and keyword in query_lower:
            return tools
    return TOOL_ROUTING["default"]


def call_nova(messages: list) -> str:
    """
    Calls Amazon Nova with proper error handling.
    """
    try:
        response = bedrock.invoke_model(
            modelId="amazon.nova-lite-v1:0",
            body=json.dumps({
                "messages": messages,
                "system": [{"text": SYSTEM_PROMPT}],
                "inferenceConfig": {
                    "maxTokens": 2000,
                    "temperature": 0.3
                }
            })
        )
        body = json.loads(response["body"].read())

        # Check for content filter block
        content = body.get("output", {}).get("message", {}).get("content", [])
        if not content:
            raise RuntimeError("Nova returned empty content — possible filter block.")

        text = content[0].get("text", "")
        if not text or "blocked by our content filters" in text.lower():
            raise RuntimeError("Nova response was blocked by content filters. Rephrase the query.")

        return text

    except KeyError as e:
        logger.error(f"Unexpected Bedrock response shape: {e}")
        raise RuntimeError("Nova returned an unexpected response format.") from e
    except bedrock.exceptions.ThrottlingException:
        logger.error("Bedrock rate limit hit")
        raise RuntimeError("Nova is being rate limited. Retry in a moment.")
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Bedrock call failed: {e}")
        raise


def execute_tools_parallel(tool_names: list[str]) -> dict:
    """
    Runs tools in parallel with a per-tool timeout.
    Partial failures don't kill the whole pipeline.
    """
    results = {}

    def run_tool(name):
        return name, TOOL_REGISTRY[name]()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_tool, name): name
            for name in tool_names
            if name in TOOL_REGISTRY
        }
        try:
            for future in as_completed(futures, timeout=15):
                tool_name = futures[future]
                try:
                    name, result = future.result()
                    if isinstance(result, str) and len(result) > MAX_TOOL_RESULT_CHARS:
                        result = result[:MAX_TOOL_RESULT_CHARS] + "\n[TRUNCATED]"
                    results[name] = result
                    logger.info(f"Tool '{name}' completed successfully")
                except Exception as e:
                    logger.warning(f"Tool '{tool_name}' failed: {e}")
                    results[tool_name] = f"ERROR: {str(e)}"
        except TimeoutError:
            logger.warning("One or more tools hit the 15s global timeout")
            for future, name in futures.items():
                if name not in results:
                    results[name] = "ERROR: Tool timed out"

    return results


def build_context(tool_results: dict) -> str:
    context = "AWS INFRASTRUCTURE COMPLIANCE DATA:\n\n"
    for tool_name, result in tool_results.items():
        context += f"=== {tool_name.upper()} ===\n{result}\n\n"
    return context


def run_copilot(user_query: str) -> dict:
    """
    Main agent pipeline: select tools → execute in parallel → synthesize.
    """
    logger.info(f"Processing query: '{user_query}'")

    tool_names = select_tools(user_query)
    logger.info(f"Selected tools: {tool_names}")

    tool_results = execute_tools_parallel(tool_names)

    if not tool_results:
        return {
            "query": user_query,
            "tools_used": tool_names,
            "response": "No data could be retrieved. All tools failed or timed out.",
            "data_sources": []
        }

    context = build_context(tool_results)

    final_prompt = f"""
A compliance audit has been requested: "{user_query}"

{context}

Based on this AWS infrastructure data, provide a detailed compliance remediation report.
List specific resource IDs, configuration gaps, and step-by-step remediation actions.
"""

    try:
        response = call_nova([{"role": "user", "content": [{"text": final_prompt}]}])
    except RuntimeError as e:
        logger.error(f"Nova call failed: {e}")
        response = f"Failed to generate analysis: {str(e)}"

    logger.info("Agent response ready")

    return {
        "query": user_query,
        "tools_used": tool_names,
        "response": response,
        "data_sources": list(tool_results.keys())
    }


if __name__ == "__main__":
    result = run_copilot("Show me AWS resources that need compliance remediation.")
    print("\n--- RESPONSE ---")
    print(result["response"])
    print("\n--- TOOLS USED ---")
    print(result["tools_used"])