# AdAce Agentic Ops - Sprint 1: Foundation & Dual-DB Topology

**AdAce Agentic Ops** is an Enterprise Agentic AI Workflow Automation Platform designed to sit directly on top of the production AdAce Amazon Advertising MySQL schema. It utilizes LangGraph for intelligent multi-tier decisioning and safe autonomous execution with strict guardrails and Human-In-The-Loop (HITL) approval gates.

---

## Sprint 1 Architectural Deliverables

1. **Dual-Database Topology:**
   - **AdAce MySQL Sandbox (`adace_mysql` on port `3307`):** Production-accurate mirror of the AdAce MariaDB/MySQL Amazon Ads database, initialized with realistic multi-tenant data.
   - **Agent PostgreSQL (`agent_pg` on port `5433`):** State store for LangGraph checkpointers, agent execution traces, and HITL approval states.
   - Port conflicts with local host services (e.g. Laragon MySQL on 3306 or default Postgres on 5432) are safely avoided.

2. **Accurate AdAce Schema & Realistic Seed Scenarios (`db/mysql/init.sql`):**
   - Tables: `sellers`, `seller_communication_management`, `campaigns`, `campaign_optimizers`, `campaign_metrics`, `keyword_reports`, `search_terms`, `adace_status_logs`.
   - **Seller 1 (`Navla Naturals`, `id=1`):**
     - Guardrails: `max_bid_cap=25.00`, `max_budget_cap=2000.00`, `neg_key_max_no_orders=8`.
     - Communication: `increase_budget_option=2` (Requires HITL approval before raising budgets).
     - Campaign 1 (`O3M-SP-AT-MAIN`): `budget=500.00`, `spend=460.00` (92% utilization > 80%), `roas=4.20` — Prime candidate for Tier 3 out-of-budget +30% budget scaling.
     - Campaign 2 (`O3M-SP-ML-EXACT`): Contains bleeder search terms exceeding 8 clicks with 0 orders for Tier 1 negative harvesting, and high-ROAS keyword for Tier 2 bid scaling.
     - Campaign 3 (`O3M-SP-BRAND-PROTECT`): Flagged with `dnt=1` (Do Not Touch) guardrail test case.
   - **Seller 2 (`Peps Mattress`, `id=2`):**
     - Autonomous pre-approved profile (`increase_budget_option=1`, `max_budget_cap=5000.00`) for testing strict tenant isolation.

3. **FastAPI Dual-DB Engine & Inspection Endpoints:**
   - `GET /api/v1/health`: Real-time async connectivity probe and latency measurement for both MySQL and Postgres.
   - `GET /api/v1/sellers/{seller_id}/overview`: Structured seller inspection endpoint returning safety caps, communication settings, active campaigns, DNT flags, and budget utilization percentages.

---

## Directory Structure

```text
adace-agentic-ops/
├── .env.example
├── .env
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
├── db/
│   └── mysql/
│       └── init.sql
└── app/
    ├── __init__.py
    ├── main.py
    ├── core/
    │   ├── __init__.py
    │   └── config.py
    ├── db/
    │   ├── __init__.py
    │   ├── mysql.py
    │   └── postgres.py
    ├── models/
    │   ├── __init__.py
    │   └── adace.py
    ├── schemas/
    │   ├── __init__.py
    │   ├── health.py
    │   └── seller.py
    ├── api/
    │   ├── __init__.py
    │   └── v1/
    │       ├── __init__.py
    │       ├── router.py
    │       └── endpoints/
    │           ├── __init__.py
    │           ├── health.py
    │           └── sellers.py
    └── tests/
        ├── __init__.py
        └── test_health_and_sandbox.py
```

---

## Quickstart Guide

### 1. Launch with Docker Compose
To start the FastAPI application and both sandbox databases:
```bash
docker-compose up --build -d
```

### 2. Verify Database Health
Probe the dual-DB health endpoint:
```bash
curl http://localhost:8000/api/v1/health
```

Expected JSON response:
```json
{
  "status": "healthy",
  "mysql": {
    "connected": true,
    "message": "AdAce MySQL connection healthy",
    "latency_ms": 1.2
  },
  "postgres": {
    "connected": true,
    "message": "Agent PostgreSQL connection healthy",
    "latency_ms": 0.8
  },
  "timestamp": "2026-11-26T15:00:00Z"
}
```

### 3. Inspect Seller 1 (Navla Naturals)
```bash
curl http://localhost:8000/api/v1/sellers/1/overview
```

Key verified fields:
- `guardrails.max_bid_cap`: `25.00`
- `communication_settings.requires_hitl_approval`: `true`
- `campaigns[0].campaign_name`: `O3M-SP-AT-MAIN` (utilization: `92.0%`, ROAS: `4.20`)
- `campaigns[2].dnt`: `true` (`O3M-SP-BRAND-PROTECT` protected by Do Not Touch)

### 4. Running the Test Suite
```bash
pytest app/tests/ -v
```
