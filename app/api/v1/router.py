from fastapi import APIRouter

from app.api.v1.endpoints import health, sellers

api_router = APIRouter()

# Register endpoint routers
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(sellers.router, prefix="/sellers", tags=["Sellers"])
