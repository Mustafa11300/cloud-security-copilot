"""
TELEMETRY & WASTE BASELINE GENERATOR
======================================
Subsystem 8 — Phase 1 Foundation

Generates time-series telemetry data using NumPy:
  - Seasonality (24-hour, 7-day cycles)
  - Independent Noise (Gaussian)
  - Trend Components (growth/decay)

Starts the world state with a 40% Wasteful Baseline:
  - 40% of compute resources are under-utilized
  - This tests the "30% savings" claim from the research

Additionally generates cross-cloud resources:
  - AWS: EC2, S3, IAM, EKS, Lambda, Security Groups, RDS
  - Azure: Blobs, OIDC, VMs, AKS
  - Cross-cloud OIDC trust relationships

Output: List of UniversalResource instances with realistic telemetry
attached, ready for the simulation engine.
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np

from cloudguard.core.schemas import (
    CloudProvider,
    DriftEvent,
    DriftType,
    EnvironmentWeights,
    OIDCTrustLink,
    ResourceType,
    Severity,
    UniversalResource,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

WASTEFUL_BASELINE = 0.40          # 40% of resources start wasteful
TOTAL_RESOURCE_COUNT = 350        # Total simulated resources


# Resource mix
RESOURCE_MIX = {
    # AWS Resources
    (CloudProvider.AWS, ResourceType.EC2): 80,
    (CloudProvider.AWS, ResourceType.S3): 50,
    (CloudProvider.AWS, ResourceType.IAM_USER): 40,
    (CloudProvider.AWS, ResourceType.IAM_ROLE): 15,
    (CloudProvider.AWS, ResourceType.EKS_CLUSTER): 5,
    (CloudProvider.AWS, ResourceType.EKS_POD): 20,
    (CloudProvider.AWS, ResourceType.LAMBDA): 25,
    (CloudProvider.AWS, ResourceType.SECURITY_GROUP): 50,
    (CloudProvider.AWS, ResourceType.RDS): 20,
    # Azure Resources
    (CloudProvider.AZURE, ResourceType.AZURE_BLOB): 15,
    (CloudProvider.AZURE, ResourceType.AZURE_OIDC): 5,
    (CloudProvider.AZURE, ResourceType.AZURE_VM): 15,
    (CloudProvider.AZURE, ResourceType.AZURE_AKS): 5,
}


# ═══════════════════════════════════════════════════════════════════════════════
# TIME-SERIES GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class TimeSeriesGenerator:
    """
    Generates realistic time-series telemetry data using NumPy.

    Components:
      1. Base level (mean utilization)
      2. 24-hour diurnal cycle (peak during business hours)
      3. 7-day weekly cycle (lower on weekends)
      4. Independent Gaussian noise
      5. Optional trend (growth/decay)

    Usage:
        gen = TimeSeriesGenerator(seed=42)
        cpu_series = gen.generate(
            n_ticks=720,       # 720 hours = 30 days
            base_level=45.0,   # 45% average CPU
            seasonality_24h=15.0,
            seasonality_7d=5.0,
            noise_std=3.0,
        )
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = np.random.default_rng(seed)

    def generate(
        self,
        n_ticks: int = 720,
        base_level: float = 50.0,
        seasonality_24h: float = 15.0,
        seasonality_7d: float = 5.0,
        noise_std: float = 5.0,
        trend_per_tick: float = 0.0,
        clip_min: float = 0.0,
        clip_max: float = 100.0,
    ) -> np.ndarray:
        """
        Generate a time series with multiple components.

        Args:
            n_ticks: Number of time steps.
            base_level: Mean value.
            seasonality_24h: Amplitude of 24-hour cycle.
            seasonality_7d: Amplitude of 7-day cycle.
            noise_std: Standard deviation of Gaussian noise.
            trend_per_tick: Linear trend per tick.
            clip_min: Minimum allowed value.
            clip_max: Maximum allowed value.

        Returns:
            NumPy array of shape (n_ticks,) with the time series.
        """
        t = np.arange(n_ticks, dtype=float)

        # Diurnal cycle (24-hour period)
        diurnal = seasonality_24h * np.sin(2 * np.pi * t / 24.0)

        # Weekly cycle (168-hour period)
        weekly = seasonality_7d * np.sin(2 * np.pi * t / 168.0)

        # Gaussian noise
        noise = self.rng.normal(0, noise_std, n_ticks)

        # Linear trend
        trend = trend_per_tick * t

        # Compose
        series = base_level + diurnal + weekly + noise + trend

        return np.clip(series, clip_min, clip_max)

    def generate_cost_series(
        self,
        n_ticks: int = 720,
        hourly_rate: float = 0.10,
        utilization_series: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """
        Generate a cost time series based on utilization.
        Cost = hourly_rate (reserved) + 0.3 * hourly_rate * (util/100) for burst.
        """
        if utilization_series is None:
            utilization_series = self.generate(n_ticks, base_level=50.0)

        base_cost = hourly_rate
        burst_cost = 0.3 * hourly_rate * (utilization_series / 100.0)
        return base_cost + burst_cost

    def generate_network_series(
        self,
        n_ticks: int = 720,
        base_bytes: float = 1e6,
        burst_factor: float = 5.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Generate inbound and outbound network byte series."""
        inbound = self.generate(
            n_ticks,
            base_level=base_bytes,
            seasonality_24h=base_bytes * 0.5,
            noise_std=base_bytes * 0.2,
            clip_min=0,
            clip_max=base_bytes * burst_factor,
        )
        outbound = inbound * self.rng.uniform(0.3, 0.8, n_ticks)
        return inbound, outbound


# ═══════════════════════════════════════════════════════════════════════════════
# WORLD STATE GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class WorldStateGenerator:
    """
    Generates the complete initial world state for the simulation.
    Produces UniversalResource instances with realistic telemetry data
    and a 40% wasteful baseline.

    Usage:
        gen = WorldStateGenerator(seed=42)
        resources, trust_links = gen.generate()
    """

    AWS_REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
    AZURE_LOCATIONS = ["eastus", "westeurope", "southeastasia"]

    EC2_INSTANCE_TYPES = {
        "t3.micro": 0.0104,
        "t3.small": 0.0208,
        "t3.medium": 0.0416,
        "t3.large": 0.0832,
        "m5.large": 0.096,
        "m5.xlarge": 0.192,
        "m5.2xlarge": 0.384,
        "c5.xlarge": 0.17,
        "r5.large": 0.126,
    }

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = np.random.default_rng(seed)
        self.ts_gen = TimeSeriesGenerator(seed)
        self._py_random = random.Random(seed)

    def generate(
        self,
        resource_mix: Optional[dict] = None,
        wasteful_pct: float = WASTEFUL_BASELINE,
    ) -> tuple[list[UniversalResource], list[OIDCTrustLink]]:
        """
        Generate the complete world state.

        Returns:
            Tuple of (resources, oidc_trust_links).
        """
        mix = resource_mix or RESOURCE_MIX
        resources: list[UniversalResource] = []
        trust_links: list[OIDCTrustLink] = []

        for (provider, res_type), count in mix.items():
            for _ in range(count):
                is_wasteful = self.rng.random() < wasteful_pct
                resource = self._generate_resource(provider, res_type, is_wasteful)
                resources.append(resource)

        # Generate cross-cloud OIDC trust links
        trust_links = self._generate_trust_links(resources)

        # Attach trust links to resources
        for link in trust_links:
            for res in resources:
                if res.resource_id == link.source_resource_id:
                    res.trust_chain.append(link)
                    break

        return resources, trust_links

    def _generate_resource(
        self,
        provider: CloudProvider,
        res_type: ResourceType,
        is_wasteful: bool,
    ) -> UniversalResource:
        """Generate a single resource with provider-specific properties."""
        generators = {
            ResourceType.EC2: self._gen_ec2,
            ResourceType.S3: self._gen_s3,
            ResourceType.IAM_USER: self._gen_iam_user,
            ResourceType.IAM_ROLE: self._gen_iam_role,
            ResourceType.EKS_CLUSTER: self._gen_eks_cluster,
            ResourceType.EKS_POD: self._gen_eks_pod,
            ResourceType.LAMBDA: self._gen_lambda,
            ResourceType.SECURITY_GROUP: self._gen_security_group,
            ResourceType.RDS: self._gen_rds,
            ResourceType.AZURE_BLOB: self._gen_azure_blob,
            ResourceType.AZURE_OIDC: self._gen_azure_oidc,
            ResourceType.AZURE_VM: self._gen_azure_vm,
            ResourceType.AZURE_AKS: self._gen_azure_aks,
        }

        gen_func = generators.get(res_type, self._gen_generic)
        return gen_func(provider, is_wasteful)

    # ── AWS Resource Generators ───────────────────────────────────────────────

    def _gen_ec2(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        itype = self._py_random.choice(list(self.EC2_INSTANCE_TYPES.keys()))
        hourly = self.EC2_INSTANCE_TYPES[itype]
        hours = self.rng.integers(1, 720)

        if wasteful:
            cpu = float(self.rng.uniform(0.5, 5.0))
            mem = float(self.rng.uniform(5.0, 15.0))
        else:
            cpu = float(self.rng.uniform(20, 85))
            mem = float(self.rng.uniform(30, 80))

        monthly = round(hourly * float(hours), 2)

        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.EC2,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"ec2-{self._py_random.choice(['web','api','worker','batch','proxy'])}-{self.rng.integers(100,999)}",
            properties={
                "instance_type": itype,
                "state": self._py_random.choice(["running"] * 3 + ["stopped"]),
                "hourly_cost_usd": hourly,
                "running_hours_30d": int(hours),
                "cpu_avg_percent": round(cpu, 2),
                "has_purpose_tag": self.rng.random() > 0.3,
            },
            tags={"Environment": self._py_random.choice(["prod", "staging", "dev"])},
            cpu_utilization=cpu,
            memory_utilization=mem,
            monthly_cost_usd=monthly,
            risk_score=45.0 if wasteful else float(self.rng.uniform(5, 25)),
            is_compliant=not wasteful,
        )

    def _gen_s3(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        public = wasteful and self.rng.random() < 0.5
        encrypted = not wasteful or self.rng.random() > 0.4
        logging = not wasteful or self.rng.random() > 0.5

        risk = 95.0 if public else (70.0 if not encrypted else 10.0)

        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.S3,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"s3-{self._py_random.choice(['data','logs','backup','assets','config'])}-{self.rng.integers(100,999)}",
            properties={
                "public_access_blocked": not public,
                "encryption_enabled": encrypted,
                "versioning_enabled": self.rng.random() > 0.4,
                "logging_enabled": logging,
                "size_gb": round(float(self.rng.uniform(0.1, 5000)), 2),
                "object_count": int(self.rng.integers(1, 1000000)),
            },
            monthly_cost_usd=round(float(self.rng.uniform(0.5, 150.0)), 2),
            risk_score=risk,
            is_compliant=not public and encrypted,
        )

    def _gen_iam_user(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        mfa = not wasteful or self.rng.random() > 0.4
        days_inactive = int(self.rng.integers(0, 365))
        key_age = int(self.rng.integers(1, 400))
        admin = wasteful and self.rng.random() < 0.15

        risk = 0.0
        if not mfa:
            risk += 35.0
        if days_inactive > 90:
            risk += 20.0
        if admin:
            risk += 40.0
        if key_age > 90:
            risk += 15.0

        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.IAM_USER,
            region="global",
            name=f"iam-user-{self.rng.integers(1000, 9999)}",
            properties={
                "username": f"user_{self.rng.integers(100, 999)}",
                "mfa_enabled": mfa,
                "days_since_last_login": days_inactive,
                "is_inactive": days_inactive > 90,
                "access_key_age_days": key_age,
                "has_admin_policy": admin,
                "policy_count": int(self.rng.integers(1, 8)),
            },
            risk_score=min(100.0, risk),
            is_compliant=risk < 20,
        )

    def _gen_iam_role(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        overly_permissive = wasteful and self.rng.random() < 0.3
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.IAM_ROLE,
            region="global",
            name=f"role-{self._py_random.choice(['lambda-exec','eks-node','admin','readonly'])}-{self.rng.integers(100,999)}",
            properties={
                "is_service_role": True,
                "trust_policy_entities": int(self.rng.integers(1, 5)),
                "overly_permissive": overly_permissive,
            },
            risk_score=60.0 if overly_permissive else 10.0,
            is_compliant=not overly_permissive,
        )

    def _gen_eks_cluster(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        public_endpoint = wasteful and self.rng.random() < 0.3
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.EKS_CLUSTER,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"eks-{self._py_random.choice(['prod','staging','dev'])}-{self.rng.integers(10,99)}",
            properties={
                "version": self._py_random.choice(["1.28", "1.29", "1.30"]),
                "public_endpoint": public_endpoint,
                "node_count": int(self.rng.integers(2, 20)),
                "rbac_enabled": True,
            },
            monthly_cost_usd=round(float(self.rng.uniform(100, 3000)), 2),
            risk_score=70.0 if public_endpoint else 15.0,
            is_compliant=not public_endpoint,
        )

    def _gen_eks_pod(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        cpu = float(self.rng.uniform(1, 10) if wasteful else self.rng.uniform(20, 80))
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.EKS_POD,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"pod-{self._py_random.choice(['api','worker','cron'])}-{self.rng.integers(1000,9999)}",
            properties={
                "namespace": self._py_random.choice(["default", "production", "monitoring"]),
                "image": f"app:{self._py_random.choice(['v1.2', 'v1.3', 'latest'])}",
                "status": "Running",
            },
            cpu_utilization=cpu,
            memory_utilization=float(self.rng.uniform(10, 70)),
            risk_score=20.0 if wasteful else 5.0,
        )

    def _gen_lambda(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        invocations = int(self.rng.integers(0, 100000))
        errors = int(invocations * (self.rng.uniform(0.05, 0.3) if wasteful else self.rng.uniform(0, 0.02)))
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.LAMBDA,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"lambda-{self._py_random.choice(['processor','handler','trigger','sync'])}-{self.rng.integers(100,999)}",
            properties={
                "runtime": self._py_random.choice(["python3.11", "nodejs20.x", "go1.x"]),
                "memory_mb": int(self._py_random.choice([128, 256, 512, 1024, 2048])),
                "timeout_sec": int(self._py_random.choice([30, 60, 300, 900])),
                "invocations_30d": invocations,
                "error_count_30d": errors,
            },
            monthly_cost_usd=round(float(self.rng.uniform(0.1, 50.0)), 2),
            risk_score=30.0 if errors / max(invocations, 1) > 0.1 else 5.0,
        )

    def _gen_security_group(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        open_to_world = wasteful and self.rng.random() < 0.5
        risky_ports = [22, 3389, 3306, 5432, 27017, 6379]
        safe_ports = [80, 443]

        if open_to_world:
            port = self._py_random.choice(risky_ports)
            rules = [{"port": port, "protocol": "tcp", "source": "0.0.0.0/0"}]
            risk = 90.0 if port in [22, 3389] else 85.0
        else:
            port = self._py_random.choice(safe_ports)
            rules = [{"port": port, "protocol": "tcp", "source": f"10.0.{self.rng.integers(0,255)}.0/24"}]
            risk = 5.0

        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.SECURITY_GROUP,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"sg-{self.rng.integers(10000000,99999999)}",
            properties={
                "inbound_rules": rules,
                "open_to_internet": open_to_world,
            },
            risk_score=risk,
            is_compliant=not open_to_world,
        )

    def _gen_rds(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        public = wasteful and self.rng.random() < 0.25
        encrypted = not wasteful or self.rng.random() > 0.2
        backup = not wasteful or self.rng.random() > 0.15

        risk = 0.0
        if public:
            risk += 45.0
        if not encrypted:
            risk += 30.0
        if not backup:
            risk += 20.0

        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.RDS,
            region=self._py_random.choice(self.AWS_REGIONS),
            name=f"rds-{self._py_random.choice(['prod','staging','analytics'])}-{self.rng.integers(10,99)}",
            properties={
                "engine": self._py_random.choice(["mysql", "postgres", "mariadb"]),
                "publicly_accessible": public,
                "encryption_at_rest": encrypted,
                "backup_enabled": backup,
                "multi_az": self.rng.random() > 0.45,
                "instance_class": self._py_random.choice(["db.t3.micro", "db.t3.small", "db.m5.large"]),
                "storage_gb": int(self.rng.integers(20, 1000)),
            },
            monthly_cost_usd=round(float(self.rng.uniform(20, 500)), 2),
            risk_score=min(100.0, risk),
            is_compliant=not public and encrypted and backup,
        )

    # ── Azure Resource Generators ─────────────────────────────────────────────

    def _gen_azure_blob(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        public = wasteful and self.rng.random() < 0.3
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.AZURE_BLOB,
            region=self._py_random.choice(self.AZURE_LOCATIONS),
            name=f"blob-{self._py_random.choice(['storage','backup','media'])}-{self.rng.integers(100,999)}",
            properties={
                "container_access": "blob" if public else "private",
                "encryption_enabled": not wasteful or self.rng.random() > 0.3,
                "immutable_storage": self.rng.random() > 0.7,
                "size_gb": round(float(self.rng.uniform(1, 2000)), 2),
            },
            monthly_cost_usd=round(float(self.rng.uniform(1, 200)), 2),
            risk_score=80.0 if public else 10.0,
            is_compliant=not public,
        )

    def _gen_azure_oidc(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.AZURE_OIDC,
            region=self._py_random.choice(self.AZURE_LOCATIONS),
            name=f"oidc-federation-{self.rng.integers(100,999)}",
            properties={
                "issuer_url": f"https://token.actions.githubusercontent.com",
                "audiences": ["api://AzureADTokenExchange"],
                "subject_claims": [f"repo:org/repo:ref:refs/heads/main"],
            },
            risk_score=15.0 if not wasteful else 50.0,
            is_compliant=not wasteful,
        )

    def _gen_azure_vm(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        cpu = float(self.rng.uniform(1, 8) if wasteful else self.rng.uniform(20, 75))
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.AZURE_VM,
            region=self._py_random.choice(self.AZURE_LOCATIONS),
            name=f"vm-{self._py_random.choice(['web','app','db'])}-{self.rng.integers(100,999)}",
            properties={
                "vm_size": self._py_random.choice(["Standard_B1s", "Standard_D2s_v3", "Standard_D4s_v3"]),
                "state": "running",
            },
            cpu_utilization=cpu,
            monthly_cost_usd=round(float(self.rng.uniform(10, 400)), 2),
            risk_score=30.0 if wasteful else 10.0,
            is_compliant=not wasteful,
        )

    def _gen_azure_aks(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.AZURE_AKS,
            region=self._py_random.choice(self.AZURE_LOCATIONS),
            name=f"aks-{self._py_random.choice(['prod','staging'])}-{self.rng.integers(10,99)}",
            properties={
                "kubernetes_version": self._py_random.choice(["1.28", "1.29"]),
                "node_count": int(self.rng.integers(3, 15)),
                "network_policy": "calico" if not wasteful else "none",
            },
            monthly_cost_usd=round(float(self.rng.uniform(200, 2000)), 2),
            risk_score=40.0 if wasteful else 10.0,
            is_compliant=not wasteful,
        )

    def _gen_generic(self, provider: CloudProvider, wasteful: bool) -> UniversalResource:
        return UniversalResource(
            provider=provider,
            resource_type=ResourceType.EC2,
            region="us-east-1",
            name=f"generic-{self.rng.integers(1000,9999)}",
            risk_score=20.0,
        )

    # ── Cross-Cloud OIDC Trust ────────────────────────────────────────────────

    def _generate_trust_links(
        self,
        resources: list[UniversalResource],
    ) -> list[OIDCTrustLink]:
        """
        Generate cross-cloud OIDC trust relationships.
        E.g., AWS Lambda → Azure Blob (federated identity).
        """
        links: list[OIDCTrustLink] = []

        aws_lambdas = [r for r in resources if r.resource_type == ResourceType.LAMBDA]
        azure_blobs = [r for r in resources if r.resource_type == ResourceType.AZURE_BLOB]
        aws_eks = [r for r in resources if r.resource_type == ResourceType.EKS_CLUSTER]
        azure_oidc = [r for r in resources if r.resource_type == ResourceType.AZURE_OIDC]

        # Lambda → Azure Blob trust
        for i in range(min(3, len(aws_lambdas), len(azure_blobs))):
            link = OIDCTrustLink(
                source_provider=CloudProvider.AWS,
                source_resource_id=aws_lambdas[i].resource_id,
                target_provider=CloudProvider.AZURE,
                target_resource_id=azure_blobs[i].resource_id,
                oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE",
                allowed_audiences=["api://AzureADTokenExchange"],
                allowed_scopes=["read", "write"],
            )
            links.append(link)

        # EKS → Azure AKS trust (cross-cloud k8s federation)
        azure_aks = [r for r in resources if r.resource_type == ResourceType.AZURE_AKS]
        for i in range(min(2, len(aws_eks), len(azure_aks))):
            link = OIDCTrustLink(
                source_provider=CloudProvider.AWS,
                source_resource_id=aws_eks[i].resource_id,
                target_provider=CloudProvider.AZURE,
                target_resource_id=azure_aks[i].resource_id,
                oidc_issuer_url="https://oidc.eks.us-west-2.amazonaws.com/id/EXAMPLED539D4633",
                allowed_audiences=["sts.amazonaws.com"],
                allowed_scopes=["cluster-admin"],
            )
            links.append(link)

        return links
