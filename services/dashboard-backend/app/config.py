"""
LogSentinel — Dashboard Backend: Configuration
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    SERVICE_NAME: str = Field(default="dashboard-backend")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    DASHBOARD_API_HOST: str = Field(default="0.0.0.0")
    DASHBOARD_API_PORT: int = Field(default=8002, ge=1, le=65535)
    DASHBOARD_API_WORKERS: int = Field(default=2, ge=1, le=32)
    DASHBOARD_DEFAULT_PAGE_SIZE: int = Field(default=20)
    DASHBOARD_MAX_PAGE_SIZE: int = Field(default=100)
    DASHBOARD_STATS_CACHE_TTL: int = Field(
        default=10, description="Redis cache TTL in seconds for /stats"
    )

    ELASTICSEARCH_HOST: str = Field(default="localhost")
    ELASTICSEARCH_PORT: int = Field(default=9200)
    ELASTICSEARCH_SCHEME: str = Field(default="http")
    ELASTICSEARCH_USERNAME: str | None = Field(default=None)
    ELASTICSEARCH_PASSWORD: str | None = Field(default=None)
    ELASTICSEARCH_INDEX_LOGS: str = Field(default="logsentinel-logs")
    ELASTICSEARCH_TIMEOUT: int = Field(default=30)

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://logsentinel:logsentinel_dev@localhost:5432/logsentinel"
    )

    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
