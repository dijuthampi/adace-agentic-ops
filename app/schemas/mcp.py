from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MCPToolParameter(BaseModel):
    """Specification of an MCP tool input parameter."""

    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Parameter data type (int, str, float, bool)")
    description: str = Field(..., description="Parameter documentation")
    required: bool = Field(True, description="Whether parameter is required")
    default: Optional[Any] = Field(None, description="Default value if optional")


class MCPToolInfo(BaseModel):
    """Metadata describing a registered MCPServer tool and its risk tier."""

    name: str = Field(..., description="Tool name exposed to agents")
    description: str = Field(..., description="Detailed tool documentation and guardrail rules")
    tier: str = Field(..., description="Risk tier: Read-Only, Tier 1 (Autonomous), Tier 2 (Bounded), Tier 3 (HITL)")
    parameters: List[MCPToolParameter] = Field(default_factory=list, description="Tool parameters")


class MCPToolsListResponse(BaseModel):
    """List of all registered MCPServer tools."""

    server_name: str = Field(..., description="Name of the MCP server instance")
    total_tools: int = Field(..., description="Count of registered tools")
    tools: List[MCPToolInfo] = Field(..., description="Registered tool definitions")


class SellerAnalysisResponse(BaseModel):
    """Aggregated result of running all AdAce analytics tools for a seller."""

    seller_id: int
    guardrails: Dict[str, Any]
    campaign_performance: List[Dict[str, Any]]
    bleeding_search_terms: List[Dict[str, Any]]
    oob_scaling_candidates: List[Dict[str, Any]]
    summary: Dict[str, Any]


class ExecuteToolRequest(BaseModel):
    """Request payload to directly execute an MCP tool."""

    tool_name: str = Field(..., description="Name of the MCP tool to execute")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Arguments to pass to the tool function")


class ExecuteToolResponse(BaseModel):
    """Response envelope for direct MCP tool execution."""

    tool_name: str
    result: Any
