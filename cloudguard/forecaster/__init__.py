"""
Forecaster Layer — Phase 4 Proactive Intelligence
====================================================
LSTM-based threat prediction, Amber Alert lifecycle management,
and Human-Grounded Learning Loop.

Modules:
  threat_forecaster    — Sequence processor, LSTM model, Shadow AI detector,
                         Recon detector, ThreatForecaster orchestrator,
                         ProactiveSentry LangGraph node.
  dissipation_handler  — DissipationHandler (auto-close Amber Alerts on P drop),
                         AttackPathResolver (transitive node graph for UI overlay),
                         AmberAlertRecord, DissipationLog.
  validation_queue     — ValidationQueue (Redis-backed HITL labeling store),
                         commit_truth_batch() (human-gated LSTM weight update),
                         ValidationEntry, TruthBatch.

Phase 4 Integration Flow:
  ThreatForecaster.predict_tick()
    → P ≥ 0.75 → DissipationHandler.open_alert()  → THREAT_HORIZON_OVERLAY (WS)
    → P < 0.75 × 3 ticks → DissipationHandler.update() → auto-close
    → Amber Alert sequence → ValidationQueue.enqueue()
    → Human labels batch → commit_truth_batch() → LSTM W_out update
    → SovereignGate: P ≥ 0.90 Shadow AI → Predictive Fast-Pass (60s → 10s)
"""

from .threat_forecaster import (
    ThreatForecaster,
    ForecastResult,
    TelemetryEvent,
    SequenceProcessor,
    LSTMForecaster,
    ShadowAIDetector,
    ReconDetector,
    AMBER_THRESHOLD,
    PredictedDriftType,
)

from .dissipation_handler import (
    DissipationHandler,
    AttackPathResolver,
    AmberAlertRecord,
    DissipationLog,
    DISSIPATION_COOLDOWN_TICKS,
)

from .validation_queue import (
    ValidationQueue,
    ValidationEntry,
    TruthBatch,
    commit_truth_batch,
    entry_from_forecast,
    VQ_QUEUE_KEY,
    VQ_COMMITTED_KEY,
)

__all__ = [
    # Forecaster
    "ThreatForecaster", "ForecastResult", "TelemetryEvent",
    "SequenceProcessor", "LSTMForecaster", "ShadowAIDetector", "ReconDetector",
    "AMBER_THRESHOLD", "PredictedDriftType",
    # Dissipation
    "DissipationHandler", "AttackPathResolver",
    "AmberAlertRecord", "DissipationLog", "DISSIPATION_COOLDOWN_TICKS",
    # Validation
    "ValidationQueue", "ValidationEntry", "TruthBatch",
    "commit_truth_batch", "entry_from_forecast",
    "VQ_QUEUE_KEY", "VQ_COMMITTED_KEY",
]
