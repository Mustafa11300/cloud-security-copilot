"""
UNIVERSAL RESOURCE SCHEMA & CROSS-CLOUD TRUST
==============================================
Subsystem 1 — Phase 1 Foundation

Implements a UniversalResource schema supporting:
  • AWS: EC2, S3, IAM, EKS
  • Azure: Blobs, OIDC

Models Cross-Cloud OIDC trust relationships to test
"Identity-Centric" security (e.g., an AWS Lambda authorized
to access Azure Storage via federated OIDC tokens).

Academic Basis:
  - Identity-Centric Zero-Trust (NIST SP 800-207, 2020)
  - Cross-Cloud Federation (RFC 7523 — JWT Profile for OAuth 2.0)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMERATIONS
# ═══════════════════════════════════════════════════════════════════════════════

class CloudProvider(str, Enum):
    """Supported cloud providers."""
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"          # Reserved for Phase 3 expansion


class ResourceType(str, Enum):
    """Canonical resource types across all providers."""
    # AWS Resources
    EC2 = "EC2"
    S3 = "S3"
    IAM_USER = "IAM_USER"
    IAM_ROLE = "IAM_ROLE"
    EKS_CLUSTER = "EKS_CLUSTER"
    EKS_POD = "EKS_POD"
    LAMBDA = "LAMBDA"
    SECURITY_GROUP = "SECURITY_GROUP"
    RDS = "RDS"
    # Azure Resources
    AZURE_BLOB = "AZURE_BLOB"
    AZURE_OIDC = "AZURE_OIDC"
    AZURE_VM = "AZURE_VM"
    AZURE_AKS = "AZURE_AKS"


class Severity(str, Enum):
    """Finding severity levels aligned with CVSS qualitative ratings."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class DriftType(str, Enum):
    """Types of configuration drift detectable by the simulation."""
    PERMISSION_ESCALATION = "permission_escalation"
    PUBLIC_EXPOSURE = "public_exposure"
    ENCRYPTION_REMOVED = "encryption_removed"
    NETWORK_RULE_CHANGE = "network_rule_change"
    IAM_POLICY_CHANGE = "iam_policy_change"
    RESOURCE_CREATED = "resource_created"
    RESOURCE_DELETED = "resource_deleted"
    TAG_REMOVED = "tag_removed"
    BACKUP_DISABLED = "backup_disabled"
    COST_SPIKE = "cost_spike"


class RemediationTier(str, Enum):
    """Remediation quality tiers (Decision #18: Gold/Silver/Bronze)."""
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"


# ═══════════════════════════════════════════════════════════════════════════════
# CORE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class UniversalResource(BaseModel):
    """
    Universal Resource Schema
    -------------------------
    Single data model representing ANY cloud resource across AWS and Azure.
    Every resource in the simulation is an instance of this schema.

    Design Decisions:
      1. `provider` + `resource_type` give a unique canonical type
      2. `properties` dict holds provider-specific fields (EC2 CPU, S3 encryption, etc.)
      3. `trust_chain` links cross-cloud identity relationships
      4. `drift_history` tracks temporal configuration changes

    This schema is the single source of truth for the simulation state.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    resource_id: str = Field(
        default_factory=lambda: f"res-{uuid.uuid4().hex[:12]}",
        description="Unique identifier across all providers"
    )
    provider: CloudProvider = Field(
        description="Cloud provider owning this resource"
    )
    resource_type: ResourceType = Field(
        description="Canonical resource type"
    )
    region: str = Field(
        default="us-east-1",
        description="Deployment region (AWS region or Azure location)"
    )
    name: str = Field(
        default="",
        description="Human-readable name or tag"
    )

    # ── State ─────────────────────────────────────────────────────────────────
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific configuration properties"
    )
    tags: dict[str, str] = Field(
        default_factory=dict,
        description="Resource tags for governance and cost allocation"
    )
    is_compliant: bool = Field(
        default=True,
        description="Current compliance status based on last scan"
    )
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Composite risk score (0=safe, 100=critical)"
    )
    monthly_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Monthly cost in USD"
    )

    # ── Telemetry ─────────────────────────────────────────────────────────────
    cpu_utilization: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="CPU utilization percentage (for compute resources)"
    )
    memory_utilization: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Memory utilization percentage (for compute resources)"
    )
    network_bytes_in: float = Field(
        default=0.0,
        ge=0.0,
        description="Inbound network bytes (last tick)"
    )
    network_bytes_out: float = Field(
        default=0.0,
        ge=0.0,
        description="Outbound network bytes (last tick)"
    )

    # ── Temporal ──────────────────────────────────────────────────────────────
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When this resource was created in the simulation"
    )
    last_modified: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last state change timestamp"
    )
    drift_history: list[DriftEvent] = Field(
        default_factory=list,
        description="Ordered list of drift events affecting this resource"
    )

    # ── Cross-Cloud Trust ─────────────────────────────────────────────────────
    trust_chain: list[OIDCTrustLink] = Field(
        default_factory=list,
        description="OIDC trust relationships (cross-cloud identity federation)"
    )

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, v: str) -> str:
        """Ensure resource IDs are non-empty and reasonably formatted."""
        if not v or len(v) < 3:
            raise ValueError("resource_id must be at least 3 characters")
        return v

    def apply_drift(self, drift: DriftEvent) -> None:
        """
        Apply a drift event to this resource.
        Updates properties, records in history, and marks non-compliant.
        """
        self.drift_history.append(drift)
        self.is_compliant = False
        self.last_modified = datetime.now(timezone.utc)

        # Apply property mutations from the drift
        for key, value in drift.mutations.items():
            self.properties[key] = value

    def to_simulation_dict(self) -> dict[str, Any]:
        """Serialize for Redis pub/sub and PostgreSQL storage."""
        return self.model_dump(mode="json")


class DriftEvent(BaseModel):
    """
    Represents a single configuration drift detected in the simulation.
    Published to Redis `cloudguard_events` channel when detected.
    Triggers Burst Mode in the TemporalClock for MTTR measurement.
    """

    event_id: str = Field(
        default_factory=lambda: f"drift-{uuid.uuid4().hex[:8]}",
        description="Unique drift event identifier"
    )
    trace_id: str = Field(
        default_factory=lambda: f"trace-{uuid.uuid4().hex[:12]}",
        description="Distributed trace ID for event correlation"
    )
    resource_id: str = Field(
        description="Resource affected by this drift"
    )
    drift_type: DriftType = Field(
        description="Category of drift detected"
    )
    severity: Severity = Field(
        default=Severity.MEDIUM,
        description="Severity of this drift event"
    )
    description: str = Field(
        default="",
        description="Human-readable description of the drift"
    )
    mutations: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value pairs of properties that changed"
    )
    previous_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Previous values before drift (for rollback)"
    )
    timestamp_tick: int = Field(
        default=0,
        description="Simulation tick when this drift was detected"
    )
    timestamp_utc: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Wall-clock time of detection"
    )
    is_false_positive: bool = Field(
        default=False,
        description="Marked True if classified as false positive (Sahay & Soto, 2026)"
    )
    cumulative_drift_score: float = Field(
        default=0.0,
        description="Cumulative drift impact score for SIEM correlation"
    )

    # ── Redis Pub/Sub payload ─────────────────────────────────────────────────
    environment_weights: EnvironmentWeights = Field(
        default_factory=lambda: EnvironmentWeights(),
        description="Current optimization weights w_R (risk) and w_C (cost)"
    )


class EnvironmentWeights(BaseModel):
    """
    Multi-objective optimization weights for the equilibrium function J.
    J = min Σ (w_R · R_i + w_C · C_i)

    These weights are published with every event to Redis so agents
    can calibrate their proposals against the current governance posture.
    """
    w_risk: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Risk weight (w_R) — higher means security-first"
    )
    w_cost: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Cost weight (w_C) — higher means cost-first"
    )

    @field_validator("w_cost")
    @classmethod
    def weights_must_sum_to_one(cls, v: float, info) -> float:
        """Ensure w_R + w_C = 1.0 (constraint for valid optimization)."""
        w_risk = info.data.get("w_risk", 0.6)
        if abs(w_risk + v - 1.0) > 1e-6:
            raise ValueError(f"w_risk ({w_risk}) + w_cost ({v}) must equal 1.0")
        return v


class OIDCTrustLink(BaseModel):
    """
    Cross-Cloud OIDC Trust Relationship
    ------------------------------------
    Models federated identity trust between cloud providers.
    Example: AWS Lambda → Azure Storage via OIDC token exchange.

    This enables testing "Identity-Centric" security where an
    AWS workload is authorized to access Azure resources through
    OIDC federation (RFC 7523).
    """

    trust_id: str = Field(
        default_factory=lambda: f"trust-{uuid.uuid4().hex[:8]}",
        description="Unique trust relationship identifier"
    )
    source_provider: CloudProvider = Field(
        description="Provider where the identity originates"
    )
    source_resource_id: str = Field(
        description="Resource ID of the identity source (e.g., Lambda ARN)"
    )
    target_provider: CloudProvider = Field(
        description="Provider where the target resource lives"
    )
    target_resource_id: str = Field(
        description="Resource ID of the target (e.g., Azure Blob container)"
    )
    oidc_issuer_url: str = Field(
        default="",
        description="OIDC issuer URL for token validation"
    )
    allowed_audiences: list[str] = Field(
        default_factory=list,
        description="Allowed audience claims in the OIDC token"
    )
    allowed_scopes: list[str] = Field(
        default_factory=list,
        description="Permitted OAuth scopes for this trust"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this trust relationship is currently active"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Expiration time for the trust (None = no expiry)"
    )

    def is_expired(self) -> bool:
        """Check if this OIDC trust has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def validate_trust(self) -> bool:
        """
        Validate that this trust relationship is secure.
        Checks: active, not expired, has audience, cross-provider.
        """
        if not self.is_active:
            return False
        if self.is_expired():
            return False
        if not self.allowed_audiences:
            return False  # No audience = overly permissive
        if self.source_provider == self.target_provider:
            return True  # Same-cloud trust is simpler
        return bool(self.oidc_issuer_url)


# ═══════════════════════════════════════════════════════════════════════════════
# SIMULATION FINDING SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

class SecurityFinding(BaseModel):
    """
    A security finding detected during a simulation scan.
    Extended from the original CloudGuard finding schema with
    additional fields for ROSI calculation and EWM weighting.
    """

    finding_id: str = Field(
        default_factory=lambda: f"finding-{uuid.uuid4().hex[:10]}",
        description="Unique finding identifier"
    )
    resource_id: str = Field(description="Resource this finding applies to")
    resource_type: ResourceType = Field(description="Type of resource")
    rule_id: str = Field(description="Rule that triggered this finding")
    title: str = Field(description="Finding title")
    description: str = Field(default="", description="Detailed description")
    severity: Severity = Field(description="CVSS-aligned severity")
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Risk score (0–100)"
    )
    remediation: str = Field(default="", description="Remediation guidance")
    business_impact: str = Field(default="", description="Business impact statement")
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── Economic fields (for ROSI/ALE calculation) ────────────────────────────
    estimated_annual_loss: float = Field(
        default=0.0,
        ge=0.0,
        description="ALE — Annualized Loss Expectancy in USD"
    )
    remediation_cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated cost to remediate in USD"
    )
    probability_of_exploit: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Probability of exploitation (0–1)"
    )

    # ── Graph centrality (for EWM/CRITIC weighting) ───────────────────────────
    dependency_centrality: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="NetworkX betweenness centrality in dependency graph"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# REMEDIATION COMMAND SCHEMA (Command Pattern — Subsystem 7)
# ═══════════════════════════════════════════════════════════════════════════════

class RemediationCommand(BaseModel):
    """
    Atomic remediation command following the Command Pattern.
    Agents output these as Python-based healing functions
    that the simulator executes directly.
    """

    command_id: str = Field(
        default_factory=lambda: f"cmd-{uuid.uuid4().hex[:8]}",
        description="Unique command identifier"
    )
    tier: RemediationTier = Field(
        default=RemediationTier.SILVER,
        description="Gold/Silver/Bronze tier (Decision #18)"
    )
    target_resource_id: str = Field(
        description="Resource this command remediates"
    )
    action: str = Field(
        description="Action verb (e.g., 'block_public_access', 'enable_encryption')"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for the remediation action"
    )
    rollback_parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters to undo this command (for branch rollback)"
    )
    estimated_risk_reduction: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Expected risk score reduction after execution"
    )
    estimated_cost_impact: float = Field(
        default=0.0,
        description="Cost impact in USD (negative = savings)"
    )
    explanation: str = Field(
        default="",
        description="Chain-of-evidence explanation (Decision #17: XAI)"
    )
    retry_count: int = Field(
        default=0,
        ge=0,
        le=3,
        description="Number of retries (Decision #19: 3 max)"
    )
    is_failed: bool = Field(
        default=False,
        description="Marked True after 3 failed retries"
    )
    failure_reason: str = Field(
        default="",
        description="Reason for failure (stored in Failed Fixes DB — Decision #20)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# BRANCH STATE SCHEMA (for StateBranchManager)
# ═══════════════════════════════════════════════════════════════════════════════

class BranchState(BaseModel):
    """
    State of a single simulation branch.
    The StateBranchManager maintains up to 3 active branches:
    Trunk, Branch_A, Branch_B.
    """

    branch_id: str = Field(
        default_factory=lambda: f"branch-{uuid.uuid4().hex[:6]}",
        description="Unique branch identifier"
    )
    name: str = Field(
        default="trunk",
        description="Branch name (trunk, branch_a, branch_b)"
    )
    parent_branch_id: Optional[str] = Field(
        default=None,
        description="Parent branch (None for trunk)"
    )
    schema_name: str = Field(
        default="",
        description="PostgreSQL schema name for isolation"
    )
    j_score: float = Field(
        default=100.0,
        description="Current J equilibrium score (0=perfect, 100=worst)"
    )
    j_score_history: list[float] = Field(
        default_factory=list,
        description="History of J scores for regression detection"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this branch is active (max 3 active)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    rolled_back: bool = Field(
        default=False,
        description="Whether this branch has been rolled back"
    )
    rollback_reason: str = Field(
        default="",
        description="Reason for rollback if applicable"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SWARM AGENT SCHEMAS
# ═══════════════════════════════════════════════════════════════════════════════

class AgentProposal(BaseModel):
    """
    A proposal from a Swarm agent (CISO or Controller).
    Contains remediation commands and the expected J impact.
    """

    proposal_id: str = Field(
        default_factory=lambda: f"prop-{uuid.uuid4().hex[:8]}"
    )
    agent_role: str = Field(
        description="Agent role: 'ciso', 'controller', or 'orchestrator'"
    )
    commands: list[RemediationCommand] = Field(
        default_factory=list,
        description="Proposed remediation commands"
    )
    expected_j_delta: float = Field(
        default=0.0,
        description="Expected change in J score (negative = improvement)"
    )
    expected_risk_delta: float = Field(
        default=0.0,
        description="Expected risk reduction"
    )
    expected_cost_delta: float = Field(
        default=0.0,
        description="Expected cost change (negative = savings)"
    )
    reasoning: str = Field(
        default="",
        description="Agent's reasoning chain (XAI)"
    )
    token_count: int = Field(
        default=0,
        description="Tokens consumed for this proposal (for budget tracking)"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Update forward references for recursive models
# ═══════════════════════════════════════════════════════════════════════════════

# Pydantic v2 handles forward references automatically via model_rebuild
UniversalResource.model_rebuild()
DriftEvent.model_rebuild()
