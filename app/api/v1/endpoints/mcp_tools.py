import asyncio
from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, status

from app.mcp.adace_server import (
    mcp,
    get_seller_guardrails,
    get_campaign_performance,
    find_bleeding_search_terms,
    find_oob_scaling_candidates,
    add_negative_keyword,
    adjust_keyword_bid,
    scale_campaign_budget,
)
from app.schemas.mcp import (
    MCPToolInfo,
    MCPToolParameter,
    MCPToolsListResponse,
    SellerAnalysisResponse,
    ExecuteToolRequest,
    ExecuteToolResponse,
)

router = APIRouter()

# Static registry metadata for OpenAPI documentation and introspection
REGISTERED_TOOLS_METADATA: List[MCPToolInfo] = [
    MCPToolInfo(
        name="get_seller_guardrails",
        description="Fetch safety guardrail caps (max_bid_cap, max_budget_cap, neg threshold) and HITL flags.",
        tier="Read-Only Analytics",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="AdAce Seller ID for tenant scoping", required=True),
        ],
    ),
    MCPToolInfo(
        name="get_campaign_performance",
        description="Fetch all campaigns with DNT guardrail flags, optimizer rules, and latest performance metrics.",
        tier="Read-Only Analytics",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="AdAce Seller ID for tenant scoping", required=True),
        ],
    ),
    MCPToolInfo(
        name="find_bleeding_search_terms",
        description="Identify zero-order bleeder search terms exceeding click threshold (excluding DNT campaigns).",
        tier="Read-Only Analytics",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="AdAce Seller ID for tenant scoping", required=True),
        ],
    ),
    MCPToolInfo(
        name="find_oob_scaling_candidates",
        description="Discover active campaigns with >=80% spend utilization and ROAS>=3.0 eligible for +30% budget scaling.",
        tier="Read-Only Analytics",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="AdAce Seller ID for tenant scoping", required=True),
        ],
    ),
    MCPToolInfo(
        name="add_negative_keyword",
        description="Tier 1 Autonomous: Negate bleeder search terms. Blocked if DNT==1. Logs to adace_status_logs.",
        tier="Tier 1 - Autonomous",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="Seller ID", required=True),
            MCPToolParameter(name="campaign_str_id", type="str", description="Campaign identifier (e.g. CAMP102)", required=True),
            MCPToolParameter(name="keyword_text", type="str", description="Search term or keyword to negate", required=True),
            MCPToolParameter(name="match_type", type="str", description="NEGATIVE_EXACT or NEGATIVE_PHRASE", required=False, default="NEGATIVE_EXACT"),
            MCPToolParameter(name="reason", type="str", description="Audit trail justification", required=False, default=""),
        ],
    ),
    MCPToolInfo(
        name="adjust_keyword_bid",
        description="Tier 2 Bounded: Adjust keyword bid. Enforces max_bid_cap and single-step +20% limit. Blocked if DNT==1.",
        tier="Tier 2 - Bounded Autonomous",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="Seller ID", required=True),
            MCPToolParameter(name="keyword_id", type="str", description="Keyword identifier (e.g. KW102_01)", required=True),
            MCPToolParameter(name="new_bid", type="float", description="Proposed new bid in USD", required=True),
            MCPToolParameter(name="reason", type="str", description="Audit trail justification", required=False, default=""),
        ],
    ),
    MCPToolInfo(
        name="scale_campaign_budget",
        description="Tier 3 HITL Guardrailed: Scale daily budget. Enforces max_budget_cap, DNT==1 block, and HITL gate if approval required.",
        tier="Tier 3 - HITL Guardrailed",
        parameters=[
            MCPToolParameter(name="seller_id", type="int", description="Seller ID", required=True),
            MCPToolParameter(name="campaign_str_id", type="str", description="Campaign identifier (e.g. CAMP101)", required=True),
            MCPToolParameter(name="proposed_budget", type="float", description="Proposed daily budget in USD", required=True),
            MCPToolParameter(name="human_approved", type="bool", description="Whether human operator approved scaling", required=False, default=False),
            MCPToolParameter(name="reason", type="str", description="Audit trail justification", required=False, default=""),
        ],
    ),
]


TIER_MAPPING: Dict[str, str] = {
    "get_seller_guardrails": "Read-Only Analytics",
    "get_campaign_performance": "Read-Only Analytics",
    "find_bleeding_search_terms": "Read-Only Analytics",
    "find_oob_scaling_candidates": "Read-Only Analytics",
    "add_negative_keyword": "Tier 1 - Autonomous",
    "adjust_keyword_bid": "Tier 2 - Bounded Autonomous",
    "scale_campaign_budget": "Tier 3 - HITL Guardrailed",
}


@router.get(
    "/tools",
    response_model=MCPToolsListResponse,
    summary="List Registered AdAce MCP Tools",
    description="Inspect all tools registered on the AdAce MCPServer, including risk tiers and guardrails.",
)
async def list_mcp_tools() -> MCPToolsListResponse:
    """Return all registered MCPServer tools with risk tier classification."""
    tools_list: List[MCPToolInfo] = []

    # Dynamically inspect MCPServer v2 if list_tools is available
    if hasattr(mcp, "list_tools"):
        try:
            tools_call = mcp.list_tools()
            raw_tools = await tools_call if asyncio.iscoroutine(tools_call) else tools_call
            if raw_tools:
                for t in raw_tools:
                    name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else str(t))
                    desc = getattr(t, "description", "") or (t.get("description", "") if isinstance(t, dict) else "")
                    tier = TIER_MAPPING.get(name, "Read-Only Analytics")
                    schema = getattr(t, "inputSchema", None) or (t.get("inputSchema") if isinstance(t, dict) else {})

                    params: List[MCPToolParameter] = []
                    if isinstance(schema, dict) and "properties" in schema:
                        required_props = schema.get("required", [])
                        for p_name, p_info in schema.get("properties", {}).items():
                            params.append(
                                MCPToolParameter(
                                    name=p_name,
                                    type=p_info.get("type", "string"),
                                    description=p_info.get("description", ""),
                                    required=(p_name in required_props),
                                    default=p_info.get("default"),
                                )
                            )

                    if not params:
                        matched = next((m for m in REGISTERED_TOOLS_METADATA if m.name == name), None)
                        if matched:
                            params = matched.parameters

                    tools_list.append(
                        MCPToolInfo(
                            name=name,
                            description=desc or next((m.description for m in REGISTERED_TOOLS_METADATA if m.name == name), ""),
                            tier=tier,
                            parameters=params,
                        )
                    )
        except Exception:
            tools_list = []

    if not tools_list:
        tools_list = REGISTERED_TOOLS_METADATA

    server_name = getattr(mcp, "name", "AdAce-AdOps-Server")
    return MCPToolsListResponse(
        server_name=server_name,
        total_tools=len(tools_list),
        tools=tools_list,
    )


@router.post(
    "/sellers/{seller_id}/analyze",
    response_model=SellerAnalysisResponse,
    summary="Execute Full Seller Analytics via MCP Tools",
    description="Runs all 4 read-only analytics tools for a seller concurrently and aggregates the findings.",
)
async def analyze_seller_via_mcp(seller_id: int) -> SellerAnalysisResponse:
    """Run all AdAce MCP analytics tools concurrently for the specified seller."""
    # Execute all 4 read-only tools concurrently
    guardrails, performance, bleeding_terms, oob_candidates = await asyncio.gather(
        get_seller_guardrails(seller_id=seller_id),
        get_campaign_performance(seller_id=seller_id),
        find_bleeding_search_terms(seller_id=seller_id),
        find_oob_scaling_candidates(seller_id=seller_id),
    )

    if not guardrails.get("found", True):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Seller {seller_id} not found in AdAce database",
        )

    summary = {
        "total_campaigns": len(performance),
        "dnt_campaigns_count": sum(1 for c in performance if c.get("dnt", False)),
        "bleeding_search_terms_count": len(bleeding_terms),
        "oob_scaling_candidates_count": len(oob_candidates),
        "requires_hitl_approval": guardrails.get("requires_hitl_approval", True),
        "max_bid_cap": guardrails.get("max_bid_cap"),
        "max_budget_cap": guardrails.get("max_budget_cap"),
    }

    return SellerAnalysisResponse(
        seller_id=seller_id,
        guardrails=guardrails,
        campaign_performance=performance,
        bleeding_search_terms=bleeding_terms,
        oob_scaling_candidates=oob_candidates,
        summary=summary,
    )


@router.post(
    "/tools/execute",
    response_model=ExecuteToolResponse,
    summary="Directly Execute an MCP Tool",
    description="Dispatches a call to any of the 7 FastMCP tools with provided arguments.",
)
async def execute_mcp_tool(req: ExecuteToolRequest) -> ExecuteToolResponse:
    """Direct dispatcher for testing and manual inspection of individual MCP tools."""
    tool_map = {
        "get_seller_guardrails": get_seller_guardrails,
        "get_campaign_performance": get_campaign_performance,
        "find_bleeding_search_terms": find_bleeding_search_terms,
        "find_oob_scaling_candidates": find_oob_scaling_candidates,
        "add_negative_keyword": add_negative_keyword,
        "adjust_keyword_bid": adjust_keyword_bid,
        "scale_campaign_budget": scale_campaign_budget,
    }

    if req.tool_name not in tool_map:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown tool '{req.tool_name}'. Available: {list(tool_map.keys())}",
        )

    tool_fn = tool_map[req.tool_name]
    try:
        result = await tool_fn(**req.arguments)
        return ExecuteToolResponse(tool_name=req.tool_name, result=result)
    except TypeError as te:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid arguments for tool '{req.tool_name}': {str(te)}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution error in tool '{req.tool_name}': {str(exc)}",
        )
