from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class DatabaseStatus(BaseModel):
    """Health status and latency metrics for an individual database engine."""

    connected: bool = Field(..., description="Whether the connection test succeeded")
    message: str = Field(..., description="Descriptive status or error message")
    latency_ms: Optional[float] = Field(None, description="Round-trip query latency in milliseconds")


class HealthResponse(BaseModel):
    """Dual-database overall health check response."""

    status: str = Field(..., description="Overall platform status ('healthy', 'degraded', or 'unhealthy')")
    mysql: DatabaseStatus = Field(..., description="AdAce MySQL sandbox connectivity")
    postgres: DatabaseStatus = Field(..., description="Agent PostgreSQL state store connectivity")
    timestamp: datetime = Field(..., description="UTC timestamp of the health inspection")
