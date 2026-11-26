# AdAce Agentic Ops - System Architecture & Engineering Deep-Dive

**AdAce Agentic Ops** is an Enterprise Agentic AI Workflow Automation Platform designed to operate directly on top of the production AdAce Amazon Advertising MySQL schema. It blends **LangGraph state persistence**, **FastMCP / MCPServer (MCP v2) tool interfaces**, a **dual-database topology (MySQL + PostgreSQL)**, and **deterministic Python guardrails** with an asynchronous **Human-in-the-Loop (HITL) interrupt engine**.

---

## 1. High-Level System Architecture

The platform separates volatile agent workflow state and immutable compliance audit trails from live advertising business data.

```mermaid
flowchart TB
    subgraph Client["Client & Operator Layer"]
        UI["Web Dashboard / Swagger UI"]
        CLI["AdAce Operator CLI / curl"]
    end

    subgraph Gateway["API Gateway (FastAPI 0.115+)"]
        H_EP["Health & Inspection (/health, /sellers)"]
        MCP_EP["MCP Tools Catalog (/mcp/tools)"]
        WF_EP["Workflow Orchestration (/workflows)"]
        AUDIT_EP["Unified Audit Trail (/audit)"]
    end

    subgraph Engine["LangGraph AdOps Engine"]
        ANALYZE["analyze_account"]
        PLAN["plan_actions<br/>(Gemini Flash ➔ Flash-Lite ➔ Rule Cascade)"]
        EXEC_AUTO["execute_autonomous_actions<br/>(Tier 1 & Tier 2)"]
        ROUTE{"route_after_autonomous<br/>(Option 1 vs Option 2)"}
        HITL["human_approval_gate<br/>[LangGraph interrupt()]"]
        FINALIZE["finalize_report"]
        CHECKPOINTER[("MemorySaver / Postgres Checkpointer")]
    end

    subgraph ToolLayer["MCPServer Tool Layer (MCP v2)"]
        MCP["AdAce-AdOps-Server"]
        T1_T4["Analytics Tools (Guardrails, Performance, Bleeders, OOB)"]
        T5_T7["Action Tools (Negations, Bids, Budget Scaling)"]
    end

    subgraph DualDB["Dual-Database Topology"]
        subgraph MySQL["MySQL Sandbox (Port 3307)"]
            MYSQL_DATA[("AdAce Production Data<br/>sellers, campaigns, metrics,<br/>search_terms, adace_status_logs")]
        end
        subgraph Postgres["PostgreSQL State DB (Port 5433)"]
            PG_DATA[("Agent State & Traces<br/>agent_workflow_runs,<br/>agent_audit_events")]
        end
    end

    Client --> Gateway
    Gateway --> Engine
    Engine --> ToolLayer
    ToolLayer --> MySQL
    Engine --> Postgres
    Engine --> CHECKPOINTER
    ANALYZE --> PLAN --> EXEC_AUTO --> ROUTE
    ROUTE -- "requires_hitl == True" --> HITL --> FINALIZE
    ROUTE -- "autonomous == True" --> FINALIZE
```

---

## 2. Dual-Database Hybrid Topology & Data Model Justification

### Why Dual-Database?

| Dimension | AdAce MySQL Sandbox (`adace_mysql`: 3307) | Agent PostgreSQL State DB (`agent_pg`: 5433) |
| :--- | :--- | :--- |
| **Primary Responsibility** | Live Amazon Advertising relational schema & business entities | Agent execution state, thread checkpoints, and immutable audit logs |
| **Data Nature** | Highly structured, transactional, relational schema mirrored from production MariaDB/MySQL | Semi-structured JSONB payloads, thread graph states, and append-only event logs |
| **Key Tables** | `sellers`, `seller_communication_management`, `campaigns`, `campaign_optimizers`, `campaign_metrics`, `keyword_reports`, `search_terms`, `adace_status_logs` | `agent_workflow_runs`, `agent_audit_events` |
| **Isolation & Security** | Read/write scoped strictly to advertising entities; mutations guarded by deterministic safety rules | Ephemeral graph state & operator audit trails; safe from ad campaign schema migrations |
| **Concurrency / ORM** | Async SQLAlchemy 2.0 with `aiomysql` connection pooling | Async SQLAlchemy 2.0 with `asyncpg` and psycopg3 connection pooling |

### Database Schema Interaction

```text
+---------------------------------------------------------------------------------------------------+
|                                      DUAL-DATABASE TOPOLOGY                                       |
+---------------------------------------------------------------------------------------------------+
|  ADACE MYSQL SANDBOX (adace_sandbox @ 3307)         |  AGENT POSTGRESQL (agent_ops @ 5433)         |
|                                                     |                                             |
|  [sellers]                                          |  [agent_workflow_runs]                      |
|    id, max_bid_cap, max_budget_cap, neg_key_limit   |    thread_id (PK), seller_id, status        |
|       │ 1:1                                         |    objective, proposed_plan (JSONB)         |
|       ▼                                             |    pending_hitl_actions (JSONB)             |
|  [seller_communication_management]                  |    execution_summary (JSONB), approved_by   |
|    increase_budget_option (1=Auto, 2=HITL)          |    created_at, updated_at                   |
|       │                                             |       │ 1:N                                 |
|       ▼ 1:N                                         |       ▼                                     |
|  [campaigns] ──1:1── [campaign_optimizers] (dnt)    |  [agent_audit_events]                        |
|       │ 1:N                                         |    id (PK), thread_id, seller_id           |
|       ▼                                             |    node_name, event_type, tier              |
|  [campaign_metrics]                                 |    payload (JSONB), created_at              |
|    spend, sales, orders, roas, acos                 |                                             |
|                                                     |                                             |
|  [adace_status_logs]                                |                                             |
|    before/after budget & bid mutation audit entries |                                             |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Three-Tier Risk Guardrail Matrix

AdAce implements a strict three-tier defense-in-depth hierarchy. Guardrails are enforced at the **Python application layer**, guaranteeing that LLM recommendations can **never** bypass safety caps.

| Risk Tier | Action Type | Pre-Conditions & Safety Guardrails | Execution Mode | Audit Destination |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1: Bleeder Negation** | Add Negative Exact Keyword | • Zero orders in 7-day attribution window (`units_sold_clicks_7d == 0`)<br/>• Non-converting clicks >= seller threshold (`neg_key_max_no_orders`)<br/>• Target campaign has `dnt == 0` | **Autonomous** | MySQL `adace_status_logs` (`module_id=3`, `action_id=1`) + PostgreSQL `AgentAuditEvent` |
| **Tier 2: Bounded Bid Scale** | Adjust Keyword Bid | • Campaign has `dnt == 0`<br/>• ROAS >= 3.5 and campaign ACOS < target ACOS<br/>• Proposed bid <= `max_bid_cap`<br/>• Single-step bid increase <= 20% (`new_bid <= cur_bid * 1.20`) | **Bounded Autonomous** | MySQL `adace_status_logs` (`module_id=6`, `action_id=2`) + PostgreSQL `AgentAuditEvent` |
| **Tier 3: Budget Scaling** | Scale Campaign Daily Budget | • Campaign spend utilization >= 80% (`spend / budget >= 0.80`)<br/>• Strong efficiency: ROAS >= 3.0<br/>• Target campaign has `dnt == 0`<br/>• Scaled budget <= `max_budget_cap`<br/>• Standard step increase: +30% | **HITL Guardrailed**<br/>• Option 1: Autonomous Pre-approved<br/>• Option 2: True HITL Suspend (`interrupt()`) | MySQL `adace_status_logs` (`module_id=14`, `action_id=2`, `rule='OOB 3xRoAS'`) + PostgreSQL `AgentAuditEvent` |

---

## 4. LangGraph StateGraph & True HITL Interrupt Engine

The platform leverages LangGraph's native `interrupt()` and `Command(resume=...)` to manage long-lived Human-In-The-Loop approvals. When a seller requires human review (`increase_budget_option != 1`), the workflow **genuinely suspends execution** at the `human_approval_gate` node.

### End-to-End Execution Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor Operator as AdAce Operator
    participant API as FastAPI Gateway
    participant Graph as LangGraph Engine
    participant MCP as MCPServer (MCP v2)
    participant MySQL as MySQL AdAce Sandbox
    participant PG as PostgreSQL State DB

    Operator->>API: POST /api/v1/workflows/sellers/1/run
    API->>PG: Insert AgentWorkflowRun (status="running")
    API->>Graph: ainvoke(initial_state, thread_id="wf-101")

    Note over Graph: Node 1: analyze_account
    Graph->>MCP: get_seller_guardrails(seller_id=1)
    MCP->>MySQL: SELECT sellers, seller_communication
    Graph->>MCP: find_bleeding_search_terms(seller_id=1)
    MCP->>MySQL: SELECT search_terms (clicks >= 8, orders = 0)
    Graph->>MCP: find_oob_scaling_candidates(seller_id=1)
    MCP->>MySQL: SELECT campaigns (spend/budget >= 80%, ROAS >= 3)
    Graph->>PG: Insert AgentAuditEvent (event_type="analysis")

    Note over Graph: Node 2: plan_actions
    Graph->>Graph: Dual-mode planner (Gemini cascade ➔ deterministic)
    Graph->>PG: Insert AgentAuditEvent (event_type="plan_created")

    Note over Graph: Node 3: execute_autonomous_actions
    Graph->>MCP: add_negative_keyword(CAMP102, "organic fake", match="NEGATIVE_EXACT")
    MCP->>MySQL: INSERT INTO adace_status_logs (module=3, action=1)
    Graph->>MCP: adjust_keyword_bid(KW102_01, new_bid=1.60)
    MCP->>MySQL: UPDATE keyword_reports, INSERT INTO adace_status_logs (module=6, action=2)
    Graph->>PG: Insert AgentAuditEvent (event_type="auto_executed")

    Note over Graph: Conditional Edge: route_after_autonomous
    alt increase_budget_option == 2 (HITL Required)
        Graph->>Graph: Route to human_approval_gate
        Note over Graph: Node 4: human_approval_gate
        Graph->>PG: Insert AgentAuditEvent (event_type="hitl_interrupted", tier=3)
        Graph->>PG: Update AgentWorkflowRun (status="pending_approval")
        Graph-->>API: interrupt({"thread_id": "wf-101", "pending_actions": [...]})
        API-->>Operator: 201 Created (status="pending_approval", pending_hitl_actions=[CAMP101])
    else increase_budget_option == 1 (Pre-approved)
        Graph->>MCP: scale_campaign_budget(CAMP201, +30%)
        Graph->>Graph: Route to finalize_report
    end

    Note over Operator,API: Out-of-band Review & Inspection
    Operator->>API: GET /api/v1/workflows/wf-101
    API-->>Operator: 200 OK (state + pending actions + audit trail)

    Note over Operator,API: Human Decision
    Operator->>API: POST /api/v1/workflows/wf-101/resume {"approved": true, "reviewer": "Diju Thampi"}
    API->>Graph: ainvoke(Command(resume={"approved": true}), thread_id="wf-101")
    
    Note over Graph: Resumed inside human_approval_gate
    Graph->>MCP: scale_campaign_budget(CAMP101, 650.00, human_approved=True)
    MCP->>MySQL: UPDATE campaigns, campaign_optimizers, INSERT INTO adace_status_logs (module=14, action=2)
    Graph->>PG: Insert AgentAuditEvent (event_type="hitl_resumed", tier=3)
    
    Note over Graph: Node 5: finalize_report
    Graph->>PG: Update AgentWorkflowRun (status="completed")
    Graph->>PG: Insert AgentAuditEvent (event_type="completed")
    Graph-->>API: Finished State
    API-->>Operator: 200 OK (status="completed", budget mutated)
```

---

## 5. Resilient Multi-Tier Gemini AI Planning Cascade

When `AI_PROVIDER=gemini` is configured, the planner implements an automated cascading fallback to ensure maximum operational uptime:

```mermaid
flowchart TD
    START(["Start Planning"]) --> CHECK{"AI_PROVIDER == 'gemini'<br/>& GEMINI_API_KEY set?"}
    
    CHECK -- No --> RULE["_plan_deterministic()<br/>(Rule Engine)"]
    CHECK -- Yes --> TRY_FLASH["Call Gemini 2.5 Flash<br/>(Structured JSON, Temp 0.2)"]
    
    TRY_FLASH -- Success --> VALIDATE["Enforce Deterministic Guardrails<br/>(DNT, Bid Cap, Budget Cap, HITL Option)"]
    TRY_FLASH -- "Exception / Quota / Timeout" --> TRY_LITE["Call Gemini 2.5 Flash-Lite<br/>(Fallback Model)"]
    
    TRY_LITE -- Success --> VALIDATE
    TRY_LITE -- "Exception / Failure" --> RULE
    
    RULE --> VALIDATE
    VALIDATE --> RETURN(["Return Safe Risk-Tiered Plan"])
```

### Executive-Grade Rationale Metrics
All generated actions include quantified business rationale:
- **Tier 1:** Immediate dollar waste eliminated (`$cost`) and projected annualized cost avoidance (`$cost * 52`).
- **Tier 2:** ROAS/ACOS efficiency deltas vs target and projected impression share gain within safe bid caps.
- **Tier 3:** Historical spend utilization percentage, ROAS, and projected incremental conversions before hitting budget caps.

---

## 6. Unified Audit Trail & Multi-Tenant Reconciliation

To achieve enterprise compliance, the system merges:
1. **PostgreSQL Event Stream:** Records agent cognitive transitions (`analysis`, `plan_created`, `auto_executed`, `hitl_interrupted`, `hitl_resumed`, `rejected`, `completed`).
2. **MySQL AdAce Status Logs:** Records the exact before-and-after values of all advertising mutations (`campaign_prv_budget` ➔ `campaign_cur_budget`, `keywd_prev_bid` ➔ `keywd_cur_bid`, `neg_keywd_product`).

The `GET /api/v1/audit/sellers/{seller_id}/trail` endpoint normalizes all timestamps to UTC, strictly scopes queries by `seller_id`, and delivers an integrated, chronologically ordered audit ledger.
