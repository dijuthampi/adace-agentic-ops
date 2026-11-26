from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.mysql import get_adace_db
from app.models.adace import Seller, Campaign, CampaignMetric, CampaignOptimizer, SellerCommunicationManagement
from app.schemas.seller import (
    SellerOverviewResponse,
    SellerGuardrailsSchema,
    CommunicationSettingsSchema,
    CampaignOverviewSchema,
    CampaignMetricSummarySchema,
)

router = APIRouter()


@router.get(
    "/{seller_id}/overview",
    response_model=SellerOverviewResponse,
    summary="Fetch Seller Overview, Guardrails & Campaigns",
    description=(
        "Retrieves the seller's configured guardrail limits, communication approval flags (HITL requirement), "
        "and active campaigns with optimizer DNT flags and recent metrics."
    ),
)
async def get_seller_overview(
    seller_id: int,
    db: AsyncSession = Depends(get_adace_db),
) -> SellerOverviewResponse:
    # Query seller with joined eager loading for related entities
    stmt = (
        select(Seller)
        .where(Seller.id == seller_id)
        .options(
            selectinload(Seller.communication),
            selectinload(Seller.campaigns).selectinload(Campaign.optimizer),
            selectinload(Seller.campaigns).selectinload(Campaign.metrics),
        )
    )

    result = await db.execute(stmt)
    seller = result.scalar_one_or_none()

    if not seller:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Seller with ID {seller_id} not found in AdAce database",
        )

    # 1. Map Guardrails
    guardrails = SellerGuardrailsSchema(
        max_bid_cap=seller.max_bid_cap,
        max_budget_cap=seller.max_budget_cap,
        neg_key_max_no_orders=seller.neg_key_max_no_orders,
        activated=seller.activated,
        status=seller.status,
    )

    # 2. Map Communication Settings (HITL gate check)
    comm_settings: Optional[CommunicationSettingsSchema] = None
    if seller.communication:
        comm = seller.communication
        requires_hitl = comm.increase_budget_option == 2
        comm_settings = CommunicationSettingsSchema(
            seller_id=seller.id,
            day_parting_option=comm.day_parting_option,
            increase_budget_option=comm.increase_budget_option,
            requires_hitl_approval=requires_hitl,
        )

    # 3. Map Campaigns and Latest Performance Metrics
    campaign_list: List[CampaignOverviewSchema] = []
    for camp in seller.campaigns:
        optimizer = camp.optimizer
        dnt = bool(optimizer.dnt) if optimizer else False
        budget_rule = optimizer.budget_rule if optimizer else None
        target_acos = optimizer.target_acos if optimizer else None

        recent_metric: Optional[CampaignMetricSummarySchema] = None
        if camp.metrics:
            # Metrics are ordered desc by status_date
            latest = camp.metrics[0]
            utilization: Optional[float] = None
            if camp.budget and camp.budget > Decimal("0.00"):
                utilization = round(float((latest.spend / camp.budget) * 100), 2)

            recent_metric = CampaignMetricSummarySchema(
                status_date=latest.status_date,
                impressions=latest.impressions,
                clicks=latest.clicks,
                spend=latest.spend,
                orders=latest.orders,
                sales=latest.sales,
                roas=latest.roas,
                acos=latest.acos,
                budget_utilization_pct=utilization,
            )

        campaign_list.append(
            CampaignOverviewSchema(
                id=camp.id,
                campaign_name=camp.campaign_name,
                campaign_str_id=camp.campaign_str_id,
                campaign_type=camp.campaign_type,
                targeting_type=camp.targeting_type,
                state=camp.state,
                budget=camp.budget,
                dnt=dnt,
                budget_rule=budget_rule,
                target_acos=target_acos,
                recent_metric=recent_metric,
            )
        )

    return SellerOverviewResponse(
        seller_id=seller.id,
        seller_name=seller.seller_name,
        seller_type=seller.seller_type,
        account_id=seller.account_id,
        profile_id=seller.profile_id,
        guardrails=guardrails,
        communication_settings=comm_settings,
        campaigns=campaign_list,
    )
