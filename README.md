# AdAce Agentic Ops - Enterprise Agentic AI Platform

**AdAce Agentic Ops** is an Enterprise Agentic AI Workflow Automation Platform designed to sit directly on top of the production AdAce Amazon Advertising MySQL schema. It utilizes LangGraph for intelligent multi-tier decisioning and safe autonomous execution with strict guardrails, FastMCP tool servers, and Human-In-The-Loop (HITL) approval gates.

---

## Architectural Sprints

### Sprint 1: Foundation & Dual-DB Topology
1. **Dual-Database Topology:**
   - **AdAce MySQL Sandbox (`adace_mysql` on host port `3307`):** Production-accurate mirror of the AdAce MariaDB/MySQL Amazon Ads database, initialized with realistic multi-tenant data.
   - **Agent PostgreSQL (`agent_pg` on host port `5433`):** State store for LangGraph checkpointers, agent execution traces, and HITL approval states.
2. **AdAce Production Schema & Seed Scenarios (`db/mysql/init.sql`):**
   - Tables: `sellers`, `seller_communication_management`, `campaigns`, `campaign_optimizers`, `campaign_metrics`, `keyword_reports`, `search_terms`, `adace_status_logs`.
   - Seeded with **Navla Naturals (Seller 1)** (HITL required, OOB candidate, bleeders, DNT campaign) and **Peps Mattress (Seller 2)** (autonomous pre-approved tenant).
3. **Dual-DB Engine & Inspection Endpoints:**
   - `GET /api/v1/health`: Concurrent health and latency probes for both databases.
   - `GET /api/v1/sellers/{seller_id}/overview`: Structured seller overview with guardrails and campaigns.

---

### Sprint 2: AdAce MCPServer (MCP v2) & Deterministic Guardrails
The MCPServer instance (`AdAce-AdOps-Server` in `app/mcp/adace_server.py`) provides 7 production tools strictly scoped to `seller_id`:

#### Read-Only Analytics Tools
1. **`get_seller_guardrails(seller_id: int) -> dict`**:
   - Fetches `max_bid_cap`, `max_budget_cap`, `neg_key_max_no_orders`, and `increase_budget_option` HITL flag.
2. **`get_campaign_performance(seller_id: int) -> list[dict]`**:
   - Joins `Campaign`, `CampaignOptimizer` (DNT flag, target ACOS, daily budget), and latest `CampaignMetric`.
3. **`find_bleeding_search_terms(seller_id: int) -> list[dict]`**:
   - Queries `SearchTerm` where `units_sold_clicks_7d == 0` and `clicks >= threshold`, strictly excluding DNT (`dnt == 1`) campaigns.
4. **`find_oob_scaling_candidates(seller_id: int) -> list[dict]`**:
   - Finds active campaigns with spend utilization >= 80% and ROAS >= 3.0, calculating +30% budget capped by `max_budget_cap`.

#### Guardrailed Action Tools (With Risk Tiers & Audit Ledger)
5. **`add_negative_keyword(seller_id, campaign_str_id, keyword_text, match_type, reason) -> dict` [Tier 1 - Autonomous]**:
   - Scoped to `seller_id`; blocked if campaign has `dnt == 1`. Records audit entry in `adace_status_logs` (`module_id=3`, `action_id=1`).
6. **`adjust_keyword_bid(seller_id, keyword_id, new_bid, reason) -> dict` [Tier 2 - Bounded Autonomous]**:
   - Enforces `new_bid <= max_bid_cap`, blocked if parent campaign has `dnt == 1`, and restricts single-step increase to `<= 20%` of current bid. Records in `adace_status_logs` (`module_id=6`, `action_id=2`).
7. **`scale_campaign_budget(seller_id, campaign_str_id, proposed_budget, human_approved, reason) -> dict` [Tier 3 - HITL Guardrailed]**:
   - Enforces `proposed_budget <= max_budget_cap` and `dnt == 0`.
   - If `increase_budget_option != 1` (Approval Required) and `human_approved is False`, **DOES NOT mutate the database**; returns `{"status": "approval_required", ...}`.
   - When approved or pre-approved, updates `Campaign.budget` & `CampaignOptimizer.daily_budget`, and logs before/after in `adace_status_logs` (`module_id=14`, `action_id=2`, `rule='OOB 3xRoAS'`).

---

## Directory Structure

```text
adace-agentic-ops/
├── .env.example
├── .env
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── pytest.ini
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
    │   ├── mcp.py
    │   └── seller.py
    ├── mcp/
    │   ├── __init__.py
    │   └── adace_server.py
    ├── api/
    │   ├── __init__.py
    │   └── v1/
    │       ├── __init__.py
    │       ├── router.py
    │       └── endpoints/
    │           ├── __init__.py
    │           ├── health.py
    │           ├── mcp_tools.py
    │           └── sellers.py
    └── tests/
        ├── __init__.py
        ├── test_health_and_sandbox.py
        └── test_mcp_tools.py
```

---

## Quickstart & Inspection Guide

### 1. Launch with Docker Compose
```bash
docker-compose up --build -d
```

### 2. Inspect Registered FastMCP Tools
```bash
curl http://localhost:8000/api/v1/mcp/tools
```

### 3. Run Automated Analysis for Seller 1 (Navla Naturals)
```bash
curl -X POST http://localhost:8000/api/v1/mcp/sellers/1/analyze
```

### 4. Interactive Swagger Documentation
Open your browser at [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs) to explore and execute the MCP tools directly.

### 5. Run the Test Suite
```bash
pytest app/tests/ -v
```
