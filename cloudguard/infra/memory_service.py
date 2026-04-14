"""
HEURISTIC MEMORY SERVICE (H-MEM) — VECTOR STORE
=================================================
Phase 2 Module 3 — Cognitive Cloud OS

Implements ChromaDB-backed heuristic remediation storage for
"Conceptual Transfer" — enabling sub-minute MTTR by recalling
past victories and applying Pareto-optimal fixes without
re-running the full swarm negotiation.

Architecture:
  1. store_victory() → Index successful remediations with J-score deltas
  2. query_victory() → Vector similarity search for Pareto-optimal matches
  3. HeuristicProposal → Bypass Round 1 of negotiation if similarity > 0.85

Academic References:
  - Conceptual Transfer: Pan & Yang (2010) — Transfer Learning Survey
  - Pareto Optimality: Deb et al. (2002) — NSGA-II
  - Vector Similarity: Mikolov et al. (2013) — Word2Vec for semantic matching

Design Decisions:
  - ChromaDB is OPTIONAL — falls back to in-memory cosine similarity
  - Indexed by drift_type (primary key) + resource_type (metadata)
  - Similarity threshold 0.85 → HeuristicProposal can bypass Round 1
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("cloudguard.memory_service")

# ── Optional ChromaDB import ─────────────────────────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    logger.info("ChromaDB not available — using in-memory heuristic store")


# ═══════════════════════════════════════════════════════════════════════════════
# SEMANTIC STRIPPER — INPUT SANITIZATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

# Keys that carry infrastructure noise rather than security semantics.
# These change on every event and poison cosine similarity.
_VOLATILE_KEYS = frozenset({
    "timestamp_tick", "trace_id", "kernel_id", "timestamp",
    "request_id", "event_id", "victory_id", "proposal_id",
    # description embeds the resource_id inline (e.g., "S3 bucket prod-bucket-01")
    # and cumulative_drift_score can vary between identical threat patterns.
    "description", "cumulative_drift_score",
})


def _anonymize_resource_id(resource_id: str) -> str:
    """
    Convert a specific resource identifier to its type-only token.

    Examples:
        's3-customer-data-482'  → 'S3'
        'ec2-i-0abc123'         → 'EC2'
        'rds-prod-db-01'        → 'RDS'
        'arn:aws:s3:::bucket'   → 'S3'

    This keeps the *kind* of resource (vital for pattern matching)
    while stripping the unique suffix (semantic noise).
    """
    if not resource_id:
        return "UNKNOWN"

    rid = resource_id.lower().strip()

    # Handle ARN-style identifiers
    if rid.startswith("arn:"):
        parts = rid.split(":")
        if len(parts) >= 3:
            return parts[2].upper()  # e.g., 's3', 'ec2', 'iam'

    # Extract leading alphabetic prefix (e.g., 's3', 'ec2', 'rds')
    prefix_match = re.match(r'^([a-zA-Z][a-zA-Z0-9]*)(?:[-_.]|$)', rid)
    if prefix_match:
        prefix = prefix_match.group(1).upper()
        # Map known short prefixes to canonical names
        _CANONICAL = {
            "S3": "S3", "EC2": "EC2", "RDS": "RDS", "IAM": "IAM",
            "EBS": "EBS", "ELB": "ELB", "VPC": "VPC", "ECS": "ECS",
            "EKS": "EKS", "LAMBDA": "LAMBDA", "SNS": "SNS", "SQS": "SQS",
        }
        return _CANONICAL.get(prefix, prefix)

    return "RESOURCE"


def sanitize_for_embedding(drift_json: dict) -> str:
    """
    Strips infrastructure noise to isolate the 'Security DNA' of a drift.

    The Semantic Stripper removes the "Unchecked Volatility Trio":
      1. timestamp_tick — changes every clock increment
      2. trace_id / kernel_id — high-entropy UUIDs
      3. resource_id (unique suffixes) — forces identical policy
         failures to look like different episodes

    Result: identical security scenarios produce >0.90 cosine similarity
    instead of the ~0.33 we observed with raw input.

    Args:
        drift_json: Raw drift event dict with noisy infrastructure fields.

    Returns:
        Canonical string suitable for bag-of-words or dense embedding.
    """
    # 1. Strip volatile keys entirely
    clean = {k: v for k, v in drift_json.items() if k not in _VOLATILE_KEYS}

    # 2. Anonymize resource IDs → type-only tokens
    if "resource_id" in clean:
        clean["resource_type"] = _anonymize_resource_id(
            str(clean.pop("resource_id"))
        )

    # 3. Flatten nested dicts to promote their keys (mutations, etc.)
    flat_parts: list[str] = []
    for k, v in sorted(clean.items()):
        if isinstance(v, dict):
            for sk, sv in sorted(v.items()):
                flat_parts.append(f"{k}_{sk}={sv}")
        elif isinstance(v, (list, tuple)):
            flat_parts.append(f"{k}={'|'.join(str(x) for x in v)}")
        else:
            flat_parts.append(f"{k}={v}")

    return " ".join(flat_parts)


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class VictorySummary:
    """
    A successful remediation event stored in H-MEM.
    Encodes the 'what worked' knowledge for future drift events.
    """

    victory_id: str = field(
        default_factory=lambda: f"vic-{uuid.uuid4().hex[:8]}"
    )
    drift_type: str = ""  # Primary key category
    resource_type: str = ""  # Metadata for filtering
    resource_id: str = ""
    remediation_action: str = ""  # e.g., "block_public_access"
    remediation_tier: str = "silver"  # gold/silver/bronze
    fix_parameters: dict[str, Any] = field(default_factory=dict)
    raw_drift: dict[str, Any] = field(default_factory=dict)

    # ── J-Score Impact ────────────────────────────────────────────────────────
    j_before: float = 0.0
    j_after: float = 0.0
    j_improvement: float = 0.0  # Calculated: j_before - j_after

    # ── Cost Impact ───────────────────────────────────────────────────────────
    risk_delta: float = 0.0
    cost_delta: float = 0.0

    # ── Context ───────────────────────────────────────────────────────────────
    environment: str = "production"  # prod/dev/staging
    reasoning: str = ""  # Agent's chain-of-evidence
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_document(self) -> str:
        """Convert to a searchable text document for vector embedding (legacy)."""
        return (
            f"Drift: {self.drift_type} on {self.resource_type} "
            f"({self.resource_id}). "
            f"Fixed with: {self.remediation_action} "
            f"(tier={self.remediation_tier}). "
            f"J improved from {self.j_before:.4f} to {self.j_after:.4f} "
            f"(Δ={self.j_improvement:.4f}). "
            f"Risk Δ={self.risk_delta:.2f}, Cost Δ=${self.cost_delta:.2f}. "
            f"Environment: {self.environment}. "
            f"Reasoning: {self.reasoning}"
        )

    def to_semantic_document(self) -> str:
        """
        Convert to a *sanitized* embedding document via the Semantic Stripper.

        Strips the "Unchecked Volatility Trio" (timestamp_tick, trace_id,
        resource_id suffix) and produces a canonical string that represents
        only the security DNA of the remediation victory.

        Two victories for the same drift_type + remediation_action on
        the same resource *type* will produce near-identical documents,
        enabling >0.90 cosine similarity for the Round 1 Bypass.
        """
        if getattr(self, "raw_drift", None):
            return sanitize_for_embedding(self.raw_drift)
            
        resource_type = self.resource_type or _anonymize_resource_id(self.resource_id)
        return (
            f"drift_type={self.drift_type} "
            f"resource_type={resource_type} "
            f"remediation_action={self.remediation_action} "
            f"remediation_tier={self.remediation_tier} "
            f"environment={self.environment}"
        )

    def to_metadata(self) -> dict[str, Any]:
        """Convert to ChromaDB-compatible metadata dict."""
        return {
            "victory_id": self.victory_id,
            "drift_type": self.drift_type,
            "resource_type": self.resource_type,
            "remediation_action": self.remediation_action,
            "remediation_tier": self.remediation_tier,
            "j_before": self.j_before,
            "j_after": self.j_after,
            "j_improvement": self.j_improvement,
            "risk_delta": self.risk_delta,
            "cost_delta": self.cost_delta,
            "environment": self.environment,
            "timestamp": self.timestamp.isoformat(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Full serialization for JSON export."""
        return {
            **self.to_metadata(),
            "resource_id": self.resource_id,
            "fix_parameters": self.fix_parameters,
            "reasoning": self.reasoning,
        }


@dataclass
class HeuristicProposal:
    """
    A pre-computed remediation proposal from H-MEM.
    If the similarity score is > 0.85, the Orchestrator can use this
    to bypass Round 1 of negotiation (sub-minute MTTR).
    """

    proposal_id: str = field(
        default_factory=lambda: f"heur-{uuid.uuid4().hex[:8]}"
    )
    source_victory_id: str = ""
    similarity_score: float = 0.0
    drift_type: str = ""
    resource_type: str = ""

    # ── Proposed Fix ──────────────────────────────────────────────────────────
    remediation_action: str = ""
    remediation_tier: str = "silver"
    fix_parameters: dict[str, Any] = field(default_factory=dict)
    raw_drift: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""

    # ── Expected Impact (from historical victory) ─────────────────────────────
    expected_j_improvement: float = 0.0
    expected_risk_delta: float = 0.0
    expected_cost_delta: float = 0.0

    # ── Bypass Logic ──────────────────────────────────────────────────────────
    can_bypass_round1: bool = False  # True if similarity > 0.85
    confidence: str = "low"  # low/medium/high

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "source_victory_id": self.source_victory_id,
            "similarity_score": self.similarity_score,
            "drift_type": self.drift_type,
            "resource_type": self.resource_type,
            "remediation_action": self.remediation_action,
            "remediation_tier": self.remediation_tier,
            "fix_parameters": self.fix_parameters,
            "reasoning": self.reasoning,
            "expected_j_improvement": self.expected_j_improvement,
            "expected_risk_delta": self.expected_risk_delta,
            "expected_cost_delta": self.expected_cost_delta,
            "can_bypass_round1": self.can_bypass_round1,
            "confidence": self.confidence,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY FALLBACK: COSINE SIMILARITY
# ═══════════════════════════════════════════════════════════════════════════════


def _text_to_vector(text: str) -> dict[str, float]:
    """
    Simple bag-of-words TF vector for in-memory similarity.
    Used when ChromaDB is not installed.
    """
    words = text.lower().split()
    vector: dict[str, float] = {}
    for word in words:
        # Strip punctuation
        clean = "".join(c for c in word if c.isalnum() or c == "_")
        if clean:
            vector[clean] = vector.get(clean, 0.0) + 1.0
    return vector


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Compute cosine similarity between two sparse vectors."""
    all_keys = set(a.keys()) | set(b.keys())
    if not all_keys:
        return 0.0

    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in all_keys)
    mag_a = math.sqrt(sum(v ** 2 for v in a.values()))
    mag_b = math.sqrt(sum(v ** 2 for v in b.values()))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY SERVICE
# ═══════════════════════════════════════════════════════════════════════════════


class MemoryService:
    """
    Heuristic Memory Service (H-MEM) backed by ChromaDB.

    Stores successful remediations as "Victory Summaries" and retrieves
    Pareto-optimal fixes via vector similarity search.

    Graceful Fallback:
      - If ChromaDB is installed → uses persistent vector store
      - Otherwise → in-memory cosine similarity with bag-of-words vectors

    Usage:
        mem = MemoryService()
        mem.initialize()

        # Store a victory
        mem.store_victory(victory_summary)

        # Query for heuristic match
        proposal = mem.query_victory(drift_type="public_exposure",
                                      resource_type="S3")

        if proposal and proposal.can_bypass_round1:
            # Skip Round 1 — apply heuristic fix directly
            ...
    """

    # Similarity threshold for bypassing Round 1
    BYPASS_THRESHOLD = 0.85
    COLLECTION_NAME = "cloudguard_victories"

    def __init__(
        self,
        persist_directory: Optional[str] = None,
        bypass_threshold: float = 0.85,
    ) -> None:
        self._persist_dir = persist_directory
        self.BYPASS_THRESHOLD = bypass_threshold
        self._initialized = False

        # ChromaDB handles
        self._client = None
        self._collection = None

        # In-memory fallback
        self._victories: list[VictorySummary] = []
        self._vectors: list[dict[str, float]] = []

        # Stats
        self._store_count = 0
        self._query_count = 0
        self._bypass_count = 0

    def initialize(self) -> bool:
        """
        Initialize the memory service.
        Returns True if ChromaDB is available, False for in-memory mode.
        """
        if HAS_CHROMADB:
            try:
                if self._persist_dir:
                    self._client = chromadb.Client(
                        ChromaSettings(
                            chroma_db_impl="duckdb+parquet",
                            persist_directory=self._persist_dir,
                            anonymized_telemetry=False,
                        )
                    )
                else:
                    self._client = chromadb.Client()

                self._collection = self._client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                self._initialized = True
                logger.info(
                    f"🧠 H-MEM initialized with ChromaDB "
                    f"(collection={self.COLLECTION_NAME})"
                )
                return True
            except Exception as e:
                logger.warning(
                    f"🧠 ChromaDB initialization failed ({e}), "
                    f"falling back to in-memory mode"
                )

        # In-memory fallback
        self._initialized = True
        logger.info("🧠 H-MEM initialized in-memory mode (no ChromaDB)")
        return False

    # ─── Store Victory ────────────────────────────────────────────────────────

    def store_victory(self, victory: VictorySummary) -> str:
        """
        Store a successful remediation in H-MEM.

        Args:
            victory: The VictorySummary to index.

        Returns:
            The victory_id of the stored document.
        """
        if not self._initialized:
            self.initialize()

        # Calculate J improvement
        victory.j_improvement = victory.j_before - victory.j_after

        # Use the semantic document for vectorization (Semantic Stripper)
        # The legacy to_document() is kept for human-readable export.
        document = victory.to_semantic_document()
        metadata = victory.to_metadata()
        doc_id = victory.victory_id

        if self._collection is not None:
            try:
                self._collection.add(
                    documents=[document],
                    metadatas=[metadata],
                    ids=[doc_id],
                )
                self._store_count += 1
                logger.info(
                    f"🧠 Stored victory {doc_id}: "
                    f"{victory.drift_type} → {victory.remediation_action} "
                    f"(ΔJ={victory.j_improvement:.4f})"
                )
                return doc_id
            except Exception as e:
                logger.error(f"ChromaDB store failed: {e}")

        # In-memory fallback — vectorize the semantic document
        self._victories.append(victory)
        self._vectors.append(_text_to_vector(document))
        self._store_count += 1
        logger.info(
            f"🧠 Stored victory (in-memory) {doc_id}: "
            f"{victory.drift_type} → {victory.remediation_action} "
            f"(ΔJ={victory.j_improvement:.4f})"
        )
        return doc_id

    # ─── Query Victory ────────────────────────────────────────────────────────

    def query_victory(
        self,
        drift_type: str,
        resource_type: str = "",
        raw_logs: Optional[list[str]] = None,
        n_results: int = 3,
    ) -> Optional[HeuristicProposal]:
        """
        Query H-MEM for the Pareto-optimal fix for a new drift.

        Uses vector similarity to find the best historical match.
        If similarity > 0.85, returns a HeuristicProposal that can
        bypass Round 1 of the swarm negotiation.

        Args:
            drift_type: Category of drift (e.g., "public_exposure").
            resource_type: Type of resource (e.g., "S3").
            raw_logs: Optional raw log snippets for context.
            n_results: Number of top results to consider.

        Returns:
            HeuristicProposal if a match is found, None otherwise.
        """
        if not self._initialized:
            self.initialize()

        self._query_count += 1

        # Build the query document using the SAME semantic template
        # as VictorySummary.to_semantic_document() — this is critical
        # for achieving high cosine similarity on identical drifts.
        # We include ALL fields that to_semantic_document() emits so
        # the bag-of-words vectors overlap maximally.  For fields not
        # known at query time we omit them rather than guessing, but
        # drift_type + resource_type carry the dominant signal.
        # If raw logs are available, use the Semantic Stripper to build a highly accurate similarity query
        if raw_logs and len(raw_logs) > 0:
            try:
                import json
                drift_dict = json.loads(raw_logs[0])
                query_text = sanitize_for_embedding(drift_dict)
            except Exception:
                query_text = f"drift_type={drift_type} resource_type={resource_type}"
        else:
            query_text = f"drift_type={drift_type} resource_type={resource_type}"


        # ChromaDB path
        if self._collection is not None:
            try:
                where_filter = {"drift_type": drift_type}
                results = self._collection.query(
                    query_texts=[query_text],
                    n_results=min(n_results, max(self._store_count, 1)),
                    where=where_filter if resource_type == "" else {
                        "$and": [
                            {"drift_type": drift_type},
                            {"resource_type": resource_type},
                        ]
                    },
                )
                if results and results["documents"] and results["documents"][0]:
                    return self._build_proposal_from_chroma(results)
            except Exception as e:
                logger.warning(f"ChromaDB query failed ({e}), trying in-memory")

        # In-memory fallback
        return self._query_in_memory(query_text, drift_type, resource_type)

    def _build_proposal_from_chroma(self, results: dict) -> Optional[HeuristicProposal]:
        """Build a HeuristicProposal from ChromaDB query results."""
        if not results["metadatas"] or not results["metadatas"][0]:
            return None

        # ChromaDB returns distances, convert to similarity
        distances = results.get("distances", [[1.0]])[0]
        similarity = 1.0 - distances[0] if distances else 0.0

        metadata = results["metadatas"][0][0]
        return self._build_proposal(metadata, similarity)

    def _query_in_memory(
        self,
        query_text: str,
        drift_type: str,
        resource_type: str,
    ) -> Optional[HeuristicProposal]:
        """Fallback in-memory cosine similarity search."""
        if not self._victories:
            return None

        query_vec = _text_to_vector(query_text)
        best_score = 0.0
        best_idx = -1

        for i, (victory, vec) in enumerate(
            zip(self._victories, self._vectors)
        ):
            # Pre-filter by drift_type for efficiency
            if victory.drift_type != drift_type:
                continue
            if resource_type and victory.resource_type != resource_type:
                continue

            score = _cosine_similarity(query_vec, vec)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx < 0:
            # No drift_type match; search across all victories
            for i, vec in enumerate(self._vectors):
                score = _cosine_similarity(query_vec, vec)
                if score > best_score:
                    best_score = score
                    best_idx = i

        if best_idx < 0:
            return None

        victory = self._victories[best_idx]
        return self._build_proposal(victory.to_metadata(), best_score)

    def _build_proposal(
        self, metadata: dict[str, Any], similarity: float
    ) -> HeuristicProposal:
        """Build a HeuristicProposal from metadata and similarity score."""
        can_bypass = similarity >= self.BYPASS_THRESHOLD
        if can_bypass:
            self._bypass_count += 1

        # Determine confidence level
        if similarity >= 0.95:
            confidence = "high"
        elif similarity >= self.BYPASS_THRESHOLD:
            confidence = "medium"
        else:
            confidence = "low"

        j_improvement = metadata.get("j_improvement", 0.0)
        proposal = HeuristicProposal(
            source_victory_id=metadata.get("victory_id", ""),
            similarity_score=round(similarity, 4),
            drift_type=metadata.get("drift_type", ""),
            resource_type=metadata.get("resource_type", ""),
            remediation_action=metadata.get("remediation_action", ""),
            remediation_tier=metadata.get("remediation_tier", "silver"),
            reasoning=(
                f"H-MEM heuristic match (similarity={similarity:.2%}). "
                f"Historical fix '{metadata.get('remediation_action', '')}' "
                f"achieved ΔJ={j_improvement:.4f} in similar scenario."
            ),
            expected_j_improvement=j_improvement,
            expected_risk_delta=metadata.get("risk_delta", 0.0),
            expected_cost_delta=metadata.get("cost_delta", 0.0),
            can_bypass_round1=can_bypass,
            confidence=confidence,
        )

        logger.info(
            f"🧠 H-MEM query result: similarity={similarity:.2%}, "
            f"action={proposal.remediation_action}, "
            f"bypass={'YES' if can_bypass else 'NO'}"
        )
        return proposal

    # ─── Batch Operations ─────────────────────────────────────────────────────

    def get_all_victories(self) -> list[dict[str, Any]]:
        """Return all stored victories as dicts."""
        if self._collection is not None:
            try:
                all_docs = self._collection.get()
                return [
                    {**meta, "document": doc}
                    for meta, doc in zip(
                        all_docs.get("metadatas", []),
                        all_docs.get("documents", []),
                    )
                ]
            except Exception:
                pass
        return [v.to_dict() for v in self._victories]

    def clear(self) -> None:
        """Clear all stored victories."""
        if self._collection is not None and self._client is not None:
            try:
                self._client.delete_collection(self.COLLECTION_NAME)
                self._collection = self._client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception:
                pass
        self._victories.clear()
        self._vectors.clear()
        self._store_count = 0
        logger.info("🧠 H-MEM cleared")

    # ─── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get memory service statistics."""
        return {
            "initialized": self._initialized,
            "backend": "chromadb" if self._collection is not None else "in-memory",
            "victories_stored": self._store_count,
            "queries_executed": self._query_count,
            "round1_bypasses": self._bypass_count,
            "bypass_threshold": self.BYPASS_THRESHOLD,
            "in_memory_count": len(self._victories),
        }
