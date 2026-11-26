from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application Settings and Configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Application
    APP_NAME: str = "AdAce Agentic Ops"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # AdAce MySQL Database (Sandbox / Production-Accurate Mirror)
    ADACE_MYSQL_URL: str = "mysql+aiomysql://adace_user:adace_pass@localhost:3307/adace_sandbox"

    # Agent PostgreSQL Database (LangGraph Checkpointers & Orchestrator State)
    AGENT_PG_URL: str = "postgresql+asyncpg://agent_user:agent_pass@localhost:5433/agent_state"

    # AI Configuration
    AI_PROVIDER: Literal["mock", "gemini", "anthropic", "openai"] = "mock"
    GEMINI_API_KEY: str = ""

    # Database Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800


settings = Settings()
