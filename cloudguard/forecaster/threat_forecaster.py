"""
THREAT FORECASTER — PROACTIVE INTELLIGENCE LAYER (Phase 4)
============================================================
LSTM-Powered Predictive Drift & Shadow AI Detection

Architecture:
  Redis truth_log → [Sliding Window] → [Vectorizer] → [LSTM Model] → [Prediction]
                                                                         ↓
  Shadow AI Detector ──────────────────────────────────────────→ [Amber Alert]
                                                                         ↓
  ProactiveSentry (LangGraph Node) ← ← ← ← ← ← ← ← ← ← ← ← [J_forecast]
                                                                         ↓
                                                              [War Room WS]

Key Components:
  1. SequenceProcessor: Sliding window (last 100 events) + vectorization
  2. LSTMForecaster: Lightweight Seq2Seq LSTM for pattern recognition
  3. ShadowAIDetector: Out-of-Band telemetry classification
  4. AmberAlertEmitter: P≥0.75 → wake Sentry → FORECAST_SIGNAL to WS
  5. ProactiveSentry: LangGraph node for J_forecast negotiation

Mathematical Framework:
  J_forecast = min Σ (w_R · P · R_i + w_C · C_i)
  Where P = LSTM prediction probability for each drift type.

Reconnaissance Pattern Detection:
  - Repeated DescribeRoles → ModifyPolicy = Recon+Exploit chain
  - Burst ListBuckets → PutBucketPolicy = S3 enumeration
  - Cross-account AssumeRole → CreateUser = Lateral movement

Academic References:
  - Hochreiter & Schmidhuber (1997): Long Short-Term Memory
  - Sequence-to-Sequence Learning: Sutskever et al. (2014)
  - Anomaly Detection via LSTM: Malhotra et al. (2015)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

import numpy as np

logger = logging.getLogger("cloudguard.forecaster")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMERATIONS & CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

class PredictedDriftType(str, Enum):
    """Drift types the LSTM model is trained to predict."""
    PERMISSION_ESCALATION = "permission_escalation"
    PUBLIC_EXPOSURE       = "public_exposure"
    ENCRYPTION_REMOVED    = "encryption_removed"
    NETWORK_RULE_CHANGE   = "network_rule_change"
    IAM_POLICY_CHANGE     = "iam_policy_change"
    OIDC_TRUST_BREACH     = "oidc_trust_breach"
    SHADOW_AI_SPAWN       = "shadow_ai_spawn"
    LATERAL_MOVEMENT      = "lateral_movement"
    DATA_EXFILTRATION     = "data_exfiltration"
    RECON_EXPLOIT_CHAIN   = "recon_exploit_chain"


# Canonical vocabulary for event type vectorization
EVENT_TYPE_VOCAB: dict[str, int] = {
    "permission_escalation": 0,
    "public_exposure":       1,
    "encryption_removed":    2,
    "network_rule_change":   3,
    "iam_policy_change":     4,
    "resource_created":      5,
    "resource_deleted":      6,
    "tag_removed":           7,
    "backup_disabled":       8,
    "cost_spike":            9,
    "oidc_trust_breach":    10,
    "shadow_ai_spawn":      11,
    # CloudTrail API call vocabulary
    "DescribeRoles":        12,
    "ModifyPolicy":         13,
    "ListBuckets":          14,
    "PutBucketPolicy":      15,
    "AssumeRole":           16,
    "CreateUser":           17,
    "GetObject":            18,
    "PutObject":            19,
    "DeleteObject":         20,
    "CreateRole":           21,
    "AttachRolePolicy":     22,
    "DetachRolePolicy":     23,
    "HEARTBEAT":            24,
    "DRIFT":                25,
    "REMEDIATION":          26,
    "UNKNOWN":              27,
}

# Tag-based vocabulary for resource context encoding
TAG_VOCAB: dict[str, int] = {
    "production":   0,
    "staging":      1,
    "development":  2,
    "Project":      3,
    "no_project":   4,
    "DataClass:PII": 5,
    "DataClass:PHI": 6,
    "DataClass:Public": 7,
    "Environment":  8,
    "Team":         9,
    "UNKNOWN_TAG": 10,
}

# Reconnaissance pattern signatures (ordered API call chains)
RECON_PATTERNS: list[list[str]] = [
    ["DescribeRoles", "DescribeRoles", "ModifyPolicy"],
    ["DescribeRoles", "DescribeRoles", "DescribeRoles", "AttachRolePolicy"],
    ["ListBuckets", "ListBuckets", "PutBucketPolicy"],
    ["AssumeRole", "CreateUser", "AttachRolePolicy"],
    ["AssumeRole", "AssumeRole", "CreateRole"],
    ["GetObject", "GetObject", "GetObject", "GetObject", "GetObject"],  # Bulk data access
    # ── Amber Sequence kill-chain (Phase 4) ──────────────────────────────────
    # DescribeRoles×3 → AssumeRole → CreateRole (OIDC pre-breach recon)
    ["DescribeRoles", "DescribeRoles", "DescribeRoles", "AssumeRole", "CreateRole"],
    # DescribeRoles×3 + any subsequent AssumeRole (shorter trigger)
    ["DescribeRoles", "DescribeRoles", "DescribeRoles", "AssumeRole"],
]

# ── Feature dimensions ────────────────────────────────────────────────────────
WINDOW_SIZE = 100          # Last 100 events
FEATURE_DIM = 8            # Per-event feature vector dimension
HIDDEN_DIM  = 64           # LSTM hidden state dimension
NUM_CLASSES = len(PredictedDriftType)  # Output classes
AMBER_THRESHOLD = 0.75     # P ≥ 0.75 → Amber Alert


# ═══════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TelemetryEvent:
    """A single telemetry/drift event in the sliding window."""
    event_id: str = ""
    resource_id: str = ""
    event_type: str = "UNKNOWN"
    drift_type: str = ""
    severity: str = "LOW"
    cpu_delta: float = 0.0       # CPU utilization change
    api_volume: float = 0.0      # API call count in this window
    network_out: float = 0.0     # Outbound network bytes
    gpu_utilization: float = 0.0 # GPU utilization (for Shadow AI)
    tags: dict[str, str] = field(default_factory=dict)
    timestamp_tick: int = 0
    timestamp_utc: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class ForecastResult:
    """Output of the LSTM prediction for a single tick."""
    forecast_id: str = field(
        default_factory=lambda: f"fc-{uuid.uuid4().hex[:8]}"
    )
    probability: float = 0.0                    # P ∈ [0, 1]
    predicted_drift_type: str = "UNKNOWN"       # Most likely drift
    class_probabilities: dict[str, float] = field(default_factory=dict)
    is_amber_alert: bool = False                # P ≥ 0.75
    is_shadow_ai: bool = False
    shadow_ai_details: Optional[dict] = None
    target_resource_id: str = ""
    horizon_ticks: int = 5                      # Prediction horizon
    recon_pattern_detected: bool = False
    recon_pattern_name: str = ""
    j_forecast: float = 0.0                     # Modified J-function value
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_id":         self.forecast_id,
            "probability":         round(self.probability, 4),
            "predicted_drift_type": self.predicted_drift_type,
            "class_probabilities": {
                k: round(v, 4) for k, v in self.class_probabilities.items()
            },
            "is_amber_alert":      self.is_amber_alert,
            "is_shadow_ai":        self.is_shadow_ai,
            "shadow_ai_details":   self.shadow_ai_details,
            "target_resource_id":  self.target_resource_id,
            "horizon_ticks":       self.horizon_ticks,
            "recon_pattern_detected": self.recon_pattern_detected,
            "recon_pattern_name":  self.recon_pattern_name,
            "j_forecast":          round(self.j_forecast, 6),
            "confidence_interval": (
                round(self.confidence_interval[0], 4),
                round(self.confidence_interval[1], 4),
            ),
            "timestamp":           self.timestamp.isoformat(),
        }

    def to_ws_payload(self) -> dict[str, Any]:
        """Build the War Room FORECAST_SIGNAL WebSocket payload."""
        return {
            "event_type": "FORECAST_SIGNAL",
            "event_id":   f"evt-{uuid.uuid4().hex[:8]}",
            "data": {
                "target":      self.target_resource_id,
                "probability": round(self.probability, 4),
                "type":        "Amber_Alert" if self.is_amber_alert else "Advisory",
                "horizon":     f"{self.horizon_ticks} ticks",
                "predicted_drift": self.predicted_drift_type,
                "is_shadow_ai":    self.is_shadow_ai,
                "j_forecast":      round(self.j_forecast, 6),
                "recon_chain":     self.recon_pattern_name or None,
                "confidence_lo":   round(self.confidence_interval[0], 4),
                "confidence_hi":   round(self.confidence_interval[1], 4),
            },
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SEQUENCE PROCESSOR — Sliding Window + Vectorization
# ═══════════════════════════════════════════════════════════════════════════════

class SequenceProcessor:
    """
    Sliding window of the last WINDOW_SIZE telemetry/drift events.
    Converts heterogeneous event data into a numerical tensor
    suitable for LSTM consumption.

    Vectorization Schema (per event, FEATURE_DIM=8):
      [0] event_type_encoded     — vocab index / max_vocab (normalized)
      [1] drift_severity_encoded — 0.0 (INFO) → 1.0 (CRITICAL)
      [2] cpu_delta_normalized   — CPU change / 100
      [3] api_volume_normalized  — log(1 + api_volume) / 10
      [4] network_out_normalized — log(1 + network_out) / 20
      [5] gpu_utilization        — GPU% / 100
      [6] has_project_tag        — 1.0 if Project tag exists, else 0.0
      [7] tag_hash_encoded       — hash of tags → [0, 1] for pattern matching
    """

    SEVERITY_MAP: dict[str, float] = {
        "INFO":     0.0,
        "LOW":      0.25,
        "MEDIUM":   0.5,
        "HIGH":     0.75,
        "CRITICAL": 1.0,
    }

    def __init__(self, window_size: int = WINDOW_SIZE) -> None:
        self._window: deque[TelemetryEvent] = deque(maxlen=window_size)
        self._window_size = window_size
        self._total_ingested = 0

    @property
    def window_size(self) -> int:
        return self._window_size

    @property
    def current_depth(self) -> int:
        return len(self._window)

    @property
    def total_ingested(self) -> int:
        return self._total_ingested

    def ingest(self, event: TelemetryEvent) -> None:
        """Add an event to the sliding window."""
        self._window.append(event)
        self._total_ingested += 1

    def ingest_from_redis(self, raw: dict[str, Any]) -> None:
        """
        Parse a raw Redis truth_log entry into a TelemetryEvent
        and add to the sliding window.
        """
        data = raw.get("data", raw)
        te = TelemetryEvent(
            event_id=raw.get("event_id", ""),
            resource_id=data.get("resource_id", ""),
            event_type=raw.get("event_type", data.get("event_name", "UNKNOWN")),
            drift_type=data.get("drift_type", ""),
            severity=data.get("severity", "LOW"),
            cpu_delta=float(data.get("cpu_delta", data.get("cpu_utilization", 0))),
            api_volume=float(data.get("api_volume", 1)),
            network_out=float(data.get("network_bytes_out", data.get("network_out", 0))),
            gpu_utilization=float(data.get("gpu_utilization", 0)),
            tags=data.get("tags", {}),
            timestamp_tick=raw.get("timestamp_tick", 0),
        )
        self.ingest(te)

    def vectorize(self) -> np.ndarray:
        """
        Convert the sliding window into a (window_size, FEATURE_DIM) tensor.
        If the window has fewer than window_size events, pad with zeros.
        """
        tensor = np.zeros((self._window_size, FEATURE_DIM), dtype=np.float32)
        events = list(self._window)

        for i, evt in enumerate(events):
            offset = self._window_size - len(events) + i
            tensor[offset] = self._vectorize_event(evt)

        return tensor

    def _vectorize_event(self, evt: TelemetryEvent) -> np.ndarray:
        """Convert a single TelemetryEvent into a FEATURE_DIM vector."""
        vec = np.zeros(FEATURE_DIM, dtype=np.float32)

        # [0] Event type encoding
        event_key = evt.drift_type or evt.event_type
        vocab_idx = EVENT_TYPE_VOCAB.get(event_key, EVENT_TYPE_VOCAB["UNKNOWN"])
        vec[0] = vocab_idx / max(len(EVENT_TYPE_VOCAB) - 1, 1)

        # [1] Severity encoding
        vec[1] = self.SEVERITY_MAP.get(evt.severity.upper(), 0.5)

        # [2] CPU delta (normalized to [0, 1])
        vec[2] = min(abs(evt.cpu_delta) / 100.0, 1.0)

        # [3] API volume (log-normalized)
        vec[3] = min(math.log1p(evt.api_volume) / 10.0, 1.0)

        # [4] Network outbound (log-normalized)
        vec[4] = min(math.log1p(evt.network_out) / 20.0, 1.0)

        # [5] GPU utilization (normalized)
        vec[5] = min(evt.gpu_utilization / 100.0, 1.0)

        # [6] Has Project tag (binary)
        vec[6] = 1.0 if evt.tags.get("Project") else 0.0

        # [7] Tag hash (deterministic embedding)
        tag_str = json.dumps(sorted(evt.tags.items())) if evt.tags else ""
        tag_hash = int(hashlib.md5(tag_str.encode()).hexdigest()[:8], 16)
        vec[7] = (tag_hash % 1000) / 1000.0

        return vec

    def get_event_type_sequence(self) -> list[str]:
        """Extract the ordered sequence of event/drift types for recon detection."""
        return [
            (evt.drift_type or evt.event_type)
            for evt in self._window
        ]

    def get_resource_telemetry(self) -> dict[str, dict[str, float]]:
        """
        Aggregate per-resource telemetry for Shadow AI detection.
        Returns {resource_id: {cpu, gpu, network_out, api_volume, has_project}}.
        """
        agg: dict[str, dict[str, list[float]]] = {}
        for evt in self._window:
            if not evt.resource_id:
                continue
            if evt.resource_id not in agg:
                agg[evt.resource_id] = {
                    "cpu": [], "gpu": [], "net_out": [], "api": [],
                    "has_project": [],
                }
            agg[evt.resource_id]["cpu"].append(evt.cpu_delta)
            agg[evt.resource_id]["gpu"].append(evt.gpu_utilization)
            agg[evt.resource_id]["net_out"].append(evt.network_out)
            agg[evt.resource_id]["api"].append(evt.api_volume)
            agg[evt.resource_id]["has_project"].append(
                1.0 if evt.tags.get("Project") else 0.0
            )

        result = {}
        for rid, metrics in agg.items():
            result[rid] = {
                "avg_cpu":         float(np.mean(metrics["cpu"])) if metrics["cpu"] else 0.0,
                "avg_gpu":         float(np.mean(metrics["gpu"])) if metrics["gpu"] else 0.0,
                "total_net_out":   float(np.sum(metrics["net_out"])),
                "total_api_calls": float(np.sum(metrics["api"])),
                "has_project":     float(np.mean(metrics["has_project"])),
                "event_count":     len(metrics["cpu"]),
            }
        return result

    def clear(self) -> None:
        """Reset the sliding window."""
        self._window.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. LSTM INTELLIGENCE NODE — Lightweight Sequence-to-Sequence Model
# ═══════════════════════════════════════════════════════════════════════════════

class LSTMCell:
    """
    Single LSTM cell implemented in pure NumPy.

    LSTM equations (Hochreiter & Schmidhuber, 1997):
      f_t = σ(W_f · [h_{t-1}, x_t] + b_f)    — Forget gate
      i_t = σ(W_i · [h_{t-1}, x_t] + b_i)    — Input gate
      ĉ_t = tanh(W_c · [h_{t-1}, x_t] + b_c) — Candidate cell state
      c_t = f_t ⊙ c_{t-1} + i_t ⊙ ĉ_t        — Cell state update
      o_t = σ(W_o · [h_{t-1}, x_t] + b_o)    — Output gate
      h_t = o_t ⊙ tanh(c_t)                   — Hidden state

    Weight initialization uses Xavier/Glorot uniform.
    """

    def __init__(self, input_dim: int, hidden_dim: int) -> None:
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        concat_dim = input_dim + hidden_dim

        # Xavier initialization
        scale = np.sqrt(2.0 / (concat_dim + hidden_dim))

        # Gate weights: [W_f, W_i, W_c, W_o] stacked
        self.W = np.random.randn(4 * hidden_dim, concat_dim).astype(np.float32) * scale
        self.b = np.zeros(4 * hidden_dim, dtype=np.float32)

        # Initialize forget gate bias to 1.0 (Jozefowicz et al., 2015)
        self.b[:hidden_dim] = 1.0

    @staticmethod
    def _sigmoid(x: np.ndarray) -> np.ndarray:
        """Numerically stable sigmoid activation."""
        return np.where(
            x >= 0,
            1.0 / (1.0 + np.exp(-np.clip(x, -500, 500))),
            np.exp(np.clip(x, -500, 500)) / (1.0 + np.exp(np.clip(x, -500, 500))),
        )

    def forward(
        self,
        x_t: np.ndarray,
        h_prev: np.ndarray,
        c_prev: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Forward pass for a single LSTM cell at time step t.

        Args:
            x_t:    Input vector [input_dim]
            h_prev: Previous hidden state [hidden_dim]
            c_prev: Previous cell state [hidden_dim]

        Returns:
            (h_t, c_t) — New hidden state and cell state.
        """
        concat = np.concatenate([h_prev, x_t])  # [concat_dim]
        gates = self.W @ concat + self.b         # [4 * hidden_dim]

        hd = self.hidden_dim
        f_t = self._sigmoid(gates[:hd])           # Forget gate
        i_t = self._sigmoid(gates[hd:2*hd])       # Input gate
        c_hat = np.tanh(gates[2*hd:3*hd])         # Candidate cell
        o_t = self._sigmoid(gates[3*hd:4*hd])     # Output gate

        c_t = f_t * c_prev + i_t * c_hat          # Cell state update
        h_t = o_t * np.tanh(c_t)                   # Hidden state

        return h_t, c_t


class LSTMForecaster:
    """
    Lightweight Sequence-to-Sequence LSTM for drift prediction.

    Architecture:
      Input  →  LSTM Layer (hidden_dim=64) →  Dense(NUM_CLASSES) →  Softmax
      (WINDOW_SIZE, FEATURE_DIM) → unrolled LSTM → classification logits

    The model processes the full sequence and uses the final hidden state
    to predict the next likely drift type and its probability.

    Training Narrative:
      The model learns "Reconnaissance Patterns" — temporal sequences
      of API calls and drift events that precede critical violations:
        - DescribeRoles × N → ModifyPolicy (IAM recon → exploit)
        - ListBuckets → PutBucketPolicy (S3 enumeration → takeover)
        - Cross-account AssumeRole → CreateUser (Lateral movement)

    Pre-seeded Weights:
      Production deployment should train on real CloudTrail/VPC logs.
      For simulation, weights are seeded to detect known recon patterns
      with configurable sensitivity.
    """

    def __init__(
        self,
        input_dim: int = FEATURE_DIM,
        hidden_dim: int = HIDDEN_DIM,
        num_classes: int = NUM_CLASSES,
        learning_rate: float = 0.001,
    ) -> None:
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.num_classes = num_classes
        self.lr = learning_rate

        # LSTM cell
        self.cell = LSTMCell(input_dim, hidden_dim)

        # Output dense layer: hidden_dim → num_classes
        scale = np.sqrt(2.0 / (hidden_dim + num_classes))
        self.W_out = np.random.randn(num_classes, hidden_dim).astype(np.float32) * scale
        self.b_out = np.zeros(num_classes, dtype=np.float32)

        # Training state
        self._epochs_trained = 0
        self._loss_history: list[float] = []

        # Seed the output layer with known pattern biases
        self._seed_recon_biases()

    def _seed_recon_biases(self) -> None:
        """
        Seed the output layer with domain-specific biases to detect
        known reconnaissance patterns even before training.

        This encodes expert knowledge about attack chains:
          - High baseline probability for recon_exploit_chain
          - Elevated bias for lateral_movement and data_exfiltration
        """
        drift_types = list(PredictedDriftType)
        for i, dt in enumerate(drift_types):
            if dt == PredictedDriftType.RECON_EXPLOIT_CHAIN:
                self.b_out[i] = 0.3
            elif dt == PredictedDriftType.LATERAL_MOVEMENT:
                self.b_out[i] = 0.2
            elif dt == PredictedDriftType.DATA_EXFILTRATION:
                self.b_out[i] = 0.15
            elif dt == PredictedDriftType.SHADOW_AI_SPAWN:
                self.b_out[i] = 0.1
            elif dt == PredictedDriftType.PERMISSION_ESCALATION:
                self.b_out[i] = 0.25

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        """Numerically stable softmax."""
        shifted = logits - logits.max()
        exp = np.exp(np.clip(shifted, -500, 500))
        return exp / (exp.sum() + 1e-10)

    def predict(self, sequence: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        Forward pass: process a sequence tensor and output class probabilities.

        Args:
            sequence: (window_size, input_dim) tensor from SequenceProcessor.

        Returns:
            (probabilities, hidden_state) — softmax class probs and final h_t.
        """
        seq_len = sequence.shape[0]
        h = np.zeros(self.hidden_dim, dtype=np.float32)
        c = np.zeros(self.hidden_dim, dtype=np.float32)

        # Unroll LSTM over the sequence
        for t in range(seq_len):
            x_t = sequence[t]
            h, c = self.cell.forward(x_t, h, c)

        # Dense layer → logits → softmax
        logits = self.W_out @ h + self.b_out
        probs = self._softmax(logits)

        return probs, h

    def train_step(
        self,
        sequence: np.ndarray,
        target_class: int,
    ) -> float:
        """
        Single training step with cross-entropy loss.

        Uses finite-difference gradient approximation for simplicity
        in this pure-NumPy implementation. Production should use PyTorch.

        Args:
            sequence: (window_size, input_dim) training sequence.
            target_class: Index of the true drift type.

        Returns:
            Cross-entropy loss value.
        """
        probs, _ = self.predict(sequence)

        # Cross-entropy loss: -log(P[target])
        loss = -np.log(probs[target_class] + 1e-10)

        # Gradient of softmax + cross-entropy (analytical)
        grad_logits = probs.copy()
        grad_logits[target_class] -= 1.0  # dL/dz = P - Y

        # Update output layer (SGD)
        seq_len = sequence.shape[0]
        h = np.zeros(self.hidden_dim, dtype=np.float32)
        c_state = np.zeros(self.hidden_dim, dtype=np.float32)
        for t in range(seq_len):
            h, c_state = self.cell.forward(sequence[t], h, c_state)

        # W_out gradient: dL/dW = grad_logits ⊗ h
        dW_out = np.outer(grad_logits, h)
        self.W_out -= self.lr * dW_out
        self.b_out -= self.lr * grad_logits

        self._epochs_trained += 1
        self._loss_history.append(float(loss))

        return float(loss)

    def train_on_pattern(
        self,
        sequences: list[np.ndarray],
        labels: list[int],
        epochs: int = 10,
    ) -> list[float]:
        """
        Train the model on a batch of labeled sequences.

        Args:
            sequences: List of (window_size, input_dim) tensors.
            labels: List of target class indices.
            epochs: Number of training epochs.

        Returns:
            List of per-epoch average losses.
        """
        epoch_losses = []
        for epoch in range(epochs):
            batch_loss = 0.0
            for seq, label in zip(sequences, labels):
                batch_loss += self.train_step(seq, label)
            avg_loss = batch_loss / max(len(sequences), 1)
            epoch_losses.append(avg_loss)
            logger.debug(
                f"🧠 LSTM epoch {epoch+1}/{epochs}: loss={avg_loss:.4f}"
            )
        return epoch_losses

    def get_stats(self) -> dict[str, Any]:
        return {
            "epochs_trained":   self._epochs_trained,
            "last_loss":        self._loss_history[-1] if self._loss_history else None,
            "avg_recent_loss":  float(np.mean(self._loss_history[-10:])) if self._loss_history else None,
            "hidden_dim":       self.hidden_dim,
            "num_classes":      self.num_classes,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SHADOW AI DETECTOR — Out-of-Band Telemetry Classification
# ═══════════════════════════════════════════════════════════════════════════════

class ShadowAIDetector:
    """
    Identifies 'Out-of-Band' telemetry indicating unauthorized AI workloads.

    Shadow AI Signature:
      A resource with NO Project tag that exhibits:
        1. Sustained GPU utilization > 30% over the window
        2. OR sustained high outbound API traffic (> 10K calls)
        3. OR both elevated CPU (> 60%) and high network egress

    Classification: Shadow AI (Security Risk) → triggers Amber Alert.

    These patterns indicate someone has spun up ML training, inference,
    or data pipeline workloads without governance approval.
    """

    GPU_THRESHOLD        = 30.0    # Sustained GPU% threshold
    API_VOLUME_THRESHOLD = 10000   # Total API calls threshold
    CPU_THRESHOLD        = 60.0    # CPU% for CPU+network combo
    NETWORK_THRESHOLD    = 1e7     # 10MB outbound network threshold
    MIN_EVENTS           = 5       # Minimum events to classify

    def detect(
        self,
        resource_telemetry: dict[str, dict[str, float]],
    ) -> list[dict[str, Any]]:
        """
        Scan aggregated resource telemetry for Shadow AI signatures.

        Args:
            resource_telemetry: Per-resource aggregated metrics from
                                SequenceProcessor.get_resource_telemetry().

        Returns:
            List of Shadow AI detection results with resource details.
        """
        detections = []

        for rid, metrics in resource_telemetry.items():
            # Must have enough data points
            if metrics.get("event_count", 0) < self.MIN_EVENTS:
                continue

            # Shadow AI requires NO Project tag
            has_project = metrics.get("has_project", 1.0) > 0.5
            if has_project:
                continue

            reasons = []
            confidence = 0.0

            # Check GPU utilization
            avg_gpu = metrics.get("avg_gpu", 0.0)
            if avg_gpu > self.GPU_THRESHOLD:
                reasons.append(
                    f"Sustained GPU utilization: {avg_gpu:.1f}% "
                    f"(threshold: {self.GPU_THRESHOLD}%)"
                )
                confidence += 0.4

            # Check API volume
            total_api = metrics.get("total_api_calls", 0.0)
            if total_api > self.API_VOLUME_THRESHOLD:
                reasons.append(
                    f"High API traffic: {total_api:.0f} calls "
                    f"(threshold: {self.API_VOLUME_THRESHOLD})"
                )
                confidence += 0.3

            # Check CPU + network combo
            avg_cpu = metrics.get("avg_cpu", 0.0)
            total_net = metrics.get("total_net_out", 0.0)
            if avg_cpu > self.CPU_THRESHOLD and total_net > self.NETWORK_THRESHOLD:
                reasons.append(
                    f"Elevated CPU ({avg_cpu:.1f}%) + high network egress "
                    f"({total_net:.0f} bytes)"
                )
                confidence += 0.3

            if reasons:
                detections.append({
                    "resource_id":  rid,
                    "is_shadow_ai": True,
                    "confidence":   min(confidence, 1.0),
                    "reasons":      reasons,
                    "metrics":      metrics,
                    "classification": "Shadow AI (Security Risk)",
                    "recommendation": (
                        f"Resource {rid} shows unauthorized AI workload patterns "
                        f"with no governance Project tag. Investigate immediately."
                    ),
                })
                logger.warning(
                    f"🕵️ Shadow AI detected: {rid} — "
                    f"{'; '.join(reasons)}"
                )

        return detections


# ═══════════════════════════════════════════════════════════════════════════════
# 4. RECONNAISSANCE PATTERN DETECTOR
# ═══════════════════════════════════════════════════════════════════════════════

class ReconDetector:
    """
    Detects temporal reconnaissance patterns in the event sequence.

    Matches the event type sequence against known attack chains:
      - DescribeRoles × N → ModifyPolicy  (IAM Recon → Exploit)
      - ListBuckets → PutBucketPolicy     (S3 Enumeration)
      - AssumeRole → CreateUser           (Lateral Movement)

    Uses subsequence matching with a configurable gap tolerance.
    """

    def __init__(self, max_gap: int = 5) -> None:
        self._max_gap = max_gap

    def detect(self, event_sequence: list[str]) -> list[dict[str, Any]]:
        """
        Scan the event sequence for known reconnaissance patterns.

        Args:
            event_sequence: Ordered list of event/drift type strings.

        Returns:
            List of detected patterns with positions and names.
        """
        detections = []

        for pattern in RECON_PATTERNS:
            positions = self._match_subsequence(event_sequence, pattern)
            if positions:
                pattern_name = f"{pattern[0]}→{'→'.join(pattern[1:])}"
                detections.append({
                    "pattern_name":    pattern_name,
                    "pattern_length":  len(pattern),
                    "match_positions": positions,
                    "pattern_events":  pattern,
                    "severity":        "CRITICAL" if "ModifyPolicy" in pattern or "CreateUser" in pattern else "HIGH",
                    "description": (
                        f"Reconnaissance pattern detected: {pattern_name}. "
                        f"This sequence is consistent with an active attack chain."
                    ),
                })
                logger.warning(
                    f"🔍 Recon pattern detected: {pattern_name} "
                    f"at positions {positions}"
                )

        return detections

    def _match_subsequence(
        self,
        sequence: list[str],
        pattern: list[str],
    ) -> list[int]:
        """
        Match a pattern as a subsequence within the event sequence,
        allowing up to max_gap events between pattern elements.
        """
        if not pattern or not sequence:
            return []

        positions = []
        pat_idx = 0
        last_match = -1

        for seq_idx, event in enumerate(sequence):
            if pat_idx >= len(pattern):
                break

            if event == pattern[pat_idx]:
                # Check gap constraint
                if last_match >= 0 and (seq_idx - last_match) > self._max_gap:
                    # Gap too large — reset
                    positions = []
                    pat_idx = 0
                    if event == pattern[0]:
                        positions = [seq_idx]
                        pat_idx = 1
                        last_match = seq_idx
                    continue

                positions.append(seq_idx)
                last_match = seq_idx
                pat_idx += 1

        return positions if pat_idx == len(pattern) else []


# ═══════════════════════════════════════════════════════════════════════════════
# 5. THREAT FORECASTER — Main Orchestration Class
# ═══════════════════════════════════════════════════════════════════════════════

class ThreatForecaster:
    """
    Phase 4 Proactive Intelligence Engine.

    Orchestrates the full prediction pipeline:
      1. Ingest events into SequenceProcessor sliding window
      2. On each tick: vectorize → LSTM predict → Shadow AI scan → Recon detect
      3. If P ≥ 0.75: trigger Amber Alert → wake Sentry (ProactiveSentry)
      4. Emit FORECAST_SIGNAL to War Room WebSocket

    Modified J-Function:
      J_forecast = min Σ (w_R · P · R_i + w_C · C_i)
      Risk reduction is weighted by the PROBABILITY of the event occurring.

    Usage:
        forecaster = ThreatForecaster()
        forecaster.ingest_event(raw_redis_event)
        result = forecaster.predict_tick(current_j=0.45, w_risk=0.6, w_cost=0.4)
        if result.is_amber_alert:
            await forecaster.emit_amber_alert(result)
    """

    def __init__(
        self,
        window_size: int = WINDOW_SIZE,
        hidden_dim: int = HIDDEN_DIM,
        amber_threshold: float = AMBER_THRESHOLD,
        horizon_ticks: int = 5,
    ) -> None:
        self._processor = SequenceProcessor(window_size)
        self._lstm = LSTMForecaster(
            input_dim=FEATURE_DIM,
            hidden_dim=hidden_dim,
        )
        self._shadow_detector = ShadowAIDetector()
        self._recon_detector = ReconDetector()
        self._amber_threshold = amber_threshold
        self._horizon_ticks = horizon_ticks

        # Alert handlers
        self._alert_handlers: list[Callable] = []

        # Stats
        self._total_predictions = 0
        self._amber_alerts_fired = 0
        self._shadow_ai_detections = 0
        self._recon_patterns_found = 0

        # Forecast history
        self._history: deque[ForecastResult] = deque(maxlen=200)

    @property
    def processor(self) -> SequenceProcessor:
        return self._processor

    @property
    def lstm(self) -> LSTMForecaster:
        return self._lstm

    # ─── Event Ingestion ──────────────────────────────────────────────────────

    def ingest_event(self, raw_event: dict[str, Any]) -> None:
        """Ingest a raw Redis/EventBus event into the sliding window."""
        self._processor.ingest_from_redis(raw_event)

    def ingest_telemetry(self, event: TelemetryEvent) -> None:
        """Ingest a structured TelemetryEvent."""
        self._processor.ingest(event)

    # ─── Core Prediction ──────────────────────────────────────────────────────

    def predict_tick(
        self,
        current_j: float = 0.5,
        w_risk: float = 0.6,
        w_cost: float = 0.4,
        resource_risks: Optional[dict[str, float]] = None,
        resource_costs: Optional[dict[str, float]] = None,
    ) -> ForecastResult:
        """
        Run the full prediction pipeline for one simulation tick.

        Pipeline:
          1. Vectorize the sliding window into a tensor
          2. Run LSTM forward pass → class probabilities
          3. Run Shadow AI detection on resource telemetry
          4. Run Reconnaissance pattern detection on event sequence
          5. Calculate J_forecast with probability weighting
          6. Build ForecastResult

        Args:
            current_j: Current J-score equilibrium value.
            w_risk: Risk weight (w_R).
            w_cost: Cost weight (w_C).
            resource_risks: {resource_id: risk_score} for J_forecast calc.
            resource_costs: {resource_id: monthly_cost} for J_forecast calc.

        Returns:
            ForecastResult with probability, predicted type, alerts, etc.
        """
        self._total_predictions += 1

        # Step 1: Vectorize
        tensor = self._processor.vectorize()

        # Step 2: LSTM predict
        probs, hidden = self._lstm.predict(tensor)
        drift_types = list(PredictedDriftType)
        class_probs = {dt.value: float(probs[i]) for i, dt in enumerate(drift_types)}

        # Identify the most likely predicted drift
        max_idx = int(np.argmax(probs))
        max_prob = float(probs[max_idx])
        predicted_type = drift_types[max_idx].value

        # Confidence interval (using sigmoid scaling of hidden state norm)
        h_norm = float(np.linalg.norm(hidden))
        ci_width = 0.1 * (1.0 / (1.0 + np.exp(-h_norm / 10.0)))
        ci_lo = max(0.0, max_prob - ci_width)
        ci_hi = min(1.0, max_prob + ci_width)

        # Step 3: Shadow AI detection
        resource_telemetry = self._processor.get_resource_telemetry()
        shadow_detections = self._shadow_detector.detect(resource_telemetry)
        is_shadow_ai = len(shadow_detections) > 0
        shadow_details = shadow_detections[0] if shadow_detections else None

        if is_shadow_ai:
            self._shadow_ai_detections += len(shadow_detections)
            # Boost shadow_ai_spawn probability if detected
            if class_probs.get("shadow_ai_spawn", 0) < 0.5:
                class_probs["shadow_ai_spawn"] = max(
                    class_probs.get("shadow_ai_spawn", 0),
                    shadow_detections[0]["confidence"],
                )
            # Override prediction if shadow AI has higher confidence
            if shadow_detections[0]["confidence"] > max_prob:
                predicted_type = PredictedDriftType.SHADOW_AI_SPAWN.value
                max_prob = shadow_detections[0]["confidence"]

        # Step 4: Recon pattern detection
        event_sequence = self._processor.get_event_type_sequence()
        recon_detections = self._recon_detector.detect(event_sequence)
        recon_detected = len(recon_detections) > 0
        recon_name = recon_detections[0]["pattern_name"] if recon_detections else ""

        if recon_detected:
            self._recon_patterns_found += len(recon_detections)
            # Boost recon probability
            max_prob = max(max_prob, 0.85)
            predicted_type = PredictedDriftType.RECON_EXPLOIT_CHAIN.value
            class_probs["recon_exploit_chain"] = max_prob

        # Step 5: Calculate J_forecast
        j_forecast = self._calculate_j_forecast(
            probability=max_prob,
            w_risk=w_risk,
            w_cost=w_cost,
            resource_risks=resource_risks or {},
            resource_costs=resource_costs or {},
        )

        # Determine target resource (most active in window)
        target_resource = ""
        if resource_telemetry:
            target_resource = max(
                resource_telemetry,
                key=lambda r: resource_telemetry[r].get("event_count", 0),
            )

        # Override with shadow AI resource if detected
        if shadow_details:
            target_resource = shadow_details["resource_id"]

        # Step 6: Build result
        is_amber = max_prob >= self._amber_threshold
        if is_amber:
            self._amber_alerts_fired += 1

        result = ForecastResult(
            probability=max_prob,
            predicted_drift_type=predicted_type,
            class_probabilities=class_probs,
            is_amber_alert=is_amber,
            is_shadow_ai=is_shadow_ai,
            shadow_ai_details=shadow_details,
            target_resource_id=target_resource,
            horizon_ticks=self._horizon_ticks,
            recon_pattern_detected=recon_detected,
            recon_pattern_name=recon_name,
            j_forecast=j_forecast,
            confidence_interval=(ci_lo, ci_hi),
        )

        self._history.append(result)

        if is_amber:
            logger.warning(
                f"🚨 AMBER ALERT: P={max_prob:.2%} for {predicted_type} "
                f"on {target_resource} (J_fc={j_forecast:.4f})"
            )
        else:
            logger.debug(
                f"🔮 Forecast: P={max_prob:.2%} for {predicted_type} "
                f"(J_fc={j_forecast:.4f})"
            )

        return result

    # ─── Modified J-Function ──────────────────────────────────────────────────

    def _calculate_j_forecast(
        self,
        probability: float,
        w_risk: float,
        w_cost: float,
        resource_risks: dict[str, float],
        resource_costs: dict[str, float],
    ) -> float:
        """
        Calculate the modified J-function for forecast-weighted optimization.

        J_forecast = min Σ (w_R · P · R_i + w_C · C_i)

        The risk reduction for each resource is weighted by the PROBABILITY
        of the predicted event actually occurring. This prevents over-investment
        in unlikely threats while maintaining defensive posture for probable ones.

        Args:
            probability: LSTM prediction probability P ∈ [0, 1].
            w_risk: Risk weight (w_R).
            w_cost: Cost weight (w_C).
            resource_risks: {resource_id: risk_score (0-100)}.
            resource_costs: {resource_id: monthly_cost_usd}.

        Returns:
            J_forecast score (lower = better governed).
        """
        if not resource_risks and not resource_costs:
            # Simplified fallback: use probability directly
            return probability * w_risk

        all_resources = set(resource_risks.keys()) | set(resource_costs.keys())
        if not all_resources:
            return probability * w_risk

        # Normalize risks and costs
        risks = np.array([resource_risks.get(r, 0.0) for r in all_resources])
        costs = np.array([resource_costs.get(r, 0.0) for r in all_resources])

        r_range = risks.max() - risks.min() if risks.max() > risks.min() else 1.0
        c_range = costs.max() - costs.min() if costs.max() > costs.min() else 1.0

        r_norm = (risks - risks.min()) / r_range
        c_norm = (costs - costs.min()) / c_range

        # J_forecast = mean(w_R · P · R̂_i + w_C · Ĉ_i)
        j_components = w_risk * probability * r_norm + w_cost * c_norm
        j_forecast = float(np.mean(j_components))

        return max(0.0, min(1.0, j_forecast))

    # ─── Amber Alert Emission ─────────────────────────────────────────────────

    def on_amber_alert(self, handler: Callable) -> None:
        """Register a handler for Amber Alert notifications."""
        self._alert_handlers.append(handler)

    async def emit_amber_alert(self, result: ForecastResult) -> None:
        """
        Emit an Amber Alert via the War Room WebSocket.
        Also invokes all registered alert handlers.
        """
        # Build FORECAST_SIGNAL payload
        ws_payload = result.to_ws_payload()

        # Emit to WebSocket via the streamer
        try:
            from cloudguard.api.streamer import emit_event
            await emit_event(ws_payload)
            logger.info(
                f"📡 FORECAST_SIGNAL emitted to War Room: "
                f"{result.predicted_drift_type} P={result.probability:.2%}"
            )
        except ImportError:
            logger.debug("Streamer not available — alert logged only")
        except Exception as e:
            logger.warning(f"Failed to emit FORECAST_SIGNAL: {e}")

        # Invoke handlers
        for handler in self._alert_handlers:
            try:
                ret = handler(result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception as e:
                logger.error(f"Alert handler error: {e}")

    # ─── Training Interface ───────────────────────────────────────────────────

    def train_on_recon_patterns(self, num_synthetic: int = 50) -> list[float]:
        """
        Generate synthetic reconnaissance pattern sequences and train
        the LSTM to recognize them.

        Creates labeled training sequences by:
          1. Building synthetic event sequences that match RECON_PATTERNS
          2. Padding/embedding them via SequenceProcessor
          3. Training the LSTM with correct class labels

        Args:
            num_synthetic: Number of synthetic sequences to generate.

        Returns:
            Training loss history.
        """
        sequences = []
        labels = []
        rng = np.random.RandomState(42)

        for _ in range(num_synthetic):
            # Pick a random reconnaissance pattern
            pattern_idx = rng.randint(0, len(RECON_PATTERNS))
            pattern = RECON_PATTERNS[pattern_idx]

            # Build a synthetic sequence
            proc = SequenceProcessor(self._processor.window_size)

            # Fill with background noise
            noise_len = rng.randint(20, 80)
            for _ in range(noise_len):
                noise_type = rng.choice(["HEARTBEAT", "DRIFT", "REMEDIATION"])
                proc.ingest(TelemetryEvent(
                    event_type=noise_type,
                    cpu_delta=float(rng.uniform(0, 50)),
                    api_volume=float(rng.randint(0, 100)),
                    severity=rng.choice(["LOW", "MEDIUM"]),
                ))

            # Inject the reconnaissance pattern
            for api_call in pattern:
                proc.ingest(TelemetryEvent(
                    event_type=api_call,
                    drift_type=api_call,
                    severity="HIGH" if "Modify" in api_call or "Create" in api_call else "MEDIUM",
                    api_volume=float(rng.randint(1, 50)),
                    cpu_delta=float(rng.uniform(10, 80)),
                ))

            tensor = proc.vectorize()
            sequences.append(tensor)

            # Label: recon_exploit_chain for most patterns
            if "AssumeRole" in pattern:
                labels.append(list(PredictedDriftType).index(
                    PredictedDriftType.LATERAL_MOVEMENT
                ))
            elif "GetObject" in pattern:
                labels.append(list(PredictedDriftType).index(
                    PredictedDriftType.DATA_EXFILTRATION
                ))
            else:
                labels.append(list(PredictedDriftType).index(
                    PredictedDriftType.RECON_EXPLOIT_CHAIN
                ))

        losses = self._lstm.train_on_pattern(sequences, labels, epochs=10)
        logger.info(
            f"🧠 LSTM trained on {num_synthetic} synthetic recon patterns. "
            f"Final loss: {losses[-1]:.4f}"
        )
        return losses

    # ─── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        return {
            "window_depth":          self._processor.current_depth,
            "total_events_ingested": self._processor.total_ingested,
            "total_predictions":     self._total_predictions,
            "amber_alerts_fired":    self._amber_alerts_fired,
            "shadow_ai_detections":  self._shadow_ai_detections,
            "recon_patterns_found":  self._recon_patterns_found,
            "lstm_stats":            self._lstm.get_stats(),
            "amber_threshold":       self._amber_threshold,
            "horizon_ticks":         self._horizon_ticks,
        }

    def get_history(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._history]


# ═══════════════════════════════════════════════════════════════════════════════
# 6. PROACTIVE SENTRY — LangGraph Node for J_forecast Negotiation
# ═══════════════════════════════════════════════════════════════════════════════

class ProactiveSentry:
    """
    The "Amber Alert" Swarm Handshake — LangGraph integration node.

    When the ThreatForecaster fires an Amber Alert (P ≥ 0.75):
      1. ProactiveSentry wakes the CISO Sentry agent
      2. Presents the forecast as a "Stochastic Violation"
      3. Sentry proposes preemptive remediation
      4. J_forecast is used to weight the negotiation:

         J_forecast = min Σ (w_R · P · R_i + w_C · C_i)

      5. Consultant evaluates cost vs. pre-crime probability
      6. Final decision is made with probability-weighted risk

    This is a PRE-CRIME negotiation — fixing things BEFORE they break.

    Integration with KernelOrchestrator:
      The ProactiveSentry hooks into the existing state machine by:
        1. Creating a synthetic PolicyViolation from the ForecastResult
        2. Using the standard negotiation pipeline
        3. Modifying J-scoring to use J_forecast instead of J_actual

    Usage:
        sentry = ProactiveSentry(
            forecaster=forecaster,
            orchestrator=kernel_orchestrator,
        )

        # Process a forecast
        kernel_state = await sentry.process_forecast(forecast_result)

        # Or run as a LangGraph node
        state = await sentry.langgraph_node(state)
    """

    def __init__(
        self,
        forecaster: Optional[ThreatForecaster] = None,
        orchestrator: Optional[Any] = None,  # KernelOrchestrator
        sentry_persona: Optional[Any] = None,  # SentryPersona
        auto_remediate_threshold: float = 0.90,
    ) -> None:
        self._forecaster = forecaster or ThreatForecaster()
        self._orchestrator = orchestrator
        self._sentry_persona = sentry_persona
        self._auto_threshold = auto_remediate_threshold

        # Stats
        self._forecasts_processed = 0
        self._preemptive_remediations = 0
        self._escalations = 0

    async def process_forecast(
        self,
        forecast: ForecastResult,
        current_j: float = 0.5,
        resource_context: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Process a ForecastResult through the proactive remediation pipeline.

        Pipeline:
          1. Validate: only process Amber Alerts (P ≥ 0.75)
          2. Build synthetic PolicyViolation from forecast
          3. If orchestrator available: run standard negotiation with J_forecast
          4. Emit FORECAST_SIGNAL to War Room
          5. Return decision result

        Args:
            forecast: ForecastResult from ThreatForecaster.
            current_j: Current actual J-score.
            resource_context: Additional context about target resource.

        Returns:
            Decision dict with preemptive action or escalation.
        """
        self._forecasts_processed += 1

        if not forecast.is_amber_alert:
            return {
                "action": "monitor",
                "reason": f"P={forecast.probability:.2%} below Amber threshold",
                "forecast": forecast.to_dict(),
            }

        # Build synthetic violation context
        violation_context = {
            "type": "STOCHASTIC_VIOLATION",
            "forecast_id": forecast.forecast_id,
            "predicted_drift_type": forecast.predicted_drift_type,
            "probability": forecast.probability,
            "target_resource_id": forecast.target_resource_id,
            "horizon_ticks": forecast.horizon_ticks,
            "is_shadow_ai": forecast.is_shadow_ai,
            "recon_pattern": forecast.recon_pattern_name,
            "j_forecast": forecast.j_forecast,
            "confidence_interval": forecast.confidence_interval,
            **(resource_context or {}),
        }

        # If we have an orchestrator, run the standard negotiation
        if self._orchestrator is not None:
            try:
                from cloudguard.agents.sentry_node import (
                    DriftEventOutput,
                    PolicyViolation,
                )

                # Create a synthetic DriftEventOutput
                synthetic_drift = DriftEventOutput(
                    resource_id=forecast.target_resource_id,
                    drift_type=forecast.predicted_drift_type,
                    severity="CRITICAL" if forecast.probability > 0.9 else "HIGH",
                    confidence=forecast.probability,
                    triage_reasoning=(
                        f"STOCHASTIC VIOLATION: LSTM forecasts "
                        f"{forecast.predicted_drift_type} with P={forecast.probability:.2%}. "
                        f"{'Shadow AI detected. ' if forecast.is_shadow_ai else ''}"
                        f"{'Recon chain: ' + forecast.recon_pattern_name + '. ' if forecast.recon_pattern_detected else ''}"
                        f"Horizon: {forecast.horizon_ticks} ticks."
                    ),
                )

                # Create a synthetic PolicyViolation
                synthetic_violation = PolicyViolation(
                    drift_events=[synthetic_drift],
                    heuristic_available=False,
                    batch_size=1,
                    total_raw_events=1,
                    confidence=forecast.probability,
                )

                # Run through kernel with modified J
                kernel_state = await self._orchestrator.process_violation(
                    violation=synthetic_violation,
                    current_j=forecast.j_forecast,  # Use J_forecast, not J_actual
                    resource_context=violation_context,
                )

                self._preemptive_remediations += 1

                return {
                    "action": "preemptive_remediation",
                    "kernel_state": kernel_state.to_dict(),
                    "forecast": forecast.to_dict(),
                    "j_forecast": forecast.j_forecast,
                    "j_actual": current_j,
                    "type": "pre_crime_negotiation",
                }

            except Exception as e:
                logger.error(f"Orchestrator failed on forecast: {e}")
                self._escalations += 1
                return {
                    "action": "escalate",
                    "reason": f"Orchestrator error: {e}",
                    "forecast": forecast.to_dict(),
                }

        # No orchestrator — return advisory
        self._escalations += 1

        # Auto-remediate if above auto-threshold and shadow AI
        if (forecast.probability >= self._auto_threshold
                and forecast.is_shadow_ai):
            return {
                "action": "auto_quarantine",
                "reason": (
                    f"Shadow AI detected on {forecast.target_resource_id} "
                    f"with P={forecast.probability:.2%} ≥ auto-threshold "
                    f"({self._auto_threshold:.0%}). "
                    f"Recommending immediate quarantine."
                ),
                "forecast": forecast.to_dict(),
                "recommended_remediation": {
                    "type": "quarantine_resource",
                    "target": forecast.target_resource_id,
                    "actions": [
                        "revoke_network_access",
                        "disable_gpu_allocation",
                        "tag_as_shadow_ai",
                        "notify_security_team",
                    ],
                },
            }

        return {
            "action": "alert",
            "reason": (
                f"Amber Alert: P={forecast.probability:.2%} for "
                f"{forecast.predicted_drift_type} on {forecast.target_resource_id}. "
                f"No orchestrator available — manual intervention required."
            ),
            "forecast": forecast.to_dict(),
        }

    async def langgraph_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        LangGraph-compatible node function.

        Reads the current KernelState from the graph state,
        runs the forecaster, and injects proactive alerts.

        Expected state keys:
          - kernel_state: KernelState
          - current_j: float
          - resource_context: dict

        Returns state with added forecast_result if Amber Alert fired.
        """
        current_j = state.get("current_j", 0.5)
        resource_context = state.get("resource_context", {})

        # Run prediction
        forecast = self._forecaster.predict_tick(
            current_j=current_j,
            w_risk=state.get("w_risk", 0.6),
            w_cost=state.get("w_cost", 0.4),
        )

        if forecast.is_amber_alert:
            decision = await self.process_forecast(
                forecast=forecast,
                current_j=current_j,
                resource_context=resource_context,
            )
            state["forecast_result"] = forecast.to_dict()
            state["forecast_decision"] = decision
            state["amber_alert_active"] = True

            # Emit to WebSocket
            await self._forecaster.emit_amber_alert(forecast)
        else:
            state["forecast_result"] = forecast.to_dict()
            state["amber_alert_active"] = False

        return state

    def get_stats(self) -> dict[str, Any]:
        return {
            "forecasts_processed":      self._forecasts_processed,
            "preemptive_remediations":   self._preemptive_remediations,
            "escalations":              self._escalations,
            "auto_remediate_threshold":  self._auto_threshold,
            "forecaster_stats":         self._forecaster.get_stats(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 7. LANGGRAPH BUILDER — Add Forecaster Node to Kernel Graph
# ═══════════════════════════════════════════════════════════════════════════════

def build_forecaster_langgraph_node(
    forecaster: Optional[ThreatForecaster] = None,
    orchestrator: Optional[Any] = None,
) -> tuple[ProactiveSentry, Optional[Any]]:
    """
    Build the ProactiveSentry LangGraph node and optionally attach it
    to an existing LangGraph kernel graph.

    The Forecaster node sits BEFORE the standard triage pipeline:
      [Forecaster] → (amber?) → [Heuristic] → [Negotiation] → ...
                   ↘ (no alert) → [Continue normal pipeline]

    Returns:
        (proactive_sentry, compiled_graph_or_none)
    """
    sentry = ProactiveSentry(
        forecaster=forecaster or ThreatForecaster(),
        orchestrator=orchestrator,
    )

    # If LangGraph is available, build the extended graph
    try:
        from langgraph.graph import StateGraph, END
        from typing import TypedDict

        class ForecastGraphState(TypedDict):
            kernel_state: Any
            current_j: float
            resource_context: dict
            resource_tags: dict
            forecast_result: Optional[dict]
            forecast_decision: Optional[dict]
            amber_alert_active: bool
            w_risk: float
            w_cost: float

        async def forecaster_node(state: ForecastGraphState) -> ForecastGraphState:
            return await sentry.langgraph_node(state)

        def should_alert(state: ForecastGraphState) -> str:
            if state.get("amber_alert_active", False):
                return "proactive_remediation"
            return "normal_pipeline"

        graph = StateGraph(ForecastGraphState)
        graph.add_node("forecaster", forecaster_node)
        graph.set_entry_point("forecaster")
        graph.add_conditional_edges("forecaster", should_alert, {
            "proactive_remediation": END,  # Handled by ProactiveSentry
            "normal_pipeline": END,        # Continue to standard kernel
        })

        compiled = graph.compile()
        logger.info("🔮 Forecaster LangGraph node compiled successfully")
        return sentry, compiled

    except ImportError:
        logger.info("🔮 LangGraph not available — ProactiveSentry in standalone mode")
        return sentry, None


# ═══════════════════════════════════════════════════════════════════════════════
# 8. REDIS TRUTH LOG SUBSCRIBER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_forecaster_loop(
    forecaster: ThreatForecaster,
    redis_url: str = "redis://localhost:6379",
    channel: str = "cloudguard_events",
    tick_interval: float = 5.0,
    current_j_getter: Optional[Callable[[], float]] = None,
) -> None:
    """
    Continuously subscribe to Redis truth_log and run the forecaster
    on each tick interval.

    This is the production entry point for the Phase 4 forecaster.

    Args:
        forecaster: Initialized ThreatForecaster instance.
        redis_url: Redis connection URL.
        channel: Redis channel to subscribe to.
        tick_interval: Seconds between prediction ticks.
        current_j_getter: Callable that returns the current J-score.
    """
    logger.info(
        f"🔮 Starting forecaster loop (interval={tick_interval}s, "
        f"channel={channel})"
    )

    # Start Redis subscriber in background
    subscriber_task = asyncio.create_task(
        _redis_ingestion_loop(forecaster, redis_url, channel)
    )

    # Prediction tick loop
    try:
        while True:
            await asyncio.sleep(tick_interval)

            current_j = current_j_getter() if current_j_getter else 0.5
            result = forecaster.predict_tick(current_j=current_j)

            if result.is_amber_alert:
                await forecaster.emit_amber_alert(result)

    except asyncio.CancelledError:
        logger.info("🔮 Forecaster loop cancelled")
    finally:
        subscriber_task.cancel()
        await asyncio.gather(subscriber_task, return_exceptions=True)


async def _redis_ingestion_loop(
    forecaster: ThreatForecaster,
    redis_url: str,
    channel: str,
) -> None:
    """Subscribe to Redis and feed events to the forecaster."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("Redis not available — forecaster in manual mode")
        return

    while True:
        try:
            client = aioredis.from_url(
                redis_url, decode_responses=True, socket_connect_timeout=5
            )
            await client.ping()
            logger.info(f"🔮 Forecaster connected to Redis at {redis_url}")

            pubsub = client.pubsub()
            await pubsub.subscribe(channel)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        forecaster.ingest_event(event)
                    except json.JSONDecodeError:
                        pass

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"🔮 Redis connection lost ({e}) — retrying in 5s")
            await asyncio.sleep(5)
