from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.mcp.adace_server import (
    mcp,
    override_mcp_db,
    get_seller_guardrails,
    get_campaign_performance,
    find_bleeding_search_terms,
    find_oob_scaling_candidates,
    add_negative_keyword,
    adjust_keyword_bid,
    scale_campaign_budget,
)
from app.models.adace import (
    Seller,
    SellerCommunicationManagement,
    Campaign,
    CampaignOptimizer,
    CampaignMetric,
    KeywordReport,
    SearchTerm,
)


@pytest.fixture
def seller_navla() -> Seller:
    """Seller 1 fixture: Navla Naturals with HITL approval required."""
    s = Seller(
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
    s.communication = SellerCommunicationManagement(
        id=1,
        seller_id=1,
        day_parting_option=1,
        increase_budget_option=2,  # 2 = HITL Approval Required
    )
    return s


@pytest.fixture
def seller_peps() -> Seller:
    """Seller 2 fixture: Peps Mattress with autonomous pre-approved budget scaling."""
    s = Seller(
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
    s.communication = SellerCommunicationManagement(
        id=2,
        seller_id=2,
        day_parting_option=1,
        increase_budget_option=1,  # 1 = Pre-approved (Autonomous)
    )
    return s


@pytest.fixture
def campaign_oob_navla(seller_navla) -> Campaign:
    """Campaign 101: O3M-SP-AT-MAIN - OOB scaling candidate (utilization 92%, ROAS 4.2)."""
    camp = Campaign(
        id=101,
        seller_id=1,
        campaign_name="O3M-SP-AT-MAIN",
        campaign_str_id="CAMP101",
        campaign_type="sp",
        targeting_type="auto",
        state="enabled",
        budget=Decimal("500.00"),
        status="active",
    )
    camp.optimizer = CampaignOptimizer(
        id=101,
        seller_id=1,
        campaign_id=101,
        campaign_str_id="CAMP101",
        dnt=0,
        daily_budget=Decimal("500.00"),
        budget_rule="aggressive_scale",
        target_acos=Decimal("25.00"),
        neg_term_opt=1,
        neg_key_max_no_orders=8,
    )
    camp.metrics = [
        CampaignMetric(
            id=1002,
            campaign_id=101,
            seller_id=1,
            campaign_str_id="CAMP101",
            campaign_status="enabled",
            campaign_budget=Decimal("500.00"),
            status_date=date(2026, 11, 25),
            impressions=18500,
            clicks=620,
            spend=Decimal("460.00"),  # 460/500 = 92% utilization
            acos=Decimal("23.81"),
            orders=38,
            sales=Decimal("1932.00"),
            roas=Decimal("4.20"),  # ROAS >= 3.0
        )
    ]
    return camp


@pytest.fixture
def campaign_dnt_navla() -> Campaign:
    """Campaign 103: O3M-SP-BRAND-PROTECT - DNT (Do Not Touch) Guardrail = 1."""
    camp = Campaign(
        id=103,
        seller_id=1,
        campaign_name="O3M-SP-BRAND-PROTECT",
        campaign_str_id="CAMP103",
        campaign_type="sp",
        targeting_type="manual",
        state="enabled",
        budget=Decimal("300.00"),
        status="active",
    )
    camp.optimizer = CampaignOptimizer(
        id=103,
        seller_id=1,
        campaign_id=103,
        campaign_str_id="CAMP103",
        dnt=1,  # DO NOT TOUCH
        daily_budget=Decimal("300.00"),
        budget_rule="brand_guard",
        target_acos=Decimal("15.00"),
        neg_term_opt=0,
        neg_key_max_no_orders=10,
    )
    return camp


@pytest.fixture
def keyword_navla() -> KeywordReport:
    """Keyword KW102_01 in CAMP102 (bid = 1.40, dnt = 0)."""
    return KeywordReport(
        id=501,
        seller_id=1,
        campaign_str_id="CAMP102",
        ad_group_id="AG102_1",
        keyword_id="KW102_01",
        keyword_text="natural organic hair oil",
        match_type="exact",
        state="enabled",
        bid=Decimal("1.40"),
        status_date=date(2026, 11, 25),
        impressions=4500,
        clicks=120,
        spend=Decimal("115.00"),
        acos=Decimal("14.38"),
        orders=18,
        sales=Decimal("800.00"),
        roas=Decimal("6.96"),
    )


# =============================================================================
# 1. DNT (DO NOT TOUCH) GUARDRAIL ENFORCEMENT TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_dnt_blocks_negative_keyword(campaign_dnt_navla):
    """Verify Tier 1 action rejects adding negative keyword on a DNT=1 campaign."""
    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = campaign_dnt_navla
    mock_db.execute.return_value = mock_res

    async with override_mcp_db(mock_db):
        result = await add_negative_keyword(
            seller_id=1,
            campaign_str_id="CAMP103",
            keyword_text="unwanted term",
            match_type="NEGATIVE_EXACT",
        )

        assert result["status"] == "blocked"
        assert result["tier"] == 1
        assert "DNT" in result["reason"] or "Do Not Touch" in result["reason"]
        assert mock_db.commit.called is False


@pytest.mark.asyncio
async def test_dnt_blocks_budget_scaling(campaign_dnt_navla):
    """Verify Tier 3 action rejects budget scaling on a DNT=1 campaign even if human approved."""
    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = campaign_dnt_navla
    mock_db.execute.return_value = mock_res

    async with override_mcp_db(mock_db):
        result = await scale_campaign_budget(
            seller_id=1,
            campaign_str_id="CAMP103",
            proposed_budget=400.00,
            human_approved=True,
        )

        assert result["status"] == "blocked"
        assert result["tier"] == 3
        assert "DNT" in result["reason"] or "Do Not Touch" in result["reason"]
        assert mock_db.commit.called is False


@pytest.mark.asyncio
async def test_dnt_blocks_keyword_bid_adjustment(campaign_dnt_navla):
    """Verify Tier 2 action rejects keyword bid changes when parent campaign has DNT=1."""
    kw = KeywordReport(
        id=503,
        seller_id=1,
        campaign_str_id="CAMP103",
        keyword_id="KW103_01",
        keyword_text="brand defense keyword",
        bid=Decimal("0.85"),
        match_type="exact",
        state="enabled",
        status_date=date(2026, 11, 25),
    )

    mock_db = AsyncMock()

    # First execute: fetch keyword; Second execute: fetch parent campaign
    res1 = MagicMock()
    res1.scalar_one_or_none.return_value = kw
    res2 = MagicMock()
    res2.scalar_one_or_none.return_value = campaign_dnt_navla

    mock_db.execute.side_effect = [res1, res2]

    async with override_mcp_db(mock_db):
        result = await adjust_keyword_bid(
            seller_id=1,
            keyword_id="KW103_01",
            new_bid=0.95,
        )

        assert result["status"] == "blocked"
        assert result["tier"] == 2
        assert "DNT" in result["reason"] or "Do Not Touch" in result["reason"]
        assert mock_db.commit.called is False


# =============================================================================
# 2. BID CAPS & BOUNDED SINGLE-STEP LIMIT TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_max_bid_cap_enforcement(keyword_navla, seller_navla):
    """Verify Tier 2 action blocks bids exceeding seller max_bid_cap (25.00 for Seller 1)."""
    camp_normal = Campaign(id=102, seller_id=1, campaign_str_id="CAMP102")
    camp_normal.optimizer = CampaignOptimizer(id=102, campaign_id=102, dnt=0)

    mock_db = AsyncMock()

    res_kw = MagicMock()
    res_kw.scalar_one_or_none.return_value = keyword_navla
    res_camp = MagicMock()
    res_camp.scalar_one_or_none.return_value = camp_normal
    res_seller = MagicMock()
    res_seller.scalar_one_or_none.return_value = seller_navla

    mock_db.execute.side_effect = [res_kw, res_camp, res_seller]

    async with override_mcp_db(mock_db):
        # Propose bid of $28.00 (exceeds seller cap of $25.00)
        result = await adjust_keyword_bid(
            seller_id=1,
            keyword_id="KW102_01",
            new_bid=28.00,
        )

        assert result["status"] == "blocked"
        assert result["tier"] == 2
        assert "max_bid_cap" in result["reason"]
        assert mock_db.commit.called is False


@pytest.mark.asyncio
async def test_bid_single_step_20pct_limit(keyword_navla, seller_navla):
    """Verify Tier 2 blocks bid increases > 20% in a single step (Current: 1.40, Max: 1.68)."""
    camp_normal = Campaign(id=102, seller_id=1, campaign_str_id="CAMP102")
    camp_normal.optimizer = CampaignOptimizer(id=102, campaign_id=102, dnt=0)

    # Sub-test 1: Proposed bid 2.00 (+42.8% increase) -> Blocked
    mock_db1 = AsyncMock()
    res_kw1 = MagicMock()
    res_kw1.scalar_one_or_none.return_value = keyword_navla
    res_camp1 = MagicMock()
    res_camp1.scalar_one_or_none.return_value = camp_normal
    res_seller1 = MagicMock()
    res_seller1.scalar_one_or_none.return_value = seller_navla
    mock_db1.execute.side_effect = [res_kw1, res_camp1, res_seller1]

    async with override_mcp_db(mock_db1):
        blocked_result = await adjust_keyword_bid(
            seller_id=1,
            keyword_id="KW102_01",
            new_bid=2.00,
        )
        assert blocked_result["status"] == "blocked"
        assert "20%" in blocked_result["reason"]
        assert mock_db1.commit.called is False

    # Sub-test 2: Proposed bid 1.60 (+14.3% increase <= 20%) -> Executed
    mock_db2 = AsyncMock()
    res_kw2 = MagicMock()
    res_kw2.scalar_one_or_none.return_value = keyword_navla
    res_camp2 = MagicMock()
    res_camp2.scalar_one_or_none.return_value = camp_normal
    res_seller2 = MagicMock()
    res_seller2.scalar_one_or_none.return_value = seller_navla
    mock_db2.execute.side_effect = [res_kw2, res_camp2, res_seller2]

    async with override_mcp_db(mock_db2):
        success_result = await adjust_keyword_bid(
            seller_id=1,
            keyword_id="KW102_01",
            new_bid=1.60,
        )
        assert success_result["status"] == "executed"
        assert success_result["new_bid"] == 1.60
        assert mock_db2.commit.called is True
        assert mock_db2.add.called is True


# =============================================================================
# 3. TIER 3 HITL GATE & BUDGET SCALING TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_hitl_gate_approval_required_for_seller1(campaign_oob_navla, seller_navla):
    """Verify Tier 3 scaling for Seller 1 (increase_budget_option=2) returns approval_required."""
    mock_db = AsyncMock()

    res_camp = MagicMock()
    res_camp.scalar_one_or_none.return_value = campaign_oob_navla
    res_seller = MagicMock()
    res_seller.scalar_one_or_none.return_value = seller_navla

    mock_db.execute.side_effect = [res_camp, res_seller]

    async with override_mcp_db(mock_db):
        result = await scale_campaign_budget(
            seller_id=1,
            campaign_str_id="CAMP101",
            proposed_budget=650.00,
            human_approved=False,  # Unapproved by human
        )

        assert result["status"] == "approval_required"
        assert result["tier"] == 3
        assert result["requires_hitl_approval"] is True
        assert result["current_budget"] == 500.00
        assert result["proposed_budget"] == 650.00
        assert "human approval" in result["reason"].lower()
        # Database must NOT be mutated
        assert mock_db.commit.called is False


@pytest.mark.asyncio
async def test_hitl_gate_execution_when_human_approved(campaign_oob_navla, seller_navla):
    """Verify Tier 3 scaling mutates DB and creates audit log when human_approved=True."""
    mock_db = AsyncMock()

    res_camp = MagicMock()
    res_camp.scalar_one_or_none.return_value = campaign_oob_navla
    res_seller = MagicMock()
    res_seller.scalar_one_or_none.return_value = seller_navla

    mock_db.execute.side_effect = [res_camp, res_seller]

    async with override_mcp_db(mock_db):
        result = await scale_campaign_budget(
            seller_id=1,
            campaign_str_id="CAMP101",
            proposed_budget=650.00,
            human_approved=True,  # Human approved!
            reason="Approved via HITL Dashboard",
        )

        assert result["status"] == "executed"
        assert result["tier"] == 3
        assert result["new_budget"] == 650.00
        assert result["human_approved"] is True
        assert result["rule"] == "OOB 3xRoAS"
        assert mock_db.commit.called is True
        assert mock_db.add.called is True


@pytest.mark.asyncio
async def test_hitl_autonomous_execution_for_seller2(seller_peps):
    """Verify Tier 3 scaling executes autonomously for Seller 2 (increase_budget_option=1)."""
    camp_peps = Campaign(
        id=201,
        seller_id=2,
        campaign_name="PEPS-SP-ORTHO-MATTRESS",
        campaign_str_id="CAMP201",
        budget=Decimal("1200.00"),
    )
    camp_peps.optimizer = CampaignOptimizer(id=201, campaign_id=201, dnt=0, daily_budget=Decimal("1200.00"))

    mock_db = AsyncMock()
    res_camp = MagicMock()
    res_camp.scalar_one_or_none.return_value = camp_peps
    res_seller = MagicMock()
    res_seller.scalar_one_or_none.return_value = seller_peps

    mock_db.execute.side_effect = [res_camp, res_seller]

    async with override_mcp_db(mock_db):
        result = await scale_campaign_budget(
            seller_id=2,
            campaign_str_id="CAMP201",
            proposed_budget=1560.00,
            human_approved=False,  # Option 1 is pre-approved!
        )

        assert result["status"] == "executed"
        assert result["tier"] == 3
        assert result["new_budget"] == 1560.00
        assert mock_db.commit.called is True


# =============================================================================
# 4. STRICT MULTI-TENANT ISOLATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_cross_tenant_isolation_rejected():
    """Verify Seller 1 cannot query or modify Seller 2's campaigns or keywords."""
    mock_db = AsyncMock()
    res_empty = MagicMock()
    res_empty.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = res_empty

    async with override_mcp_db(mock_db):
        # 1. Attempt to add negative keyword to Seller 2's campaign from Seller 1
        res1 = await add_negative_keyword(
            seller_id=1,
            campaign_str_id="CAMP201",  # belongs to Seller 2
            keyword_text="bad term",
        )
        assert res1["status"] == "rejected"
        assert "not found" in res1["reason"].lower()

        # 2. Attempt to adjust Seller 2's keyword from Seller 1
        res2 = await adjust_keyword_bid(
            seller_id=1,
            keyword_id="KW201_01",  # belongs to Seller 2
            new_bid=3.50,
        )
        assert res2["status"] == "rejected"
        assert "not found" in res2["reason"].lower()

        # 3. Attempt to scale Seller 2's budget from Seller 1
        res3 = await scale_campaign_budget(
            seller_id=1,
            campaign_str_id="CAMP201",
            proposed_budget=1400.00,
        )
        assert res3["status"] == "rejected"
        assert "not found" in res3["reason"].lower()


# =============================================================================
# 5. READ-ONLY ANALYTICS TOOLS TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_get_seller_guardrails(seller_navla):
    """Verify get_seller_guardrails tool returns structured guardrails."""
    mock_db = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = seller_navla
    mock_db.execute.return_value = mock_res

    async with override_mcp_db(mock_db):
        data = await get_seller_guardrails(seller_id=1)
        assert data["status"] == "success"
        assert data["found"] is True
        assert data["seller_name"] == "Navla Naturals"
        assert data["max_bid_cap"] == 25.00
        assert data["max_budget_cap"] == 2000.00
        assert data["requires_hitl_approval"] is True


@pytest.mark.asyncio
async def test_find_bleeding_search_terms(seller_navla):
    """Verify find_bleeding_search_terms finds bleeder keywords above click threshold with 0 orders."""
    camp = Campaign(id=102, seller_id=1, campaign_str_id="CAMP102", campaign_name="O3M-SP-ML-EXACT")
    opt = CampaignOptimizer(id=102, campaign_id=102, dnt=0, neg_key_max_no_orders=8)
    st = SearchTerm(
        id=801,
        seller_id=1,
        campaign_id=102,
        campaign_name="O3M-SP-ML-EXACT",
        keyword="ayurvedic hair regrowth oil",
        match_type="phrase",
        search_term="organic aloe vera gel 500ml fake",
        clicks=14,  # > 8 threshold
        cost=Decimal("42.00"),
        units_sold_clicks_7d=0,  # 0 orders
        sales_7d=Decimal("0.00"),
    )

    mock_db = AsyncMock()
    res_seller = MagicMock()
    res_seller.scalar_one_or_none.return_value = seller_navla
    res_terms = MagicMock()
    res_terms.all.return_value = [(st, camp, opt)]

    mock_db.execute.side_effect = [res_seller, res_terms]

    async with override_mcp_db(mock_db):
        candidates = await find_bleeding_search_terms(seller_id=1)
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["search_term"] == "organic aloe vera gel 500ml fake"
        assert cand["clicks"] == 14
        assert cand["recommendation"] == "ADD_NEGATIVE_EXACT"


@pytest.mark.asyncio
async def test_find_oob_scaling_candidates(seller_navla, campaign_oob_navla):
    """Verify find_oob_scaling_candidates discovers high-spend high-ROAS campaign and calculates +30%."""
    mock_db = AsyncMock()
    res_seller = MagicMock()
    res_seller.scalar_one_or_none.return_value = seller_navla
    res_camps = MagicMock()
    res_camps.scalars.return_value.all.return_value = [campaign_oob_navla]

    mock_db.execute.side_effect = [res_seller, res_camps]

    async with override_mcp_db(mock_db):
        candidates = await find_oob_scaling_candidates(seller_id=1)
        assert len(candidates) == 1
        cand = candidates[0]
        assert cand["campaign_str_id"] == "CAMP101"
        assert cand["current_budget"] == 500.00
        assert cand["spend"] == 460.00
        assert cand["proposed_budget"] == 650.00  # 500 * 1.30
        assert cand["requires_hitl_approval"] is True


# =============================================================================
# 6. REST API ENDPOINTS FOR MCP TOOLS
# =============================================================================


@pytest.mark.asyncio
async def test_api_list_mcp_tools():
    """Verify GET /api/v1/mcp/tools returns registered tools and tiers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/mcp/tools")
        assert response.status_code == 200
        data = response.json()
        assert data["server_name"] == "AdAce-AdOps-Server"
        assert data["total_tools"] == 7
        tool_names = [t["name"] for t in data["tools"]]
        assert "get_seller_guardrails" in tool_names
        assert "add_negative_keyword" in tool_names
        assert "adjust_keyword_bid" in tool_names
        assert "scale_campaign_budget" in tool_names


@pytest.mark.asyncio
async def test_mcp_server_instance():
    """Verify MCPServer instance is initialized with the correct server name."""
    assert mcp.name == "AdAce-AdOps-Server"

