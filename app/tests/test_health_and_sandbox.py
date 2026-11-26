from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.mysql import get_adace_db
from app.models.adace import (
    Seller,
    SellerCommunicationManagement,
    Campaign,
    CampaignOptimizer,
    CampaignMetric,
)


@pytest.fixture
def mock_navla_naturals_seller() -> Seller:
    """Fixture providing Seller 1 (Navla Naturals) with campaigns and guardrails."""
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

    # Communication management: option 2 = HITL Required
    seller.communication = SellerCommunicationManagement(
        id=1,
        seller_id=1,
        day_parting_option=1,
        increase_budget_option=2,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # Campaign 1: O3M-SP-AT-MAIN (Candidate for Tier 3 OOB +30% Scaling)
    c1 = Campaign(
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
    c1.optimizer = CampaignOptimizer(
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
    c1.metrics = [
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
            spend=Decimal("460.00"),
            acos=Decimal("23.81"),
            orders=38,
            sales=Decimal("1932.00"),
            roas=Decimal("4.20"),
        )
    ]

    # Campaign 2: O3M-SP-ML-EXACT (Tier 1 Neg Term Opt & Tier 2 Bid Scale)
    c2 = Campaign(
        id=102,
        seller_id=1,
        campaign_name="O3M-SP-ML-EXACT",
        campaign_str_id="CAMP102",
        campaign_type="sp",
        targeting_type="manual",
        state="enabled",
        budget=Decimal("400.00"),
        status="active",
    )
    c2.optimizer = CampaignOptimizer(
        id=102,
        seller_id=1,
        campaign_id=102,
        campaign_str_id="CAMP102",
        dnt=0,
        daily_budget=Decimal("400.00"),
        budget_rule="target_acos_opt",
        target_acos=Decimal("25.00"),
        neg_term_opt=1,
        neg_key_max_no_orders=8,
    )
    c2.metrics = [
        CampaignMetric(
            id=1004,
            campaign_id=102,
            seller_id=1,
            campaign_str_id="CAMP102",
            campaign_status="enabled",
            campaign_budget=Decimal("400.00"),
            status_date=date(2026, 11, 25),
            impressions=12000,
            clicks=310,
            spend=Decimal("280.00"),
            acos=Decimal("21.54"),
            orders=24,
            sales=Decimal("1300.00"),
            roas=Decimal("4.64"),
        )
    ]

    # Campaign 3: O3M-SP-BRAND-PROTECT (DNT Guardrail = 1)
    c3 = Campaign(
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
    c3.optimizer = CampaignOptimizer(
        id=103,
        seller_id=1,
        campaign_id=103,
        campaign_str_id="CAMP103",
        dnt=1,
        daily_budget=Decimal("300.00"),
        budget_rule="brand_guard",
        target_acos=Decimal("15.00"),
        neg_term_opt=0,
        neg_key_max_no_orders=10,
    )
    c3.metrics = [
        CampaignMetric(
            id=1005,
            campaign_id=103,
            seller_id=1,
            campaign_str_id="CAMP103",
            campaign_status="enabled",
            campaign_budget=Decimal("300.00"),
            status_date=date(2026, 11, 25),
            impressions=8000,
            clicks=150,
            spend=Decimal("120.00"),
            acos=Decimal("10.00"),
            orders=22,
            sales=Decimal("1200.00"),
            roas=Decimal("10.00"),
        )
    ]

    seller.campaigns = [c1, c2, c3]
    return seller


@pytest.fixture
def mock_peps_mattress_seller() -> Seller:
    """Fixture providing Seller 2 (Peps Mattress) for tenant isolation testing."""
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

    # Communication: Option 1 = Pre-approved (Autonomous execution)
    seller.communication = SellerCommunicationManagement(
        id=2,
        seller_id=2,
        day_parting_option=1,
        increase_budget_option=1,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    c1 = Campaign(
        id=201,
        seller_id=2,
        campaign_name="PEPS-SP-ORTHO-MATTRESS",
        campaign_str_id="CAMP201",
        campaign_type="sp",
        targeting_type="manual",
        state="enabled",
        budget=Decimal("1200.00"),
        status="active",
    )
    c1.optimizer = CampaignOptimizer(
        id=201,
        seller_id=2,
        campaign_id=201,
        campaign_str_id="CAMP201",
        dnt=0,
        daily_budget=Decimal("1200.00"),
        budget_rule="standard_scale",
        target_acos=Decimal("20.00"),
        neg_term_opt=1,
        neg_key_max_no_orders=10,
    )
    c1.metrics = [
        CampaignMetric(
            id=2001,
            campaign_id=201,
            seller_id=2,
            campaign_str_id="CAMP201",
            campaign_status="enabled",
            campaign_budget=Decimal("1200.00"),
            status_date=date(2026, 11, 25),
            impressions=25000,
            clicks=400,
            spend=Decimal("750.00"),
            acos=Decimal("18.75"),
            orders=10,
            sales=Decimal("4000.00"),
            roas=Decimal("5.33"),
        )
    ]
    seller.campaigns = [c1]
    return seller


@pytest.mark.asyncio
async def test_root_endpoint():
    """Verify root information endpoint returns operational status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "AdAce Agentic Ops"
        assert data["status"] == "operational"


@pytest.mark.asyncio
async def test_health_endpoint_healthy():
    """Verify /api/v1/health returns healthy when both MySQL and Postgres respond."""
    with patch("app.api.v1.endpoints.health.check_mysql_health") as mock_mysql, \
         patch("app.api.v1.endpoints.health.check_pg_health") as mock_pg:

        mock_mysql.return_value = {
            "connected": True,
            "message": "AdAce MySQL connection healthy",
            "latency_ms": 1.25,
        }
        mock_pg.return_value = {
            "connected": True,
            "message": "Agent PostgreSQL connection healthy",
            "latency_ms": 0.85,
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["mysql"]["connected"] is True
            assert data["postgres"]["connected"] is True


@pytest.mark.asyncio
async def test_health_endpoint_degraded():
    """Verify /api/v1/health returns degraded when one database is offline."""
    with patch("app.api.v1.endpoints.health.check_mysql_health") as mock_mysql, \
         patch("app.api.v1.endpoints.health.check_pg_health") as mock_pg:

        mock_mysql.return_value = {
            "connected": True,
            "message": "AdAce MySQL connection healthy",
            "latency_ms": 1.5,
        }
        mock_pg.return_value = {
            "connected": False,
            "message": "Agent PostgreSQL connection error: Connection refused",
            "latency_ms": None,
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["mysql"]["connected"] is True
            assert data["postgres"]["connected"] is False


@pytest.mark.asyncio
async def test_health_endpoint_unhealthy():
    """Verify /api/v1/health returns 503 unhealthy when both databases are offline."""
    with patch("app.api.v1.endpoints.health.check_mysql_health") as mock_mysql, \
         patch("app.api.v1.endpoints.health.check_pg_health") as mock_pg:

        mock_mysql.return_value = {
            "connected": False,
            "message": "MySQL connection timed out",
            "latency_ms": None,
        }
        mock_pg.return_value = {
            "connected": False,
            "message": "Postgres connection timed out",
            "latency_ms": None,
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert data["mysql"]["connected"] is False
            assert data["postgres"]["connected"] is False


@pytest.mark.asyncio
async def test_seller_overview_navla_naturals(mock_navla_naturals_seller):
    """Verify retrieval of Seller 1 (Navla Naturals) with guardrails, HITL flags, and campaigns."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_navla_naturals_seller
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_adace_db] = lambda: mock_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/sellers/1/overview")
            assert response.status_code == 200
            data = response.json()

            # Verify Seller Information
            assert data["seller_id"] == 1
            assert data["seller_name"] == "Navla Naturals"

            # Verify Guardrails
            guardrails = data["guardrails"]
            assert float(guardrails["max_bid_cap"]) == 25.00
            assert float(guardrails["max_budget_cap"]) == 2000.00
            assert guardrails["neg_key_max_no_orders"] == 8

            # Verify Communication & HITL Gate
            comm = data["communication_settings"]
            assert comm is not None
            assert comm["increase_budget_option"] == 2
            assert comm["requires_hitl_approval"] is True

            # Verify Campaigns
            campaigns = data["campaigns"]
            assert len(campaigns) == 3

            # Campaign 1: High Spend Utilization (>80%)
            camp1 = next(c for c in campaigns if c["campaign_str_id"] == "CAMP101")
            assert camp1["dnt"] is False
            assert camp1["recent_metric"] is not None
            assert camp1["recent_metric"]["budget_utilization_pct"] == 92.0
            assert float(camp1["recent_metric"]["roas"]) == 4.20

            # Campaign 2: Optimizer config
            camp2 = next(c for c in campaigns if c["campaign_str_id"] == "CAMP102")
            assert camp2["dnt"] is False
            assert float(camp2["target_acos"]) == 25.00

            # Campaign 3: Do Not Touch (DNT) Guardrail
            camp3 = next(c for c in campaigns if c["campaign_str_id"] == "CAMP103")
            assert camp3["dnt"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_seller_overview_peps_mattress(mock_peps_mattress_seller):
    """Verify tenant isolation and autonomous pre-approved flags for Seller 2."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_peps_mattress_seller
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_adace_db] = lambda: mock_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/sellers/2/overview")
            assert response.status_code == 200
            data = response.json()

            assert data["seller_id"] == 2
            assert data["seller_name"] == "Peps Mattress"
            assert float(data["guardrails"]["max_budget_cap"]) == 5000.00
            assert data["communication_settings"]["increase_budget_option"] == 1
            assert data["communication_settings"]["requires_hitl_approval"] is False
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_seller_overview_not_found():
    """Verify 404 is returned when seller does not exist."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    app.dependency_overrides[get_adace_db] = lambda: mock_db

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/sellers/999/overview")
            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
