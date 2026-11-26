from datetime import date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SellerGuardrailsSchema(BaseModel):
    """Configured safety caps and threshold guardrails for an AdAce seller."""

    model_config = ConfigDict(from_attributes=True)

    max_bid_cap: Decimal = Field(..., description="Hard upper limit for individual keyword or adgroup bids")
    max_budget_cap: Decimal = Field(..., description="Hard upper limit for daily campaign budget")
    neg_key_max_no_orders: int = Field(..., description="Click threshold with zero orders before auto-negation")
    activated: bool = Field(..., description="Whether optimization is actively enabled")
    status: str = Field(..., description="Seller account status ('active', 'paused', etc.)")


class CommunicationSettingsSchema(BaseModel):
    """Communication approval settings and Human-In-The-Loop gate rules."""

    model_config = ConfigDict(from_attributes=True)

    seller_id: int
    day_parting_option: int = Field(..., description="1 = Active, 0 = Disabled")
    increase_budget_option: int = Field(..., description="1 = Pre-approved (Autonomous), 2 = Approval required (HITL)")
    requires_hitl_approval: bool = Field(..., description="True if budget increases require human sign-off")


class CampaignMetricSummarySchema(BaseModel):
    """Latest aggregated campaign metrics and spend utilization."""

    model_config = ConfigDict(from_attributes=True)

    status_date: date
    impressions: int
    clicks: int
    spend: Decimal
    orders: int
    sales: Decimal
    roas: Decimal
    acos: Decimal
    budget_utilization_pct: Optional[float] = Field(
        None,
        description="Percentage of campaign budget spent on the given status date",
    )


class CampaignOverviewSchema(BaseModel):
    """High-level summary of a campaign, its optimizer rules, and recent performance."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_name: str
    campaign_str_id: str
    campaign_type: str
    targeting_type: str
    state: str
    budget: Decimal
    dnt: bool = Field(..., description="Do Not Touch flag. When true, autonomous agents must never modify this campaign")
    budget_rule: Optional[str] = Field(None, description="Optimizer budget scaling strategy")
    target_acos: Optional[Decimal] = Field(None, description="Target ACOS configured in optimizer")
    recent_metric: Optional[CampaignMetricSummarySchema] = Field(None, description="Latest daily performance metric")


class SellerOverviewResponse(BaseModel):
    """Complete seller overview including guardrails, HITL flags, and campaigns."""

    model_config = ConfigDict(from_attributes=True)

    seller_id: int
    seller_name: str
    seller_type: str
    account_id: str
    profile_id: str
    guardrails: SellerGuardrailsSchema
    communication_settings: Optional[CommunicationSettingsSchema] = None
    campaigns: List[CampaignOverviewSchema] = Field(default_factory=list)
