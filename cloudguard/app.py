"""
CLOUDGUARD-B — UNIFIED API SERVER
===================================
Phase 1 Foundation + Original CloudGuard API

Serves both:
  - Original CloudGuard API (v1): /api/findings, /api/score, /api/chat
  - Phase 1 Foundation API (v2): /api/v2/simulation, /api/v2/math, etc.

Run with:
  uvicorn cloudguard.app:app --reload --port 8000
"""

import os
import sys
import logging

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Phase 1 Foundation routers
from cloudguard.api.routes import (
    simulation_router,
    math_router,
    branches_router,
    events_router,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CloudGuard-B — Autonomous Cloud Governance",
    description=(
        "GenAI-Powered Autonomous Cloud Governance Platform.\n\n"
        "**Phase 1**: SimulationEngine, MathEngine, StateBranchManager.\n"
        "**Phase 2**: Multi-Agent Swarm (CISO + Controller + Orchestrator)."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "https://cloudgaurd.vercel.app"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Phase 1 Foundation Routes (v2) ───────────────────────────────────────────
app.include_router(simulation_router)
app.include_router(math_router)
app.include_router(branches_router)
app.include_router(events_router)

# ── Original CloudGuard Routes (v1) ──────────────────────────────────────────
try:
    from api.findings import router as findings_router
    from api.score import router as score_router
    from api.chat import router as chat_router

    app.include_router(findings_router, prefix="/api/findings", tags=["Findings (v1)"])
    app.include_router(score_router, prefix="/api/score", tags=["Score (v1)"])
    app.include_router(chat_router, prefix="/api/chat", tags=["Chat (v1)"])
except ImportError:
    logging.getLogger("cloudguard.app").info(
        "Original CloudGuard v1 routes not available (missing dependencies)"
    )


# ── Health Check ──────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def health_check():
    return {
        "status": "CloudGuard-B is running",
        "version": "0.1.0",
        "phase": "Phase 1 — Research-Valid Foundation",
        "docs": "/docs",
    }


@app.get("/api/v2/health", tags=["Health"])
def health_v2():
    return {
        "status": "healthy",
        "subsystems": {
            "simulation_engine": True,
            "math_engine": True,
            "branch_manager": True,
            "event_bus": True,
            "temporal_clock": True,
            "remediation_protocol": True,
            "swarm_interfaces": True,
            "telemetry_generator": True,
        },
    }
