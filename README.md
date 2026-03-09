# 🛡️ CloudGuard — GenAI-Powered Cloud Security Copilot

> **Built for the [Elasticsearch Agent Builder Hackathon](https://hackathon.elastic.co) & [Amazon Nova AI Hackathon](https://amazonova.devpost.com) — 2026**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Elasticsearch](https://img.shields.io/badge/Elasticsearch-8.x-005571?style=for-the-badge&logo=elasticsearch&logoColor=white)
![Amazon Nova](https://img.shields.io/badge/Amazon_Nova-2_Lite-FF9900?style=for-the-badge&logo=amazonaws&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Problem Statement](#-problem-statement)
- [Solution](#-solution)
- [Architecture](#-architecture)
- [Tech Stack](#-tech-stack)
- [Folder Structure](#-folder-structure)
- [Setup & Installation](#-setup--installation)
- [Detection Rules](#-detection-rules-logic-focus)
- [Risk Scoring Formula](#-risk-scoring-formula)
- [AI Agent — Multi-Step Reasoning](#-ai-agent--multi-step-reasoning)
- [API Reference](#-api-reference)
- [Environment Variables](#-environment-variables)
- [Demo](#-demo)
- [Troubleshooting](#-troubleshooting)
- [Submission Checklist](#-submission-checklist)

---

## 🎯 Overview

**CloudGuard** is a multi-step AI agent that continuously scans a simulated AWS cloud environment, detects misconfigurations and cost waste, scores overall security posture, and provides natural-language explanations and prioritized remediation guidance through a conversational copilot interface.

| Field | Details |
|-------|---------|
| **Hackathons** | Elasticsearch Agent Builder • Amazon Nova AI |
| **Category** | Agentic AI / Multi-step Reasoning |
| **License** | MIT Open Source |
| **Dataset** | 290 simulated AWS resources with injected misconfigurations |

---

## 🚨 Problem Statement

> *"Rapid cloud adoption leads to unused resources, misconfigurations, and security gaps, increasing cost and attack surface."*

Cloud teams face:

- 🔴 **Security misconfigurations** — S3 buckets publicly accessible, SSH open to the entire internet, databases with no encryption
- 💸 **Cost waste** — EC2 instances running at 2% CPU 24/7, paying for nothing
- 🌊 **Alert fatigue** — engineers drowning in fragmented dashboards with no prioritization
- 🔁 **Reactive posture** — problems discovered after incidents, never before

No single tool correlates security risk + cost waste + trend analysis + plain-English remediation in one place. CloudGuard is that tool.

---

## 💡 Solution

CloudGuard encodes the expertise of a cloud security analyst into a 6-layer pipeline:

1. **Generates** 290 simulated AWS cloud resources (EC2, S3, IAM, Security Groups, RDS) with realistic injected misconfigurations
2. **Detects** problems using a 15-rule engine — each rule encodes a real security best practice with severity weights and business impact framing
3. **Scores** overall security posture using a composite weighted penalty formula (0–100)
4. **Indexes** everything into Elasticsearch across 3 purpose-built indices with ES|QL analytics queries
5. **Reasons** using Amazon Nova 2 Lite — the agent plans which tools to call, chains them contextually, and synthesizes a prioritized recommendation
6. **Displays** results through a React dashboard with 4 analytical panels and a conversational copilot chat

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CloudGuard Architecture                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [Python Faker]  →  [Rule Engine]  →  [Scorer]                     │
│       ↓                  ↓               ↓                         │
│  290 Resources      15 Findings    Posture Score                   │
│                          ↓                                         │
│              [Elasticsearch Indices]                                │
│         cloud-resources | security-findings | scan-history         │
│                          ↓                                         │
│            [Elastic Agent Builder Tools]                            │
│     get_critical | get_cost_waste | get_trend | get_top_risks      │
│                          ↓                                         │
│              [Amazon Nova 2 Lite]                                  │
│         Plan → Execute Tools → Contextualize → Synthesize          │
│                          ↓                                         │
│               [FastAPI REST API]                                    │
│          /findings  |  /score  |  /chat                            │
│                          ↓                                         │
│              [React Dashboard]                                      │
│    ScoreCard | FindingsDonut | CostWaste | DriftChart | Copilot    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Data Generation** | Python + Faker | 290 fake AWS resources with injected misconfigs |
| **Rule Engine** | Pure Python | 15 detection rules with severity + business impact |
| **Scoring** | Pure Python | Composite weighted penalty formula |
| **Database** | Elasticsearch 8.x | 3 indices, ES\|QL analytics, vector KB |
| **Agent Orchestration** | Elastic Agent Builder | 6 named tools backed by ES queries |
| **AI Reasoning** | Amazon Nova 2 Lite | Multi-step tool planning + synthesis |
| **Backend** | FastAPI + Python | REST API connecting all layers |
| **Frontend** | React + Tailwind + Recharts | Dashboard + conversational UI |

---

## 📁 Folder Structure

```
cloud-security-copilot/
│
├── backend/
│   ├── main.py                     # FastAPI entry point
│   ├── requirements.txt            # Python dependencies
│   ├── bootstrap.py                # One-shot setup script
│   ├── test_connections.py         # Verify ES + Nova before running
│   ├── .env                        # Secrets (never commit this!)
│   │
│   ├── data/
│   │   └── generator.py            # Generates 290 fake AWS resources ⭐
│   │
│   ├── engine/                     # ⭐ THE LOGIC CORE
│   │   ├── rules.py                # 15 misconfiguration detection rules
│   │   └── scorer.py               # Composite risk scoring formula
│   │
│   ├── elastic/
│   │   ├── client.py               # Elasticsearch connection
│   │   ├── indexer.py              # Pushes data into ES indices
│   │   └── queries.py              # Named ES|QL business queries
│   │
│   ├── agent/
│   │   ├── tools.py                # 6 agent tools backed by ES
│   │   └── copilot.py              # Nova 2 Lite multi-step agent
│   │
│   └── api/
│       ├── findings.py             # GET /api/findings/*
│       ├── score.py                # GET /api/score/
│       └── chat.py                 # POST /api/chat/
│
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx                 # Root dashboard component
│       └── components/
│           ├── ScoreCard.jsx       # Security posture score (big number)
│           ├── FindingsChart.jsx   # Donut chart by severity
│           ├── CostWaste.jsx       # Bar chart of wasted money
│           ├── DriftChart.jsx      # Line chart — score over time
│           └── CopilotChat.jsx     # Conversational AI interface
│
└── README.md
```

---

## 🚀 Setup & Installation

### Prerequisites

- Python 3.10+
- Node.js 18+
- [Elasticsearch Cloud](https://cloud.elastic.co) account (free trial)
- [AWS account](https://aws.amazon.com/free) with Bedrock Nova Lite enabled in `us-east-1`

---

### Step 1 — Clone & Install

```bash
git clone https://github.com/your-username/cloud-security-copilot
cd cloud-security-copilot/backend
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

### Step 2 — Create `__init__.py` files

```bash
touch api/__init__.py engine/__init__.py elastic/__init__.py agent/__init__.py data/__init__.py
```

---

### Step 3 — Configure `.env`

Create `backend/.env`:

```env
# Elasticsearch
ES_HOST=https://your-deployment.es.us-central1.gcp.elastic.cloud:443
ES_API_KEY=your-encoded-elastic-api-key

# AWS (IAM credentials with Bedrock access)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_REGION=us-east-1
```

> ⚠️ **Never commit `.env` to Git.** It's already in `.gitignore`.

---

### Step 4 — Test Connections

```bash
cd backend
python test_connections.py
```

Expected output:
```
Testing Elasticsearch...
✅ Elasticsearch connected!
   Cluster: your-cluster-name

Testing AWS Bedrock (Nova)...
✅ Nova connected! Response: 'Hello there, how are you!'
```

---

### Step 5 — Bootstrap Data

```bash
python bootstrap.py
```

This single command:
- Creates 3 Elasticsearch indices
- Generates 290 simulated AWS resources
- Runs the 15-rule detection engine
- Indexes all resources and findings into ES
- Saves the first scan snapshot for trend tracking

Expected output:
```
1️⃣  Creating Elasticsearch indices...
2️⃣  Generating simulated cloud dataset... ✅ 290 resources
3️⃣  Running security rule engine... 🔴 CRITICAL: 25  🟠 HIGH: 40
4️⃣  Indexing resources...
5️⃣  Indexing findings...
6️⃣  Saving scan snapshot...
✅ Bootstrap complete!
   Security Score:  42/100
   Total Findings:  128
   Monthly Waste:   $485.32
```

---

### Step 6 — Start the API Server

```bash
cd backend
uvicorn main:app --reload
```

- API: `http://localhost:8000`
- Swagger docs: `http://localhost:8000/docs`

---

### Step 7 — Start the Frontend

```bash
cd frontend
npm install
npm start
```

Dashboard: `http://localhost:3000`

---

## 🔍 Detection Rules (Logic Focus)

> The rule engine is the core of the project. Each rule encodes a real security best practice with documented thresholds and business impact framing. **Judges: this is where the logic lives.**

| Rule ID | Rule Name | Severity | Score | Logic Threshold |
|---------|-----------|----------|-------|-----------------|
| `EC2-001` | Underutilized EC2 Instance | MEDIUM | -45 | `cpu_avg < 5%` AND `running_hours > 168` → 85% of cost is waste |
| `EC2-002` | Missing Purpose Tag | LOW | -20 | `has_purpose_tag == False` → cannot allocate cost or ownership |
| `S3-001` | **S3 Publicly Accessible** | 🔴 CRITICAL | -95 | `public_access_blocked == False` → anyone on internet reads your files |
| `S3-002` | S3 Encryption Disabled | HIGH | -70 | `encryption_enabled == False` → fails PCI-DSS, HIPAA, SOC2 |
| `S3-003` | S3 Access Logging Disabled | MEDIUM | -40 | `logging_enabled == False` → no audit trail for data access |
| `IAM-001` | **MFA Not Enabled** | HIGH | -75 | `mfa_enabled == False` → stolen password = full account access |
| `IAM-002` | Inactive User 90+ Days | MEDIUM | -50 | `days_since_last_login > 90` → ghost door into system |
| `IAM-003` | Admin Policy Attached | HIGH | -80 | `has_admin_policy == True` → violates least-privilege principle |
| `IAM-004` | Access Key Not Rotated | MEDIUM | -45 | `access_key_age_days > 90` → stale key, long exposure window |
| `SG-001` | **SSH Open to Internet** | 🔴 CRITICAL | -90 | `port 22` + `source 0.0.0.0/0` → brute force & exploit target |
| `SG-002` | **RDP Open to Internet** | 🔴 CRITICAL | -90 | `port 3389` + `source 0.0.0.0/0` → #1 ransomware initial access vector |
| `SG-003` | Database Port Exposed | HIGH | -85 | `ports 3306/5432/27017` + `0.0.0.0/0` → direct database access |
| `RDS-001` | **RDS Publicly Accessible** | 🔴 CRITICAL | -88 | `publicly_accessible == True` → database reachable from internet |
| `RDS-002` | RDS Encryption Disabled | HIGH | -72 | `encryption_at_rest == False` → plain text database storage |
| `RDS-003` | RDS Backups Disabled | HIGH | -65 | `backup_enabled == False` → ransomware = permanent data loss |

### Why These Thresholds?

- **5% CPU = idle:** Industry standard for "underutilized" (AWS Trusted Advisor uses the same)
- **90 days = inactive:** CIS Benchmark v1.4 for IAM user lifecycle management
- **168 hours (1 week):** Minimum run time to confirm waste isn't a fluke
- **0.0.0.0/0:** CIDR notation for "entire internet" — always dangerous for sensitive ports

---

## 📊 Risk Scoring Formula

The Security Posture Score is a single **0–100** number computed using a weighted penalty system:

```
Score = max(0, 100 − (CRITICAL × 20) − (HIGH × 10) − (MEDIUM × 5) − (LOW × 2))
```

### Why These Weights?

| Severity | Penalty | Rationale |
|----------|---------|-----------|
| CRITICAL | −20 pts | Immediate breach risk — data exposure or account takeover possible right now |
| HIGH | −10 pts | Significant attack surface — exploitable with moderate effort |
| MEDIUM | −5 pts | Compliance gaps and best practice violations |
| LOW | −2 pts | Hygiene issues — no immediate risk but should be resolved |

### Score Tiers

| Score | Tier | Meaning |
|-------|------|---------|
| 80–100 | 🟢 GOOD | Healthy posture. Continue monitoring. |
| 60–79 | 🟡 FAIR | Notable issues. Schedule remediation within 30 days. |
| 40–59 | 🟠 POOR | Significant vulnerabilities. Prioritize immediately. |
| 0–39 | 🔴 CRITICAL | Immediate action required. Active exposure detected. |

---

## 🤖 AI Agent — Multi-Step Reasoning

The Nova 2 Lite agent follows a **4-step reasoning pipeline** for every query:

```
User Query
    ↓
Step 1: PLAN   → Nova reads query, selects 2–4 relevant tools from registry
    ↓
Step 2: EXECUTE → Each tool queries Elasticsearch, returns structured data
    ↓
Step 3: CONTEXTUALIZE → All tool results concatenated into rich context
    ↓
Step 4: SYNTHESIZE → Nova reasons over full context, generates prioritized answer
    ↓
Business-Language Response with Priority Actions
```

### Available Tools

| Tool | ES Query | Answers |
|------|----------|---------|
| `get_critical_findings` | security-findings index, severity=CRITICAL | What are my most dangerous issues? |
| `get_high_findings` | security-findings index, severity=HIGH | What needs fixing this week? |
| `get_cost_waste` | findings with rule_id=EC2-001 | How much money am I wasting? |
| `get_risk_trend` | scan-history index, last N days | Is my posture getting better or worse? |
| `get_top_risks` | Top N by risk_score desc | Which specific resources need attention first? |
| `get_resource_type_breakdown` | ES aggregation by resource_type | Which resource type has the most problems? |

### Example Agent Interaction

```
User: "What should I fix first?"

Agent Step 1 → Plans: ["get_critical_findings", "get_top_risks", "get_risk_trend"]
Agent Step 2 → Executes all 3 tools against Elasticsearch
Agent Step 3 → Builds context from 3 tool results
Agent Step 4 → Synthesizes:

## Summary
Your environment has 3 critical exposures requiring immediate action.
Security score is 42/100 (POOR) and has declined 8 points in 7 days.

## Key Findings
1. S3 bucket s3-customer-data-482 is publicly accessible (50,000 objects exposed)
2. Security group sg-a1b2c3d4 has SSH port 22 open to 0.0.0.0/0
3. RDS database rds-prod-main is publicly accessible

## Priority Actions
1. TODAY: Block public access on s3-customer-data-482 (S3 Console → Permissions → Block Public Access)
2. THIS WEEK: Restrict SSH to VPN subnet only in sg-a1b2c3d4
3. THIS MONTH: Set RDS publicly_accessible=false and enable encryption
```

---

## 🔌 API Reference

All endpoints served at `http://localhost:8000`. Full docs at `/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/score/` | Current security score + cost health + monthly waste |
| `GET` | `/api/score/trend` | Score history for drift chart (`?days=7`) |
| `GET` | `/api/findings/summary` | Finding counts by severity — drives donut chart |
| `GET` | `/api/findings/critical` | All CRITICAL findings with full remediation details |
| `GET` | `/api/findings/top` | Top N highest risk_score findings (`?limit=10`) |
| `GET` | `/api/findings/by-type` | ES aggregation: findings grouped by resource type |
| `POST` | `/api/chat/` | Body: `{"message": "..."}` — runs Nova agent, returns reasoning + answer |

### Example Chat Request

```bash
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "What are my top 3 security risks?"}'
```

---

## ⚙️ Environment Variables

| Variable | Example | How to Get It |
|----------|---------|---------------|
| `ES_HOST` | `https://abc.es.us-central1.gcp.elastic.cloud:443` | Elastic Cloud → Deployment → Copy endpoint (swap `kb` → `es`, add `:443`) |
| `ES_API_KEY` | `dGVzdDp0ZXN0MTIz==` | Kibana → Stack Management → API Keys → Create → copy **Encoded** value |
| `AWS_ACCESS_KEY_ID` | `AKIAIOSFODNN7EXAMPLE` | AWS Console → Account name → Security credentials → Create access key |
| `AWS_SECRET_ACCESS_KEY` | `wJalrXUtnFEMI/...` | Same page — shown once, download CSV immediately |
| `AWS_REGION` | `us-east-1` | Must be `us-east-1` — Nova Lite only available here |

---

## 🎬 Demo

### Dashboard Panels

| Panel | Question It Answers |
|-------|-------------------|
| Security Posture Score | Are we secure right now? |
| Findings by Severity | What type of problems do we have? |
| Cost Waste | How much money are we wasting and on what? |
| Risk Drift Over Time | Is our security getting better or worse? |
| AI Copilot Chat | What should I do about it? |

### Suggested Copilot Queries

```
"What should I fix first?"
"What are my biggest security risks?"
"How much money am I wasting?"
"Is my security posture getting better or worse?"
"Show me all critical findings"
"Which resource type has the most problems?"
```

---

## 🔧 Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ValueError: URL must include scheme, host, port` | `ES_HOST` missing `:443` | Add `:443` to end of ES_HOST |
| `Could not connect to Elasticsearch` | Wrong ES_HOST or API key | Verify ES_HOST uses `.es.` subdomain not `.kb.` |
| `Unable to locate credentials` | AWS keys missing | Add `AWS_ACCESS_KEY_ID` + `SECRET` to `.env` |
| `ModuleNotFoundError: No module named 'api'` | Running from wrong directory | `cd backend` first, then `uvicorn main:app` |
| `CORS Error in browser` | Frontend can't reach API | Check `allow_origins` in `main.py` |
| Empty dashboard after launch | Bootstrap not run | Run `python bootstrap.py` from `backend/` |
| `AccessDeniedException` from Nova | Nova not enabled in Bedrock | Bedrock → Model catalog → Nova Lite → Enable |

---

## ✅ Submission Checklist

- [ ] `data/generator.py` — 290 resources with injected misconfigs
- [ ] `engine/rules.py` — 15 rules with documented thresholds + business impact
- [ ] `engine/scorer.py` — Composite scoring formula with tier classification
- [ ] `elastic/` — 3 ES indices + 6 ES|QL queries answering business questions
- [ ] `agent/copilot.py` — Nova 2 Lite multi-step tool-chaining agent
- [ ] `frontend/` — React dashboard with 4 panels + copilot chat
- [ ] Architecture diagram
- [ ] 3-minute demo video
- [ ] Public GitHub repo with MIT license
- [ ] Social post tagging `@elastic_devs` and `@AWSCloud`
- [ ] Blog post on builder.aws.com (Amazon Nova bonus prize)

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

