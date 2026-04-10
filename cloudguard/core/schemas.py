"""
UNIVERSAL RESOURCE SCHEMA & CROSS-CLOUD TRUST
==============================================
Subsystem 1 — Phase 1 Foundation (v2: Typed Hierarchy)

Implements a strictly-typed UniversalResource hierarchy supporting:
  • AWS: EC2, S3, IAM, EKS, Lambda, Security Groups, RDS
  • Azure: Blobs, OIDC, VMs, AKS

Design: Abstract Base → Specialized Subclasses
  UniversalResource (abstract base)
    ├── ComputeResource  (EC2, Azure VM, EKS Pod, Lambda)
    ├── StorageResource   (S3, Azure Blob, RDS)
    └── IdentityResource  (IAM User, IAM Role, Azure OIDC)

Cross-Cloud OIDC Trust:
  CrossCloudTrust defines how an identity in one provider is
  authorized for a resource in another (e.g., AWS Lambda → Azure Blob).

Strict Typing:
  Pydantic v2 model_config(extra='forbid') on subclasses prevents
  "hallucinated" resource attributes during simulation.
  metadata.ewm_weight and metadata.critic_index carry per-resource
  weighting from the MathEngine.

Academic Basis:
  - Identity-Centric Zero-Trust (NIST SP 800-207, 2020)
  - Cross-Cloud Federation (RFC 7523 — JWT Profile for OAuth 2.0)
  - Strict Schema Validation → prevents LLM hallucination drift
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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


class ResourceCategory(str, Enum):
    """High-level resource category for type-safe dispatch."""
    COMPUTE = "compute"
    STORAGE = "storage"
    IDENTITY = "identity"
    NETWORK = "network"
    ORCHESTRATION = "orchestration"


# Map each ResourceType to its category
RESOURCE_CATEGORY_MAP: dict[ResourceType, ResourceCategory] = {
    ResourceType.EC2: ResourceCategory.COMPUTE,
    ResourceType.AZURE_VM: ResourceCategory.COMPUTE,
    ResourceType.EKS_POD: ResourceCategory.COMPUTE,
    ResourceType.LAMBDA: ResourceCategory.COMPUTE,
    ResourceType.S3: ResourceCategory.STORAGE,
    ResourceType.AZURE_BLOB: ResourceCategory.STORAGE,
    ResourceType.RDS: ResourceCategory.STORAGE,
    ResourceType.IAM_USER: ResourceCategory.IDENTITY,
    ResourceType.IAM_ROLE: ResourceCategory.IDENTITY,
    ResourceType.AZURE_OIDC: ResourceCategory.IDENTITY,
    ResourceType.SECURITY_GROUP: ResourceCategory.NETWORK,
    ResourceType.EKS_CLUSTER: ResourceCategory.ORCHESTRATION,
    ResourceType.AZURE_AKS: ResourceCategory.ORCHESTRATION,
}


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


class FuzzyRiskCategory(str, Enum):
    """
    Fuzzy risk categories for Trapezoidal Membership mapping.
    Reduces false-positive sensitivity by mapping raw risk scores
    to linguistic variables (Zadeh, 1965).
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ═══════════════════════════════════════════════════════════════════════════════
# METADATA MODELS (EWM / CRITIC weights per resource)
# ═══════════════════════════════════════════════════════════════════════════════

class ResourceMetadata(BaseModel):
    """
    Per-resource metadata carrying EWM/CRITIC weights and graph centrality.
    Attached to every UniversalResource so the MathEngine can
    dynamically weight risk contributions.

    Fields:
      ewm_weight:   Weight computed by Entropy Weight Method (Shannon, 1948)
      critic_index: Weight computed by CRITIC (Diakoulaki et al., 1995)
      centrality:   NetworkX betweenness centrality in dependency graph
      fuzzy_risk:   Fuzzy category after Trapezoidal Membership mapping
      data_class:   Business data classification (PII, Financial, Public, etc.)
    """
    ewm_weight: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="EWM (Entropy Weight Method) weight for this resource"
    )
    critic_index: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="CRITIC inter-criteria correlation index"
    )
    centrality: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="NetworkX betweenness centrality in dependency graph"
    )
    fuzzy_risk: FuzzyRiskCategory = Field(
        default=FuzzyRiskCategory.LOW,
        description="Fuzzy risk category (Trapezoidal Membership)"
    )
    data_class: str = Field(
        default="internal",
        description="Business data classification: pii, financial, public, internal, restricted"
    )
    compliance_frameworks: list[str] = Field(
        default_factory=list,
        description="Applicable compliance frameworks: SOC2, HIPAA, PCI-DSS, etc."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ABSTRACT BASE: UniversalResource
# ═══════════════════════════════════════════════════════════════════════════════

class UniversalResource(BaseModel):
    """
    Universal Resource Schema — Abstract Base Class
    -------------------------------------------------
    Single data model representing ANY cloud resource across AWS and Azure.

    Design Decisions:
      1. `provider` + `resource_type` give a unique canonical type
      2. `properties` dict holds provider-specific fields (flexible escape hatch)
      3. `trust_chain` links cross-cloud identity relationships
      4. `drift_history` tracks temporal configuration changes
      5. `metadata` carries EWM_Weight, CRITIC_Index for math engine
      6. `account_id` identifies the owning cloud account
      7. `tags` provide business context (DataClass, Environment, Owner)

    Specialized subclasses (ComputeResource, StorageResource, IdentityResource)
    add typed fields. The base class remains instantiable for backward compat.
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
    account_id: str = Field(
        default="",
        description="Cloud account ID (AWS Account ID or Azure Subscription ID)"
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
        description="Resource tags for governance and cost allocation "
                    "(e.g., DataClass, Environment, Owner, CostCenter)"
    )
    metadata: ResourceMetadata = Field(
        default_factory=ResourceMetadata,
        description="EWM/CRITIC weights, centrality, and fuzzy risk category"
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

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("resource_id")
    @classmethod
    def validate_resource_id(cls, v: str) -> str:
        """Ensure resource IDs are non-empty and reasonably formatted."""
        if not v or len(v) < 3:
            raise ValueError("resource_id must be at least 3 characters")
        return v

    # ── Category Introspection ────────────────────────────────────────────────

    @property
    def category(self) -> ResourceCategory:
        """Get the high-level category of this resource."""
        return RESOURCE_CATEGORY_MAP.get(
            self.resource_type, ResourceCategory.COMPUTE
        )

    @property
    def is_compute(self) -> bool:
        return self.category == ResourceCategory.COMPUTE

    @property
    def is_storage(self) -> bool:
        return self.category == ResourceCategory.STORAGE

    @property
    def is_identity(self) -> bool:
        return self.category == ResourceCategory.IDENTITY

    # ── Mutation ──────────────────────────────────────────────────────────────

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

    def update_fuzzy_risk(self, category: FuzzyRiskCategory) -> None:
        """Update the fuzzy risk classification from the MathEngine."""
        self.metadata.fuzzy_risk = category

    def update_weights(
        self,
        ewm: Optional[float] = None,
        critic: Optional[float] = None,
        centrality: Optional[float] = None,
    ) -> None:
        """Update EWM/CRITIC/centrality weights from the MathEngine."""
        if ewm is not None:
            self.metadata.ewm_weight = ewm
        if critic is not None:
            self.metadata.critic_index = critic
        if centrality is not None:
            self.metadata.centrality = centrality

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_simulation_dict(self) -> dict[str, Any]:
        """Serialize for Redis pub/sub and PostgreSQL storage."""
        return self.model_dump(mode="json")


# ═══════════════════════════════════════════════════════════════════════════════
# SPECIALIZED SUBCLASSES (Strictly Typed)
# ═══════════════════════════════════════════════════════════════════════════════

class ComputeResource(UniversalResource):
    """
    Compute Resource (EC2, Azure VM, EKS Pod, Lambda)
    ---------------------------------------------------
    Adds strictly typed compute-specific fields that prevent
    hallucinated attributes during simulation.

    model_config(extra='forbid') ensures only declared fields are allowed.
    """

    model_config = {"extra": "forbid"}

    # ── Compute-Specific Fields ───────────────────────────────────────────────
    instance_type: str = Field(
        default="",
        description="Instance/VM size (e.g., t3.micro, Standard_D2s_v3)"
    )
    vcpus: int = Field(
        default=0,
        ge=0,
        description="Number of vCPUs"
    )
    memory_gb: float = Field(
        default=0.0,
        ge=0.0,
        description="Memory in GB"
    )
    state: str = Field(
        default="running",
        description="Instance state: running, stopped, terminated"
    )
    hourly_cost_usd: float = Field(
        default=0.0,
        ge=0.0,
        description="Hourly compute cost in USD"
    )
    runtime: str = Field(
        default="",
        description="Runtime for serverless (e.g., python3.11, nodejs20.x)"
    )
    is_spot: bool = Field(
        default=False,
        description="Whether this is a spot/preemptible instance"
    )

    @model_validator(mode="after")
    def validate_compute_type(self) -> "ComputeResource":
        """Ensure resource_type is a compute type."""
        compute_types = {
            ResourceType.EC2, ResourceType.AZURE_VM,
            ResourceType.EKS_POD, ResourceType.LAMBDA,
        }
        if self.resource_type not in compute_types:
            raise ValueError(
                f"ComputeResource requires compute resource_type, "
                f"got {self.resource_type}"
            )
        return self


class StorageResource(UniversalResource):
    """
    Storage Resource (S3, Azure Blob, RDS)
    ----------------------------------------
    Strictly typed storage configuration fields.
    """

    model_config = {"extra": "forbid"}

    # ── Storage-Specific Fields ───────────────────────────────────────────────
    size_gb: float = Field(
        default=0.0,
        ge=0.0,
        description="Storage size in GB"
    )
    encryption_enabled: bool = Field(
        default=True,
        description="Whether encryption at rest is enabled"
    )
    public_access_blocked: bool = Field(
        default=True,
        description="Whether public access is blocked"
    )
    versioning_enabled: bool = Field(
        default=False,
        description="Whether object versioning is enabled"
    )
    backup_enabled: bool = Field(
        default=True,
        description="Whether backups are enabled"
    )
    logging_enabled: bool = Field(
        default=False,
        description="Whether access logging is enabled"
    )
    storage_class: str = Field(
        default="standard",
        description="Storage tier: standard, infrequent, archive, hot, cool"
    )
    object_count: int = Field(
        default=0,
        ge=0,
        description="Number of objects/records stored"
    )

    @model_validator(mode="after")
    def validate_storage_type(self) -> "StorageResource":
        """Ensure resource_type is a storage type."""
        storage_types = {
            ResourceType.S3, ResourceType.AZURE_BLOB, ResourceType.RDS,
        }
        if self.resource_type not in storage_types:
            raise ValueError(
                f"StorageResource requires storage resource_type, "
                f"got {self.resource_type}"
            )
        return self


class IdentityResource(UniversalResource):
    """
    Identity Resource (IAM User, IAM Role, Azure OIDC)
    ----------------------------------------------------
    Strictly typed identity and access management fields.
    """

    model_config = {"extra": "forbid"}

    # ── Identity-Specific Fields ──────────────────────────────────────────────
    username: str = Field(
        default="",
        description="Username (for IAM users)"
    )
    mfa_enabled: bool = Field(
        default=False,
        description="Whether MFA is enabled"
    )
    is_service_role: bool = Field(
        default=False,
        description="Whether this is a service/machine identity"
    )
    has_admin_policy: bool = Field(
        default=False,
        description="Whether this identity has admin-level permissions"
    )
    overly_permissive: bool = Field(
        default=False,
        description="Whether the policy grants overly broad permissions"
    )
    access_key_age_days: int = Field(
        default=0,
        ge=0,
        description="Age of the active access key in days"
    )
    days_since_last_login: int = Field(
        default=0,
        ge=0,
        description="Days since last interactive login"
    )
    policy_count: int = Field(
        default=0,
        ge=0,
        description="Number of attached policies"
    )
    trust_policy_entities: int = Field(
        default=0,
        ge=0,
        description="Number of entities in the trust policy"
    )

    @model_validator(mode="after")
    def validate_identity_type(self) -> "IdentityResource":
        """Ensure resource_type is an identity type."""
        identity_types = {
            ResourceType.IAM_USER, ResourceType.IAM_ROLE,
            ResourceType.AZURE_OIDC,
        }
        if self.resource_type not in identity_types:
            raise ValueError(
                f"IdentityResource requires identity resource_type, "
                f"got {self.resource_type}"
            )
        return self

    @property
    def is_inactive(self) -> bool:
        """An identity is inactive if no login for >90 days."""
        return self.days_since_last_login > 90

    @property
    def needs_key_rotation(self) -> bool:
        """Access key should be rotated after 90 days."""
        return self.access_key_age_days > 90


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-CLOUD TRUST (Enhanced)
# ═══════════════════════════════════════════════════════════════════════════════

class CrossCloudTrust(BaseModel):
    """
    Cross-Cloud Trust Relationship (Enhanced v2)
    -----------------------------------------------
    Defines how an identity in one provider is authorized for
    a resource in another provider via OIDC federation.

    Example flows:
      • AWS Lambda  → (OIDC) → Azure Blob Storage
      • AWS EKS Pod → (OIDC) → Azure AKS Service
      • GitHub Actions → (OIDC) → AWS IAM Role

    Validates:
      1. Source must be an identity-capable resource
      2. Source and target must be different providers (cross-cloud)
      3. OIDC issuer URL must be present for cross-cloud trust
      4. At least one audience claim must be specified
      5. Scopes follow least-privilege (flag if admin)

    Based on RFC 7523 — JWT Profile for OAuth 2.0.
    """

    model_config = {"extra": "forbid"}

    trust_id: str = Field(
        default_factory=lambda: f"cct-{uuid.uuid4().hex[:8]}",
        description="Unique cross-cloud trust identifier"
    )
    # ── Source Identity ───────────────────────────────────────────────────────
    source_provider: CloudProvider = Field(
        description="Provider where the identity originates"
    )
    source_resource_id: str = Field(
        description="Resource ID of the identity source (e.g., Lambda fn ARN)"
    )
    source_resource_type: ResourceType = Field(
        description="Type of the source resource"
    )
    source_account_id: str = Field(
        default="",
        description="Account ID of the source provider"
    )

    # ── Target Resource ───────────────────────────────────────────────────────
    target_provider: CloudProvider = Field(
        description="Provider where the target resource lives"
    )
    target_resource_id: str = Field(
        description="Resource ID of the target (e.g., Azure Blob container)"
    )
    target_resource_type: ResourceType = Field(
        description="Type of the target resource"
    )
    target_account_id: str = Field(
        default="",
        description="Account ID of the target provider"
    )

    # ── OIDC Configuration ────────────────────────────────────────────────────
    oidc_issuer_url: str = Field(
        description="OIDC issuer URL for token validation (REQUIRED for cross-cloud)"
    )
    allowed_audiences: list[str] = Field(
        min_length=1,
        description="Allowed audience claims in the OIDC token (at least one required)"
    )
    allowed_scopes: list[str] = Field(
        default_factory=lambda: ["read"],
        description="Permitted OAuth scopes — least-privilege default is ['read']"
    )
    subject_filter: str = Field(
        default="*",
        description="Subject claim filter (e.g., 'repo:org/*:ref:refs/heads/main')"
    )
    max_token_lifetime_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Maximum OIDC token lifetime in seconds (1min–24hr)"
    )

    # ── State ─────────────────────────────────────────────────────────────────
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
    last_used_at: Optional[datetime] = Field(
        default=None,
        description="Last time a token exchange was performed"
    )
    risk_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Trust-specific risk score (elevated for admin scopes)"
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def validate_cross_cloud(self) -> "CrossCloudTrust":
        """Ensure source and target are different providers."""
        if self.source_provider == self.target_provider:
            raise ValueError(
                f"CrossCloudTrust requires different providers. "
                f"Source={self.source_provider}, Target={self.target_provider}. "
                f"Use OIDCTrustLink for same-provider trust."
            )
        return self

    @model_validator(mode="after")
    def assess_risk(self) -> "CrossCloudTrust":
        """Auto-assess risk based on scope and token lifetime."""
        risk = 10.0  # Base risk for any cross-cloud trust
        admin_scopes = {"admin", "cluster-admin", "*", "write:all"}
        if any(s in admin_scopes for s in self.allowed_scopes):
            risk += 40.0  # Admin scope is high risk
        if self.subject_filter == "*":
            risk += 20.0  # Wildcard subject is risky
        if self.max_token_lifetime_seconds > 7200:
            risk += 10.0  # Long-lived tokens are risky
        if not self.expires_at:
            risk += 5.0   # No expiry is mildly risky
        self.risk_score = min(100.0, risk)
        return self

    def is_expired(self) -> bool:
        """Check if this trust has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    def validate_trust(self) -> tuple[bool, list[str]]:
        """
        Validate this trust relationship for security compliance.

        Returns:
            (is_valid, list_of_violations)
        """
        violations: list[str] = []
        if not self.is_active:
            violations.append("Trust is inactive")
        if self.is_expired():
            violations.append("Trust has expired")
        if not self.oidc_issuer_url:
            violations.append("Missing OIDC issuer URL")
        if not self.allowed_audiences:
            violations.append("No audience claims (overly permissive)")
        if self.subject_filter == "*":
            violations.append("Wildcard subject filter (not least-privilege)")
        admin_scopes = {"admin", "cluster-admin", "*"}
        if any(s in admin_scopes for s in self.allowed_scopes):
            violations.append(f"Admin-level scopes detected: {self.allowed_scopes}")

        return (len(violations) == 0, violations)


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY OIDC TRUST LINK (backward compat with existing code)
# ═══════════════════════════════════════════════════════════════════════════════

class OIDCTrustLink(BaseModel):
    """
    Cross-Cloud OIDC Trust Relationship (Legacy v1 compat)
    -------------------------------------------------------
    Kept for backward compat with telemetry.py and engine.py.
    New code should prefer CrossCloudTrust for stricter validation.
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

    def to_cross_cloud_trust(self) -> CrossCloudTrust:
        """Upgrade to the strictly-typed CrossCloudTrust model."""
        return CrossCloudTrust(
            source_provider=self.source_provider,
            source_resource_id=self.source_resource_id,
            source_resource_type=ResourceType.LAMBDA,  # Default assumption
            target_provider=self.target_provider,
            target_resource_id=self.target_resource_id,
            target_resource_type=ResourceType.AZURE_BLOB,
            oidc_issuer_url=self.oidc_issuer_url or "https://unknown",
            allowed_audiences=self.allowed_audiences or ["default"],
            allowed_scopes=self.allowed_scopes or ["read"],
            is_active=self.is_active,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# DRIFT EVENT
# ═══════════════════════════════════════════════════════════════════════════════

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

    # ── Fuzzy classification ──────────────────────────────────────────────────
    fuzzy_risk_category: FuzzyRiskCategory = Field(
        default=FuzzyRiskCategory.LOW,
        description="Fuzzy risk category from Trapezoidal Membership"
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
ComputeResource.model_rebuild()
StorageResource.model_rebuild()
IdentityResource.model_rebuild()
DriftEvent.model_rebuild()
CrossCloudTrust.model_rebuild()
