from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown routines."""
    # Startup phase
    yield
    # Shutdown phase: dispose connection pools
    from app.db.mysql import adace_async_engine
    from app.db.postgres import agent_async_engine

    await adace_async_engine.dispose()
    await agent_async_engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Enterprise Agentic AI Workflow Automation Platform built on top of the "
        "AdAce Amazon Ads MySQL schema. Features LangGraph agent orchestration, "
        "human-in-the-loop guardrails, and automated campaign optimization."
    ),
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API v1 router
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
async def root():
    """Root metadata endpoint."""
    return {
        "service": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "api_docs": f"{settings.API_V1_PREFIX}/docs",
        "health_check": f"{settings.API_V1_PREFIX}/health",
        "status": "operational",
    }
