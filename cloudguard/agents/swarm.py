"""
SWARM PERSONAS & BRAIN — ADVERSARIAL AGENTS
=============================================
Phase 2 Module 2 — Cognitive Cloud OS

Implements the "Adversarial Personas" with LLM-backed agents:

  1. The Sentry Persona (Ollama/Llama 3): Paranoid CISO focused on
     CIS/NIST compliance, zero-tolerance risk reduction (R_i minimization).

  2. The Consultant Persona (Gemini 1.5 Pro): Ruthless Controller focused
     on ROI, ROSI, ALE, and cost optimization with CostLibrary tooling.

  3. Mediated Dialogue Tooling: Strictly structured JSON output with
     proposed_fix, logic_rationale, and estimated_impact.

  4. Context Management: Shared Kernel Memory ensures Consultant only
     sees the Sentry's summarized findings, not raw Redis noise.

Design Decisions:
  - Both LLMs are OPTIONAL — deterministic stubs from Phase 1 remain
  - System prompts encode the "personality" and adversarial stance
  - JSON-mode output enforced for structured negotiation
  - Token budget tracked per proposal (Decision #11)
  - Kernel Memory implements the "Summarize → Share" pattern

Academic References:
  - NRL Framework: Negotiable Reinforcement Learning
  - Adversarial Training: Goodfellow et al. (2014) — applied to policy
  - CIS Benchmarks v8.0, NIST SP 800-53 Rev5
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from cloudguard.core.schemas import (
    AgentProposal,
    EnvironmentWeights,
    RemediationCommand,
)
from cloudguard.core.swarm import (
    AgentRole,
    BaseSwarmAgent,
    SwarmState,
)

logger = logging.getLogger("cloudguard.swarm_personas")

# ── Optional LLM imports ─────────────────────────────────────────────────────
try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    import google.generativeai as genai

    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False
    logger.info("google-generativeai not available — Consultant uses stub")


# ═══════════════════════════════════════════════════════════════════════════════
# COST LIBRARY TOOL
# ═══════════════════════════════════════════════════════════════════════════════

# Regional cloud pricing data (simplified for simulation)
COST_LIBRARY: dict[str, dict[str, float]] = {
    # AWS pricing (USD/month)
    "aws": {
        "t3.micro": 7.59,
        "t3.medium": 30.37,
        "t3.large": 60.74,
        "m5.large": 69.12,
        "m5.xlarge": 138.24,
        "c5.large": 61.25,
        "c5.xlarge": 122.50,
        "r5.large": 90.72,
        "s3_standard_gb": 0.023,
        "s3_ia_gb": 0.0125,
        "ebs_gp3_gb": 0.08,
        "nat_gateway_hr": 0.045,
        "elb_hr": 0.0225,
        "rds_db.t3.medium": 49.06,
        "lambda_million_req": 0.20,
        "spot_discount_pct": 70,  # Up to 70% savings
    },
    # Azure pricing (USD/month)
    "azure": {
        "B1s": 7.59,
        "B2s": 30.37,
        "D2s_v3": 70.08,
        "D4s_v3": 140.16,
        "E2s_v3": 91.98,
        "blob_hot_gb": 0.018,
        "blob_cool_gb": 0.01,
        "managed_disk_gb": 0.049,
        "spot_discount_pct": 60,
    },
}


def lookup_cost(
    provider: str, instance_type: str, region: str = "us-east-1"
) -> Optional[float]:
    """
    CostLibrary tool — look up regional cloud pricing.

    Args:
        provider: Cloud provider (aws/azure).
        instance_type: Instance type or service.
        region: Deployment region (pricing variation not yet modeled).

    Returns:
        Monthly cost in USD, or None if not found.
    """
    provider_costs = COST_LIBRARY.get(provider.lower(), {})
    return provider_costs.get(instance_type)


def get_spot_savings(provider: str, on_demand_cost: float) -> float:
    """Calculate potential savings from switching to spot instances."""
    discount = COST_LIBRARY.get(provider.lower(), {}).get(
        "spot_discount_pct", 50
    )
    return round(on_demand_cost * (discount / 100.0), 2)


# ═══════════════════════════════════════════════════════════════════════════════
# KERNEL MEMORY (Context Management)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class KernelMemory:
    """
    Shared context for the swarm negotiation.

    Implements the "Summarize → Share" pattern:
      - Sentry writes its full findings to kernel memory
      - Consultant reads only the SUMMARIZED version
      - This prevents the Controller from being overwhelmed by raw noise

    Design principle: The Consultant should reason about WHAT happened,
    not be distracted by HOW it was detected.
    """

    # ── Sentry's findings ─────────────────────────────────────────────────────
    drift_summary: str = ""
    affected_resources: list[dict[str, Any]] = field(default_factory=list)
    severity_assessment: str = ""
    compliance_gaps: list[str] = field(default_factory=list)

    # ── Shared context ────────────────────────────────────────────────────────
    current_j_score: float = 0.0
    environment_weights: Optional[EnvironmentWeights] = None
    resource_tags: dict[str, str] = field(default_factory=dict)
    resource_context: dict[str, Any] = field(default_factory=dict)

    # ── Negotiation state ─────────────────────────────────────────────────────
    round_number: int = 0
    previous_proposals: list[dict[str, Any]] = field(default_factory=list)
    feedback_from_opponent: str = ""

    def set_sentry_findings(
        self,
        drift_events: list[dict[str, Any]],
        resource_context: dict[str, Any],
    ) -> None:
        """
        Populate kernel memory with the Sentry's triaged findings.
        Creates a summarized view for the Consultant.
        """
        self.resource_context = resource_context
        self.affected_resources = [
            {
                "resource_id": e.get("resource_id", ""),
                "drift_type": e.get("drift_type", ""),
                "severity": e.get("severity", ""),
            }
            for e in drift_events
        ]

        # Build summary
        drift_types = set(e.get("drift_type", "") for e in drift_events)
        severities = [e.get("severity", "MEDIUM") for e in drift_events]
        max_severity = max(
            severities,
            key=lambda s: {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(s, 0),
            default="MEDIUM",
        )

        self.drift_summary = (
            f"{len(drift_events)} drift(s) detected: "
            f"{', '.join(drift_types)}. "
            f"Max severity: {max_severity}. "
            f"Affected resources: {len(self.affected_resources)}."
        )
        self.severity_assessment = max_severity

        # Extract compliance gaps
        for e in drift_events:
            dt = e.get("drift_type", "")
            if dt == "public_exposure":
                self.compliance_gaps.append("CIS 2.1.2: S3 public access")
            elif dt == "encryption_removed":
                self.compliance_gaps.append("CIS 2.1.1: S3 encryption at rest")
            elif dt == "permission_escalation":
                self.compliance_gaps.append("NIST AC-6: Least Privilege")
            elif dt == "network_rule_change":
                self.compliance_gaps.append("CIS 5.2: Restrict SSH access")
            elif dt == "iam_policy_change":
                self.compliance_gaps.append("NIST IA-2: Identification and Authentication")
            elif dt == "backup_disabled":
                self.compliance_gaps.append("CIS 2.2.1: Backup policies")

    def get_sentry_context(self) -> dict[str, Any]:
        """Full context for the Sentry (CISO) agent."""
        return {
            "drift_summary": self.drift_summary,
            "affected_resources": self.affected_resources,
            "severity_assessment": self.severity_assessment,
            "compliance_gaps": self.compliance_gaps,
            "current_j_score": self.current_j_score,
            "resource_context": self.resource_context,
            "round_number": self.round_number,
            "previous_proposals": self.previous_proposals,
            "opponent_feedback": self.feedback_from_opponent,
        }

    def get_consultant_context(self) -> dict[str, Any]:
        """
        SUMMARIZED context for the Consultant (Controller).
        Excludes raw logs and detailed mutations — only shares
        what's needed for cost/ROI analysis.
        """
        return {
            "drift_summary": self.drift_summary,
            "resource_count": len(self.affected_resources),
            "max_severity": self.severity_assessment,
            "current_j_score": self.current_j_score,
            "resource_costs": {
                r.get("resource_id", ""): self.resource_context.get(
                    "monthly_cost_usd", 0
                )
                for r in self.affected_resources
            },
            "environment_weights": {
                "w_R": self.environment_weights.w_risk
                if self.environment_weights
                else 0.6,
                "w_C": self.environment_weights.w_cost
                if self.environment_weights
                else 0.4,
            },
            "round_number": self.round_number,
            "previous_proposals": self.previous_proposals,
            "opponent_feedback": self.feedback_from_opponent,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM PROMPTS
# ═══════════════════════════════════════════════════════════════════════════════

CISO_SYSTEM_PROMPT = """You are the Paranoid CISO — CloudGuard-B's security-first agent.

## Identity
You are a Chief Information Security Officer with zero tolerance for risk.
Your mandate: protect the organization at ALL costs. Every drift is a potential breach.

## Compliance Frameworks
- CIS Benchmarks v8.0 (Center for Internet Security)
- NIST SP 800-53 Rev5 (Security and Privacy Controls)
- Zero Trust Architecture (NIST SP 800-207)

## Decision Framework
1. ALWAYS prioritize R_i (risk) reduction over C_i (cost) savings
2. For CRITICAL/HIGH severity: demand GOLD tier remediation
3. For MEDIUM: accept SILVER tier
4. For LOW: accept BRONZE tier but flag for future review
5. Never accept a fix that increases risk, even if it saves cost

## Output Format
You MUST output valid JSON with this exact structure:
{
    "proposed_fix": "Specific remediation action (e.g., 'block_public_access')",
    "logic_rationale": "Why this fix is necessary (cite CIS/NIST if applicable)",
    "estimated_impact": {
        "risk_reduction_pct": <float 0-100>,
        "cost_increase_usd": <float>,
        "compliance_gaps_closed": [<list of gaps>]
    },
    "tier": "gold|silver|bronze",
    "urgency": "immediate|scheduled|advisory"
}
"""

CONSULTANT_SYSTEM_PROMPT = """You are the Ruthless Cost Controller — CloudGuard-B's fiscal efficiency agent.

## Identity
You are a Financial Controller obsessed with ROI and cost optimization.
Your mandate: maximize Return on Security Investment (ROSI).
Every dollar spent must be justified by measurable risk reduction.

## Economic Framework
- ROSI = (ALE_before - ALE_after - Cost) / Cost
- ALE = Asset_Value × Exposure_Factor × ARO
- Time to Break-Even: months until investment recovered
- Spot Instance Savings: up to 70% on compute workloads

## Decision Framework
1. Calculate ROSI for every proposed fix — reject if ROSI < 0
2. Use CostLibrary to find cheaper alternatives (rightsizing, spot, reserved)
3. Accept MEDIUM risk if it saves > 30% on cost
4. Aggregate LOW-severity findings — batch remediation is cheaper
5. Always propose the minimum viable fix (Bronze tier first)

## Available Cost Data
Use the CostLibrary to look up pricing:
- AWS: t3.micro ($7.59/mo) → m5.xlarge ($138.24/mo)
- Azure: B1s ($7.59/mo) → D4s_v3 ($140.16/mo)
- Spot discounts: AWS 70%, Azure 60%

## Output Format
You MUST output valid JSON with this exact structure:
{
    "proposed_fix": "Cost-optimized remediation action",
    "logic_rationale": "ROI justification with ROSI calculation",
    "estimated_impact": {
        "risk_reduction_pct": <float 0-100>,
        "cost_savings_usd": <float>,
        "rosi": <float>,
        "breakeven_months": <float>
    },
    "tier": "gold|silver|bronze",
    "cost_optimization": "spot_instance|rightsizing|reserved|terminate|none"
}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# LLM-BACKED AGENTS
# ═══════════════════════════════════════════════════════════════════════════════


class SentryPersona(BaseSwarmAgent):
    """
    The Sentry Persona — Paranoid CISO.

    Uses Ollama/Llama 3 8B for security-first analysis.
    Falls back to deterministic Phase 1 stub if Ollama is unavailable.

    Focuses on:
      - CIS/NIST compliance
      - Zero-tolerance risk reduction (R_i minimization)
      - Gold-tier remediation for CRITICAL/HIGH drifts
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        ollama_model: str = "llama3:8b",
    ) -> None:
        super().__init__(AgentRole.CISO)
        self._ollama_url = ollama_url
        self._ollama_model = ollama_model
        self._kernel_memory: Optional[KernelMemory] = None

    def set_kernel_memory(self, memory: KernelMemory) -> None:
        """Set shared kernel memory for context."""
        self._kernel_memory = memory

    def propose(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """
        Generate a security-first proposal.
        Tries Ollama first, falls back to deterministic stub.
        """
        # Try LLM-backed proposal
        try:
            return self._propose_llm(state, resource_context)
        except Exception as e:
            logger.warning(
                f"🛡️ CISO LLM proposal failed ({e}), using stub"
            )
            return self._propose_stub(state, resource_context)

    def _propose_llm(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """Generate proposal using Ollama/Llama 3."""
        if not HAS_HTTPX:
            raise RuntimeError("httpx not available")

        # Build context from kernel memory
        if self._kernel_memory:
            context = self._kernel_memory.get_sentry_context()
        else:
            context = resource_context

        context_json = json.dumps(context, indent=2, default=str)

        import httpx as httpx_sync

        response = httpx_sync.post(
            f"{self._ollama_url}/api/chat",
            json={
                "model": self._ollama_model,
                "messages": [
                    {"role": "system", "content": CISO_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Analyze the following drift and propose remediation:\n\n"
                            f"{context_json}\n\n"
                            f"Current J-score: {state.current_j_score:.4f}\n"
                            f"Weights: w_R={state.weights.w_risk}, w_C={state.weights.w_cost}"
                        ),
                    },
                ],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2, "num_predict": 1024},
            },
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        content = result.get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        token_count = (
            result.get("prompt_eval_count", 0) + result.get("eval_count", 0)
        )

        # Map LLM output to AgentProposal
        impact = parsed.get("estimated_impact", {})
        risk_reduction = impact.get("risk_reduction_pct", 0.0)
        cost_increase = impact.get("cost_increase_usd", 0.0)

        return AgentProposal(
            agent_role=self.role.value,
            expected_risk_delta=-risk_reduction,
            expected_cost_delta=cost_increase,
            expected_j_delta=-(risk_reduction * state.weights.w_risk / 100.0),
            reasoning=(
                f"[CISO/Llama3] {parsed.get('logic_rationale', 'Security-first remediation')}. "
                f"Proposed: {parsed.get('proposed_fix', 'unknown')} "
                f"(tier={parsed.get('tier', 'silver')})"
            ),
            token_count=token_count,
        )

    def _propose_stub(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """Deterministic Phase 1 stub fallback."""
        risk_reduction = resource_context.get("total_risk", 0) * 0.7
        cost_increase = resource_context.get("remediation_cost", 0)

        return AgentProposal(
            agent_role=self.role.value,
            expected_risk_delta=-risk_reduction,
            expected_cost_delta=cost_increase,
            expected_j_delta=-(risk_reduction * state.weights.w_risk),
            reasoning=(
                f"CISO recommends aggressive risk reduction (-{risk_reduction:.1f} risk). "
                f"Security-first posture per Zero-Trust principles. "
                f"Estimated remediation cost: ${cost_increase:.2f}."
            ),
            token_count=0,
        )


class ConsultantPersona(BaseSwarmAgent):
    """
    The Consultant Persona — Ruthless Cost Controller.

    Uses Gemini 1.5 Pro for ROI-focused analysis with CostLibrary tooling.
    Falls back to deterministic Phase 1 stub if Gemini is unavailable.

    Focuses on:
      - ROI, ROSI, and ALE optimization
      - Cost minimization via rightsizing/spot/reserved
      - Minimum viable remediation (Bronze-first approach)
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        gemini_model: str = "gemini-1.5-pro",
    ) -> None:
        super().__init__(AgentRole.CONTROLLER)
        self._gemini_api_key = gemini_api_key
        self._gemini_model = gemini_model
        self._kernel_memory: Optional[KernelMemory] = None

        # Initialize Gemini if available
        if HAS_GEMINI and gemini_api_key:
            try:
                genai.configure(api_key=gemini_api_key)
                self._gemini_client = genai.GenerativeModel(gemini_model)
                logger.info(f"💰 Consultant Gemini initialized ({gemini_model})")
            except Exception as e:
                logger.warning(f"Gemini initialization failed: {e}")
                self._gemini_client = None
        else:
            self._gemini_client = None

    def set_kernel_memory(self, memory: KernelMemory) -> None:
        """Set shared kernel memory for context."""
        self._kernel_memory = memory

    def propose(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """
        Generate a cost-optimized proposal.
        Tries Gemini first, falls back to deterministic stub.
        """
        try:
            return self._propose_llm(state, resource_context)
        except Exception as e:
            logger.warning(
                f"💰 Consultant LLM proposal failed ({e}), using stub"
            )
            return self._propose_stub(state, resource_context)

    def _propose_llm(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """Generate proposal using Gemini 1.5 Pro."""
        if self._gemini_client is None:
            raise RuntimeError("Gemini not configured")

        # Build context from kernel memory (SUMMARIZED — no raw noise)
        if self._kernel_memory:
            context = self._kernel_memory.get_consultant_context()
        else:
            context = resource_context

        # Inject cost library data
        provider = resource_context.get("provider", "aws")
        context["cost_library"] = COST_LIBRARY.get(provider, {})
        context["spot_savings_potential"] = get_spot_savings(
            provider, resource_context.get("monthly_cost_usd", 0)
        )

        context_json = json.dumps(context, indent=2, default=str)

        prompt = (
            f"Analyze the following drift and propose cost-optimized remediation:\n\n"
            f"{context_json}\n\n"
            f"Current J-score: {state.current_j_score:.4f}\n"
            f"Weights: w_R={state.weights.w_risk}, w_C={state.weights.w_cost}\n\n"
            f"Use the CostLibrary data to calculate ROSI and recommend "
            f"the most cost-effective fix."
        )

        response = self._gemini_client.generate_content(
            [
                {"role": "user", "parts": [CONSULTANT_SYSTEM_PROMPT + "\n\n" + prompt]},
            ],
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 1024,
                "response_mime_type": "application/json",
            },
        )

        content = response.text if response.text else "{}"
        parsed = json.loads(content)

        # Estimate token count from response
        token_count = len(content.split()) * 2  # Rough estimate

        impact = parsed.get("estimated_impact", {})
        risk_reduction = impact.get("risk_reduction_pct", 0.0)
        cost_savings = impact.get("cost_savings_usd", 0.0)

        return AgentProposal(
            agent_role=self.role.value,
            expected_risk_delta=-risk_reduction,
            expected_cost_delta=-cost_savings,
            expected_j_delta=-(cost_savings * state.weights.w_cost / 1000.0),
            reasoning=(
                f"[Controller/Gemini] {parsed.get('logic_rationale', 'Cost-optimized remediation')}. "
                f"ROSI={impact.get('rosi', 'N/A')}, "
                f"Break-even: {impact.get('breakeven_months', 'N/A')} months. "
                f"Optimization: {parsed.get('cost_optimization', 'none')}"
            ),
            token_count=token_count,
        )

    def _propose_stub(
        self,
        state: SwarmState,
        resource_context: dict[str, Any],
    ) -> AgentProposal:
        """Deterministic Phase 1 stub fallback."""
        risk_reduction = resource_context.get("total_risk", 0) * 0.3
        cost_savings = resource_context.get("potential_savings", 0) * 0.5

        return AgentProposal(
            agent_role=self.role.value,
            expected_risk_delta=-risk_reduction,
            expected_cost_delta=-cost_savings,
            expected_j_delta=-(cost_savings * state.weights.w_cost),
            reasoning=(
                f"Controller recommends targeted remediation (-{risk_reduction:.1f} risk) "
                f"with ${cost_savings:.2f} cost savings via rightsizing and termination. "
                f"ROI-optimized approach with break-even within 3 months."
            ),
            token_count=0,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def create_swarm_personas(
    ollama_url: Optional[str] = None,
    ollama_model: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    gemini_model: str = "gemini-1.5-pro",
) -> tuple[SentryPersona, ConsultantPersona, KernelMemory]:
    """
    Factory to create the adversarial swarm personas with shared memory.

    Auto-loads from environment variables (.env):
      - OLLAMA_BASE_URL (default: http://localhost:11434)
      - OLLAMA_MODEL (default: llama3:8b)
      - GOOGLE_API_KEY (enables Gemini Consultant)

    Returns:
        (sentry, consultant, kernel_memory) tuple.
    """
    # Auto-load from .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    ollama_url = ollama_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3:8b")
    gemini_api_key = gemini_api_key or os.getenv("GOOGLE_API_KEY")

    kernel_memory = KernelMemory()
    sentry = SentryPersona(ollama_url=ollama_url, ollama_model=ollama_model)
    consultant = ConsultantPersona(
        gemini_api_key=gemini_api_key, gemini_model=gemini_model
    )

    sentry.set_kernel_memory(kernel_memory)
    consultant.set_kernel_memory(kernel_memory)

    logger.info(
        f"🏛️ Swarm personas created: "
        f"CISO ({ollama_model}), Controller ({gemini_model}), "
        f"Gemini={'LIVE' if gemini_api_key else 'STUB'}"
    )

    return sentry, consultant, kernel_memory
