"""
REMEDIATION PROTOCOL — COMMAND PATTERN
========================================
Subsystem 7 — Phase 1 Foundation

Agents output Python-based Healing Functions (atomic commands)
that the simulator executes directly against UniversalResource state.

Implements:
  - Command Pattern with execute() and undo() for each remediation
  - Gold/Silver/Bronze tiers (Decision #18)
  - 3-retry validation (Decision #19)
  - Failed Fixes persistent log (Decision #20)
  - Chain-of-Evidence explanations (Decision #17: XAI)

Each concrete command class encodes a specific remediation action
(e.g., block public access, enable encryption, restrict network rules).
The simulator invokes these commands atomically and measures the
resulting J-score delta to determine if the fix improved governance.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from cloudguard.core.schemas import (
    RemediationCommand,
    RemediationTier,
    UniversalResource,
)

logger = logging.getLogger("cloudguard.remediation")


# ═══════════════════════════════════════════════════════════════════════════════
# ABSTRACT COMMAND
# ═══════════════════════════════════════════════════════════════════════════════

class HealingCommand(ABC):
    """
    Abstract base for all healing commands.
    Implements the Command Pattern with execute/undo semantics.

    Subclasses define specific remediation actions (e.g., block S3 public).
    Each command is atomic — either fully succeeds or fully rolls back.

    Decision #19: 3-retry validation. If execute() fails 3 times,
    the command is marked as failed and logged to the Failed Fixes DB.
    """

    MAX_RETRIES: int = 3  # Decision #19

    def __init__(
        self,
        target_resource: UniversalResource,
        tier: RemediationTier = RemediationTier.SILVER,
        explanation: str = "",
    ) -> None:
        self.command_id = f"cmd-{uuid.uuid4().hex[:8]}"
        self.target_resource = target_resource
        self.tier = tier
        self.explanation = explanation
        self._retry_count = 0
        self._is_executed = False
        self._is_failed = False
        self._failure_reason = ""
        self._previous_state: dict[str, Any] = {}
        self._created_at = datetime.now(timezone.utc)

    @abstractmethod
    def execute(self) -> bool:
        """
        Execute the remediation action.
        Returns True if successful, False if failed.
        """
        ...

    @abstractmethod
    def undo(self) -> bool:
        """
        Undo the remediation action (rollback).
        Restores the resource to its pre-execution state.
        Returns True if rollback was successful.
        """
        ...

    @abstractmethod
    def validate(self) -> bool:
        """
        Validate that the remediation was applied correctly.
        Called after execute() to confirm the fix took effect.
        """
        ...

    @property
    def action_name(self) -> str:
        """Human-readable name of this remediation action."""
        return self.__class__.__name__

    def execute_with_retry(self) -> bool:
        """
        Execute with retry logic (Decision #19: 3 retries).

        Returns:
            True if execution and validation succeeded.
            False if all retries exhausted.
        """
        for attempt in range(1, self.MAX_RETRIES + 1):
            self._retry_count = attempt
            logger.info(
                f"🔧 Executing {self.action_name} "
                f"(attempt {attempt}/{self.MAX_RETRIES}) "
                f"on {self.target_resource.resource_id}"
            )

            try:
                # Capture state for rollback
                self._previous_state = self.target_resource.properties.copy()

                success = self.execute()
                if not success:
                    logger.warning(f"   Execution returned False (attempt {attempt})")
                    continue

                # Validate the fix
                if self.validate():
                    self._is_executed = True
                    logger.info(f"   ✅ Validated successfully on attempt {attempt}")
                    return True
                else:
                    logger.warning(f"   Validation failed (attempt {attempt})")
                    self.undo()  # Rollback the invalid fix

            except Exception as e:
                logger.error(f"   ❌ Exception on attempt {attempt}: {e}")
                self._failure_reason = str(e)
                try:
                    self.undo()
                except Exception:
                    pass  # Best-effort rollback

        # All retries exhausted — mark as failed
        self._is_failed = True
        if not self._failure_reason:
            self._failure_reason = f"Failed after {self.MAX_RETRIES} attempts"

        logger.error(
            f"❌ {self.action_name} FAILED after {self.MAX_RETRIES} retries: "
            f"{self._failure_reason}"
        )
        return False

    def to_failed_fix_record(self) -> dict[str, Any]:
        """
        Serialize this failed command for the Failed Fixes DB.
        Decision #20: Persistent SQL table for failed fixes so agents
        don't repeat the same mistake across simulation runs.
        """
        return {
            "command_id": self.command_id,
            "action_name": self.action_name,
            "target_resource_id": self.target_resource.resource_id,
            "target_resource_type": self.target_resource.resource_type.value,
            "tier": self.tier.value,
            "retry_count": self._retry_count,
            "failure_reason": self._failure_reason,
            "explanation": self.explanation,
            "previous_state": self._previous_state,
            "created_at": self._created_at.isoformat(),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }

    def to_schema(self) -> RemediationCommand:
        """Convert to the Pydantic schema for serialization."""
        return RemediationCommand(
            command_id=self.command_id,
            tier=self.tier,
            target_resource_id=self.target_resource.resource_id,
            action=self.action_name,
            parameters=self._get_parameters(),
            rollback_parameters=self._previous_state,
            explanation=self.explanation,
            retry_count=self._retry_count,
            is_failed=self._is_failed,
            failure_reason=self._failure_reason,
        )

    def _get_parameters(self) -> dict[str, Any]:
        """Override to provide action-specific parameters."""
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# CONCRETE HEALING COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

class BlockPublicAccess(HealingCommand):
    """
    Block public access on an S3 bucket or Azure Blob container.
    Gold tier: block all public access + enable encryption + enable logging.
    Silver tier: block public access + enable encryption.
    Bronze tier: block public access only.
    """

    def execute(self) -> bool:
        props = self.target_resource.properties

        if self.tier in (RemediationTier.GOLD, RemediationTier.SILVER, RemediationTier.BRONZE):
            props["public_access_blocked"] = True

        if self.tier in (RemediationTier.GOLD, RemediationTier.SILVER):
            props["encryption_enabled"] = True

        if self.tier == RemediationTier.GOLD:
            props["logging_enabled"] = True
            props["versioning_enabled"] = True

        self.target_resource.is_compliant = True
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 40)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return self.target_resource.properties.get("public_access_blocked", False)

    def _get_parameters(self) -> dict[str, Any]:
        return {"public_access_blocked": True, "tier": self.tier.value}


class EnableEncryption(HealingCommand):
    """Enable encryption at rest for storage or database resources."""

    def execute(self) -> bool:
        props = self.target_resource.properties
        props["encryption_enabled"] = True
        props["encryption_at_rest"] = True
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 25)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return self.target_resource.properties.get("encryption_enabled", False)


class RestrictNetworkAccess(HealingCommand):
    """
    Restrict network access rules (security groups, NSGs).
    Changes 0.0.0.0/0 sources to specific CIDR ranges.
    """

    def __init__(
        self,
        target_resource: UniversalResource,
        allowed_cidr: str = "10.0.0.0/8",
        **kwargs,
    ) -> None:
        super().__init__(target_resource, **kwargs)
        self.allowed_cidr = allowed_cidr

    def execute(self) -> bool:
        props = self.target_resource.properties
        inbound_rules = props.get("inbound_rules", [])

        for rule in inbound_rules:
            if rule.get("source") == "0.0.0.0/0":
                rule["source"] = self.allowed_cidr
                rule["restricted_by"] = self.command_id

        props["open_to_internet"] = False
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 50)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        rules = self.target_resource.properties.get("inbound_rules", [])
        return not any(r.get("source") == "0.0.0.0/0" for r in rules)

    def _get_parameters(self) -> dict[str, Any]:
        return {"allowed_cidr": self.allowed_cidr}


class EnableMFA(HealingCommand):
    """Enable MFA for an IAM user."""

    def execute(self) -> bool:
        self.target_resource.properties["mfa_enabled"] = True
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 30)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return self.target_resource.properties.get("mfa_enabled", False)


class DisablePublicDatabase(HealingCommand):
    """Disable public accessibility for RDS/database instances."""

    def execute(self) -> bool:
        self.target_resource.properties["publicly_accessible"] = False
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 45)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return not self.target_resource.properties.get("publicly_accessible", True)


class TerminateIdleResource(HealingCommand):
    """Terminate/deallocate an idle compute resource for cost savings."""

    def execute(self) -> bool:
        self.target_resource.properties["state"] = "terminated"
        self.target_resource.monthly_cost_usd = 0.0
        self.target_resource.cpu_utilization = 0.0
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return self.target_resource.properties.get("state") == "terminated"


class RotateAccessKey(HealingCommand):
    """Rotate an expired/old IAM access key."""

    def execute(self) -> bool:
        self.target_resource.properties["access_key_age_days"] = 0
        self.target_resource.properties["access_key_rotated"] = True
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 15)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return self.target_resource.properties.get("access_key_age_days", 999) < 1


class RevokeAdminPolicy(HealingCommand):
    """Revoke overly permissive admin policy from IAM user."""

    def execute(self) -> bool:
        self.target_resource.properties["has_admin_policy"] = False
        self.target_resource.risk_score = max(0, self.target_resource.risk_score - 35)
        return True

    def undo(self) -> bool:
        for key, value in self._previous_state.items():
            self.target_resource.properties[key] = value
        return True

    def validate(self) -> bool:
        return not self.target_resource.properties.get("has_admin_policy", True)


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

COMMAND_REGISTRY: dict[str, type[HealingCommand]] = {
    "block_public_access": BlockPublicAccess,
    "enable_encryption": EnableEncryption,
    "restrict_network_access": RestrictNetworkAccess,
    "enable_mfa": EnableMFA,
    "disable_public_database": DisablePublicDatabase,
    "terminate_idle_resource": TerminateIdleResource,
    "rotate_access_key": RotateAccessKey,
    "revoke_admin_policy": RevokeAdminPolicy,
}


# ═══════════════════════════════════════════════════════════════════════════════
# FAILED FIXES LOG (Decision #20: Long-Term Database)
# ═══════════════════════════════════════════════════════════════════════════════

class FailedFixesLog:
    """
    In-memory log of failed remediation attempts.
    In production, this is backed by a persistent SQL table (Decision #20).
    Agents check this log before proposing fixes to avoid repeating mistakes.
    """

    def __init__(self) -> None:
        self._failures: list[dict[str, Any]] = []

    def record_failure(self, command: HealingCommand) -> None:
        """Record a failed remediation attempt."""
        record = command.to_failed_fix_record()
        self._failures.append(record)
        logger.info(
            f"📝 Recorded failed fix: {record['action_name']} "
            f"on {record['target_resource_id']}"
        )

    def has_failed_before(
        self,
        action_name: str,
        resource_id: str,
    ) -> bool:
        """
        Check if a similar fix has failed before.
        Agents call this before proposing to avoid repeating mistakes.
        """
        return any(
            f["action_name"] == action_name and
            f["target_resource_id"] == resource_id
            for f in self._failures
        )

    def get_failures_for_resource(self, resource_id: str) -> list[dict]:
        """Get all failed fix attempts for a specific resource."""
        return [f for f in self._failures if f["target_resource_id"] == resource_id]

    @property
    def total_failures(self) -> int:
        return len(self._failures)

    def to_list(self) -> list[dict]:
        return self._failures.copy()
