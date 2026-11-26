from fastapi import APIRouter

from app.api.v1.endpoints import health, sellers, mcp_tools, workflows, audit

api_router = APIRouter()

# Register endpoint routers
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(sellers.router, prefix="/sellers", tags=["Sellers"])
api_router.include_router(mcp_tools.router, prefix="/mcp", tags=["MCP Tools"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["Workflows"])
api_router.include_router(audit.router, prefix="/audit", tags=["Audit & History"])

