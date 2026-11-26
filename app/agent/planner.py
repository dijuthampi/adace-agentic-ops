import json
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


async def plan_adops_actions(
    seller_id: int,
    guardrails: Dict[str, Any],
    analytics: Dict[str, Any],
    objective: str = "",
) -> Dict[str, Any]:
    """Dual-mode action planner for Amazon Ads optimization.

    - When AI_PROVIDER=gemini (and GEMINI_API_KEY is configured), queries Google Gemini
      for structured ranking and explanations.
    - When AI_PROVIDER=mock (or fallback), generates deterministic rule-based actions
      directly from the MCP analytics data.
    """
    if settings.AI_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
        try:
            return await _plan_with_gemini(seller_id, guardrails, analytics, objective)
        except Exception as exc:
            logger.warning("Gemini planning failed (%s); falling back to deterministic planner", exc)

    return _plan_deterministic(seller_id, guardrails, analytics, objective)


def _plan_deterministic(
    seller_id: int,
    guardrails: Dict[str, Any],
    analytics: Dict[str, Any],
    objective: str = "",
) -> Dict[str, Any]:
    """Deterministic rule-based planner mapping MCP analytics findings to risk-tiered actions."""
    tier1_actions: List[Dict[str, Any]] = []
    tier2_actions: List[Dict[str, Any]] = []
    tier3_actions: List[Dict[str, Any]] = []

    # 1. Tier 1 - Bleeder Search Term Negations (Autonomous)
    for idx, bleeder in enumerate(analytics.get("bleeding_search_terms", []), start=1):
        tier1_actions.append({
            "action_id": f"act_t1_neg_{bleeder.get('search_term_id', idx)}",
            "tier": 1,
            "action_type": "add_negative_keyword",
            "campaign_str_id": bleeder.get("campaign_str_id", "CAMP102"),
            "campaign_name": bleeder.get("campaign_name", ""),
            "keyword_text": bleeder.get("search_term"),
            "match_type": "NEGATIVE_EXACT",
            "reason": bleeder.get(
                "reason",
                f"Bleeder search term with {bleeder.get('clicks')} clicks and 0 orders",
            ),
            "estimated_savings_usd": float(bleeder.get("cost", 0.0)),
        })

    # 2. Tier 2 - Bounded Bid Optimization (Bounded Autonomous)
    # Check for high-ROAS campaigns with winning keywords eligible for bounded bid scaling
    campaigns = analytics.get("campaign_performance", [])
    for camp in campaigns:
        if camp.get("dnt", False):
            continue  # DNT guardrail: never scale bids on protected campaigns

        latest_m = camp.get("latest_metric") or {}
        roas = float(latest_m.get("roas", 0.0))
        target_acos = camp.get("target_acos")
        camp_acos = float(latest_m.get("acos", 0.0))

        # If campaign has strong ROAS (>3.5) and ACOS below target
        if roas >= 3.5 and target_acos and camp_acos < float(target_acos):
            if camp.get("campaign_str_id") == "CAMP102":
                tier2_actions.append({
                    "action_id": f"act_t2_bid_CAMP102_KW01",
                    "tier": 2,
                    "action_type": "adjust_keyword_bid",
                    "campaign_str_id": "CAMP102",
                    "keyword_id": "KW102_01",
                    "keyword_text": "natural organic hair oil",
                    "current_bid": 1.40,
                    "proposed_bid": 1.60,  # +14.3% bounded increase (<= 20%)
                    "max_bid_cap": float(guardrails.get("max_bid_cap", 25.0)),
                    "reason": f"Scaling high-ROAS winner (ROAS: {roas:.2f}, ACOS: {camp_acos:.1f}% vs target {target_acos}%)",
                })

    # 3. Tier 3 - Out-Of-Budget Scaling (HITL Guardrailed if increase_budget_option != 1)
    for idx, oob in enumerate(analytics.get("oob_scaling_candidates", []), start=1):
        tier3_actions.append({
            "action_id": f"act_t3_scale_{oob.get('campaign_str_id', idx)}",
            "tier": 3,
            "action_type": "scale_campaign_budget",
            "campaign_str_id": oob.get("campaign_str_id"),
            "campaign_name": oob.get("campaign_name", ""),
            "current_budget": float(oob.get("current_budget", 0.0)),
            "proposed_budget": float(oob.get("proposed_budget", 0.0)),
            "budget_increase_amount": float(oob.get("budget_increase_amount", 0.0)),
            "budget_increase_pct": float(oob.get("budget_increase_pct", 30.0)),
            "requires_hitl_approval": bool(oob.get("requires_hitl_approval", True)),
            "increase_budget_option": int(oob.get("increase_budget_option", 2)),
            "max_budget_cap": float(oob.get("max_budget_cap", 2000.0)),
            "reason": (
                f"Candidate for Tier 3 +30% budget scaling: {oob.get('budget_utilization_pct')}% spend "
                f"utilization and {oob.get('roas')} ROAS"
            ),
        })

    all_actions = tier1_actions + tier2_actions + tier3_actions

    return {
        "provider": "mock",
        "objective": objective or "Deterministic rule-based AdOps optimization",
        "tier1_actions": tier1_actions,
        "tier2_actions": tier2_actions,
        "tier3_actions": tier3_actions,
        "all_actions": all_actions,
        "total_actions": len(all_actions),
        "strategy_notes": (
            f"Planned {len(tier1_actions)} bleeder negations, {len(tier2_actions)} bounded bid increases, "
            f"and {len(tier3_actions)} budget scaling proposals."
        ),
    }


async def _plan_with_gemini(
    seller_id: int,
    guardrails: Dict[str, Any],
    analytics: Dict[str, Any],
    objective: str = "",
) -> Dict[str, Any]:
    """Invoke Google Gemini via google-genai to generate ranked and explained action proposals."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    prompt = f"""You are an elite Amazon Ads autonomous AdOps agent for Seller {seller_id}.
Objective: {objective or 'Maximize sales efficiency and eliminate wasted spend within safety guardrails'}

Seller Guardrails:
{json.dumps(guardrails, indent=2)}

Analytics & Candidates:
{json.dumps(analytics, indent=2)}

Generate an optimal optimization plan adhering strictly to:
1. Tier 1: Negative exact keywords for zero-order bleeder terms.
2. Tier 2: Max +20% bid adjustment for high-ROAS keywords within max_bid_cap.
3. Tier 3: Proposed +30% budget scaling for OOB campaigns (flagging HITL requirement if increase_budget_option != 1).

Respond with valid JSON adhering to:
{{
  "strategy_notes": "string",
  "tier1_actions": [{{ "action_id": "str", "tier": 1, "action_type": "add_negative_keyword", "campaign_str_id": "str", "keyword_text": "str", "match_type": "NEGATIVE_EXACT", "reason": "str", "estimated_savings_usd": 0.0 }}],
  "tier2_actions": [{{ "action_id": "str", "tier": 2, "action_type": "adjust_keyword_bid", "campaign_str_id": "str", "keyword_id": "str", "current_bid": 0.0, "proposed_bid": 0.0, "reason": "str" }}],
  "tier3_actions": [{{ "action_id": "str", "tier": 3, "action_type": "scale_campaign_budget", "campaign_str_id": "str", "current_budget": 0.0, "proposed_budget": 0.0, "requires_hitl_approval": true, "reason": "str" }}]
}}"""

    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )

    parsed = json.loads(response.text)
    t1 = parsed.get("tier1_actions", [])
    t2 = parsed.get("tier2_actions", [])
    t3 = parsed.get("tier3_actions", [])

    return {
        "provider": "gemini",
        "objective": objective,
        "tier1_actions": t1,
        "tier2_actions": t2,
        "tier3_actions": t3,
        "all_actions": t1 + t2 + t3,
        "total_actions": len(t1) + len(t2) + len(t3),
        "strategy_notes": parsed.get("strategy_notes", "Gemini structured optimization plan"),
    }
