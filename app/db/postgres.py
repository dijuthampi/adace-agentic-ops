import time
from typing import AsyncGenerator, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class AgentBase(DeclarativeBase):
    """SQLAlchemy Declarative Base for Agent State PostgreSQL Tables."""
    pass


# Asynchronous engine for Agent State PostgreSQL
agent_async_engine = create_async_engine(
    settings.AGENT_PG_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

# Async sessionmaker factory
agent_session_factory = async_sessionmaker(
    bind=agent_async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_agent_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for yielding an Agent State PostgreSQL async database session."""
    async with agent_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_pg_health() -> Dict[str, Any]:
    """Execute a lightweight probe to verify Agent PostgreSQL connectivity and measure latency."""
    start_time = time.perf_counter()
    try:
        async with agent_async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "connected": True,
            "message": "Agent PostgreSQL connection healthy",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "connected": False,
            "message": f"Agent PostgreSQL connection error: {str(exc)}",
            "latency_ms": None,
        }
