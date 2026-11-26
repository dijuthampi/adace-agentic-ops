# AdAce Agentic Ops - Enterprise Agentic AI Platform

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.50+-blue?logo=python&logoColor=white)](https://langchain-ai.github.io/langgraph/)
[![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-MCP%20v2-purple)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://python.org)
[![MySQL](https://img.shields.io/badge/MySQL-8.0%20Sandbox-4479A1?logo=mysql&logoColor=white)](https://mysql.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20State%20DB-336791?logo=postgresql&logoColor=white)](https://postgresql.org)

**AdAce Agentic Ops** is an Enterprise Agentic AI Workflow Automation Platform designed to operate directly on top of the production AdAce Amazon Advertising MySQL schema. It brings together **LangGraph state persistence**, **FastMCP / MCPServer (MCP v2) tools**, a **dual-database topology (MySQL + PostgreSQL)**, and **deterministic Python guardrails** with an asynchronous **Human-in-the-Loop (HITL) interrupt engine**.

---

## 🏛️ System Architecture Overview

```text
                                  +---------------------------------------+
                                  |      Client / Web Dashboard / CLI     |
                                  +---------------------------------------+
                                                      │
                                                      ▼
+---------------------------------------------------------------------------------------------------+
|                                FASTAPI 0.115+ ASYNC API GATEWAY                                    |
|   /api/v1/health       /api/v1/sellers      /api/v1/mcp/tools      /api/v1/workflows      /api/v1/audit |
+---------------------------------------------------------------------------------------------------+
                                                      │
                                                      ▼
+---------------------------------------------------------------------------------------------------+
|                                LANGGRAPH ADOPS WORKFLOW ENGINE                                    |
|                                                                                                   |
|  [ analyze_account ] ──► [ plan_actions ] ──► [ execute_autonomous ] ──► [ route_after_auto ]      |
|                                                                                 │                 |
|                                             Option 2 (HITL Required)            │  Option 1       |
|                                        ┌────────────────────────────────────────┴────────┐        |
|                                        ▼                                                 ▼        |
|                         [ human_approval_gate ]                                 [ finalize ]      |
|                          • LangGraph interrupt()                                         ▲        |
|                          • Command(resume=...) ──────────────────────────────────────────┘        |
+---------------------------------------------------------------------------------------------------+
                        │                                                   │
                        ▼                                                   ▼
+-----------------------------------------------+   +-----------------------------------------------+
|       MCPSERVER TOOL LAYER (MCP v2)           |   |           POSTGRESQL STATE DB (5433)          |
|                                               |   |                                               |
|  Read-Only Tools:                             |   |  • agent_workflow_runs (thread state)         |
|  • get_seller_guardrails(seller_id)           |   |  • agent_audit_events (immutable node trail)  |
|  • get_campaign_performance(seller_id)        |   |  • LangGraph MemorySaver / Postgres checkpt   |
|  • find_bleeding_search_terms(seller_id)      |   +-----------------------------------------------+
|  • find_oob_scaling_candidates(seller_id)     |
|                                               |
|  Action Tools (Enforcing Guardrails):         |
|  • add_negative_keyword(seller_id, ...)       |
|  • adjust_keyword_bid(seller_id, ...)         |
|  • scale_campaign_budget(seller_id, ...)      |
+-----------------------------------------------+
                        │
                        ▼
+---------------------------------------------------------------------------------------------------+
|                                  ADACE MYSQL SANDBOX (3307)                                       |
|  • sellers, seller_communication_management (day_parting, increase_budget_option)                 |
|  • campaigns, campaign_optimizers (dnt, daily_budget, target_acos)                                |
|  • campaign_metrics, keyword_reports, search_terms                                                 |
|  • adace_status_logs (before/after budget & bid mutation audit records)                           |
+---------------------------------------------------------------------------------------------------+
```

---

## 🚀 Key Sprints & Capabilities

### Sprint 1: Foundation, Dual-DB Topology & AdAce MySQL Sandbox
- **Dual-Database Architecture:**
  - **AdAce MySQL Sandbox (`adace_mysql` on port `3307`):** Production-accurate mirror of the AdAce Amazon Advertising MariaDB/MySQL database.
  - **Agent PostgreSQL (`agent_pg` on port `5433`):** State store for LangGraph checkpoints, workflow runs, and immutable audit events.
- **Production Schema & Seed Data (`db/mysql/init.sql`):**
  - **Seller 1 (Navla Naturals):** `increase_budget_option = 2` (HITL approval required), contains out-of-budget candidate `CAMP101`, bleeder search terms, and brand defense campaign `CAMP103` (`dnt = 1`).
  - **Seller 2 (Peps Mattress):** `increase_budget_option = 1` (Pre-approved autonomous scaling).
- **Core Endpoints:**
  - `GET /api/v1/health`: Dual-DB connectivity and latency monitoring.
  - `GET /api/v1/sellers/{seller_id}/overview`: Structured multi-tenant inspection.

### Sprint 2: AdAce MCPServer (MCP v2) & Deterministic Guardrails
- Implemented `MCPServer("AdAce-AdOps-Server")` in `app/mcp/adace_server.py` exposing 7 tools strictly scoped to `seller_id`:
  1. `get_seller_guardrails`: Queries `max_bid_cap`, `max_budget_cap`, `neg_key_max_no_orders`, and `increase_budget_option`.
  2. `get_campaign_performance`: Joins campaign metadata, optimizer parameters, and latest metrics.
  3. `find_bleeding_search_terms`: Identifies search terms with 0 orders and clicks >= seller threshold (excluding DNT campaigns).
  4. `find_oob_scaling_candidates`: Identifies high-ROAS (>= 3.0) campaigns with >= 80% budget utilization.
  5. `add_negative_keyword` (Tier 1): Autonomous exact-match negation, writing to `adace_status_logs`.
  6. `adjust_keyword_bid` (Tier 2): Bounded autonomous bid scaling (<= 20% increase, <= `max_bid_cap`, DNT check).
  7. `scale_campaign_budget` (Tier 3): Guardrailed scaling requiring `human_approved=True` if `increase_budget_option != 1`.
- `GET /api/v1/mcp/tools`: Self-describing tool discovery catalog.

### Sprint 3: LangGraph Agentic Workflow & True HITL Interrupt Engine
- **Dual-Mode Planner (`app/agent/planner.py`):**
  - Deterministic rule-based planning for local testing and offline CI/CD.
  - LLM-assisted planning with Google Gemini for rich strategic rationales.
- **LangGraph StateGraph (`app/agent/adops_graph.py`):**
  - `analyze_account` ➔ `plan_actions` ➔ `execute_autonomous_actions` ➔ `route_after_autonomous` ➔ `human_approval_gate` (`interrupt()`) ➔ `finalize_report`.
  - True pause-and-resume capability via LangGraph's native `interrupt()` and `Command(resume=...)`.
- **Workflow Management Endpoints:**
  - `POST /api/v1/workflows/sellers/{seller_id}/run`: Starts autonomous execution. Pauses at `pending_approval` for Seller 1; completes immediately for Seller 2.
  - `GET /api/v1/workflows/{thread_id}`: Retrieves complete execution state and audit trail.
  - `POST /api/v1/workflows/{thread_id}/resume`: Resumes suspended thread with operator decision (`approved: true/false`).

### Sprint 4: Unified Audit Trail API, Resilient Gemini Planner & Executive Portfolio
- **Unified Audit Trail API (`app/api/v1/endpoints/audit.py`):**
  - `GET /api/v1/audit/sellers/{seller_id}/trail`: Merges PostgreSQL agent node transitions with MySQL `adace_status_logs` mutation records, normalized to UTC and chronologically ordered.
  - `GET /api/v1/audit/sellers/{seller_id}/workflows`: Historical workflow execution ledger with operator approval tracking.
- **Resilient Live Gemini Planner:**
  - Automated fallback cascade: `gemini-2.5-flash` ➔ `gemini-2.5-flash-lite` ➔ `_plan_deterministic`.
  - Rich executive-grade rationales: Quantified spend savings ($ saved / annualized cost avoidance), ROAS/ACOS efficiency deltas, and projected incremental conversions.
  - Deterministic Python guardrail post-processing clamps.
- **Executive Portfolio Documentation:**
  - [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): Full architectural deep-dive with Mermaid sequence diagrams and design justifications.

---

## 🛡️ Three-Tier Risk Guardrail Matrix

| Risk Tier | Action | Pre-Conditions & Invariants | Execution Mode | Audit Ledger |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | Add Negative Exact Keyword | • 0 orders in 7-day window<br/>• Clicks >= seller threshold (`neg_key_max_no_orders`)<br/>• `dnt == 0` | **Autonomous** | MySQL `adace_status_logs` (`module_id=3`, `action_id=1`) + PostgreSQL `AgentAuditEvent` |
| **Tier 2** | Bounded Keyword Bid Increase | • `dnt == 0`<br/>• ROAS >= 3.5, ACOS < target ACOS<br/>• Bid increase <= 20%<br/>• Proposed bid <= `max_bid_cap` | **Bounded Autonomous** | MySQL `adace_status_logs` (`module_id=6`, `action_id=2`) + PostgreSQL `AgentAuditEvent` |
| **Tier 3** | Campaign Budget Scaling (+30%) | • Spend utilization >= 80% (`spend / budget >= 0.80`)<br/>• ROAS >= 3.0<br/>• `dnt == 0`<br/>• Proposed budget <= `max_budget_cap` | **HITL Guardrailed**<br/>• Option 1: Autonomous pre-approved<br/>• Option 2: LangGraph `interrupt()` | MySQL `adace_status_logs` (`module_id=14`, `action_id=2`, `rule='OOB 3xRoAS'`) + PostgreSQL `AgentAuditEvent` |

---

## 📂 Repository Directory Layout

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
├── docs/
│   └── ARCHITECTURE.md
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
    │   ├── adace.py
    │   └── agent.py
    ├── schemas/
    │   ├── __init__.py
    │   ├── audit.py
    │   ├── health.py
    │   ├── mcp.py
    │   ├── seller.py
    │   └── workflow.py
    ├── mcp/
    │   ├── __init__.py
    │   └── adace_server.py
    ├── agent/
    │   ├── __init__.py
    │   ├── planner.py
    │   └── adops_graph.py
    ├── api/
    │   ├── __init__.py
    │   └── v1/
    │       ├── __init__.py
    │       ├── router.py
    │       └── endpoints/
    │           ├── __init__.py
    │           ├── audit.py
    │           ├── health.py
    │           ├── mcp_tools.py
    │           ├── sellers.py
    │           └── workflows.py
    └── tests/
        ├── __init__.py
        ├── test_health_and_sandbox.py
        ├── test_mcp_tools.py
        ├── test_langgraph_workflows.py
        └── test_audit_trail.py
```

---

## ⚡ 5-Minute Quickstart Guide

### 1. Launch with Docker Compose
Clone the repository and run:
```bash
docker compose up --build -d
```
This spins up:
- `api` on `http://localhost:8000` (FastAPI + Swagger at `/docs`)
- `adace_mysql` on host port `3307` (MySQL 8.0 with pre-seeded AdAce database)
- `agent_pg` on host port `5433` (PostgreSQL 16 state store)

---

## 🔍 End-to-End API Walkthrough & Verification

### Step 1: Check Dual-Database Health
```bash
curl -s http://localhost:8000/api/v1/health | jq .
```
*Expected response:* Both `adace_mysql` and `agent_pg` report `status: "healthy"` with low latency.

---

### Step 2: Inspect Seller Guardrails (Seller 1 - Navla Naturals)
```bash
curl -s http://localhost:8000/api/v1/sellers/1/overview | jq .
```
*Expected response:*
- `max_bid_cap: 25.0`, `max_budget_cap: 2000.0`, `neg_key_max_no_orders: 8`
- `increase_budget_option: 2` (**Approval Required**)

---

### Step 3: Discover Registered MCPServer Tools
```bash
curl -s http://localhost:8000/api/v1/mcp/tools | jq .
```
*Expected response:* Returns all 7 production tools with descriptions and parameter schemas.

---

### Step 4: Run Workflow for Seller 1 (Pauses at HITL Interrupt Gate)
```bash
curl -s -X POST http://localhost:8000/api/v1/workflows/sellers/1/run \
  -H "Content-Type: application/json" \
  -d '{"objective": "Maximize Q4 efficiency and scale top-performing campaigns"}' | jq .
```
*Expected response:*
- `status: "pending_approval"`
- `auto_executed_actions`: Contains Tier 1 bleeder negation in `CAMP102` and Tier 2 bid increase on `KW102_01`
- `pending_hitl_actions`: Contains Tier 3 proposed scaling for `CAMP101` from $500.00 to $650.00 (+30%)
- Note the returned `"thread_id"` (e.g., `wf_adops_1_...`).

---

### Step 5: Inspect Suspended Workflow State
```bash
curl -s http://localhost:8000/api/v1/workflows/<thread_id> | jq .
```
*Expected response:* Displays current thread status, pending HITL actions, and the chronological PostgreSQL audit trail.

---

### Step 6: Resume Workflow with Human Approval
```bash
curl -s -X POST http://localhost:8000/api/v1/workflows/<thread_id>/resume \
  -H "Content-Type: application/json" \
  -d '{
    "seller_id": 1,
    "approved": true,
    "reviewer": "Diju Thampi",
    "notes": "Approved Q4 budget expansion to capture holiday demand"
  }' | jq .
```
*Expected response:*
- `status: "completed"`
- `hitl_decision`: `{"approved": true, "reviewer": "Diju Thampi"}`
- `Campaign.budget` and `CampaignOptimizer.daily_budget` in MySQL are updated to $650.00, and a mutation entry is logged in `adace_status_logs`.

---

### Step 7: Run Workflow for Seller 2 (Autonomous Pre-Approved Execution)
```bash
curl -s -X POST http://localhost:8000/api/v1/workflows/sellers/2/run \
  -H "Content-Type: application/json" \
  -d '{"objective": "Autonomous growth for Peps Mattress"}' | jq .
```
*Expected response:*
- `status: "completed"` immediately. Seller 2 has `increase_budget_option: 1`, so Tier 3 scaling executes without human suspension.

---

### Step 8: Inspect Unified Cross-Database Audit Trail
```bash
curl -s http://localhost:8000/api/v1/audit/sellers/1/trail | jq .
```
*Expected response:*
- `total_events`: 6+ events.
- Seamlessly combines PostgreSQL `AgentAuditEvent` (workflow transitions) and MySQL `AdAceStatusLog` records (exact before/after budget & bid values).
- Sorted chronologically descending.

---

### Step 9: Inspect Seller Workflow Execution History
```bash
curl -s http://localhost:8000/api/v1/audit/sellers/1/workflows | jq .
```
*Expected response:* Lists all historical workflow runs for Seller 1 showing thread IDs, execution summaries, and operator approvals.

---

### Step 10: Run the Complete Pytest Suite
```bash
pytest app/tests/ -v
```
*Expected result:* All 29 unit and integration tests pass cleanly without deprecation warnings or unawaited mock coroutine warnings.
