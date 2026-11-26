from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.mysql import get_adace_db
from app.db.postgres import get_agent_db
from app.main import app
from app.models.adace import AdAceStatusLog
from app.models.agent import AgentAuditEvent, AgentWorkflowRun


# =============================================================================
# FIXTURES: MOCK AUDIT DATA
# =============================================================================


@pytest.fixture
def mock_audit_events_seller_1():
    """Mock PostgreSQL AgentAuditEvent records for Seller 1."""
    return [
        AgentAuditEvent(
            id=1,
            thread_id="thread-audit-101",
            seller_id=1,
            node_name="analyze_account",
            event_type="analysis",
            tier=None,
            payload={"guardrails": {"max_bid_cap": 25.0}, "campaigns_count": 3},
            created_at=datetime(2026, 11, 26, 10, 0, 0, tzinfo=timezone.utc),
        ),
        AgentAuditEvent(
            id=2,
            thread_id="thread-audit-101",
            seller_id=1,
            node_name="execute_autonomous_actions",
            event_type="auto_executed",
            tier=1,
            payload={"campaign_str_id": "CAMP102", "rule": "BLEEDER_NEGATION", "executed_count": 1},
            created_at=datetime(2026, 11, 26, 10, 1, 0, tzinfo=timezone.utc),
        ),
        AgentAuditEvent(
            id=3,
            thread_id="thread-audit-101",
            seller_id=1,
            node_name="human_approval_gate",
            event_type="hitl_interrupted",
            tier=3,
            payload={
                "pending_actions": [
                    {"campaign_str_id": "CAMP101", "proposed_budget": 650.0, "current_budget": 500.0}
                ]
            },
            created_at=datetime(2026, 11, 26, 10, 2, 0, tzinfo=timezone.utc),
        ),
        AgentAuditEvent(
            id=4,
            thread_id="thread-audit-101",
            seller_id=1,
            node_name="human_approval_gate",
            event_type="hitl_resumed",
            tier=3,
            payload={"approved": True, "reviewer": "Diju Thampi", "notes": "Approved Q4 scaling"},
            created_at=datetime(2026, 11, 26, 10, 5, 0, tzinfo=timezone.utc),
        ),
    ]


@pytest.fixture
def mock_status_logs_seller_1():
    """Mock MySQL AdAceStatusLog records for Seller 1."""
    return [
        AdAceStatusLog(
            id=201,
            run_date=datetime(2026, 11, 26, 10, 1, 30, tzinfo=timezone.utc),
            seller_id=1,
            campaign_str_id="CAMP102",
            module_id=3,
            action_id=1,
            rule="NEGATIVE_KEYWORD_BLEEDER",
            status_text="Added negative keyword 'organic aloe vera gel fake' in CAMP102",
            neg_keywd_product="organic aloe vera gel fake",
            cost=Decimal("42.00"),
            clicks=14,
            orders=0,
        ),
        AdAceStatusLog(
            id=202,
            run_date=datetime(2026, 11, 26, 10, 5, 30, tzinfo=timezone.utc),
            seller_id=1,
            campaign_str_id="CAMP101",
            module_id=14,
            action_id=2,
            rule="OOB 3xRoAS",
            status_text="Scaled daily budget from $500.00 to $650.00 (+30%)",
            campaign_prv_budget=Decimal("500.00"),
            campaign_cur_budget=Decimal("650.00"),
        ),
    ]


@pytest.fixture
def mock_workflow_runs_seller_1():
    """Mock PostgreSQL AgentWorkflowRun records for Seller 1."""
    return [
        AgentWorkflowRun(
            thread_id="wf-run-001",
            seller_id=1,
            status="completed",
            objective="Maximize Q4 profit with multi-tier guardrails",
            proposed_plan={"total_actions": 3},
            pending_hitl_actions=[],
            execution_summary={"total_executed_actions": 3, "status": "completed"},
            approved_by="Diju Thampi",
            created_at=datetime(2026, 11, 26, 9, 30, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 11, 26, 9, 35, 0, tzinfo=timezone.utc),
        ),
        AgentWorkflowRun(
            thread_id="wf-run-002",
            seller_id=1,
            status="pending_approval",
            objective="Mid-day OOB Budget Optimization",
            proposed_plan={"total_actions": 2},
            pending_hitl_actions=[{"campaign_str_id": "CAMP101", "proposed_budget": 650.0}],
            execution_summary=None,
            approved_by=None,
            created_at=datetime(2026, 11, 26, 11, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 11, 26, 11, 1, 0, tzinfo=timezone.utc),
        ),
    ]


# =============================================================================
# 1. TEST UNIFIED AUDIT TRAIL MERGING & SORTING
# =============================================================================


@pytest.mark.asyncio
async def test_get_unified_audit_trail_merging(
    mock_audit_events_seller_1,
    mock_status_logs_seller_1,
):
    """Verify GET /api/v1/audit/sellers/{seller_id}/trail combines PG events and MySQL logs chronologically."""
    mock_pg_db = AsyncMock()
    mock_pg_res = MagicMock()
    mock_pg_res.scalars.return_value.all.return_value = mock_audit_events_seller_1
    mock_pg_db.execute = AsyncMock(return_value=mock_pg_res)

    mock_mysql_db = AsyncMock()
    mock_mysql_res = MagicMock()
    mock_mysql_res.scalars.return_value.all.return_value = mock_status_logs_seller_1
    mock_mysql_db.execute = AsyncMock(return_value=mock_mysql_res)

    app.dependency_overrides[get_agent_db] = lambda: mock_pg_db
    app.dependency_overrides[get_adace_db] = lambda: mock_mysql_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/audit/sellers/1/trail")
            assert res.status_code == 200
            data = res.json()

            # Verify aggregation counts
            assert data["seller_id"] == 1
            assert data["postgres_events_count"] == 4
            assert data["mysql_logs_count"] == 2
            assert data["total_events"] == 6

            events = data["events"]
            assert len(events) == 6

            # Verify sources are preserved
            sources = {e["source"] for e in events}
            assert sources == {"postgres_agent_audit", "mysql_status_log"}

            # Verify chronological descending ordering
            timestamps = [e["timestamp"] for e in events]
            assert timestamps == sorted(timestamps, reverse=True)

            # Verify the most recent event is the MySQL budget scaling at 10:05:30
            latest = events[0]
            assert latest["source"] == "mysql_status_log"
            assert latest["campaign_str_id"] == "CAMP101"
            assert latest["action"] == "CAMPAIGN_BUDGET_MUTATION"
            assert latest["prev_value"] == 500.00
            assert latest["cur_value"] == 650.00

            # Verify Tier 1 bleeder negation log details
            bleeder_event = next(e for e in events if e.get("neg_keywd_product") or (e.get("details") and "neg_keywd_product" in (e.get("details") or {})))
            assert bleeder_event["campaign_str_id"] == "CAMP102"
            assert bleeder_event["details"]["clicks"] == 14
            assert bleeder_event["details"]["cost"] == 42.00
    finally:
        app.dependency_overrides.clear()


# =============================================================================
# 2. TEST WORKFLOW EXECUTION HISTORY ENDPOINT
# =============================================================================


@pytest.mark.asyncio
async def test_get_seller_workflow_history(mock_workflow_runs_seller_1):
    """Verify GET /api/v1/audit/sellers/{seller_id}/workflows returns historical execution summaries."""
    mock_pg_db = AsyncMock()
    mock_pg_res = MagicMock()
    mock_pg_res.scalars.return_value.all.return_value = mock_workflow_runs_seller_1
    mock_pg_db.execute = AsyncMock(return_value=mock_pg_res)

    app.dependency_overrides[get_agent_db] = lambda: mock_pg_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/v1/audit/sellers/1/workflows")
            assert res.status_code == 200
            data = res.json()

            assert data["seller_id"] == 1
            assert data["total_workflows"] == 2
            workflows = data["workflows"]

            # Workflow 1 (Completed)
            wf1 = next(w for w in workflows if w["thread_id"] == "wf-run-001")
            assert wf1["status"] == "completed"
            assert wf1["approved_by"] == "Diju Thampi"
            assert wf1["pending_hitl_count"] == 0
            assert wf1["auto_executed_count"] == 3

            # Workflow 2 (Pending Approval)
            wf2 = next(w for w in workflows if w["thread_id"] == "wf-run-002")
            assert wf2["status"] == "pending_approval"
            assert wf2["approved_by"] is None
            assert wf2["pending_hitl_count"] == 1
    finally:
        app.dependency_overrides.clear()


# =============================================================================
# 3. TEST MULTI-TENANT ISOLATION ON AUDIT ENDPOINTS
# =============================================================================


@pytest.mark.asyncio
async def test_audit_multi_tenant_isolation(
    mock_audit_events_seller_1,
    mock_status_logs_seller_1,
    mock_workflow_runs_seller_1,
):
    """Verify audit endpoints strictly query for the requested seller_id and do not leak cross-tenant records."""
    recorded_pg_stmts = []
    recorded_mysql_stmts = []

    async def dynamic_pg_execute(stmt, *args, **kwargs):
        recorded_pg_stmts.append(str(stmt).lower())
        res = MagicMock()
        compiled = stmt.compile()
        params = getattr(compiled, "params", {})
        # If seller_id is 2, return empty; if 1, return Seller 1 data
        if 2 in params.values() or "seller_id = 2" in str(stmt).lower():
            res.scalars.return_value.all.return_value = []
        else:
            res.scalars.return_value.all.return_value = mock_audit_events_seller_1
        return res

    async def dynamic_mysql_execute(stmt, *args, **kwargs):
        recorded_mysql_stmts.append(str(stmt).lower())
        res = MagicMock()
        compiled = stmt.compile()
        params = getattr(compiled, "params", {})
        if 2 in params.values() or "seller_id = 2" in str(stmt).lower():
            res.scalars.return_value.all.return_value = []
        else:
            res.scalars.return_value.all.return_value = mock_status_logs_seller_1
        return res

    mock_pg = AsyncMock()
    mock_pg.execute = AsyncMock(side_effect=dynamic_pg_execute)
    mock_mysql = AsyncMock()
    mock_mysql.execute = AsyncMock(side_effect=dynamic_mysql_execute)

    app.dependency_overrides[get_agent_db] = lambda: mock_pg
    app.dependency_overrides[get_adace_db] = lambda: mock_mysql

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Query for Seller 2
            res = await client.get("/api/v1/audit/sellers/2/trail")
            assert res.status_code == 200
            data = res.json()
            assert data["seller_id"] == 2
            assert data["total_events"] == 0
            assert data["events"] == []

            # Verify that query filtered on seller_id
            assert any("seller_id" in s for s in recorded_pg_stmts)
            assert any("seller_id" in s for s in recorded_mysql_stmts)
    finally:
        app.dependency_overrides.clear()


# =============================================================================
# 4. TEST EMPTY STATE FOR FRESH SELLER
# =============================================================================


@pytest.mark.asyncio
async def test_audit_trail_empty_state():
    """Verify empty response when seller has no audit events or status logs."""
    mock_pg = AsyncMock()
    mock_pg_res = MagicMock()
    mock_pg_res.scalars.return_value.all.return_value = []
    mock_pg.execute = AsyncMock(return_value=mock_pg_res)

    mock_mysql = AsyncMock()
    mock_mysql_res = MagicMock()
    mock_mysql_res.scalars.return_value.all.return_value = []
    mock_mysql.execute = AsyncMock(return_value=mock_mysql_res)

    app.dependency_overrides[get_agent_db] = lambda: mock_pg
    app.dependency_overrides[get_adace_db] = lambda: mock_mysql

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            trail_res = await client.get("/api/v1/audit/sellers/999/trail")
            assert trail_res.status_code == 200
            trail_data = trail_res.json()
            assert trail_data["total_events"] == 0
            assert trail_data["events"] == []

            wf_res = await client.get("/api/v1/audit/sellers/999/workflows")
            assert wf_res.status_code == 200
            wf_data = wf_res.json()
            assert wf_data["total_workflows"] == 0
            assert wf_data["workflows"] == []
    finally:
        app.dependency_overrides.clear()
