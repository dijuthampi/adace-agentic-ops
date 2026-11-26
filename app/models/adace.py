from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    String,
    Integer,
    Numeric,
    Boolean,
    Date,
    DateTime,
    Text,
    ForeignKey,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mysql import AdAceBase


class Seller(AdAceBase):
    """AdAce Seller Account Entity."""

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False)
    seller_type: Mapped[str] = mapped_column(String(50), nullable=False, default="seller")
    account_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    max_bid_cap: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("50.00"))
    max_budget_cap: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("2000.00"))
    neg_key_max_no_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    activated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    communication: Mapped[Optional["SellerCommunicationManagement"]] = relationship(
        "SellerCommunicationManagement",
        back_populates="seller",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    campaigns: Mapped[List["Campaign"]] = relationship(
        "Campaign",
        back_populates="seller",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    optimizers: Mapped[List["CampaignOptimizer"]] = relationship(
        "CampaignOptimizer",
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    metrics: Mapped[List["CampaignMetric"]] = relationship(
        "CampaignMetric",
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    keywords: Mapped[List["KeywordReport"]] = relationship(
        "KeywordReport",
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    search_terms: Mapped[List["SearchTerm"]] = relationship(
        "SearchTerm",
        back_populates="seller",
        cascade="all, delete-orphan",
    )
    status_logs: Mapped[List["AdAceStatusLog"]] = relationship(
        "AdAceStatusLog",
        back_populates="seller",
        cascade="all, delete-orphan",
    )


class SellerCommunicationManagement(AdAceBase):
    """Communication approval preferences and HITL gates."""

    __tablename__ = "seller_communication_management"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sellers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    day_parting_option: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 1 = Pre-approved (Autonomous), 2 = Approval required (HITL required)
    increase_budget_option: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="communication")


class Campaign(AdAceBase):
    """Amazon Ads Campaign Mirror."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    campaign_str_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    campaign_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sp")
    targeting_type: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="enabled", index=True)
    budget_type: Mapped[str] = mapped_column(String(50), nullable=False, default="daily")
    budget: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    seller: Mapped["Seller"] = relationship("Seller", back_populates="campaigns")
    optimizer: Mapped[Optional["CampaignOptimizer"]] = relationship(
        "CampaignOptimizer",
        back_populates="campaign",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    metrics: Mapped[List["CampaignMetric"]] = relationship(
        "CampaignMetric",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="desc(CampaignMetric.status_date)",
        lazy="selectin",
    )
    search_terms: Mapped[List["SearchTerm"]] = relationship(
        "SearchTerm",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )


class CampaignOptimizer(AdAceBase):
    """AdAce Optimizer Rules and DNT (Do Not Touch) Guardrails per Campaign."""

    __tablename__ = "campaign_optimizers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    campaign_str_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # 1 = Do Not Touch (DNT), 0 = Allow Optimization
    dnt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    budget_rule: Mapped[str] = mapped_column(String(100), nullable=False, default="standard")
    target_acos: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("25.00"))
    neg_term_opt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    neg_key_max_no_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="optimizers")
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="optimizer")


class CampaignMetric(AdAceBase):
    """Daily Aggregated Campaign Performance Metrics."""

    __tablename__ = "campaign_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(Integer, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_str_id: Mapped[str] = mapped_column(String(100), nullable=False)
    campaign_status: Mapped[str] = mapped_column(String(50), nullable=False, default="enabled")
    campaign_budget: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    status_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    acos: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    roas: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="metrics")
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="metrics")


class KeywordReport(AdAceBase):
    """Keyword Level Bids and Performance."""

    __tablename__ = "keyword_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    campaign_str_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    ad_group_id: Mapped[str] = mapped_column(String(100), nullable=False)
    keyword_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    keyword_text: Mapped[str] = mapped_column(String(255), nullable=False)
    match_type: Mapped[str] = mapped_column(String(50), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False, default="enabled")
    bid: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    status_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    acos: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0.00"))
    orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sales: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    roas: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="keywords")


class SearchTerm(AdAceBase):
    """Customer Search Terms for Negative Exact / Negative Phrase Harvesting."""

    __tablename__ = "search_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(Integer, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    campaign_id: Mapped[int] = mapped_column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    adgroup_id: Mapped[str] = mapped_column(String(100), nullable=False)
    keyword_id: Mapped[str] = mapped_column(String(100), nullable=False)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False)
    adgroup_name: Mapped[str] = mapped_column(String(255), nullable=False)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False)
    match_type: Mapped[str] = mapped_column(String(50), nullable=False)
    search_term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    sales_7d: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    units_sold_clicks_7d: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="search_terms")
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="search_terms")


class AdAceStatusLog(AdAceBase):
    """Audit Trail and Execution Logs for AdAce Optimizers."""

    __tablename__ = "adace_status_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)
    seller_id: Mapped[int] = mapped_column(Integer, ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True)
    module_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    action_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    campaign_str_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    campaign_prv_budget: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    campaign_cur_budget: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ad_grp_prev_bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    ad_grp_cur_bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    keywd_prev_bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    keywd_cur_bid: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    neg_keywd_product: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    cpc: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    orders: Mapped[int] = mapped_column(Integer, default=0)

    seller: Mapped["Seller"] = relationship("Seller", back_populates="status_logs")
