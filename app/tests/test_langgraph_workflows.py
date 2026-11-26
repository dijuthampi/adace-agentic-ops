from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.adops_graph import (
    run_adops_workflow,
    resume_adops_workflow,
    get_workflow_state,
)
from app.db.postgres import get_agent_db
from app.main import app
from app.mcp.adace_server import override_mcp_db
from app.models.adace import (
    Campaign,
    CampaignMetric,
    CampaignOptimizer,
    KeywordReport,
    SearchTerm,
    Seller,
    SellerCommunicationManagement,
)
from app.models.agent import AgentAuditEvent, AgentWorkflowRun


# =============================================================================
# FIXTURES: REALISTIC MULTI-TENANT TEST DATA
# =============================================================================


@pytest.fixture
def mock_seller_1_data():
    """Seller 1 (Navla Naturals): increase_budget_option = 2 (HITL Required)."""
    seller = Seller(
        id=1,
        seller_name="Navla Naturals",
        seller_type="seller",
        account_id="A3NAVLANATURALS",
        profile_id="PROF_NAVLA_001",
        max_bid_cap=Decimal("25.00"),
        max_budget_cap=Decimal("2000.00"),
        neg_key_max_no_orders=8,
        activated=True,
        status="active",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    seller.communication = SellerCommunicationManagement(
        id=1,
        seller_id=1,
        day_parting_option=1,
        increase_budget_option=2,  # 2 = HITL Required!
    )

    # Campaign 101: OOB Scaling Candidate (Spend 460 / Budget 500 = 92% >= 80%, ROAS 4.2 >= 3.0)
    c101 = Campaign(
        id=101,
        seller_id=1,
        campaign_name="O3M-SP-AT-MAIN",
        campaign_str_id="CAMP101",
        budget=Decimal("500.00"),
        state="enabled",
    )
    c101.optimizer = CampaignOptimizer(id=101, campaign_id=101, dnt=0, daily_budget=Decimal("500.00"))
    c101.metrics = [
        CampaignMetric(
            id=1001,
            campaign_id=101,
            seller_id=1,
            campaign_str_id="CAMP101",
            campaign_budget=Decimal("500.00"),
            status_date=date(2026, 11, 25),
            impressions=18500,
            clicks=620,
            spend=Decimal("460.00"),
            orders=38,
            sales=Decimal("1932.00"),
            roas=Decimal("4.20"),
            acos=Decimal("23.81"),
        )
    ]

    # Campaign 102: Exact Keyword Campaign
    c102 = Campaign(
        id=102,
        seller_id=1,
        campaign_name="O3M-SP-ML-EXACT",
        campaign_str_id="CAMP102",
        budget=Decimal("400.00"),
        state="enabled",
    )
    c102.optimizer = CampaignOptimizer(
        id=102,
        campaign_id=102,
        dnt=0,
        daily_budget=Decimal("400.00"),
        target_acos=Decimal("25.00"),
        neg_key_max_no_orders=8,
    )
    c102.metrics = [
        CampaignMetric(
            id=1002,
            campaign_id=102,
            seller_id=1,
            campaign_str_id="CAMP102",
            campaign_budget=Decimal("400.00"),
            status_date=date(2026, 11, 25),
            impressions=12000,
            clicks=310,
            spend=Decimal("280.00"),
            orders=24,
            sales=Decimal("1300.00"),
            roas=Decimal("4.64"),
            acos=Decimal("21.54"),
        )
    ]

    # Campaign 103: Brand defense (DNT = 1)
    c103 = Campaign(
        id=103,
        seller_id=1,
        campaign_name="O3M-SP-BRAND-PROTECT",
        campaign_str_id="CAMP103",
        budget=Decimal("300.00"),
        state="enabled",
    )
    c103.optimizer = CampaignOptimizer(id=103, campaign_id=103, dnt=1, daily_budget=Decimal("300.00"))

    # Winning keyword in CAMP102
    kw102 = KeywordReport(
        id=501,
        seller_id=1,
        campaign_str_id="CAMP102",
        keyword_id="KW102_01",
        keyword_text="natural organic hair oil",
        bid=Decimal("1.40"),
        match_type="exact",
        state="enabled",
        status_date=date(2026, 11, 25),
    )

    # Bleeder search term in CAMP102 (14 clicks > 8 threshold, 0 orders)
    st_bleeder = SearchTerm(
        id=801,
        seller_id=1,
        campaign_id=102,
        campaign_name="O3M-SP-ML-EXACT",
        keyword="ayurvedic hair regrowth oil",
        match_type="phrase",
        search_term="organic aloe vera gel 500ml fake",
        clicks=14,
        cost=Decimal("42.00"),
        units_sold_clicks_7d=0,
        sales_7d=Decimal("0.00"),
    )

    return {
        "seller": seller,
        "campaigns": [c101, c102, c103],
        "camp101": c101,
        "camp102": c102,
        "camp103": c103,
        "keyword": kw102,
        "search_terms": [(st_bleeder, c102, c102.optimizer)],
    }


@pytest.fixture
def mock_seller_2_data():
    """Seller 2 (Peps Mattress): increase_budget_option = 1 (Pre-approved / Autonomous)."""
    seller = Seller(
        id=2,
        seller_name="Peps Mattress",
        seller_type="seller",
        account_id="A2PEPSMATTRESS",
        profile_id="PROF_PEPS_002",
        max_bid_cap=Decimal("50.00"),
        max_budget_cap=Decimal("5000.00"),
        neg_key_max_no_orders=10,
        activated=True,
        status="active",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    seller.communication = SellerCommunicationManagement(
        id=2,
        seller_id=2,
        day_parting_option=1,
        increase_budget_option=1,  # 1 = Pre-approved (Autonomous)!
    )

    c201 = Campaign(
        id=201,
        seller_id=2,
        campaign_name="PEPS-SP-ORTHO-MATTRESS",
        campaign_str_id="CAMP201",
        budget=Decimal("1200.00"),
        state="enabled",
    )
    c201.optimizer = CampaignOptimizer(id=201, campaign_id=201, dnt=0, daily_budget=Decimal("1200.00"))
    c201.metrics = [
        CampaignMetric(
            id=2001,
            campaign_id=201,
            seller_id=2,
            campaign_str_id="CAMP201",
            campaign_budget=Decimal("1200.00"),
            status_date=date(2026, 11, 25),
            impressions=25000,
            clicks=400,
            spend=Decimal("1000.00"),  # 1000/1200 = 83.3% >= 80%
            orders=12,
            sales=Decimal("4500.00"),
            roas=Decimal("4.50"),  # ROAS >= 3.0
            acos=Decimal("22.22"),
        )
    ]

    return {
        "seller": seller,
        "campaigns": [c201],
        "camp201": c201,
        "keyword": None,
        "search_terms": [],
    }


@pytest.fixture
def smart_mock_mysql_db(mock_seller_1_data, mock_seller_2_data):
    """Dynamic mock MySQL session returning accurate data for all MCP queries."""
    mock_db = AsyncMock()

    async def dynamic_execute(stmt, *args, **kwargs):
        stmt_str = str(stmt).lower()
        res = MagicMock()

        # Check tenant context
        is_seller_2 = False
        try:
            compiled = stmt.compile()
            params = getattr(compiled, "params", {})
            if 2 in params.values():
                is_seller_2 = True
            elif 1 in params.values():
                is_seller_2 = False
        except Exception:
            pass

        if not is_seller_2:
            if "seller_id = 2" in stmt_str or "id = 2" in stmt_str or "camp201" in stmt_str or "peps" in stmt_str:
                is_seller_2 = True

        if "search_terms" in stmt_str:
            res.all.return_value = mock_seller_1_data["search_terms"] if not is_seller_2 else []
            res.scalars.return_value.all.return_value = []
            res.scalar_one_or_none.return_value = None
        elif "keyword_reports" in stmt_str:
            kw = mock_seller_1_data["keyword"] if not is_seller_2 else None
            res.scalar_one_or_none.return_value = kw
            res.scalars.return_value.all.return_value = [kw] if kw else []
            res.all.return_value = [kw] if kw else []
        elif "campaigns" in stmt_str:
            camps = mock_seller_2_data["campaigns"] if is_seller_2 else mock_seller_1_data["campaigns"]
            if "camp101" in stmt_str:
                res.scalar_one_or_none.return_value = mock_seller_1_data["camp101"]
            elif "camp102" in stmt_str:
                res.scalar_one_or_none.return_value = mock_seller_1_data["camp102"]
            elif "camp103" in stmt_str:
                res.scalar_one_or_none.return_value = mock_seller_1_data["camp103"]
            elif "camp201" in stmt_str:
                res.scalar_one_or_none.return_value = mock_seller_2_data["camp201"]
            else:
                res.scalar_one_or_none.return_value = camps[0] if camps else None
            res.scalars.return_value.all.return_value = camps
            res.all.return_value = [(c, c.optimizer) for c in camps]
        elif "sellers" in stmt_str:
            s = mock_seller_2_data["seller"] if is_seller_2 else mock_seller_1_data["seller"]
            res.scalar_one_or_none.return_value = s
            res.scalars.return_value.all.return_value = [s]
            res.all.return_value = [s]
        else:
            res.scalar_one_or_none.return_value = None
            res.scalars.return_value.all.return_value = []
            res.all.return_value = []

        return res

    mock_db.execute = AsyncMock(side_effect=dynamic_execute)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


# =============================================================================
# 1. TEST SELLER 1 HITL SUSPENSION & APPROVAL RESUME
# =============================================================================


@pytest.mark.asyncio
async def test_seller1_hitl_pause_and_approval_resume(smart_mock_mysql_db, mock_seller_1_data):
    """Verify Seller 1 (increase_budget_option=2) pauses at 'pending_approval' and executes Tier 3 upon resume."""
    async with override_mcp_db(smart_mock_mysql_db):
        thread_id = "test-thread-navla-001"

        # 1. Run workflow: Should execute Tier 1 & 2, then pause at Tier 3 HITL gate
        run_res = await run_adops_workflow(
            thread_id=thread_id,
            seller_id=1,
            objective="Maximize Q4 profit with multi-tier guardrails",
        )

        assert run_res["seller_id"] == 1
        assert run_res["status"] == "pending_approval"
        assert len(run_res["pending_hitl_actions"]) == 1

        # Verify Tier 3 candidate is CAMP101
        pending_t3 = run_res["pending_hitl_actions"][0]
        assert pending_t3["campaign_str_id"] == "CAMP101"
        assert pending_t3["current_budget"] == 500.00
        assert pending_t3["proposed_budget"] == 650.00  # +30%
        assert pending_t3["requires_hitl_approval"] is True

        # Verify autonomous actions (Tier 1 & Tier 2) were already executed
        executed = run_res["auto_executed_actions"]
        assert len(executed) >= 1
        assert any(a.get("action") == "NEGATIVE_KEYWORD_ADDED" for a in executed)

        # Budget of CAMP101 must NOT be modified yet
        camp101 = mock_seller_1_data["camp101"]
        assert float(camp101.budget) == 500.00

        # 2. Resume workflow with human approval
        resume_res = await resume_adops_workflow(
            thread_id=thread_id,
            approved=True,
            reviewer="Diju Thampi",
            notes="Approved Q4 budget increase to capture peak demand",
        )

        assert resume_res["status"] == "completed"
        assert resume_res["hitl_decision"]["approved"] is True
        assert resume_res["hitl_decision"]["reviewer"] == "Diju Thampi"

        # Budget must now be updated to proposed amount ($650.00)
        assert float(camp101.budget) == 650.00
        assert smart_mock_mysql_db.commit.called is True


# =============================================================================
# 2. TEST HITL REJECTION FLOW
# =============================================================================


@pytest.mark.asyncio
async def test_seller1_hitl_rejection_flow(smart_mock_mysql_db, mock_seller_1_data):
    """Verify resuming with approved=False marks workflow rejected and leaves budget unchanged."""
    async with override_mcp_db(smart_mock_mysql_db):
        thread_id = "test-thread-navla-reject-002"

        # 1. Run workflow -> Pauses at pending_approval
        run_res = await run_adops_workflow(
            thread_id=thread_id,
            seller_id=1,
            objective="Test rejection flow",
        )
        assert run_res["status"] == "pending_approval"

        camp101 = mock_seller_1_data["camp101"]
        original_budget = float(camp101.budget)

        # 2. Resume with approved=False (human rejection)
        resume_res = await resume_adops_workflow(
            thread_id=thread_id,
            approved=False,
            reviewer="Risk Manager",
            notes="Rejected: Inventory levels insufficient to support budget scaling",
        )

        assert resume_res["status"] == "rejected"
        assert resume_res["hitl_decision"]["approved"] is False

        # Budget must remain strictly untouched
        assert float(camp101.budget) == original_budget


# =============================================================================
# 3. TEST SELLER 2 AUTONOMOUS WORKFLOW (NO PAUSE)
# =============================================================================


@pytest.mark.asyncio
async def test_seller2_autonomous_workflow(smart_mock_mysql_db, mock_seller_2_data):
    """Verify Seller 2 (increase_budget_option=1, Pre-approved) completes autonomously without pausing."""
    async with override_mcp_db(smart_mock_mysql_db):
        thread_id = "test-thread-peps-auto-003"

        run_res = await run_adops_workflow(
            thread_id=thread_id,
            seller_id=2,
            objective="Autonomous budget expansion for Peps Mattress",
        )

        # Autonomous completion: No pause, status is completed immediately
        assert run_res["seller_id"] == 2
        assert run_res["status"] == "completed"
        assert len(run_res["pending_hitl_actions"]) == 0

        # Tier 3 scaling was executed autonomously
        camp201 = mock_seller_2_data["camp201"]
        assert float(camp201.budget) == 1560.00  # 1200 * 1.30


# =============================================================================
# 4. TEST API WORKFLOW ENDPOINTS (RUN, GET, RESUME)
# =============================================================================


@pytest.mark.asyncio
async def test_api_workflow_lifecycle(smart_mock_mysql_db):
    """Test full workflow HTTP API lifecycle via /api/v1/workflows endpoints."""
    mock_agent_db = AsyncMock()

    # Create mock workflow run in postgres
    mock_run = AgentWorkflowRun(
        thread_id="api-thread-test-101",
        seller_id=1,
        status="pending_approval",
        objective="API Lifecycle Test",
        proposed_plan={"tier3_actions": [{"campaign_str_id": "CAMP101", "proposed_budget": 650.0}]},
        pending_hitl_actions=[{"campaign_str_id": "CAMP101", "proposed_budget": 650.0}],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    mock_run.audit_events = [
        AgentAuditEvent(
            id=1,
            thread_id="api-thread-test-101",
            seller_id=1,
            node_name="analyze_account",
            event_type="analysis",
            created_at=datetime.now(),
        ),
        AgentAuditEvent(
            id=2,
            thread_id="api-thread-test-101",
            seller_id=1,
            node_name="human_approval_gate",
            event_type="hitl_interrupted",
            tier=3,
            created_at=datetime.now(),
        ),
    ]

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = mock_run
    mock_agent_db.execute.return_value = mock_res

    app.dependency_overrides[get_agent_db] = lambda: mock_agent_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with override_mcp_db(smart_mock_mysql_db):
                # 1. Start a new workflow run for Seller 1
                start_res = await client.post(
                    "/api/v1/workflows/sellers/1/run",
                    json={"objective": "API Integration Test"},
                )
                assert start_res.status_code == 201
                start_data = start_res.json()
                assert start_data["status"] == "pending_approval"
                created_thread_id = start_data["thread_id"]

                # 2. Inspect workflow via GET /workflows/{thread_id}
                get_res = await client.get(f"/api/v1/workflows/{mock_run.thread_id}")
                assert get_res.status_code == 200
                get_data = get_res.json()
                assert get_data["workflow"]["status"] == "pending_approval"
                assert len(get_data["audit_trail"]) == 2

                # 3. Multi-tenant violation: Seller 2 cannot resume Seller 1's workflow
                forbidden_res = await client.post(
                    f"/api/v1/workflows/{created_thread_id}/resume",
                    json={"seller_id": 2, "approved": True},  # Wrong seller_id!
                )
                assert forbidden_res.status_code == 403
                assert "multi-tenant violation" in forbidden_res.json()["detail"].lower()

                # 4. Valid Resume by Seller 1
                resume_res = await client.post(
                    f"/api/v1/workflows/{created_thread_id}/resume",
                    json={
                        "seller_id": 1,
                        "approved": True,
                        "reviewer": "Diju Thampi",
                        "notes": "Approved via Web Dashboard",
                    },
                )
                assert resume_res.status_code == 200
                assert resume_res.json()["status"] == "completed"
    finally:
        app.dependency_overrides.clear()
