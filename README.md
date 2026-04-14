<p align="center">
  <img src="public/logo.png" alt="CloudGuard Logo" width="80" />
</p>

<h1 align="center">CloudGuard</h1>

<p align="center">
  <strong>GenAI-Powered Autonomous Cloud Security Governance Platform</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-0.3.0-blue?style=flat-square" alt="Version" />
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Next.js-16-black?style=flat-square&logo=next.js&logoColor=white" alt="Next.js" />
  <img src="https://img.shields.io/badge/FastAPI-0.110+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License" />
</p>

<p align="center">
  <img src="public/landing screenshot.png" alt="CloudGuard Dashboard" width="85%" />
</p>

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Frontend Dashboard](#frontend-dashboard)
- [Core Engine Deep Dive](#core-engine-deep-dive)
- [Real-Time Data Flow](#real-time-data-flow)
- [Testing](#testing)
- [NIST Compliance](#nist-compliance)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

CloudGuard is an autonomous cloud security governance platform that leverages a **multi-agent AI swarm** to detect misconfigurations, forecast threats, and autonomously remediate vulnerabilities — all in real time. It combines cutting-edge concepts from multi-objective optimization, stochastic forecasting, and explainable AI into a unified command center.

### What It Does

| Capability | Description |
|------------|-------------|
| **Detect** | Identifies cloud misconfigurations and configuration drift via simulated SIEM telemetry (VPC flow, CloudTrail, K8s audit logs) |
| **Forecast** | Predicts emerging threats using a stochastic J-Score cost-risk function with Amber Alert early warnings |
| **Remediate** | Executes autonomous fixes with a 10-second **Fast-Pass** human-override window before auto-execution |
| **Audit** | Records every decision through a NIST AI RMF-aligned forensic black-box recorder with full audit trails |

The system runs a continuous simulation loop where specialized agents (**Sentry**, **Controller**, **Orchestrator**) negotiate remediation strategies on a Pareto-optimal frontier, and a sovereign decision engine either auto-executes or defers to human veto.

---

## Key Features

### 🛡️ Multi-Agent Swarm Intelligence
- **Sentry Node** — Threat detection and risk assessment agent
- **Controller Agent** — Cost optimization and resource efficiency
- **Orchestrator** — Pareto synthesis with NSGA-II multi-objective optimization
- **Audit Surgeon** — Compliance verification with jailbreak/code-veto detection

### 📊 Stochastic J-Score Engine
```
J = min Σᵢ (w_R · P · Rᵢ + w_C · Cᵢ)
```
Multi-objective equilibrium function that balances **risk** vs **cost** across all cloud resources, powered by:
- Entropy Weight Method (EWM) — Shannon information-theoretic risk prioritization
- CRITIC weighting — Criteria Importance Through Intercriteria Correlation
- NetworkX dependency graph centrality for infrastructure topology analysis
- Fuzzy logic classification with trapezoidal membership functions

### ⚡ Real-Time War Room
- WebSocket streaming engine (`/ws/war-room`) with 50-event replay buffer
- 50ms batched event ingestion with deduplication on the frontend
- Auto-stepper tick loop (~1.5s) driving continuous simulation
- Exponential backoff reconnection with ping/pong keepalive

### 🔮 Predictive Threat Forecasting
- Amber Alert system for high-probability emerging threats (P ≥ 0.75)
- Shadow AI detection for unauthorized model deployments
- Threat Horizon Overlay with transitive attack-path visualization
- Signal dissipation tracking when threat probabilities decay

### 🏛️ NIST AI RMF Compliance
- Full audit trail for every autonomous decision
- Monotone Invariant verification (J_forecast < J_actual)
- 1% Execution Floor — prevents action on noise-level drifts
- CODE_VETO mechanism for adversarial payload interception
- Downloadable NIST-compliant audit reports

### ⏱️ Fast-Pass Human Override
- 10-second countdown before autonomous remediation execution
- One-click veto via REST API from the Liaison Console
- Full explainability trace showing agent reasoning and ROSI calculations

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    FRONTEND · Next.js · Port 3000               │
│  ┌──────────┐ ┌───────────┐ ┌────────────┐ ┌────────────────┐  │
│  │ Overview  │ │ Iron Dome │ │ Friction   │ │ Liaison        │  │
│  │ (KPIs)    │ │ (Hex Grid)│ │ HUD (Nego) │ │ Console (XAI)  │  │
│  └─────┬────┘ └─────┬─────┘ └──────┬─────┘ └───────┬────────┘  │
│        │             │              │               │           │
│        └─────────────┴──────────────┴───────────────┘           │
│                  WebSocket + REST (hooks)                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                   ┌────────┴────────┐
                   │  BACKEND · FastAPI · Port 8000                │
                   │                                               │
                   │  ┌─────────────────────────────────────────┐  │
                   │  │  Auto Stepper (1.5s tick loop)          │  │
                   │  │  ├── Simulation Engine (drift inject)   │  │
                   │  │  ├── Threat Forecaster (Amber Alerts)   │  │
                   │  │  ├── Agent Swarm (negotiate)            │  │
                   │  │  └── Narrative Engine (XAI chunks)      │  │
                   │  └─────────────────────────────────────────┘  │
                   │                                               │
                   │  ┌──────────────┐  ┌────────────────────────┐ │
                   │  │ Math Engine  │  │ Decision Logic         │ │
                   │  │ (J-Score,    │  │ (Sovereign Execute     │ │
                   │  │  EWM, CRITIC,│  │  vs Human Defer)       │ │
                   │  │  ROSI, ALE)  │  │                        │ │
                   │  └──────────────┘  └────────────────────────┘ │
                   │                                               │
                   │  ┌──────────────┐  ┌────────────────────────┐ │
                   │  │ Collision    │  │ State Branch Manager   │ │
                   │  │ Manager      │  │ (A/B testing, rollback)│ │
                   │  └──────────────┘  └────────────────────────┘ │
                   └───────────────────────────────────────────────┘
                            │
                   ┌────────┴────────┐
                   │  INFRASTRUCTURE                               │
                   │  ├── Redis (pub/sub event bus)                │
                   │  ├── PostgreSQL + TimescaleDB (persistence)   │
                   │  └── Docker Compose                           │
                   └───────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend
| Technology | Purpose |
|------------|---------|
| **Python 3.11+** | Core language |
| **FastAPI** | REST API + WebSocket server |
| **Uvicorn** | ASGI server |
| **Pydantic v2** | Data validation and schema enforcement |
| **NumPy** | J-Score optimization and statistical computations |
| **NetworkX** | Dependency graph analysis and betweenness centrality |
| **Redis** | Pub/sub event bus (graceful fallback if unavailable) |
| **PostgreSQL + TimescaleDB** | Persistent storage (optional, Docker Compose provided) |

### Frontend
| Technology | Purpose |
|------------|---------|
| **Next.js 16** | React framework with App Router |
| **React 19** | UI library |
| **Framer Motion** | Animations and micro-interactions |
| **Recharts** | Data visualization (charts, graphs) |
| **Lucide React** | Icon system |
| **Tailwind CSS v4** | Utility-first styling |

---

## Project Structure

```
cloud-security-copilot/
├── cloudguard/                      # ─── BACKEND (Python / FastAPI) ───
│   ├── app.py                       # Unified FastAPI server entry point
│   ├── __init__.py                  # Package metadata (v0.1.0)
│   │
│   ├── api/                         # HTTP & WebSocket interfaces
│   │   ├── routes.py                # REST endpoints (/api/v2/*)
│   │   ├── streamer.py              # WebSocket /ws/war-room + event buffer
│   │   ├── auto_stepper.py          # Background tick loop (drives simulation)
│   │   └── narrative_engine.py      # NarrativeChunk explainability events
│   │
│   ├── core/                        # Core business logic
│   │   ├── math_engine.py           # J-Score, EWM, CRITIC, ROSI, ALE, fuzzy logic
│   │   ├── decision_logic.py        # Sovereign decision: auto-execute vs defer
│   │   ├── remediation.py           # Remediation protocol (command pattern)
│   │   ├── collision_manager.py     # Prevents conflicting concurrent remediations
│   │   ├── audit_reporter.py        # NIST AI RMF-aligned audit report generator
│   │   ├── scheduler.py             # Task scheduling
│   │   ├── clock.py                 # Temporal clock (Tick / Epoch / Cycle / Burst)
│   │   ├── schemas.py               # Pydantic models (UniversalResource, DriftEvent, etc.)
│   │   ├── swarm.py                 # Swarm coordination (CISO, Controller, Orchestrator)
│   │   └── tasks.py                 # Background task definitions
│   │
│   ├── agents/                      # Multi-agent swarm
│   │   ├── swarm.py                 # Agent orchestration logic
│   │   ├── sentry_node.py           # Threat detection & risk assessment
│   │   └── audit_surgeon.py         # Compliance verification & CODE_VETO
│   │
│   ├── forecaster/                  # Threat forecasting subsystem
│   │   ├── threat_forecaster.py     # Amber Alert generation (P ≥ 0.75)
│   │   ├── forecaster.py            # Base forecaster logic
│   │   ├── validation_queue.py      # Forecast validation pipeline
│   │   └── dissipation_handler.py   # Signal decay tracking
│   │
│   ├── simulation/                  # Simulation engine
│   │   ├── engine.py                # Core SimulationEngine orchestrator
│   │   ├── telemetry.py             # SIEM telemetry generator (VPC, CloudTrail, K8s)
│   │   └── chaos_monkey.py          # Drift injection for stress testing
│   │
│   ├── simulator/                   # Advanced simulation scenarios
│   │   ├── amber_sequence_generator.py  # Amber Alert sequence testing
│   │   ├── chaos_monkey.py          # Extended chaos scenarios
│   │   └── inject_drift.py          # Manual drift injection tools
│   │
│   ├── graph/
│   │   └── state_machine.py         # Governance state machine (FSM)
│   │
│   ├── infra/                       # Infrastructure layer
│   │   ├── branch_manager.py        # State branch management (A/B testing)
│   │   ├── memory_service.py        # H-MEM in-memory knowledge store
│   │   └── redis_bus.py             # Redis pub/sub + SIEM log emulator
│   │
│   └── kernel/
│       └── main.py                  # Kernel entry point
│
├── src/                             # ─── FRONTEND (Next.js / React) ───
│   ├── app/
│   │   ├── layout.js                # Root layout (Inter font, metadata)
│   │   ├── page.js                  # Landing page
│   │   ├── globals.css              # Global styles
│   │   └── dashboard/
│   │       ├── layout.js            # Dashboard shell (sidebar navigation)
│   │       ├── page.js              # Overview — Temporal Command Center
│   │       ├── findings/page.js     # Iron Dome — Hex Grid Topology
│   │       ├── cost/page.js         # Friction HUD — Agent Negotiation
│   │       ├── copilot/page.js      # Liaison Console — Explainability
│   │       ├── logs/page.js         # NIST Sovereign Audit Logs
│   │       └── settings/page.js     # Settings
│   │
│   ├── components/
│   │   ├── dashboard/
│   │   │   ├── views/               # Page-level view components
│   │   │   │   ├── TemporalCommandCenter.js
│   │   │   │   ├── IronDomeView.js
│   │   │   │   ├── FrictionHudView.js
│   │   │   │   ├── LiaisonConsoleView.js
│   │   │   │   ├── SovereignAuditLogs.js
│   │   │   │   └── SettingsView.js
│   │   │   └── components/          # Reusable UI components
│   │   │       ├── MetricCard.js
│   │   │       ├── RiskItem.js
│   │   │       ├── HoneycombCell.js
│   │   │       ├── NegotiationLog.js
│   │   │       ├── AuditRow.js
│   │   │       ├── LogTerminalItem.js
│   │   │       └── SidebarItem.js
│   │   └── landing/
│   │       ├── NavBar.js
│   │       ├── FeatureCard.js
│   │       ├── PricingRow.js
│   │       └── AnimatedWorkflowPipeline.js
│   │
│   └── lib/                         # Hooks & API client
│       ├── useSovereignStream.js     # WebSocket hook (real-time + dedup + batch)
│       ├── useMetricData.js          # REST polling (5s interval) + manual refetch()
│       ├── useFastPassTimer.js       # Fast-Pass 10s countdown + veto trigger
│       └── api.js                    # REST client wrapper
│
├── tests/                           # Test suite
│   ├── test_phase1.py               # Phase 1 Foundation tests
│   ├── test_phase2_stress.py        # Multi-agent swarm stress tests
│   ├── test_phase4_validation_suite.py  # Full validation suite
│   ├── test_hmem_amnesia_cure.py    # H-MEM memory service tests
│   ├── test_copilot.py              # Copilot integration tests
│   └── test_routing.py              # API routing tests
│
├── docker-compose.yml               # PostgreSQL + TimescaleDB + Redis
├── pyproject.toml                   # Python project configuration
├── requirements.txt                 # Python dependencies
├── package.json                     # Node.js dependencies
├── .env                             # Environment variables (gitignored)
├── .gitignore                       # Git ignore rules
└── sovereign_safety_report.md       # NIST AI RMF compliance report
```

---

## Getting Started

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Docker (optional) | For Redis & PostgreSQL |

### 1. Clone the Repository

```bash
git clone https://github.com/Mustafa11300/cloud-security-copilot.git
cd cloud-security-copilot
```

### 2. Set Up the Backend

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Start the backend server
uvicorn cloudguard.app:app --port 8000
```

> [!WARNING]
> **Do NOT use the `--reload` flag** — it causes duplicate auto-stepper background tasks resulting in double event emissions.

### 3. Set Up the Frontend

```bash
# Install Node.js dependencies
npm install

# Start the development server
npm run dev
```

The frontend will be available at **http://localhost:3000**.

### 4. Environment Variables

Create a `.env` file in the project root:

```env
# Frontend → Backend connection
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/war-room

# Optional: Gemini API (for LLM-powered narratives)
GOOGLE_API_KEY=your_gemini_api_key

# Optional: AWS (for real cloud integration)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_REGION=us-east-1

```

### 5. Infrastructure (Optional)

```bash
# Start PostgreSQL + TimescaleDB + Redis
docker-compose up -d
```

> [!NOTE]
> The backend **gracefully degrades** if Redis or PostgreSQL are unavailable — all subsystems fall back to in-memory operation.

---

## API Reference

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | `GET` | Health check — confirms server is running |
| `/api/v2/health` | `GET` | Detailed health with subsystem status and war room stats |
| `/api/v2/simulation/state` | `GET` | Current simulation state snapshot |
| `/api/v2/simulation/step` | `POST` | Manually advance simulation by one tick |
| `/api/v2/math/j-score` | `GET` | Current J-Score breakdown (per-resource + Pareto front) |
| `/api/v2/math/j-history` | `GET` | Full J-Score history over time |
| `/api/v2/branches` | `GET` | State branch tree (trunk + experiment branches) |
| `/api/v2/events/audit-report` | `GET` | Download NIST-compliant audit report |
| `/api/v2/events/metrics` | `GET` | Compliance metrics and economics |
| `/api/v2/events/veto` | `POST` | Manual operator veto (cancels Fast-Pass) |
| `/docs` | `GET` | Interactive Swagger UI |
| `/redoc` | `GET` | ReDoc API documentation |

### WebSocket

| Endpoint | Protocol | Description |
|----------|----------|-------------|
| `/ws/war-room` | `WebSocket` | Real-time bidirectional event stream |

**On connect**, the server sends:
1. **BufferReplay** — Last 50 events for instant UI hydration
2. **TopologySync** — Current resource status map (Green/Yellow/Red)

**Emitted event types:**

| Event Type | Source | Description |
|------------|--------|-------------|
| `ForecastSignal` | Threat Forecaster | Amber Alerts and threat predictions |
| `NarrativeChunk` | Narrative Engine | Agent reasoning traces with XAI |
| `Remediation` | Decision Logic | Fix applied (success/failure + J delta) |
| `TopologySync` | Simulation Engine | Resource status snapshot |
| `TickerUpdate` | Auto Stepper | J-Score + weight changes |
| `SwarmCoolingDown` | Swarm | API quota exceeded, backoff active |
| `Heartbeat` | Streamer | 15-second keepalive ping |
| `BufferReplay` | Streamer | Initial event replay for new clients |

---

## Frontend Dashboard

### Design System

- **Theme**: Cyber-Obsidian — light glassmorphism, soft blues, white cards, premium feel
- **Typography**: Inter (Google Fonts)
- **Animations**: Framer Motion with micro-interactions
- **Layout**: Collapsible sidebar (icon navigation) + responsive main content area

### Views

| View | Route | Description |
|------|-------|-------------|
| **Landing Page** | `/` | Product showcase with animated workflow pipeline, feature cards, and pricing tiers |
| **Overview** | `/dashboard` | Temporal Command Center — KPI metric cards, risk horizon, live event feed, active remediations |
| **Iron Dome** | `/dashboard/findings` | Interactive hex-grid topology map showing resource health (Green/Yellow/Red/Amber) |
| **Friction HUD** | `/dashboard/cost` | Agent negotiation visualization + Fast-Pass countdown timer with savings breakdown |
| **Liaison Console** | `/dashboard/copilot` | Explainability feed with J-Score trace, agent reasoning, ROSI calculation, and veto button |
| **Audit Logs** | `/dashboard/logs` | NIST forensic recorder with terminal-style log viewer and report download |
| **Settings** | `/dashboard/settings` | Configuration panel |

### Custom React Hooks

| Hook | Type | Description |
|------|------|-------------|
| `useSovereignStream()` | WebSocket | Real-time events with 50ms batched flushing, dedup by `event_id`, exponential backoff reconnect |
| `useMetricData()` | REST | 5-second polling for compliance metrics and J-history with manual `refetch()` |
| `useFastPassTimer()` | Derived | 10-second countdown derived from `NarrativeChunk` events, triggers veto via REST |

---

## Core Engine Deep Dive

### Simulation Engine

The `SimulationEngine` is the central orchestrator that wires together all subsystems:

```python
engine = SimulationEngine(seed=42)
engine.initialize()  # Generates 345 resources with 40% wasteful baseline

for _ in range(100):
    report = engine.step()  # Advances one tick
    print(f"Tick {report.tick}: J={report.j_percentage}% Governed")
```

**Each tick:**
1. Advances the temporal clock (standard or burst mode)
2. Injects drift events with 5% probability per standard tick
3. Generates SIEM telemetry (VPC flow logs, CloudTrail events, K8s audit logs)
4. Runs agent swarm negotiation if drift detected
5. Calculates new J-Score equilibrium
6. Executes self-correction check (rollback if J worsened)

### J-Score Optimization

The equilibrium function minimizes a weighted sum across all cloud resources:

| Variable | Description |
|----------|-------------|
| `w_R` | Risk weight (Sentry preference) |
| `w_C` | Cost weight (Controller preference) |
| `P` | Probability of threat materialization |
| `R_i` | Risk impact of resource _i_ |
| `C_i` | Remediation cost for resource _i_ |

**Interpretation:**
- `J = 0.0` → Perfectly governed (all risk and cost minimized)
- `J = 1.0` → Worst governance state
- `J%` → `(1 - J) × 100` expressed as "% Governed"

### Economic Analysis

| Metric | Formula | Academic Reference |
|--------|---------|-------------------|
| **ROSI** | `(ALE_before - ALE_after - Cost) / Cost` | Gordon & Loeb (2002) |
| **ALE** | `Asset_Value × Exposure_Factor × ARO` | Standard risk model |
| **Break-Even** | `Remediation_Cost / (Monthly_Savings)` | Time-to-ROI |

### Weighting Methods

| Method | Based On | Purpose |
|--------|----------|---------|
| **EWM** (Entropy Weight) | Shannon Entropy (1948) | High entropy → less discriminating → lower weight |
| **CRITIC** | Diakoulaki et al. (1995) | Combines standard deviation with inter-criteria correlation |
| **Combined** | `α · EWM + (1-α) · CRITIC` | Blended weighting with tunable alpha |

---

## Real-Time Data Flow

```
┌─────────────────┐    Every ~1.5s    ┌───────────────────┐
│  Auto Stepper   │ ───────────────── │ Simulation Engine │
│  (tick loop)    │                   │ (advance_tick)    │
└────────┬────────┘                   └────────┬──────────┘
         │                                     │
         │  telemetry events                   │  drift injection
         ▼                                     ▼
┌─────────────────┐                   ┌───────────────────┐
│  Agent Swarm    │ ◄──── negotiate ──│ Threat Forecaster │
│  (CISO + Ctrl   │                   │ (Amber Alerts)    │
│   + Orch)       │                   └───────────────────┘
└────────┬────────┘
         │  NarrativeChunks + Decision
         ▼
┌─────────────────┐    broadcast()    ┌───────────────────┐
│  WebSocket      │ ─────────────────▶│  React Frontend   │
│  Streamer       │   JSON events     │  (batch + dedup   │
│  (/ws/war-room) │                   │   + setState)     │
└─────────────────┘                   └───────────────────┘
         ▲                                     │
         │  POST /api/v2/events/veto           │
         └─────────────────────────────────────┘
```

### Event Priority Chain

| Priority | Event | Action |
|----------|-------|--------|
| 🔴 **P0** | Amber Alert (P ≥ 0.75) | Immediate Fast-Pass countdown |
| 🟠 **P1** | Critical Drift (PUBLIC_EXPOSURE, PERMISSION_ESCALATION) | Burst mode + swarm debate |
| 🟡 **P2** | High Drift (ENCRYPTION_REMOVED, NETWORK_RULE_CHANGE) | Standard remediation |
| 🟢 **P3** | Medium/Low Drift | Logged, may be filtered by 1% floor |

---

## Testing

The project includes a comprehensive test suite covering all phases:

```bash
# Run all tests
pytest tests/ -v

# Run specific test phases
pytest tests/test_phase1.py -v            # Foundation subsystems
pytest tests/test_phase2_stress.py -v     # Multi-agent stress test
pytest tests/test_phase4_validation_suite.py -v  # Full validation
pytest tests/test_hmem_amnesia_cure.py -v # Memory service tests

# Run the sovereign core integration test
python sovereign_core_test.py
```

### Test Coverage

| Test Suite | Scope | Tests |
|------------|-------|-------|
| `test_phase1.py` | SimulationEngine, MathEngine, Clock, Schemas, BranchManager | Foundation |
| `test_phase2_stress.py` | Swarm negotiation, ChaosMonkey, CollisionManager, ROSI | Stress |
| `test_phase4_validation_suite.py` | Full pipeline: Drift → Forecast → Negotiate → Remediate → Audit | Integration |
| `test_hmem_amnesia_cure.py` | H-MEM memory persistence, recall accuracy | Memory |
| `sovereign_core_test.py` | End-to-end sovereign engine validation | E2E |

---

## NIST Compliance

CloudGuard implements verification against the **NIST AI Risk Management Framework (AI RMF)**:

| # | Behavior | RMF Category | Status |
|---|----------|-------------|--------|
| 1 | Monotone Invariant (J_forecast < J_actual) | `MEASURE-2.1` Robustness | ✅ |
| 2 | 1% Execution Floor (no action on noise) | `MEASURE-2.2` Reliability | ✅ |
| 3 | Jailbreak Detection (CODE_VETO) | `GOVERN-1.3` Robustness | ✅ |
| 4 | J-Function Normalization Stability | `MEASURE-2.1` Reliability | ✅ |
| 5 | Chaos Monkey Stress Resilience | `MEASURE-2.2` Robustness | ✅ |
| 6 | Predictive Amber Alert Accuracy | `MAP-2.1` Explainability | ✅ |
| 7 | Drift Type Distribution Bias Check | `MANAGE-4.1` Bias | ✅ |
| 8 | Dialectical Truth Log (full audit) | `GOVERN-6.1` Explainability | ✅ |

Full report available in [`sovereign_safety_report.md`](sovereign_safety_report.md).

---

## Roadmap

### ✅ Completed

| Phase | Name | Key Deliverables |
|-------|------|-----------------|
| **Phase 1** | Research-Valid Foundation | SimulationEngine, MathEngine (J-Score, EWM, CRITIC), TemporalClock, StateBranchManager, Pydantic schemas, SIEM telemetry |
| **Phase 2** | Multi-Agent Swarm | Sentry Node, Controller Agent, Orchestrator (Pareto/NSGA-II), ChaosMonkey, CollisionManager |
| **Phase 3** | War Room Streaming | WebSocket `/ws/war-room`, Auto Stepper, NarrativeEngine, ping/pong keepalive, backoff reconnection |
| **Phase 4** | Frontend Dashboard | Landing page, 6-view dashboard, real-time WebSocket, T-Minus Sync, Fast-Pass veto, NIST audit download |

### 🔜 Upcoming

| Phase | Name | Key Tasks |
|-------|------|-----------|
| **Phase 5** | Production Hardening | Redis pub/sub for multi-instance, PostgreSQL persistence, JWT auth (Operator/CISO/Viewer roles), rate limiting, Prometheus + Grafana |
| **Phase 6** | Real Cloud Integration | AWS connector (EC2, S3, IAM, SecurityHub), Azure Policy + Defender, GCP Security Command Center, Terraform state drift detection |
| **Phase 7** | LLM Integration | Gemini/GPT-powered narratives (replace rule-based), RAG pipeline (NIST, CIS, SOC2 frameworks), NL-validated veto reasons |
| **Phase 8** | Threat Horizon Overlay | Predictive probability overlay on Iron Dome, attack-path lateral movement visualization, historical state replay/scrubbing |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'feat: add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

### Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable release |
| `testing` | Active development and integration |

---

## License

This project is licensed under the **MIT License**. See [`pyproject.toml`](pyproject.toml) for details.

---

<p align="center">
  <sub>Built by <a href="https://github.com/Mustafa11300">Mustafa Hussain</a> · © 2026 CloudGuard AI</sub>
</p>
