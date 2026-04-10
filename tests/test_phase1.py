"""
CloudGuard-B Phase 1 — Test Suite
===================================
Comprehensive tests for ALL 8 subsystems.

Run with:
  cd cloud-security-copilot
  python -m pytest tests/test_phase1.py -v
"""

import json
import math

import numpy as np
import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# 1. UNIVERSAL SCHEMA TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestUniversalSchema:
    """Tests for Subsystem 1: Universal Resource Schema."""

    def test_create_aws_ec2_resource(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
            region="us-east-1",
            name="test-ec2",
            properties={"instance_type": "t3.micro", "state": "running"},
            monthly_cost_usd=10.0,
            risk_score=25.0,
        )
        assert res.provider == CloudProvider.AWS
        assert res.resource_type == ResourceType.EC2
        assert res.risk_score == 25.0
        assert res.is_compliant is True

    def test_create_azure_blob_resource(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AZURE,
            resource_type=ResourceType.AZURE_BLOB,
            region="eastus",
            name="test-blob",
            properties={"container_access": "private"},
        )
        assert res.provider == CloudProvider.AZURE
        assert res.resource_type == ResourceType.AZURE_BLOB

    def test_oidc_trust_link(self):
        from cloudguard.core.schemas import CloudProvider, OIDCTrustLink
        link = OIDCTrustLink(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-123",
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-456",
            oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLE",
            allowed_audiences=["api://AzureADTokenExchange"],
        )
        assert link.validate_trust() is True
        assert link.is_expired() is False

    def test_oidc_trust_no_audience_invalid(self):
        from cloudguard.core.schemas import CloudProvider, OIDCTrustLink
        link = OIDCTrustLink(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-123",
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-456",
            oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com",
            allowed_audiences=[],  # Empty = overly permissive
        )
        assert link.validate_trust() is False

    def test_drift_event_application(self):
        from cloudguard.core.schemas import (
            CloudProvider, DriftEvent, DriftType, ResourceType, UniversalResource
        )
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.S3,
            properties={"public_access_blocked": True},
            is_compliant=True,
        )
        drift = DriftEvent(
            resource_id=res.resource_id,
            drift_type=DriftType.PUBLIC_EXPOSURE,
            mutations={"public_access_blocked": False},
        )
        res.apply_drift(drift)
        assert res.is_compliant is False
        assert res.properties["public_access_blocked"] is False
        assert len(res.drift_history) == 1

    def test_environment_weights_validation(self):
        from cloudguard.core.schemas import EnvironmentWeights
        w = EnvironmentWeights(w_risk=0.7, w_cost=0.3)
        assert w.w_risk == 0.7
        assert w.w_cost == 0.3

    def test_environment_weights_invalid(self):
        from cloudguard.core.schemas import EnvironmentWeights
        with pytest.raises(Exception):
            EnvironmentWeights(w_risk=0.7, w_cost=0.5)

    def test_serialization_roundtrip(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
            name="test",
            properties={"key": "value"},
            monthly_cost_usd=50.0,
        )
        data = res.to_simulation_dict()
        assert isinstance(data, dict)
        assert data["provider"] == "aws"
        assert data["monthly_cost_usd"] == 50.0

    def test_resource_metadata_defaults(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
        )
        assert res.metadata.ewm_weight == 0.0
        assert res.metadata.critic_index == 0.0
        assert res.metadata.centrality == 0.0
        assert res.metadata.fuzzy_risk.value == "low"
        assert res.metadata.data_class == "internal"

    def test_update_weights(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
        )
        res.update_weights(ewm=0.35, critic=0.42, centrality=0.8)
        assert res.metadata.ewm_weight == 0.35
        assert res.metadata.critic_index == 0.42
        assert res.metadata.centrality == 0.8

    def test_update_fuzzy_risk(self):
        from cloudguard.core.schemas import (
            CloudProvider, FuzzyRiskCategory, ResourceType, UniversalResource,
        )
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
        )
        res.update_fuzzy_risk(FuzzyRiskCategory.HIGH)
        assert res.metadata.fuzzy_risk == FuzzyRiskCategory.HIGH

    def test_account_id_field(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
            account_id="123456789012",
        )
        assert res.account_id == "123456789012"

    def test_category_introspection(self):
        from cloudguard.core.schemas import CloudProvider, ResourceCategory, ResourceType, UniversalResource
        ec2 = UniversalResource(provider=CloudProvider.AWS, resource_type=ResourceType.EC2)
        assert ec2.category == ResourceCategory.COMPUTE
        assert ec2.is_compute is True
        assert ec2.is_storage is False

        s3 = UniversalResource(provider=CloudProvider.AWS, resource_type=ResourceType.S3)
        assert s3.category == ResourceCategory.STORAGE
        assert s3.is_storage is True

        iam = UniversalResource(provider=CloudProvider.AWS, resource_type=ResourceType.IAM_USER)
        assert iam.category == ResourceCategory.IDENTITY
        assert iam.is_identity is True

    def test_tags_business_context(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        res = UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.RDS,
            tags={
                "DataClass": "PII",
                "Environment": "production",
                "Owner": "security-team",
                "CostCenter": "CC-1234",
            },
        )
        assert res.tags["DataClass"] == "PII"
        assert res.tags["CostCenter"] == "CC-1234"


# ═══════════════════════════════════════════════════════════════════════════════
# 1B. TYPED SUBCLASS TESTS (ComputeResource, StorageResource, IdentityResource)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTypedSubclasses:
    """Tests for strictly-typed resource subclasses with extra='forbid'."""

    def test_compute_resource_creation(self):
        from cloudguard.core.schemas import CloudProvider, ComputeResource, ResourceType
        res = ComputeResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.EC2,
            instance_type="t3.large",
            vcpus=2,
            memory_gb=8.0,
            state="running",
            hourly_cost_usd=0.0832,
        )
        assert res.instance_type == "t3.large"
        assert res.vcpus == 2
        assert res.is_compute is True
        assert res.state == "running"

    def test_compute_resource_lambda(self):
        from cloudguard.core.schemas import CloudProvider, ComputeResource, ResourceType
        res = ComputeResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.LAMBDA,
            runtime="python3.11",
            memory_gb=0.256,
        )
        assert res.resource_type == ResourceType.LAMBDA
        assert res.runtime == "python3.11"

    def test_compute_resource_rejects_storage_type(self):
        from cloudguard.core.schemas import CloudProvider, ComputeResource, ResourceType
        with pytest.raises(Exception):
            ComputeResource(
                provider=CloudProvider.AWS,
                resource_type=ResourceType.S3,  # Not a compute type
            )

    def test_compute_resource_rejects_extra_fields(self):
        from cloudguard.core.schemas import CloudProvider, ComputeResource, ResourceType
        with pytest.raises(Exception):
            ComputeResource(
                provider=CloudProvider.AWS,
                resource_type=ResourceType.EC2,
                hallucinated_field="this should fail",  # extra='forbid'
            )

    def test_storage_resource_creation(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, StorageResource
        res = StorageResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.S3,
            size_gb=500.0,
            encryption_enabled=True,
            public_access_blocked=True,
            versioning_enabled=True,
            storage_class="standard",
        )
        assert res.size_gb == 500.0
        assert res.encryption_enabled is True
        assert res.is_storage is True

    def test_storage_resource_rds(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, StorageResource
        res = StorageResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.RDS,
            size_gb=100.0,
            encryption_enabled=True,
            backup_enabled=True,
        )
        assert res.resource_type == ResourceType.RDS
        assert res.backup_enabled is True

    def test_storage_resource_rejects_compute_type(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, StorageResource
        with pytest.raises(Exception):
            StorageResource(
                provider=CloudProvider.AWS,
                resource_type=ResourceType.EC2,  # Not a storage type
            )

    def test_storage_resource_rejects_extra_fields(self):
        from cloudguard.core.schemas import CloudProvider, ResourceType, StorageResource
        with pytest.raises(Exception):
            StorageResource(
                provider=CloudProvider.AWS,
                resource_type=ResourceType.S3,
                hallucinated_encryption_key="bad",  # extra='forbid'
            )

    def test_identity_resource_creation(self):
        from cloudguard.core.schemas import CloudProvider, IdentityResource, ResourceType
        res = IdentityResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.IAM_USER,
            username="admin-user",
            mfa_enabled=True,
            has_admin_policy=False,
            access_key_age_days=45,
            days_since_last_login=10,
            policy_count=3,
        )
        assert res.username == "admin-user"
        assert res.mfa_enabled is True
        assert res.is_inactive is False
        assert res.needs_key_rotation is False
        assert res.is_identity is True

    def test_identity_resource_inactive(self):
        from cloudguard.core.schemas import CloudProvider, IdentityResource, ResourceType
        res = IdentityResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.IAM_USER,
            days_since_last_login=120,
        )
        assert res.is_inactive is True  # >90 days

    def test_identity_resource_key_rotation(self):
        from cloudguard.core.schemas import CloudProvider, IdentityResource, ResourceType
        res = IdentityResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.IAM_USER,
            access_key_age_days=100,
        )
        assert res.needs_key_rotation is True  # >90 days

    def test_identity_resource_rejects_compute_type(self):
        from cloudguard.core.schemas import CloudProvider, IdentityResource, ResourceType
        with pytest.raises(Exception):
            IdentityResource(
                provider=CloudProvider.AWS,
                resource_type=ResourceType.EC2,  # Not an identity type
            )

    def test_identity_resource_rejects_extra_fields(self):
        from cloudguard.core.schemas import CloudProvider, IdentityResource, ResourceType
        with pytest.raises(Exception):
            IdentityResource(
                provider=CloudProvider.AWS,
                resource_type=ResourceType.IAM_USER,
                fake_permissions=["admin"],  # extra='forbid'
            )

    def test_subclass_inherits_from_universal(self):
        from cloudguard.core.schemas import (
            CloudProvider, ComputeResource, IdentityResource,
            ResourceType, StorageResource, UniversalResource,
        )
        compute = ComputeResource(
            provider=CloudProvider.AWS, resource_type=ResourceType.EC2,
        )
        storage = StorageResource(
            provider=CloudProvider.AWS, resource_type=ResourceType.S3,
        )
        identity = IdentityResource(
            provider=CloudProvider.AWS, resource_type=ResourceType.IAM_USER,
        )
        # All should be instances of UniversalResource
        assert isinstance(compute, UniversalResource)
        assert isinstance(storage, UniversalResource)
        assert isinstance(identity, UniversalResource)


# ═══════════════════════════════════════════════════════════════════════════════
# 1C. CROSS-CLOUD TRUST TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestCrossCloudTrust:
    """Tests for CrossCloudTrust (enhanced v2 OIDC federation)."""

    def test_valid_cross_cloud_trust(self):
        from cloudguard.core.schemas import (
            CloudProvider, CrossCloudTrust, ResourceType,
        )
        trust = CrossCloudTrust(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-123",
            source_resource_type=ResourceType.LAMBDA,
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-456",
            target_resource_type=ResourceType.AZURE_BLOB,
            oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLE",
            allowed_audiences=["api://AzureADTokenExchange"],
            allowed_scopes=["read"],
        )
        is_valid, violations = trust.validate_trust()
        assert is_valid is True
        assert len(violations) == 0

    def test_same_provider_rejected(self):
        from cloudguard.core.schemas import (
            CloudProvider, CrossCloudTrust, ResourceType,
        )
        with pytest.raises(Exception):
            CrossCloudTrust(
                source_provider=CloudProvider.AWS,
                source_resource_id="lambda-1",
                source_resource_type=ResourceType.LAMBDA,
                target_provider=CloudProvider.AWS,  # Same provider!
                target_resource_id="s3-1",
                target_resource_type=ResourceType.S3,
                oidc_issuer_url="https://oidc.example.com",
                allowed_audiences=["aud"],
            )

    def test_admin_scope_auto_risk(self):
        from cloudguard.core.schemas import (
            CloudProvider, CrossCloudTrust, ResourceType,
        )
        trust = CrossCloudTrust(
            source_provider=CloudProvider.AWS,
            source_resource_id="eks-1",
            source_resource_type=ResourceType.EKS_CLUSTER,
            target_provider=CloudProvider.AZURE,
            target_resource_id="aks-1",
            target_resource_type=ResourceType.AZURE_AKS,
            oidc_issuer_url="https://oidc.eks.us-west-2.amazonaws.com/id/EX",
            allowed_audiences=["sts.amazonaws.com"],
            allowed_scopes=["cluster-admin"],  # Admin scope
        )
        # Auto-risk should be elevated (base 10 + admin 40 + wildcard 20)
        assert trust.risk_score >= 50.0
        is_valid, violations = trust.validate_trust()
        assert is_valid is False
        assert any("admin" in v.lower() for v in violations)

    def test_wildcard_subject_flagged(self):
        from cloudguard.core.schemas import (
            CloudProvider, CrossCloudTrust, ResourceType,
        )
        trust = CrossCloudTrust(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-1",
            source_resource_type=ResourceType.LAMBDA,
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-1",
            target_resource_type=ResourceType.AZURE_BLOB,
            oidc_issuer_url="https://oidc.example.com",
            allowed_audiences=["aud"],
            subject_filter="*",  # Wildcard
        )
        is_valid, violations = trust.validate_trust()
        assert is_valid is False
        assert any("wildcard" in v.lower() for v in violations)

    def test_trust_extra_fields_rejected(self):
        from cloudguard.core.schemas import (
            CloudProvider, CrossCloudTrust, ResourceType,
        )
        with pytest.raises(Exception):
            CrossCloudTrust(
                source_provider=CloudProvider.AWS,
                source_resource_id="lambda-1",
                source_resource_type=ResourceType.LAMBDA,
                target_provider=CloudProvider.AZURE,
                target_resource_id="blob-1",
                target_resource_type=ResourceType.AZURE_BLOB,
                oidc_issuer_url="https://example.com",
                allowed_audiences=["aud"],
                hallucinated_field="should fail",  # extra='forbid'
            )

    def test_legacy_oidc_upgrade(self):
        from cloudguard.core.schemas import CloudProvider, CrossCloudTrust, OIDCTrustLink
        link = OIDCTrustLink(
            source_provider=CloudProvider.AWS,
            source_resource_id="lambda-123",
            target_provider=CloudProvider.AZURE,
            target_resource_id="blob-456",
            oidc_issuer_url="https://oidc.eks.us-east-1.amazonaws.com",
            allowed_audiences=["api://AzureADTokenExchange"],
        )
        trust = link.to_cross_cloud_trust()
        assert isinstance(trust, CrossCloudTrust)
        assert trust.source_provider == CloudProvider.AWS
        assert trust.target_provider == CloudProvider.AZURE


# ═══════════════════════════════════════════════════════════════════════════════
# 1D. FUZZY LOGIC TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestFuzzyLogic:
    """Tests for Trapezoidal Membership Functions and Fuzzy Risk Engine."""

    def test_trapezoidal_mf_basic(self):
        from cloudguard.core.math_engine import TrapezoidalMF
        mf = TrapezoidalMF(a=0, b=10, c=30, d=40)

        # Below a → 0
        assert mf.evaluate(-5) == 0.0
        # On rising edge
        assert mf.evaluate(5) == 0.5
        # On plateau
        assert mf.evaluate(20) == 1.0
        # On falling edge
        assert mf.evaluate(35) == 0.5
        # Above d → 0
        assert mf.evaluate(45) == 0.0

    def test_trapezoidal_mf_boundaries(self):
        from cloudguard.core.math_engine import TrapezoidalMF
        mf = TrapezoidalMF(a=0, b=0, c=20, d=35)

        # Left degenerate (triangle-like left)
        assert mf.evaluate(0) == 1.0  # b==a, so inside [b,c]
        assert mf.evaluate(10) == 1.0
        assert mf.evaluate(27.5) == 0.5

    def test_trapezoidal_mf_invalid_params(self):
        from cloudguard.core.math_engine import TrapezoidalMF
        with pytest.raises(ValueError):
            TrapezoidalMF(a=30, b=10, c=20, d=40)  # a > b

    def test_trapezoidal_mf_vectorized(self):
        from cloudguard.core.math_engine import TrapezoidalMF
        mf = TrapezoidalMF(a=0, b=10, c=30, d=40)
        x = np.array([0, 5, 10, 20, 30, 35, 40, 50])
        result = mf.evaluate_array(x)
        assert len(result) == 8
        assert result[3] == 1.0  # x=20, plateau
        assert result[0] == 0.0  # x=0, at boundary a

    def test_fuzzy_classify_low(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = engine.classify(5.0)
        assert m.dominant_category == "low"
        assert m.low > 0.5

    def test_fuzzy_classify_medium(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = engine.classify(42.0)
        assert m.dominant_category == "medium"
        assert m.medium > 0.5

    def test_fuzzy_classify_high(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = engine.classify(72.0)
        assert m.dominant_category == "high"
        assert m.high > 0.5

    def test_fuzzy_classify_critical(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = engine.classify(92.0)
        assert m.dominant_category == "critical"
        assert m.critical > 0.5

    def test_fuzzy_ambiguity_at_boundary(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        # Score 32 is near low/medium boundary
        m = engine.classify(32.0)
        # Both low and medium should have significant membership
        assert m.low > 0.1
        assert m.medium > 0.1
        assert m.is_ambiguous is True

    def test_fuzzy_defuzzify_low(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = engine.classify(10.0)
        defuzzified = engine.defuzzify(m)
        # Defuzzified should be in low range
        assert 0 <= defuzzified <= 30

    def test_fuzzy_defuzzify_critical(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = engine.classify(95.0)
        defuzzified = engine.defuzzify(m)
        # Defuzzified should be in critical range
        assert defuzzified >= 70

    def test_fuzzy_defuzzify_zero_membership(self):
        from cloudguard.core.math_engine import FuzzyMembership, FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m = FuzzyMembership(low=0, medium=0, high=0, critical=0)
        defuzzified = engine.defuzzify(m)
        assert defuzzified == 0.0  # Edge case

    def test_fuzzy_batch_classification(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        ids = ["r1", "r2", "r3", "r4"]
        scores = [5.0, 42.0, 72.0, 92.0]
        result = engine.classify_batch(ids, scores)

        assert result.category_counts["low"] >= 1
        assert result.category_counts["medium"] >= 1
        assert result.category_counts["high"] >= 1
        assert result.category_counts["critical"] >= 1
        assert len(result.memberships) == 4
        assert len(result.defuzzified_scores) == 4

    def test_fuzzy_reduces_false_positives(self):
        """
        Core test: Scores 49 and 51 should NOT land in drastically
        different categories. Fuzzy logic smooths this boundary.
        """
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine()
        m49 = engine.classify(49.0)
        m51 = engine.classify(51.0)
        # Both should have similar medium membership
        assert abs(m49.medium - m51.medium) < 0.2
        # Both should have similar dominant category
        assert m49.dominant_category == m51.dominant_category

    def test_fuzzy_custom_parameters(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine
        engine = FuzzyRiskEngine(
            low_params=(0, 0, 10, 20),
            medium_params=(15, 25, 45, 55),
            high_params=(50, 60, 75, 85),
            critical_params=(80, 90, 100, 100),
        )
        m = engine.classify(12.0)
        assert m.low > 0
        assert m.dominant_category == "low"
        params = engine.get_params()
        assert params["low"] == (0, 0, 10, 20)

    def test_j_score_includes_fuzzy_categories(self):
        """Verify J calculation now includes fuzzy_category per resource."""
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        resources = [
            ResourceRiskCost("r1", risk_score=10, monthly_cost_usd=100),
            ResourceRiskCost("r2", risk_score=50, monthly_cost_usd=50),
            ResourceRiskCost("r3", risk_score=90, monthly_cost_usd=200),
        ]
        result = engine.calculate_j(resources, w_risk=0.6, w_cost=0.4)
        # per_resource should now include fuzzy_category
        for pr in result.per_resource:
            assert "fuzzy_category" in pr
            assert "fuzzy_ambiguous" in pr
            assert pr["fuzzy_category"] in ("low", "medium", "high", "critical")

    def test_math_engine_has_fuzzy_attribute(self):
        from cloudguard.core.math_engine import FuzzyRiskEngine, MathEngine
        engine = MathEngine()
        assert hasattr(engine, "fuzzy")
        assert isinstance(engine.fuzzy, FuzzyRiskEngine)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TEMPORAL CLOCK TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemporalClock:
    """Tests for Subsystem 2: Temporal Clock."""

    def test_standard_mode_ticking(self):
        from cloudguard.core.clock import ClockMode, TemporalClock
        clock = TemporalClock()
        event = clock.tick_sync()
        assert event.tick_number == 0
        assert event.mode == ClockMode.STANDARD
        assert event.elapsed_sim_minutes == 60  # 1 tick = 60 min

    def test_burst_mode_activation(self):
        from cloudguard.core.clock import ClockMode, TemporalClock
        clock = TemporalClock()
        clock.enter_burst_mode(duration_ticks=10)
        assert clock.mode == ClockMode.BURST

        event = clock.tick_sync()
        assert event.mode == ClockMode.BURST
        assert event.elapsed_sim_minutes == 1  # 1 tick = 1 min in burst

    def test_burst_mode_exit(self):
        from cloudguard.core.clock import ClockMode, TemporalClock
        clock = TemporalClock()
        clock.enter_burst_mode(duration_ticks=3)

        # Tick through burst
        for _ in range(4):
            clock.tick_sync()

        # Should have reverted to standard
        assert clock.mode == ClockMode.STANDARD

    def test_heartbeat_every_10_ticks(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        heartbeats = []
        for _ in range(25):
            event = clock.tick_sync()
            if event.is_heartbeat:
                heartbeats.append(event.tick_number)

        # Ticks 10 and 20 should be heartbeats
        assert 10 in heartbeats
        assert 20 in heartbeats

    def test_mttr_measurement(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        clock.enter_burst_mode(duration_ticks=100, drift_id="test-drift")

        # Simulate 7 burst ticks (= 7 simulated minutes)
        for _ in range(7):
            clock.tick_sync()

        mttr = clock.exit_burst_mode(remediation_successful=True)
        assert mttr == 7.0  # 7 burst ticks × 1 min
        assert len(clock.mttr_measurements) == 1

    def test_clock_reset(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        for _ in range(10):
            clock.tick_sync()
        clock.reset()
        assert clock.current_tick == 0
        assert clock.elapsed_sim_minutes == 0

    def test_callback_registration(self):
        from cloudguard.core.clock import TemporalClock
        clock = TemporalClock()
        ticks_received = []

        def my_callback(event):
            ticks_received.append(event.tick_number)

        clock.register_callback(my_callback)
        clock.tick_sync()
        clock.tick_sync()
        assert len(ticks_received) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REDIS EVENT BUS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBus:
    """Tests for Subsystem 3: Redis Pub/Sub Event Bus."""

    def test_event_payload_creation(self):
        from cloudguard.infra.redis_bus import EventPayload
        payload = EventPayload.create(
            event_type="TEST",
            timestamp_tick=5,
            w_risk=0.7,
            w_cost=0.3,
            data={"key": "value"},
        )
        assert payload["event_type"] == "TEST"
        assert payload["timestamp_tick"] == 5
        assert payload["environment_weights"]["w_R"] == 0.7
        assert payload["environment_weights"]["w_C"] == 0.3
        assert "trace_id" in payload
        assert "event_id" in payload

    def test_heartbeat_payload(self):
        from cloudguard.infra.redis_bus import EventPayload
        hb = EventPayload.heartbeat(tick=10)
        assert hb["event_type"] == "HEARTBEAT"
        assert hb["data"]["tick"] == 10

    def test_drift_payload(self):
        from cloudguard.infra.redis_bus import EventPayload
        drift = EventPayload.drift(
            resource_id="s3-test",
            drift_type="public_exposure",
            severity="CRITICAL",
            tick=42,
            is_false_positive=True,
        )
        assert drift["event_type"] == "DRIFT"
        assert drift["data"]["resource_id"] == "s3-test"
        assert drift["data"]["is_false_positive"] is True

    def test_in_memory_event_bus(self):
        from cloudguard.infra.redis_bus import EventBus, EventPayload
        bus = EventBus()
        payload = EventPayload.heartbeat(tick=1)
        bus.publish_sync(payload)
        assert bus.published_count == 1
        assert bus.queue_size == 1

    def test_event_bus_drain(self):
        from cloudguard.infra.redis_bus import EventBus, EventPayload
        bus = EventBus()
        for i in range(5):
            bus.publish_sync(EventPayload.heartbeat(tick=i))
        events = bus.drain_queue(3)
        assert len(events) == 3
        assert bus.queue_size == 2

    def test_event_bus_subscriber(self):
        from cloudguard.infra.redis_bus import EventBus, EventPayload
        bus = EventBus()
        received = []
        bus.subscribe(lambda e: received.append(e))
        bus.publish_sync(EventPayload.heartbeat(tick=1))
        assert len(received) == 1

    def test_siem_log_emulator(self):
        from cloudguard.infra.redis_bus import SIEMLogEmulator
        vpc = SIEMLogEmulator.vpc_flow_log("res-1", tick=10)
        assert vpc["log_type"] == "VPC_FLOW"

        ct = SIEMLogEmulator.cloudtrail_event("PutObject", "s3-1", tick=10)
        assert ct["log_type"] == "CLOUDTRAIL"

        k8s = SIEMLogEmulator.k8s_audit_log("pod-1", verb="create", tick=10)
        assert k8s["log_type"] == "K8S_AUDIT"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STATE BRANCH MANAGER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateBranchManager:
    """Tests for Subsystem 4: Isolated Branching & Rollback."""

    def test_initialize_trunk(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        resources = [{"resource_id": f"res-{i}", "risk": i * 10} for i in range(5)]
        trunk_id = mgr.initialize_trunk(resources, j_score=0.85)
        assert trunk_id is not None
        assert mgr.active_branch_count == 1

    def test_create_branch(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        resources = [{"resource_id": "res-1"}]
        mgr.initialize_trunk(resources)
        branch_id = mgr.create_branch("branch_a")
        assert branch_id is not None
        assert mgr.active_branch_count == 2

    def test_max_3_branches(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "r1"}])
        mgr.create_branch("branch_a")
        mgr.create_branch("branch_b")
        # 4th branch should fail
        result = mgr.create_branch("branch_a")
        assert result is None

    def test_branch_isolation(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "res-1", "value": "original"}])
        branch_id = mgr.create_branch("branch_a")
        # Modify branch
        mgr.update_resource(branch_id, "res-1", {"value": "modified"})
        # Trunk should be unchanged
        trunk_res = mgr.get_resources(mgr.trunk_id)
        assert trunk_res[0]["value"] == "original"
        # Branch should be modified
        branch_res = mgr.get_resources(branch_id)
        assert branch_res[0]["value"] == "modified"

    def test_rollback(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "res-1", "value": "v1"}], j_score=0.5)
        branch_id = mgr.create_branch("branch_a")
        mgr.update_resource(branch_id, "res-1", {"value": "v2"})

        success = mgr.rollback(branch_id, reason="J_new >= J_old")
        assert success is True

        # After rollback, branch state should match trunk
        branch_res = mgr.get_resources(branch_id)
        assert branch_res[0]["value"] == "v1"

    def test_self_correction_logic_gate(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        # J_new >= J_old → should rollback
        assert mgr.should_rollback("any", j_old=0.5, j_new=0.6) is True
        assert mgr.should_rollback("any", j_old=0.5, j_new=0.5) is True
        assert mgr.should_rollback("any", j_old=0.5, j_new=0.4) is False

    def test_cannot_rollback_trunk(self):
        from cloudguard.infra.branch_manager import StateBranchManager
        mgr = StateBranchManager()
        mgr.initialize_trunk([{"resource_id": "r1"}])
        assert mgr.rollback(mgr.trunk_id) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MATH ENGINE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMathEngine:
    """Tests for Subsystem 5: Governance & ROI Math Engine."""

    def test_j_equilibrium_basic(self):
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        resources = [
            ResourceRiskCost("r1", risk_score=80, monthly_cost_usd=100),
            ResourceRiskCost("r2", risk_score=20, monthly_cost_usd=50),
            ResourceRiskCost("r3", risk_score=50, monthly_cost_usd=75),
        ]
        result = engine.calculate_j(resources, w_risk=0.6, w_cost=0.4)
        assert 0 <= result.j_score <= 1
        assert 0 <= result.j_percentage <= 100
        assert len(result.per_resource) == 3

    def test_j_empty_resources(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        result = engine.calculate_j([], w_risk=0.6, w_cost=0.4)
        assert result.j_score == 0.0
        assert result.j_percentage == 100.0

    def test_j_weights_must_sum_to_one(self):
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        with pytest.raises(ValueError):
            engine.calculate_j(
                [ResourceRiskCost("r1", 50, 50)],
                w_risk=0.5, w_cost=0.6,
            )

    def test_rosi_positive(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        result = engine.calculate_rosi(
            ale_before=50000,
            ale_after=5000,
            remediation_cost=10000,
        )
        assert result.rosi > 0
        assert result.is_positive is True
        assert result.time_to_breakeven_months > 0

    def test_rosi_negative(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        result = engine.calculate_rosi(
            ale_before=10000,
            ale_after=9000,
            remediation_cost=5000,
        )
        assert result.rosi < 0
        assert result.is_positive is False

    def test_ale_calculation(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        ale = engine.calculate_ale(
            asset_value=1_000_000,
            exposure_factor=0.25,
            annual_rate_of_occurrence=0.1,
        )
        assert ale == 25000.0  # 1M × 0.25 × 0.1 = 25K

    def test_ewm_weights(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        matrix = np.array([
            [10, 20, 30],
            [40, 50, 60],
            [70, 80, 90],
            [25, 35, 45],
        ])
        names = ["risk", "cost", "impact"]
        result = engine.calculate_ewm(matrix, names)
        assert len(result.weights) == 3
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_critic_weights(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        matrix = np.array([
            [10, 80, 5],
            [20, 60, 10],
            [70, 30, 50],
            [40, 50, 25],
        ])
        names = ["risk", "cost", "impact"]
        result = engine.calculate_critic(matrix, names)
        assert len(result.weights) == 3
        assert abs(sum(result.weights.values()) - 1.0) < 0.01

    def test_pareto_front(self):
        from cloudguard.core.math_engine import MathEngine, ResourceRiskCost
        engine = MathEngine()
        resources = [
            ResourceRiskCost("r1", risk_score=10, monthly_cost_usd=100),  # Low risk, high cost
            ResourceRiskCost("r2", risk_score=90, monthly_cost_usd=10),   # High risk, low cost
            ResourceRiskCost("r3", risk_score=50, monthly_cost_usd=50),   # Middle
        ]
        result = engine.calculate_j(resources, w_risk=0.5, w_cost=0.5)
        assert len(result.pareto_front) > 0

    def test_self_correction_gate(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        assert engine.should_rollback(j_old=0.5, j_new=0.6) is True
        assert engine.should_rollback(j_old=0.5, j_new=0.4) is False

    def test_governance_percentage(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        assert engine.governance_percentage(0.0) == 100.0
        assert engine.governance_percentage(1.0) == 0.0
        assert engine.governance_percentage(0.5) == 50.0

    def test_dependency_graph(self):
        from cloudguard.core.math_engine import MathEngine
        engine = MathEngine()
        edges = [("a", "b"), ("b", "c"), ("c", "d"), ("a", "d")]
        centrality = engine.build_dependency_graph(edges)
        assert len(centrality) == 4
        stats = engine.get_graph_stats()
        assert stats["nodes"] == 4
        assert stats["edges"] == 4


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SWARM HANDSHAKE TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSwarmHandshake:
    """Tests for Subsystem 6: Dialectical Swarm."""

    def test_ciso_proposes_risk_reduction(self):
        from cloudguard.core.swarm import CISOAgent, SwarmState
        ciso = CISOAgent()
        state = SwarmState(current_j_score=0.7)
        context = {"total_risk": 80, "remediation_cost": 100}
        proposal = ciso.propose(state, context)
        assert proposal.agent_role == "ciso"
        assert proposal.expected_risk_delta < 0

    def test_controller_proposes_cost_savings(self):
        from cloudguard.core.swarm import ControllerAgent, SwarmState
        ctrl = ControllerAgent()
        state = SwarmState(current_j_score=0.7)
        context = {"total_risk": 80, "potential_savings": 200}
        proposal = ctrl.propose(state, context)
        assert proposal.agent_role == "controller"
        assert proposal.expected_cost_delta <= 0

    def test_orchestrator_selects_winner(self):
        from cloudguard.core.swarm import (
            CISOAgent, ControllerAgent, OrchestratorAgent, SwarmState,
        )
        orch = OrchestratorAgent()
        ciso = CISOAgent()
        ctrl = ControllerAgent()
        state = SwarmState(current_j_score=0.7)
        context = {"total_risk": 80, "remediation_cost": 50, "potential_savings": 200}

        state = orch.negotiate(state, ciso, ctrl, context)
        assert state.selected_proposal is not None
        assert state.status.value == "consensus"

    def test_token_budget_enforcement(self):
        from cloudguard.core.swarm import SwarmState
        state = SwarmState(token_budget=100, tokens_consumed=0)
        assert state.consume_tokens(50) is True
        assert state.consume_tokens(60) is False
        assert state.budget_exceeded is True


# ═══════════════════════════════════════════════════════════════════════════════
# 7. REMEDIATION PROTOCOL TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRemediationProtocol:
    """Tests for Subsystem 7: Command Pattern Remediation."""

    def _make_resource(self, **props):
        from cloudguard.core.schemas import CloudProvider, ResourceType, UniversalResource
        return UniversalResource(
            provider=CloudProvider.AWS,
            resource_type=ResourceType.S3,
            properties=props,
            risk_score=90.0,
        )

    def test_block_public_access(self):
        from cloudguard.core.remediation import BlockPublicAccess, RemediationTier
        from cloudguard.core.schemas import RemediationTier as RT
        res = self._make_resource(public_access_blocked=False)
        cmd = BlockPublicAccess(res, tier=RT.SILVER)
        success = cmd.execute_with_retry()
        assert success is True
        assert res.properties["public_access_blocked"] is True

    def test_command_undo(self):
        from cloudguard.core.remediation import BlockPublicAccess
        from cloudguard.core.schemas import RemediationTier
        res = self._make_resource(public_access_blocked=False, encryption_enabled=False)
        cmd = BlockPublicAccess(res, tier=RemediationTier.SILVER)
        cmd._previous_state = res.properties.copy()
        cmd.execute()
        assert res.properties["public_access_blocked"] is True
        cmd.undo()
        assert res.properties["public_access_blocked"] is False

    def test_failed_fixes_log(self):
        from cloudguard.core.remediation import FailedFixesLog, BlockPublicAccess
        from cloudguard.core.schemas import RemediationTier
        log = FailedFixesLog()
        res = self._make_resource(public_access_blocked=False)
        cmd = BlockPublicAccess(res, tier=RemediationTier.BRONZE)
        cmd._is_failed = True
        cmd._failure_reason = "test failure"
        log.record_failure(cmd)
        assert log.total_failures == 1
        assert log.has_failed_before("BlockPublicAccess", res.resource_id)

    def test_command_registry(self):
        from cloudguard.core.remediation import COMMAND_REGISTRY
        assert "block_public_access" in COMMAND_REGISTRY
        assert "enable_encryption" in COMMAND_REGISTRY
        assert "restrict_network_access" in COMMAND_REGISTRY
        assert len(COMMAND_REGISTRY) >= 7


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TELEMETRY GENERATOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTelemetryGenerator:
    """Tests for Subsystem 8: Telemetry & Waste Baseline."""

    def test_time_series_generation(self):
        from cloudguard.simulation.telemetry import TimeSeriesGenerator
        gen = TimeSeriesGenerator(seed=42)
        series = gen.generate(n_ticks=720, base_level=50.0)
        assert len(series) == 720
        assert series.min() >= 0
        assert series.max() <= 100

    def test_seasonality_present(self):
        from cloudguard.simulation.telemetry import TimeSeriesGenerator
        gen = TimeSeriesGenerator(seed=42)
        series = gen.generate(n_ticks=168, base_level=50.0, seasonality_24h=20.0, noise_std=0.1)
        # Series should oscillate around 50 with 24h period
        assert series.std() > 5  # Significant variation from seasonality

    def test_world_state_generation(self):
        from cloudguard.simulation.telemetry import WorldStateGenerator
        gen = WorldStateGenerator(seed=42)
        resources, trust_links = gen.generate()
        assert len(resources) > 300
        assert len(trust_links) > 0

        # Check provider distribution
        aws_count = sum(1 for r in resources if r.provider.value == "aws")
        azure_count = sum(1 for r in resources if r.provider.value == "azure")
        assert aws_count > 200
        assert azure_count > 20

    def test_wasteful_baseline(self):
        from cloudguard.simulation.telemetry import WorldStateGenerator
        gen = WorldStateGenerator(seed=42)
        resources, _ = gen.generate(wasteful_pct=0.40)
        non_compliant = sum(1 for r in resources if not r.is_compliant)
        total = len(resources)
        waste_pct = non_compliant / total
        # Should be roughly 40% (±15% due to randomness)
        assert 0.20 < waste_pct < 0.60

    def test_cross_cloud_trust_links(self):
        from cloudguard.simulation.telemetry import WorldStateGenerator
        gen = WorldStateGenerator(seed=42)
        _, trust_links = gen.generate()
        # Should have Lambda→Blob and EKS→AKS links
        aws_to_azure = [
            l for l in trust_links
            if l.source_provider.value == "aws" and l.target_provider.value == "azure"
        ]
        assert len(aws_to_azure) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 9. SIMULATION ENGINE (INTEGRATION)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSimulationEngine:
    """Integration tests for the complete SimulationEngine."""

    def test_initialization(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        report = engine.initialize()
        assert report["status"] == "initialized"
        assert report["total_resources"] > 300
        assert report["j_percentage"] > 0
        assert report["wasteful_percentage"] > 20

    def test_step_advances_tick(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        engine.initialize()
        report = engine.step()
        assert report.tick == 0
        report2 = engine.step()
        assert report2.tick == 1

    def test_metrics_after_steps(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        engine.initialize()
        for _ in range(5):
            engine.step()
        metrics = engine.get_metrics()
        assert metrics["simulation"]["total_ticks"] == 5
        assert "governance" in metrics
        assert "economics" in metrics
        assert "mttr" in metrics

    def test_uninitialised_step_raises(self):
        from cloudguard.simulation.engine import SimulationEngine
        engine = SimulationEngine(seed=42)
        with pytest.raises(RuntimeError):
            engine.step()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
