"""AdAce MCPServer (MCP v2) & Deterministic Guardrailed Tools.

Provides production-accurate Amazon Ads optimization tools for LangGraph and external agents.
Strictly enforces:
1. Multi-tenant isolation (every tool requires seller_id: int and scopes all queries).
2. Deterministic guardrails (DNT flag, max bid cap, max budget cap, single-step +20% bid limit).
3. Human-in-the-loop (HITL) gate enforcement for Tier 3 budget scaling.
"""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from typing import AsyncGenerator, Dict, List, Optional, Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        class MCPServer:  # type: ignore
            def __init__(self, name: str):
                self.name = name

            def tool(self, *args, **kwargs):
                def decorator(fn):
                    return fn

                return decorator

            async def list_tools(self):
                return []
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.mysql import adace_session_factory
from app.models.adace import (
    Seller,
    SellerCommunicationManagement,
    Campaign,
    CampaignOptimizer,
    CampaignMetric,
    KeywordReport,
    SearchTerm,
    AdAceStatusLog,
)

# Initialize MCPServer instance (MCP v2)
mcp = MCPServer("AdAce-AdOps-Server")

# Context variable for database session override (e.g. for testing / unit isolation)
_db_session_override: ContextVar[Optional[AsyncSession]] = ContextVar("_db_session_override", default=None)


@asynccontextmanager
async def override_mcp_db(session: AsyncSession) -> AsyncGenerator[None, None]:
    """Context manager to override the database session used by MCP tools (ideal for tests)."""
    token = _db_session_override.set(session)
    try:
        yield
    finally:
        _db_session_override.reset(token)


@asynccontextmanager
async def get_tool_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an active AsyncSession, respecting any test/thread overrides."""
    override = _db_session_override.get()
    if override is not None:
        yield override
    else:
        async with adace_session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


# =============================================================================
# READ-ONLY ANALYTICS TOOLS
# =============================================================================


@mcp.tool()
async def get_seller_guardrails(seller_id: int) -> dict:
    """Fetch safety guardrail caps, threshold settings, and communication approval rules for a seller.

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).

    Returns:
        dict containing max_bid_cap, max_budget_cap, neg_key_max_no_orders, and HITL flags.
    """
    async with get_tool_db() as db:
        stmt = (
            select(Seller)
            .where(Seller.id == seller_id)
            .options(selectinload(Seller.communication))
        )
        res = await db.execute(stmt)
        seller = res.scalar_one_or_none()

        if not seller:
            return {
                "status": "not_found",
                "found": False,
                "seller_id": seller_id,
                "message": f"Seller with ID {seller_id} not found in AdAce database",
            }

        comm = seller.communication
        increase_budget_option = comm.increase_budget_option if comm else 2
        day_parting_option = comm.day_parting_option if comm else 1

        return {
            "status": "success",
            "found": True,
            "seller_id": seller.id,
            "seller_name": seller.seller_name,
            "seller_type": seller.seller_type,
            "account_id": seller.account_id,
            "profile_id": seller.profile_id,
            "max_bid_cap": float(seller.max_bid_cap),
            "max_budget_cap": float(seller.max_budget_cap),
            "neg_key_max_no_orders": seller.neg_key_max_no_orders,
            "activated": bool(seller.activated),
            "seller_status": seller.status,
            "day_parting_option": day_parting_option,
            "increase_budget_option": increase_budget_option,
            "requires_hitl_approval": increase_budget_option != 1,
        }


@mcp.tool()
async def get_campaign_performance(seller_id: int) -> list:
    """Retrieve all campaigns for a seller along with optimizer rules, DNT guardrails, and latest performance metrics.

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).

    Returns:
        list of campaign performance dictionaries.
    """
    async with get_tool_db() as db:
        stmt = (
            select(Campaign)
            .where(Campaign.seller_id == seller_id)
            .options(
                selectinload(Campaign.optimizer),
                selectinload(Campaign.metrics),
            )
        )
        res = await db.execute(stmt)
        campaigns = res.scalars().all()

        results = []
        for camp in campaigns:
            opt = camp.optimizer
            dnt = bool(opt.dnt) if opt else False
            target_acos = float(opt.target_acos) if (opt and opt.target_acos is not None) else None
            daily_budget = float(opt.daily_budget) if (opt and opt.daily_budget is not None) else float(camp.budget)
            budget_rule = opt.budget_rule if opt else "standard"

            latest_metric: Optional[Dict[str, Any]] = None
            if camp.metrics:
                sorted_metrics = sorted(camp.metrics, key=lambda m: m.status_date, reverse=True)
                m = sorted_metrics[0]
                utilization = None
                if camp.budget and camp.budget > Decimal("0.00"):
                    utilization = round(float((m.spend / camp.budget) * 100), 2)

                latest_metric = {
                    "status_date": str(m.status_date),
                    "impressions": m.impressions,
                    "clicks": m.clicks,
                    "spend": float(m.spend),
                    "acos": float(m.acos),
                    "orders": m.orders,
                    "sales": float(m.sales),
                    "roas": float(m.roas),
                    "campaign_budget": float(m.campaign_budget),
                    "budget_utilization_pct": utilization,
                }

            results.append({
                "seller_id": seller_id,
                "campaign_id": camp.id,
                "campaign_str_id": camp.campaign_str_id,
                "campaign_name": camp.campaign_name,
                "campaign_type": camp.campaign_type,
                "targeting_type": camp.targeting_type,
                "state": camp.state,
                "budget": float(camp.budget),
                "dnt": dnt,
                "target_acos": target_acos,
                "daily_budget": daily_budget,
                "budget_rule": budget_rule,
                "latest_metric": latest_metric,
            })

        return results


@mcp.tool()
async def find_bleeding_search_terms(seller_id: int) -> list:
    """Identify bleeder search terms exceeding orderless click thresholds for Tier 1 negative harvesting.

    Filters strictly for the specified seller, excludes campaigns protected by DNT (dnt == 1),
    and filters for units_sold_clicks_7d == 0 with clicks >= neg_key_max_no_orders threshold.

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).

    Returns:
        list of bleeding search term candidates with negation recommendations.
    """
    async with get_tool_db() as db:
        # Load seller to verify and get fallback threshold
        seller_stmt = select(Seller).where(Seller.id == seller_id)
        seller_res = await db.execute(seller_stmt)
        seller = seller_res.scalar_one_or_none()
        if not seller:
            return []

        # Join search_terms with Campaign and CampaignOptimizer, ensuring dnt == 0
        stmt = (
            select(SearchTerm, Campaign, CampaignOptimizer)
            .join(Campaign, and_(SearchTerm.campaign_id == Campaign.id, Campaign.seller_id == seller_id))
            .join(CampaignOptimizer, and_(Campaign.id == CampaignOptimizer.campaign_id, CampaignOptimizer.seller_id == seller_id))
            .where(
                SearchTerm.seller_id == seller_id,
                CampaignOptimizer.dnt == 0,
                SearchTerm.units_sold_clicks_7d == 0,
                SearchTerm.clicks >= func.coalesce(CampaignOptimizer.neg_key_max_no_orders, seller.neg_key_max_no_orders),
            )
            .order_by(SearchTerm.clicks.desc(), SearchTerm.cost.desc())
        )
        res = await db.execute(stmt)
        rows = res.all()

        results = []
        for row in rows:
            if hasattr(row, "SearchTerm"):
                st = row.SearchTerm
                camp = row.Campaign
                opt = row.CampaignOptimizer
            else:
                st, camp, opt = row[0], row[1], row[2]

            threshold = opt.neg_key_max_no_orders if (opt and opt.neg_key_max_no_orders is not None) else seller.neg_key_max_no_orders

            results.append({
                "seller_id": seller_id,
                "search_term_id": st.id,
                "campaign_id": st.campaign_id,
                "campaign_str_id": camp.campaign_str_id if camp else "UNKNOWN",
                "campaign_name": st.campaign_name,
                "adgroup_id": st.adgroup_id,
                "keyword_id": st.keyword_id,
                "keyword": st.keyword,
                "match_type": st.match_type,
                "search_term": st.search_term,
                "clicks": st.clicks,
                "cost": float(st.cost),
                "sales_7d": float(st.sales_7d),
                "units_sold_clicks_7d": st.units_sold_clicks_7d,
                "neg_threshold": threshold,
                "recommendation": "ADD_NEGATIVE_EXACT",
                "reason": (
                    f"Search term '{st.search_term}' has {st.clicks} clicks with 0 orders "
                    f"(threshold: {threshold}) and spend ${float(st.cost):.2f}"
                ),
            })

        return results


@mcp.tool()
async def find_oob_scaling_candidates(seller_id: int) -> list:
    """Discover high-performing out-of-budget (OOB) campaigns eligible for +30% budget scaling.

    Criteria:
    - Campaign is ENABLED and dnt == 0.
    - Spend utilization >= 80% (spend >= 0.80 * budget).
    - ROAS >= 3.0.
    - Proposed budget: min(current_budget * 1.30, seller.max_budget_cap).
    - Flags requires_hitl_approval = (increase_budget_option != 1).

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).

    Returns:
        list of candidate campaigns with proposed budget scaling calculations.
    """
    async with get_tool_db() as db:
        # Load seller and communication settings
        seller_stmt = (
            select(Seller)
            .where(Seller.id == seller_id)
            .options(selectinload(Seller.communication))
        )
        seller_res = await db.execute(seller_stmt)
        seller = seller_res.scalar_one_or_none()
        if not seller:
            return []

        comm = seller.communication
        requires_hitl = (comm.increase_budget_option != 1) if comm else True
        max_budget_cap = float(seller.max_budget_cap)

        # Query enabled campaigns with dnt == 0
        stmt = (
            select(Campaign)
            .join(CampaignOptimizer, and_(Campaign.id == CampaignOptimizer.campaign_id, CampaignOptimizer.seller_id == seller_id))
            .where(
                Campaign.seller_id == seller_id,
                func.lower(Campaign.state) == "enabled",
                CampaignOptimizer.dnt == 0,
            )
            .options(
                selectinload(Campaign.optimizer),
                selectinload(Campaign.metrics),
            )
        )
        res = await db.execute(stmt)
        campaigns = res.scalars().all()

        candidates = []
        for camp in campaigns:
            if not camp.metrics:
                continue

            # Latest metric
            sorted_metrics = sorted(camp.metrics, key=lambda m: m.status_date, reverse=True)
            m = sorted_metrics[0]

            spend = float(m.spend)
            roas = float(m.roas)
            current_budget = float(camp.budget)

            if current_budget <= 0:
                continue

            utilization_pct = (spend / current_budget) * 100

            # Condition: spend utilization >= 80% and ROAS >= 3.0
            if utilization_pct >= 80.0 and roas >= 3.0:
                raw_proposed = current_budget * 1.30
                proposed_budget = round(min(raw_proposed, max_budget_cap), 2)
                capped_by_max_limit = raw_proposed > max_budget_cap

                candidates.append({
                    "seller_id": seller_id,
                    "campaign_id": camp.id,
                    "campaign_str_id": camp.campaign_str_id,
                    "campaign_name": camp.campaign_name,
                    "current_budget": current_budget,
                    "spend": spend,
                    "roas": roas,
                    "budget_utilization_pct": round(utilization_pct, 2),
                    "proposed_budget": proposed_budget,
                    "budget_increase_amount": round(proposed_budget - current_budget, 2),
                    "budget_increase_pct": 30.0 if not capped_by_max_limit else round(((proposed_budget - current_budget) / current_budget) * 100, 2),
                    "max_budget_cap": max_budget_cap,
                    "capped_by_max_limit": capped_by_max_limit,
                    "requires_hitl_approval": requires_hitl,
                    "increase_budget_option": comm.increase_budget_option if comm else 2,
                    "status": "candidate_found",
                    "recommendation": "SCALE_BUDGET_30_PCT",
                })

        return candidates


# =============================================================================
# GUARDRAILED ACTION TOOLS (WITH RISK TIERS & AUDIT LEDGER)
# =============================================================================


@mcp.tool()
async def add_negative_keyword(
    seller_id: int,
    campaign_str_id: str,
    keyword_text: str,
    match_type: str = "NEGATIVE_EXACT",
    reason: str = "",
) -> dict:
    """Tier 1 Autonomous Action: Add a negative keyword to a campaign to eliminate bleeder spend.

    Deterministic Guardrails:
    - Scoped strictly to seller_id.
    - Campaign must have dnt == 0. Rejects if dnt == 1.
    - Logs audit trail in adace_status_logs (module_id=3, action_id=1).

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).
        campaign_str_id: The campaign string ID (e.g. 'CAMP102').
        keyword_text: The search term or keyword to negate.
        match_type: Negation match type ('NEGATIVE_EXACT' or 'NEGATIVE_PHRASE').
        reason: Justification recorded in audit trail.

    Returns:
        dict with action status ('executed', 'blocked', or 'rejected').
    """
    async with get_tool_db() as db:
        # 1. Fetch Campaign and CampaignOptimizer scoped to seller_id
        stmt = (
            select(Campaign)
            .where(
                Campaign.seller_id == seller_id,
                Campaign.campaign_str_id == campaign_str_id,
            )
            .options(selectinload(Campaign.optimizer))
        )
        res = await db.execute(stmt)
        campaign = res.scalar_one_or_none()

        if not campaign:
            return {
                "status": "rejected",
                "tier": 1,
                "seller_id": seller_id,
                "campaign_str_id": campaign_str_id,
                "reason": f"Campaign '{campaign_str_id}' not found for seller {seller_id}",
            }

        # 2. Enforce DNT Guardrail
        optimizer = campaign.optimizer
        if optimizer and optimizer.dnt == 1:
            return {
                "status": "blocked",
                "tier": 1,
                "seller_id": seller_id,
                "campaign_str_id": campaign_str_id,
                "reason": "Deterministic Guardrail: Campaign has DNT (Do Not Touch) flag enabled",
            }

        # 3. Insert audit log into adace_status_logs
        log_entry = AdAceStatusLog(
            seller_id=seller_id,
            module_id=3,
            action_id=1,
            status_text=reason or f"Autonomous negative keyword added: '{keyword_text}' ({match_type})",
            rule="TIER1_NEG_KEYWORD_AUTONOMOUS",
            campaign_str_id=campaign_str_id,
            neg_keywd_product=keyword_text,
            run_date=datetime.now(),
        )
        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)

        return {
            "status": "executed",
            "tier": 1,
            "seller_id": seller_id,
            "campaign_str_id": campaign_str_id,
            "campaign_name": campaign.campaign_name,
            "keyword_text": keyword_text,
            "match_type": match_type,
            "action": "NEGATIVE_KEYWORD_ADDED",
            "log_id": log_entry.id,
            "reason": reason,
        }


@mcp.tool()
async def adjust_keyword_bid(
    seller_id: int,
    keyword_id: str,
    new_bid: float,
    reason: str = "",
) -> dict:
    """Tier 2 Bounded Autonomous Action: Adjust bid for a target keyword within safety limits.

    Deterministic Guardrails:
    - Scoped strictly to seller_id.
    - Parent campaign must have dnt == 0.
    - new_bid must not exceed seller.max_bid_cap.
    - Single-step bid increase must not exceed +20% of current bid.
    - Records before/after bids in adace_status_logs (module_id=6, action_id=2).

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).
        keyword_id: The keyword ID (e.g. 'KW102_01').
        new_bid: Proposed new bid in USD.
        reason: Justification recorded in audit trail.

    Returns:
        dict with action status ('executed', 'blocked', or 'rejected').
    """
    async with get_tool_db() as db:
        # 1. Fetch KeywordReport scoped to seller_id
        kw_stmt = (
            select(KeywordReport)
            .where(
                KeywordReport.seller_id == seller_id,
                KeywordReport.keyword_id == keyword_id,
            )
        )
        kw_res = await db.execute(kw_stmt)
        keyword = kw_res.scalar_one_or_none()

        if not keyword:
            return {
                "status": "rejected",
                "tier": 2,
                "seller_id": seller_id,
                "keyword_id": keyword_id,
                "reason": f"Keyword '{keyword_id}' not found for seller {seller_id}",
            }

        # 2. Check parent campaign DNT guardrail
        camp_stmt = (
            select(Campaign)
            .where(
                Campaign.seller_id == seller_id,
                Campaign.campaign_str_id == keyword.campaign_str_id,
            )
            .options(selectinload(Campaign.optimizer))
        )
        camp_res = await db.execute(camp_stmt)
        campaign = camp_res.scalar_one_or_none()

        if campaign and campaign.optimizer and campaign.optimizer.dnt == 1:
            return {
                "status": "blocked",
                "tier": 2,
                "seller_id": seller_id,
                "keyword_id": keyword_id,
                "campaign_str_id": keyword.campaign_str_id,
                "reason": "Deterministic Guardrail: Parent campaign has DNT (Do Not Touch) flag enabled",
            }

        # 3. Check seller max_bid_cap guardrail
        seller_stmt = select(Seller).where(Seller.id == seller_id)
        seller_res = await db.execute(seller_stmt)
        seller = seller_res.scalar_one_or_none()

        if not seller:
            return {
                "status": "rejected",
                "tier": 2,
                "seller_id": seller_id,
                "reason": f"Seller {seller_id} not found",
            }

        max_bid_cap = float(seller.max_bid_cap)
        if new_bid > max_bid_cap:
            return {
                "status": "blocked",
                "tier": 2,
                "seller_id": seller_id,
                "keyword_id": keyword_id,
                "current_bid": float(keyword.bid),
                "proposed_bid": new_bid,
                "max_bid_cap": max_bid_cap,
                "reason": f"Deterministic Guardrail: Proposed bid {new_bid:.2f} exceeds seller max_bid_cap {max_bid_cap:.2f}",
            }

        # 4. Check bounded single-step increase limit (+20%)
        current_bid = float(keyword.bid)
        if new_bid > current_bid:
            max_allowed_bid = round(current_bid * 1.20, 2)
            if new_bid > (max_allowed_bid + 0.001):
                return {
                    "status": "blocked",
                    "tier": 2,
                    "seller_id": seller_id,
                    "keyword_id": keyword_id,
                    "current_bid": current_bid,
                    "proposed_bid": new_bid,
                    "max_allowed_bid": max_allowed_bid,
                    "reason": (
                        f"Deterministic Guardrail: Proposed bid increase exceeds 20% single-step limit "
                        f"(Current: {current_bid:.2f}, Max Allowed: {max_allowed_bid:.2f})"
                    ),
                }

        # 5. Mutate bid and record audit log
        prev_bid_dec = keyword.bid
        new_bid_dec = Decimal(str(round(new_bid, 2)))
        keyword.bid = new_bid_dec

        log_entry = AdAceStatusLog(
            seller_id=seller_id,
            module_id=6,
            action_id=2,
            status_text=reason or f"Adjusted bid for keyword {keyword_id} from {float(prev_bid_dec):.2f} to {float(new_bid_dec):.2f}",
            rule="TIER2_BID_OPTIMIZATION",
            campaign_str_id=keyword.campaign_str_id,
            keywd_prev_bid=prev_bid_dec,
            keywd_cur_bid=new_bid_dec,
            run_date=datetime.now(),
        )
        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)

        bid_change_pct = (
            round(((new_bid - current_bid) / current_bid) * 100, 2)
            if current_bid > 0
            else 0.0
        )

        return {
            "status": "executed",
            "tier": 2,
            "seller_id": seller_id,
            "keyword_id": keyword_id,
            "keyword_text": keyword.keyword_text,
            "campaign_str_id": keyword.campaign_str_id,
            "previous_bid": current_bid,
            "new_bid": round(new_bid, 2),
            "bid_change_pct": bid_change_pct,
            "action": "BID_UPDATED",
            "log_id": log_entry.id,
            "reason": reason,
        }


@mcp.tool()
async def scale_campaign_budget(
    seller_id: int,
    campaign_str_id: str,
    proposed_budget: float,
    human_approved: bool = False,
    reason: str = "",
) -> dict:
    """Tier 3 HITL Guardrailed Action: Scale daily budget for high-performing OOB campaigns.

    Deterministic Guardrails:
    - Scoped strictly to seller_id.
    - Campaign must have dnt == 0.
    - proposed_budget must not exceed seller.max_budget_cap.
    - If seller_communication_management.increase_budget_option != 1 (Approval Required),
      DOES NOT mutate database unless human_approved is True. Returns 'approval_required'.
    - When approved (or pre-approved), updates Campaign and CampaignOptimizer budgets,
      and writes audit log to adace_status_logs (module_id=14, action_id=2, rule='OOB 3xRoAS').

    Args:
        seller_id: The ID of the seller (strict multi-tenant scoping).
        campaign_str_id: The campaign string ID (e.g. 'CAMP101').
        proposed_budget: Proposed new daily budget in USD.
        human_approved: Explicit flag indicating a human operator verified the change.
        reason: Justification recorded in audit trail.

    Returns:
        dict with action status ('executed', 'approval_required', 'blocked', or 'rejected').
    """
    async with get_tool_db() as db:
        # 1. Fetch Campaign and CampaignOptimizer scoped to seller_id
        stmt = (
            select(Campaign)
            .where(
                Campaign.seller_id == seller_id,
                Campaign.campaign_str_id == campaign_str_id,
            )
            .options(selectinload(Campaign.optimizer))
        )
        res = await db.execute(stmt)
        campaign = res.scalar_one_or_none()

        if not campaign:
            return {
                "status": "rejected",
                "tier": 3,
                "seller_id": seller_id,
                "campaign_str_id": campaign_str_id,
                "reason": f"Campaign '{campaign_str_id}' not found for seller {seller_id}",
            }

        # 2. Check DNT Guardrail
        optimizer = campaign.optimizer
        if optimizer and optimizer.dnt == 1:
            return {
                "status": "blocked",
                "tier": 3,
                "seller_id": seller_id,
                "campaign_str_id": campaign_str_id,
                "reason": "Deterministic Guardrail: Campaign has DNT (Do Not Touch) flag enabled",
            }

        # 3. Check seller max_budget_cap guardrail
        seller_stmt = (
            select(Seller)
            .where(Seller.id == seller_id)
            .options(selectinload(Seller.communication))
        )
        seller_res = await db.execute(seller_stmt)
        seller = seller_res.scalar_one_or_none()

        if not seller:
            return {
                "status": "rejected",
                "tier": 3,
                "seller_id": seller_id,
                "reason": f"Seller {seller_id} not found",
            }

        max_budget_cap = float(seller.max_budget_cap)
        if proposed_budget > max_budget_cap:
            return {
                "status": "blocked",
                "tier": 3,
                "seller_id": seller_id,
                "campaign_str_id": campaign_str_id,
                "current_budget": float(campaign.budget),
                "proposed_budget": proposed_budget,
                "max_budget_cap": max_budget_cap,
                "reason": f"Deterministic Guardrail: Proposed budget {proposed_budget:.2f} exceeds seller max_budget_cap {max_budget_cap:.2f}",
            }

        # 4. Check Human-in-the-Loop (HITL) Gate
        comm = seller.communication
        increase_budget_option = comm.increase_budget_option if comm else 2
        current_budget = float(campaign.budget)

        # Option 1 = Pre-approved (Autonomous); Option 2 = Approval Required (HITL)
        if increase_budget_option != 1 and not human_approved:
            # DO NOT mutate database; return approval_required envelope
            return {
                "status": "approval_required",
                "tier": 3,
                "seller_id": seller_id,
                "campaign_str_id": campaign_str_id,
                "campaign_name": campaign.campaign_name,
                "current_budget": current_budget,
                "proposed_budget": round(proposed_budget, 2),
                "increase_budget_option": increase_budget_option,
                "requires_hitl_approval": True,
                "reason": "Seller requires human approval for budget scaling",
            }

        # 5. When approved or pre-approved, mutate budget and log audit record
        prev_budget_dec = campaign.budget
        new_budget_dec = Decimal(str(round(proposed_budget, 2)))

        campaign.budget = new_budget_dec
        if optimizer:
            optimizer.daily_budget = new_budget_dec

        log_entry = AdAceStatusLog(
            seller_id=seller_id,
            module_id=14,
            action_id=2,
            status_text=reason or f"Scaled budget for campaign {campaign_str_id} from {float(prev_budget_dec):.2f} to {float(new_budget_dec):.2f}",
            rule="OOB 3xRoAS",
            campaign_str_id=campaign_str_id,
            campaign_prv_budget=prev_budget_dec,
            campaign_cur_budget=new_budget_dec,
            run_date=datetime.now(),
        )
        db.add(log_entry)
        await db.commit()
        await db.refresh(log_entry)

        return {
            "status": "executed",
            "tier": 3,
            "seller_id": seller_id,
            "campaign_str_id": campaign_str_id,
            "campaign_name": campaign.campaign_name,
            "previous_budget": current_budget,
            "new_budget": round(proposed_budget, 2),
            "human_approved": human_approved,
            "action": "BUDGET_SCALED",
            "rule": "OOB 3xRoAS",
            "log_id": log_entry.id,
            "reason": reason,
        }
