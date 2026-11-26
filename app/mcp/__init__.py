# app/mcp/__init__.py
from app.mcp.adace_server import (
    mcp,
    get_seller_guardrails,
    get_campaign_performance,
    find_bleeding_search_terms,
    find_oob_scaling_candidates,
    add_negative_keyword,
    adjust_keyword_bid,
    scale_campaign_budget,
    override_mcp_db,
)

__all__ = [
    "mcp",
    "get_seller_guardrails",
    "get_campaign_performance",
    "find_bleeding_search_terms",
    "find_oob_scaling_candidates",
    "add_negative_keyword",
    "adjust_keyword_bid",
    "scale_campaign_budget",
    "override_mcp_db",
]
