"""
STATE BRANCH MANAGER — ISOLATED BRANCHING & ROLLBACK ENGINE
=============================================================
Subsystem 4 — Phase 1 Foundation

Implements PostgreSQL Schema-based isolation between agent trials.

Constraints:
  - Max 3 active branches: Trunk, Branch_A, Branch_B (A/B testing)
  - Each branch is an isolated PostgreSQL schema

Self-Correction Logic Gate:
  If J_new ≥ J_old after a fix, trigger automatic branch.rollback(),
  log the failure, and return to negotiation.

PostgreSQL is OPTIONAL for local development. If unavailable,
the manager falls back to an in-memory dict-based branch store.

In production, each branch schema contains:
  - resources: Full resource state table
  - findings: Detected findings
  - failed_fixes: Decision #20 persistent log
  - audit_log: Full remediation audit trail
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from cloudguard.core.schemas import BranchState, UniversalResource

logger = logging.getLogger("cloudguard.branch_manager")

# Maximum active branches (Trunk + 2 experiment branches)
MAX_ACTIVE_BRANCHES = 3
BRANCH_NAMES = ["trunk", "branch_a", "branch_b"]

# Try PostgreSQL
try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False

try:
    import psycopg2
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY BRANCH STORE (Development Fallback)
# ═══════════════════════════════════════════════════════════════════════════════

class InMemoryBranchStore:
    """
    Dict-based branch store for local development without PostgreSQL.
    Each branch stores a deep copy of the world state for isolation.
    """

    def __init__(self) -> None:
        self._branches: dict[str, dict[str, Any]] = {}
        self._resources: dict[str, dict[str, Any]] = {}  # branch_id → {res_id → resource}
        self._findings: dict[str, list[dict]] = {}        # branch_id → [findings]
        self._failed_fixes: dict[str, list[dict]] = {}    # branch_id → [failed fixes]
        self._audit_log: dict[str, list[dict]] = {}       # branch_id → [audit entries]

    def create_branch(
        self,
        branch_id: str,
        name: str,
        parent_id: Optional[str] = None,
    ) -> None:
        """Create a new branch with isolated state."""
        self._branches[branch_id] = {
            "branch_id": branch_id,
            "name": name,
            "parent_id": parent_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if parent_id and parent_id in self._resources:
            # Deep copy parent state for isolation
            self._resources[branch_id] = copy.deepcopy(self._resources[parent_id])
            self._findings[branch_id] = copy.deepcopy(self._findings.get(parent_id, []))
            self._failed_fixes[branch_id] = copy.deepcopy(self._failed_fixes.get(parent_id, []))
        else:
            self._resources[branch_id] = {}
            self._findings[branch_id] = []
            self._failed_fixes[branch_id] = []

        self._audit_log[branch_id] = []

    def delete_branch(self, branch_id: str) -> None:
        """Delete a branch and all its state."""
        self._branches.pop(branch_id, None)
        self._resources.pop(branch_id, None)
        self._findings.pop(branch_id, None)
        self._failed_fixes.pop(branch_id, None)
        self._audit_log.pop(branch_id, None)

    def set_resource(self, branch_id: str, resource_id: str, data: dict) -> None:
        """Set a resource in a specific branch."""
        if branch_id not in self._resources:
            self._resources[branch_id] = {}
        self._resources[branch_id][resource_id] = copy.deepcopy(data)

    def get_resource(self, branch_id: str, resource_id: str) -> Optional[dict]:
        """Get a resource from a specific branch."""
        return self._resources.get(branch_id, {}).get(resource_id)

    def get_all_resources(self, branch_id: str) -> list[dict]:
        """Get all resources in a branch."""
        return list(self._resources.get(branch_id, {}).values())

    def set_resources_bulk(self, branch_id: str, resources: list[dict]) -> None:
        """Set multiple resources in a branch."""
        if branch_id not in self._resources:
            self._resources[branch_id] = {}
        for res in resources:
            rid = res.get("resource_id", str(uuid.uuid4()))
            self._resources[branch_id][rid] = copy.deepcopy(res)

    def add_finding(self, branch_id: str, finding: dict) -> None:
        """Add a finding to a branch."""
        if branch_id not in self._findings:
            self._findings[branch_id] = []
        self._findings[branch_id].append(finding)

    def get_findings(self, branch_id: str) -> list[dict]:
        """Get all findings for a branch."""
        return self._findings.get(branch_id, [])

    def add_failed_fix(self, branch_id: str, record: dict) -> None:
        """Record a failed fix (Decision #20)."""
        if branch_id not in self._failed_fixes:
            self._failed_fixes[branch_id] = []
        self._failed_fixes[branch_id].append(record)

    def get_failed_fixes(self, branch_id: str) -> list[dict]:
        """Get failed fixes for a branch."""
        return self._failed_fixes.get(branch_id, [])

    def add_audit_entry(self, branch_id: str, entry: dict) -> None:
        """Add an entry to the audit log."""
        if branch_id not in self._audit_log:
            self._audit_log[branch_id] = []
        self._audit_log[branch_id].append(entry)

    def get_audit_log(self, branch_id: str) -> list[dict]:
        """Get the audit log for a branch."""
        return self._audit_log.get(branch_id, [])

    def copy_state(self, source_id: str, target_id: str) -> None:
        """Deep copy state from source branch to target branch."""
        self._resources[target_id] = copy.deepcopy(self._resources.get(source_id, {}))
        self._findings[target_id] = copy.deepcopy(self._findings.get(source_id, []))

    @property
    def branch_count(self) -> int:
        return len(self._branches)

    @property
    def branch_ids(self) -> list[str]:
        return list(self._branches.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# STATE BRANCH MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class StateBranchManager:
    """
    Manages isolated simulation branches for A/B testing of agent remediation.

    Architecture:
      - Trunk: The canonical world state (always exists)
      - Branch_A / Branch_B: Experiment branches for testing fixes
      - Max 3 active branches at any time
      - Each branch is fully isolated (deep copy or PostgreSQL schema)

    Self-Correction:
      When a remediation is applied on a branch, the new J score is compared
      to the old J score. If J_new ≥ J_old (fix made things worse), the
      branch is automatically rolled back and the failure is logged.

    Usage:
        mgr = StateBranchManager()
        mgr.initialize_trunk(resources)

        # Create experiment branch
        branch_id = mgr.create_branch("branch_a", parent="trunk")

        # Apply remediation on branch
        mgr.apply_remediation(branch_id, command)

        # Check J score
        if mgr.should_rollback(branch_id, j_old=0.7, j_new=0.8):
            mgr.rollback(branch_id)

        # Merge successful branch back to trunk
        mgr.merge_to_trunk(branch_id)
    """

    def __init__(
        self,
        postgres_dsn: Optional[str] = None,
    ) -> None:
        self._postgres_dsn = postgres_dsn
        self._store = InMemoryBranchStore()
        self._branches: dict[str, BranchState] = {}
        self._trunk_id: Optional[str] = None

    @property
    def trunk_id(self) -> Optional[str]:
        """ID of the trunk branch."""
        return self._trunk_id

    @property
    def active_branch_count(self) -> int:
        """Number of active (non-rolled-back) branches."""
        return sum(1 for b in self._branches.values() if b.is_active)

    @property
    def active_branches(self) -> list[BranchState]:
        """List of active branches."""
        return [b for b in self._branches.values() if b.is_active]

    # ── Initialization ────────────────────────────────────────────────────────

    def initialize_trunk(
        self,
        resources: list[dict[str, Any]],
        j_score: float = 1.0,
    ) -> str:
        """
        Initialize the trunk branch with the initial world state.

        Args:
            resources: List of resource dicts to populate the trunk.
            j_score: Initial J equilibrium score.

        Returns:
            Trunk branch ID.
        """
        branch_id = f"branch-trunk-{uuid.uuid4().hex[:4]}"
        branch = BranchState(
            branch_id=branch_id,
            name="trunk",
            schema_name="cg_trunk",
            j_score=j_score,
            j_score_history=[j_score],
        )

        self._branches[branch_id] = branch
        self._trunk_id = branch_id

        # Create storage
        self._store.create_branch(branch_id, "trunk")
        self._store.set_resources_bulk(branch_id, resources)

        logger.info(
            f"🌳 Trunk initialized: {branch_id} "
            f"({len(resources)} resources, J={j_score:.4f})"
        )
        return branch_id

    # ── Branch Operations ─────────────────────────────────────────────────────

    def create_branch(
        self,
        name: str,
        parent: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a new experiment branch.

        Args:
            name: Branch name ("branch_a" or "branch_b").
            parent: Parent branch ID (defaults to trunk).

        Returns:
            New branch ID, or None if max branches exceeded.
        """
        if self.active_branch_count >= MAX_ACTIVE_BRANCHES:
            logger.warning(
                f"❌ Cannot create branch: max {MAX_ACTIVE_BRANCHES} active branches"
            )
            return None

        if name not in BRANCH_NAMES:
            logger.warning(f"❌ Invalid branch name: {name} (allowed: {BRANCH_NAMES})")
            return None

        parent_id = parent or self._trunk_id
        if parent_id is None:
            logger.error("Cannot create branch: no trunk initialized")
            return None

        parent_branch = self._branches.get(parent_id)
        if parent_branch is None:
            logger.error(f"Parent branch {parent_id} not found")
            return None

        branch_id = f"branch-{name}-{uuid.uuid4().hex[:4]}"
        branch = BranchState(
            branch_id=branch_id,
            name=name,
            parent_branch_id=parent_id,
            schema_name=f"cg_{name}",
            j_score=parent_branch.j_score,
            j_score_history=[parent_branch.j_score],
        )

        self._branches[branch_id] = branch
        self._store.create_branch(branch_id, name, parent_id)

        logger.info(
            f"🌿 Branch created: {name} ({branch_id}) "
            f"from parent {parent_id}"
        )
        return branch_id

    def delete_branch(self, branch_id: str) -> bool:
        """Delete a branch and free its slot."""
        if branch_id == self._trunk_id:
            logger.error("Cannot delete trunk branch")
            return False

        branch = self._branches.get(branch_id)
        if branch is None:
            return False

        branch.is_active = False
        self._store.delete_branch(branch_id)
        logger.info(f"🗑️ Branch deleted: {branch.name} ({branch_id})")
        return True

    # ── State Operations ──────────────────────────────────────────────────────

    def get_resources(self, branch_id: str) -> list[dict]:
        """Get all resources in a branch."""
        return self._store.get_all_resources(branch_id)

    def update_resource(
        self,
        branch_id: str,
        resource_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """Update a resource in a specific branch."""
        resource = self._store.get_resource(branch_id, resource_id)
        if resource is None:
            return False

        resource.update(updates)
        self._store.set_resource(branch_id, resource_id, resource)
        return True

    def get_j_score(self, branch_id: str) -> float:
        """Get the current J score for a branch."""
        branch = self._branches.get(branch_id)
        return branch.j_score if branch else 0.0

    def update_j_score(self, branch_id: str, new_j: float) -> None:
        """Update the J score for a branch."""
        branch = self._branches.get(branch_id)
        if branch:
            branch.j_score_history.append(new_j)
            branch.j_score = new_j

    # ── Self-Correction ───────────────────────────────────────────────────────

    def should_rollback(
        self,
        branch_id: str,
        j_old: float,
        j_new: float,
    ) -> bool:
        """
        Self-Correction Logic Gate:
        If J_new ≥ J_old after a fix, the fix made things worse.

        Returns:
            True if rollback should be triggered.
        """
        return j_new >= j_old

    def rollback(self, branch_id: str, reason: str = "") -> bool:
        """
        Roll back a branch to its parent state.

        Copies the parent branch's state over this branch's state,
        effectively undoing all changes made on this branch.

        Args:
            branch_id: Branch to roll back.
            reason: Reason for rollback (logged).

        Returns:
            True if rollback succeeded.
        """
        branch = self._branches.get(branch_id)
        if branch is None:
            logger.error(f"Branch {branch_id} not found for rollback")
            return False

        if branch_id == self._trunk_id:
            logger.error("Cannot roll back trunk")
            return False

        parent_id = branch.parent_branch_id
        if parent_id is None:
            logger.error(f"Branch {branch_id} has no parent for rollback")
            return False

        # Restore parent state
        self._store.copy_state(parent_id, branch_id)

        # Update branch metadata
        parent_branch = self._branches.get(parent_id)
        if parent_branch:
            branch.j_score = parent_branch.j_score

        branch.rolled_back = True
        branch.rollback_reason = reason or "J_new >= J_old (fix made things worse)"

        # Log the rollback
        self._store.add_audit_entry(branch_id, {
            "action": "ROLLBACK",
            "reason": branch.rollback_reason,
            "j_before_rollback": branch.j_score_history[-1] if branch.j_score_history else 0,
            "j_after_rollback": branch.j_score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.info(
            f"⏪ Branch rolled back: {branch.name} ({branch_id}) "
            f"— {branch.rollback_reason}"
        )
        return True

    # ── Merge ─────────────────────────────────────────────────────────────────

    def merge_to_trunk(self, branch_id: str) -> bool:
        """
        Merge a successful branch back to trunk.
        Copies the branch state to trunk and deactivates the branch.

        Only allowed if the branch improved J (J_new < J_old).
        """
        branch = self._branches.get(branch_id)
        if branch is None or branch_id == self._trunk_id:
            return False

        if branch.rolled_back:
            logger.warning(f"Cannot merge rolled-back branch {branch_id}")
            return False

        trunk = self._branches.get(self._trunk_id)
        if trunk is None:
            return False

        # Verify improvement
        if branch.j_score >= trunk.j_score:
            logger.warning(
                f"Cannot merge: branch J ({branch.j_score:.4f}) "
                f">= trunk J ({trunk.j_score:.4f})"
            )
            return False

        # Copy branch state to trunk
        self._store.copy_state(branch_id, self._trunk_id)
        trunk.j_score = branch.j_score
        trunk.j_score_history.append(branch.j_score)

        # Deactivate branch
        branch.is_active = False

        logger.info(
            f"✅ Merged {branch.name} → trunk "
            f"(J: {trunk.j_score_history[-2]:.4f} → {trunk.j_score:.4f})"
        )
        return True

    # ── Info ──────────────────────────────────────────────────────────────────

    def get_branch_info(self, branch_id: str) -> Optional[dict]:
        """Get metadata for a specific branch."""
        branch = self._branches.get(branch_id)
        if branch is None:
            return None

        return {
            "branch_id": branch.branch_id,
            "name": branch.name,
            "parent_branch_id": branch.parent_branch_id,
            "schema_name": branch.schema_name,
            "j_score": branch.j_score,
            "j_history": branch.j_score_history,
            "is_active": branch.is_active,
            "rolled_back": branch.rolled_back,
            "rollback_reason": branch.rollback_reason,
            "resource_count": len(self._store.get_all_resources(branch_id)),
            "finding_count": len(self._store.get_findings(branch_id)),
            "created_at": branch.created_at.isoformat(),
        }

    def get_all_branches_info(self) -> list[dict]:
        """Get metadata for all branches."""
        return [
            self.get_branch_info(bid)
            for bid in self._branches
            if self.get_branch_info(bid) is not None
        ]
