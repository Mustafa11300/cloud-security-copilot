"""
CLOUDGUARD-B — PHASE 4 HUMAN-GROUNDED LEARNING LOOP
=====================================================
ValidationQueue & Ground-Truth Batch Commit Manager

Architecture:
  Amber Alert fires → ForecastResult stored in Redis ValidationQueue
                   ↓
  Human operator reviews sequences in War Room
                   ↓
  Operator marks batch as "Verified Ground Truth"
                   ↓
  commit_truth_batch() → updates LSTM W_out weights (NOT automatic)

Key Design Decisions:
  1. NO automatic retraining. The model is NEVER updated without a
     human operator explicitly marking a batch as "Verified Ground Truth".
  2. Redis Queue (List): LPUSH / BRPOP pattern for durable storage.
     Key: cloudguard:validation_queue
  3. Pending batches are kept in: cloudguard:vq:pending:<batch_id>
  4. Committed truth labels stored in: cloudguard:vq:committed

Mathematical Note:
  Weight update uses minibatch gradient descent on cross-entropy loss:
    L = -Σ y_i · log(P_i + ε)
    ΔW_out = -α · Σ (P_i - y_i) ⊗ h_i   (analytical CE gradient)
  Only the output layer (W_out, b_out) is updated per batch.
  The LSTM hidden weights are frozen until a full retrain is authorized
  by human sign-off (kept separate from this module).

Redis Schema:
  cloudguard:validation_queue       LIST  — raw sequence JSON
  cloudguard:vq:pending:<batch_id>  HASH  — sequences + predicted labels
  cloudguard:vq:committed           LIST  — committed (label, sequence) pairs
  cloudguard:vq:audit_log           LIST  — full audit trail of human decisions
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("cloudguard.validation_queue")

# ─── Redis key constants ───────────────────────────────────────────────────────
VQ_QUEUE_KEY       = "cloudguard:validation_queue"
VQ_PENDING_PREFIX  = "cloudguard:vq:pending"
VQ_COMMITTED_KEY   = "cloudguard:vq:committed"
VQ_AUDIT_LOG_KEY   = "cloudguard:vq:audit_log"

# ─── Learning hyper-parameters ────────────────────────────────────────────────
LEARNING_RATE      = 0.001
MAX_BATCH_SIZE     = 50    # Max sequences per commit batch


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationEntry:
    """
    A single Amber Alert sequence awaiting human ground-truth labeling.
    Stored in the Redis ValidationQueue.
    """
    entry_id: str = field(default_factory=lambda: f"vq-{uuid.uuid4().hex[:8]}")
    forecast_id: str = ""
    alert_id: str = ""                  # OMEGA-NNN identifier
    target_resource_id: str = ""
    predicted_drift_type: str = ""
    probability: float = 0.0
    recon_pattern_name: str = ""
    # The raw sequence tensor (serialized as list of lists)
    sequence_tensor: list[list[float]] = field(default_factory=list)
    # LSTM probabilities at time of alert
    class_probabilities: dict[str, float] = field(default_factory=dict)
    # Human label (filled in after verification)
    verified_label: Optional[str] = None        # drift type string
    verified_label_idx: Optional[int] = None    # class index
    is_true_positive: Optional[bool] = None     # operator judgment
    operator_id: str = ""
    operator_notes: str = ""
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    verified_at: Optional[datetime] = None

    def to_redis_json(self) -> str:
        """Serialize for Redis storage."""
        d = {
            "entry_id":            self.entry_id,
            "forecast_id":         self.forecast_id,
            "alert_id":            self.alert_id,
            "target_resource_id":  self.target_resource_id,
            "predicted_drift_type": self.predicted_drift_type,
            "probability":         self.probability,
            "recon_pattern_name":  self.recon_pattern_name,
            "sequence_tensor":     self.sequence_tensor,
            "class_probabilities": self.class_probabilities,
            "verified_label":      self.verified_label,
            "verified_label_idx":  self.verified_label_idx,
            "is_true_positive":    self.is_true_positive,
            "operator_id":         self.operator_id,
            "operator_notes":      self.operator_notes,
            "queued_at":           self.queued_at.isoformat(),
            "verified_at":         self.verified_at.isoformat() if self.verified_at else None,
        }
        return json.dumps(d, default=str)

    @classmethod
    def from_redis_json(cls, raw: str) -> "ValidationEntry":
        d = json.loads(raw)
        entry = cls(
            entry_id              = d.get("entry_id", ""),
            forecast_id           = d.get("forecast_id", ""),
            alert_id              = d.get("alert_id", ""),
            target_resource_id    = d.get("target_resource_id", ""),
            predicted_drift_type  = d.get("predicted_drift_type", ""),
            probability           = float(d.get("probability", 0.0)),
            recon_pattern_name    = d.get("recon_pattern_name", ""),
            sequence_tensor       = d.get("sequence_tensor", []),
            class_probabilities   = d.get("class_probabilities", {}),
            verified_label        = d.get("verified_label"),
            verified_label_idx    = d.get("verified_label_idx"),
            is_true_positive      = d.get("is_true_positive"),
            operator_id           = d.get("operator_id", ""),
            operator_notes        = d.get("operator_notes", ""),
        )
        if d.get("queued_at"):
            entry.queued_at = datetime.fromisoformat(d["queued_at"])
        if d.get("verified_at"):
            entry.verified_at = datetime.fromisoformat(d["verified_at"])
        return entry


@dataclass
class TruthBatch:
    """
    A labeled batch of ValidationEntry items marked as Verified Ground Truth
    by a human operator. Passed to commit_truth_batch() to update LSTM weights.
    """
    batch_id: str = field(default_factory=lambda: f"batch-{uuid.uuid4().hex[:8]}")
    entries: list[ValidationEntry] = field(default_factory=list)
    operator_id: str = ""
    approval_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    commit_status: str = "pending"   # pending | committed | failed
    weight_delta_norm: float = 0.0   # ||ΔW_out||_F after commit


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION QUEUE
# ═══════════════════════════════════════════════════════════════════════════════

class ValidationQueue:
    """
    Redis-backed queue for storing and retrieving Amber Alert sequences
    pending human ground-truth labeling.

    Queue Pattern:
        Enqueue: LPUSH cloudguard:validation_queue <entry_json>
        Dequeue: BRPOP cloudguard:validation_queue 0  (blocking pop)
        Batch: LRANGE cloudguard:validation_queue 0 <N-1>

    If Redis is unavailable, falls back to an in-memory deque as an
    ephemeral buffer (no durability guarantee flagged in logs).

    Usage:
        vq = ValidationQueue(redis_url="redis://localhost:6379")
        await vq.connect()

        # Store Amber Alert sequence
        await vq.enqueue(entry)

        # Get pending batch for human review
        batch = await vq.get_pending_batch(max_size=20)

        # After human labels entries, commit to LSTM
        results = await commit_truth_batch(batch, lstm_model)
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._in_memory: list[ValidationEntry] = []
        self._redis_available = False

    async def connect(self) -> bool:
        """
        Attempt to connect to Redis.
        Falls back silently to in-memory mode if Redis is unavailable.

        Returns:
            True if Redis connection succeeded, False if using in-memory fallback.
        """
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=3,
            )
            await client.ping()
            self._redis = client
            self._redis_available = True
            logger.info(f"✅ ValidationQueue connected to Redis: {self._redis_url}")
            return True
        except Exception as exc:
            logger.warning(
                f"⚠️  ValidationQueue: Redis unavailable ({exc}). "
                f"Using in-memory fallback — sequences will NOT persist across restarts."
            )
            self._redis_available = False
            return False

    async def enqueue(self, entry: ValidationEntry) -> str:
        """
        Store a ValidationEntry in the Redis queue.

        Args:
            entry: The Amber Alert sequence to store.

        Returns:
            entry_id of the stored entry.
        """
        payload = entry.to_redis_json()

        if self._redis_available and self._redis:
            try:
                await self._redis.lpush(VQ_QUEUE_KEY, payload)
                # Also store in a pending hash keyed by entry_id for random access
                await self._redis.hset(
                    f"{VQ_PENDING_PREFIX}:entries",
                    entry.entry_id,
                    payload,
                )
                logger.debug(
                    f"📥 ValidationQueue: enqueued {entry.entry_id} "
                    f"(alert={entry.alert_id}, P={entry.probability:.2%})"
                )
            except Exception as exc:
                logger.warning(f"ValidationQueue Redis enqueue error: {exc}")
                self._in_memory.append(entry)
        else:
            self._in_memory.append(entry)

        return entry.entry_id

    async def get_pending_batch(
        self,
        max_size: int = MAX_BATCH_SIZE,
    ) -> list[ValidationEntry]:
        """
        Retrieve up to max_size unverified entries for human review.
        Does NOT dequeue them — entries remain until commit or expiry.

        Returns:
            List of ValidationEntry items for the human operator to label.
        """
        if self._redis_available and self._redis:
            try:
                raws = await self._redis.lrange(VQ_QUEUE_KEY, 0, max_size - 1)
                return [ValidationEntry.from_redis_json(r) for r in raws]
            except Exception as exc:
                logger.warning(f"ValidationQueue Redis get_pending error: {exc}")

        return self._in_memory[:max_size]

    async def pending_count(self) -> int:
        """Return the number of items awaiting human verification."""
        if self._redis_available and self._redis:
            try:
                return int(await self._redis.llen(VQ_QUEUE_KEY))
            except Exception:
                pass
        return len(self._in_memory)

    async def mark_verified(
        self,
        entry_id: str,
        verified_label: str,
        verified_label_idx: int,
        is_true_positive: bool,
        operator_id: str,
        notes: str = "",
    ) -> Optional[ValidationEntry]:
        """
        Mark a specific entry as Verified Ground Truth by the human operator.

        This does NOT update the LSTM yet — that only happens in commit_truth_batch().

        Args:
            entry_id:          ID of the entry to verify.
            verified_label:    Human-assigned drift type label.
            verified_label_idx: Class index (0-based) for LSTM training.
            is_true_positive:  Did this sequence represent a real threat?
            operator_id:       ID of the approving human operator.
            notes:             Optional operator notes.

        Returns:
            Updated ValidationEntry, or None if not found.
        """
        entry = await self._find_entry(entry_id)
        if not entry:
            logger.warning(f"ValidationQueue: entry {entry_id} not found")
            return None

        entry.verified_label     = verified_label
        entry.verified_label_idx = verified_label_idx
        entry.is_true_positive   = is_true_positive
        entry.operator_id        = operator_id
        entry.operator_notes     = notes
        entry.verified_at        = datetime.now(timezone.utc)

        # Update in Redis
        if self._redis_available and self._redis:
            try:
                await self._redis.hset(
                    f"{VQ_PENDING_PREFIX}:verified",
                    entry_id,
                    entry.to_redis_json(),
                )
                # Audit trail
                audit = {
                    "entry_id":       entry_id,
                    "operator_id":    operator_id,
                    "verified_label": verified_label,
                    "is_true_positive": is_true_positive,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                    "notes":          notes,
                }
                await self._redis.lpush(VQ_AUDIT_LOG_KEY, json.dumps(audit))
            except Exception as exc:
                logger.warning(f"ValidationQueue Redis mark_verified error: {exc}")

        logger.info(
            f"✅ ValidationQueue: {entry_id} verified by {operator_id} "
            f"as '{verified_label}' (TP={is_true_positive})"
        )
        return entry

    async def _find_entry(self, entry_id: str) -> Optional[ValidationEntry]:
        """Lookup an entry by ID from Redis or in-memory."""
        if self._redis_available and self._redis:
            try:
                raw = await self._redis.hget(
                    f"{VQ_PENDING_PREFIX}:entries", entry_id
                )
                if raw:
                    return ValidationEntry.from_redis_json(raw)
            except Exception:
                pass
        for e in self._in_memory:
            if e.entry_id == entry_id:
                return e
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# GROUND-TRUTH BATCH COMMIT  (Human-Gated LSTM Weight Update)
# ═══════════════════════════════════════════════════════════════════════════════

async def commit_truth_batch(
    batch: TruthBatch,
    lstm_model: Any,                   # LSTMForecaster instance
    validation_queue: Optional[ValidationQueue] = None,
    learning_rate: float = LEARNING_RATE,
) -> dict[str, Any]:
    """
    Update the LSTM output-layer weights (W_out, b_out) using the
    human-verified ground-truth labels in the batch.

    ─── CRITICAL SAFETY GATE ────────────────────────────────────────────────────
    This function MUST ONLY be called after a human operator has explicitly
    marked the batch as "Verified Ground Truth" in the War Room.
    There is NO automatic invocation path. The operator approval is the gate.

    Mathematical update (minibatch SGD on cross-entropy):
        For each verified entry (sequence tensor X, label y):
            ĥ = LSTM_forward(X)           — re-run forward pass
            P = softmax(W_out · ĥ + b_out) — current predictions
            L = -log(P[y] + ε)            — cross-entropy loss
            ΔW_out = (P - Y) ⊗ ĥ          — gradient (analytical)
            W_out -= α · ΔW_out           — SGD step
            b_out -= α · (P - Y)

    IMPORTANT:
        - Only W_out and b_out are updated. LSTM hidden weights are FROZEN.
        - Full retrain (including LSTMCell weights) requires separate
          human-authorized training session via train_on_pattern().

    Args:
        batch:            TruthBatch with human-verified entries.
        lstm_model:       LSTMForecaster instance to update.
        validation_queue: If provided, move committed entries to VQ_COMMITTED_KEY.
        learning_rate:    SGD learning rate override.

    Returns:
        Dict with commit statistics:
            batch_id, entries_committed, skipped, losses, delta_norm, timestamp.
    """
    if not batch.entries:
        logger.warning("commit_truth_batch: empty batch — nothing to commit")
        return {
            "batch_id":          batch.batch_id,
            "entries_committed": 0,
            "skipped":           0,
            "losses":            [],
            "delta_norm":        0.0,
            "status":            "empty_batch",
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }

    # ── Audit gate ────────────────────────────────────────────────────────────
    if not batch.operator_id:
        raise PermissionError(
            "commit_truth_batch: operator_id MUST be set on the TruthBatch. "
            "No anonymous weight updates permitted. "
            "[NIST AI RMF — Govern 2.2 — Human Oversight]"
        )

    logger.info(
        f"🔬 commit_truth_batch: Processing batch {batch.batch_id} "
        f"({len(batch.entries)} entries, operator={batch.operator_id})"
    )

    # ── Snapshot weights before update ───────────────────────────────────────
    W_out_before = lstm_model.W_out.copy()
    b_out_before = lstm_model.b_out.copy()

    losses = []
    skipped = 0
    committed = 0

    # ── Per-entry weight update ───────────────────────────────────────────────
    for entry in batch.entries:
        # Skip if not verified or not a true positive (false positives teach nothing)
        if entry.verified_label_idx is None:
            logger.debug(f"  → Skipping unverified entry {entry.entry_id}")
            skipped += 1
            continue
        if entry.is_true_positive is False:
            logger.debug(
                f"  → Skipping false positive {entry.entry_id} "
                f"(label: '{entry.verified_label}')"
            )
            skipped += 1
            continue

        # Reconstruct tensor from stored list-of-lists
        try:
            seq_tensor = np.array(entry.sequence_tensor, dtype=np.float32)
            if seq_tensor.ndim != 2 or seq_tensor.shape[1] != lstm_model.input_dim:
                logger.warning(
                    f"  ⚠️  {entry.entry_id}: tensor shape {seq_tensor.shape} "
                    f"incompatible with model input_dim={lstm_model.input_dim} — skip"
                )
                skipped += 1
                continue
        except Exception as exc:
            logger.warning(f"  ⚠️  {entry.entry_id}: tensor reconstruct failed ({exc}) — skip")
            skipped += 1
            continue

        target_class = entry.verified_label_idx

        # Run forward pass to get current predictions + final hidden state
        seq_len = seq_tensor.shape[0]
        h = np.zeros(lstm_model.hidden_dim, dtype=np.float32)
        c = np.zeros(lstm_model.hidden_dim, dtype=np.float32)
        for t in range(seq_len):
            h, c = lstm_model.cell.forward(seq_tensor[t], h, c)

        # Dense layer forward
        logits = lstm_model.W_out @ h + lstm_model.b_out

        # Softmax (reuse model's static method)
        probs = lstm_model._softmax(logits)

        # Cross-entropy loss
        loss = -float(np.log(probs[target_class] + 1e-10))
        losses.append(loss)

        # Gradient of softmax + cross-entropy (analytical: dL/dz = P - Y)
        grad_logits = probs.copy()
        grad_logits[target_class] -= 1.0

        # SGD update on output layer ONLY
        dW_out = np.outer(grad_logits, h)
        lstm_model.W_out -= learning_rate * dW_out
        lstm_model.b_out -= learning_rate * grad_logits

        committed += 1
        logger.debug(
            f"  ✅ {entry.entry_id}: label='{entry.verified_label}' "
            f"(class={target_class}), loss={loss:.4f}"
        )

    # ── Delta norm (measure of weight change) ─────────────────────────────────
    delta_W   = lstm_model.W_out - W_out_before
    delta_b   = lstm_model.b_out - b_out_before
    delta_norm = float(np.sqrt(np.sum(delta_W**2) + np.sum(delta_b**2)))

    avg_loss = float(np.mean(losses)) if losses else 0.0

    batch.commit_status     = "committed" if committed > 0 else "skipped"
    batch.weight_delta_norm = delta_norm

    # ── Persist committed entries to Redis ────────────────────────────────────
    if validation_queue and committed > 0:
        if validation_queue._redis_available and validation_queue._redis:
            try:
                commit_record = {
                    "batch_id":      batch.batch_id,
                    "operator_id":   batch.operator_id,
                    "committed":     committed,
                    "skipped":       skipped,
                    "avg_loss":      avg_loss,
                    "delta_norm":    delta_norm,
                    "timestamp":     datetime.now(timezone.utc).isoformat(),
                    "entry_ids":     [e.entry_id for e in batch.entries],
                }
                await validation_queue._redis.lpush(
                    VQ_COMMITTED_KEY, json.dumps(commit_record)
                )
                # Audit trail
                await validation_queue._redis.lpush(
                    VQ_AUDIT_LOG_KEY,
                    json.dumps({
                        "event":      "weight_commit",
                        "batch_id":   batch.batch_id,
                        "operator":   batch.operator_id,
                        "committed":  committed,
                        "delta_norm": delta_norm,
                        "timestamp":  datetime.now(timezone.utc).isoformat(),
                    }),
                )
            except Exception as exc:
                logger.warning(f"commit_truth_batch: Redis persist error: {exc}")

    result = {
        "batch_id":          batch.batch_id,
        "operator_id":       batch.operator_id,
        "entries_committed": committed,
        "skipped":           skipped,
        "total_entries":     len(batch.entries),
        "losses":            [round(l, 6) for l in losses],
        "avg_loss":          round(avg_loss, 6),
        "delta_norm":        round(delta_norm, 8),
        "status":            batch.commit_status,
        "timestamp":         batch.approval_timestamp.isoformat(),
        "audit_note": (
            f"LSTM W_out updated by human-authorized batch {batch.batch_id}. "
            f"Operator: {batch.operator_id}. "
            f"Weight delta norm: {delta_norm:.6f}. "
            f"[NIST AI RMF — Govern 2.2 — Human Oversight of AI Learning]"
        ),
    }

    logger.info(
        f"🔬 commit_truth_batch COMPLETE: {committed} entries committed, "
        f"{skipped} skipped. Δ‖W_out‖={delta_norm:.6f}, avg_loss={avg_loss:.4f}. "
        f"Operator: {batch.operator_id}"
    )

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FACTORY  — Create ValidationEntry from ForecastResult
# ═══════════════════════════════════════════════════════════════════════════════

def entry_from_forecast(
    forecast_result: Any,       # ForecastResult from threat_forecaster
    sequence_tensor: Any,       # np.ndarray (window_size, feature_dim)
    alert_id: str = "",
) -> ValidationEntry:
    """
    Build a ValidationEntry from a ForecastResult for queue storage.

    Args:
        forecast_result: ForecastResult with P, drift type, recon details.
        sequence_tensor: The LSTM input tensor at time of alert.
        alert_id:        The Amber Alert OMEGA-NNN label.

    Returns:
        ValidationEntry ready for enqueueing.
    """
    return ValidationEntry(
        forecast_id           = forecast_result.forecast_id,
        alert_id              = alert_id,
        target_resource_id    = forecast_result.target_resource_id,
        predicted_drift_type  = forecast_result.predicted_drift_type,
        probability           = forecast_result.probability,
        recon_pattern_name    = forecast_result.recon_pattern_name,
        sequence_tensor       = sequence_tensor.tolist() if hasattr(sequence_tensor, "tolist") else sequence_tensor,
        class_probabilities   = dict(forecast_result.class_probabilities),
    )
