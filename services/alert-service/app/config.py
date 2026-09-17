"""
LogSentinel — Alert Service: Configuration
==========================================
All configuration loaded from environment variables via pydantic-settings.
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

    # General
    SERVICE_NAME: str = Field(default="alert-service")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    KAFKA_TOPIC_ANOMALY_ALERTS: str = Field(default="anomaly-alerts")
    KAFKA_CONSUMER_GROUP: str = Field(default="alert-service-group")
    KAFKA_AUTO_OFFSET_RESET: str = Field(default="earliest")
    KAFKA_SESSION_TIMEOUT_MS: int = Field(default=30_000)
    KAFKA_MAX_POLL_RECORDS: int = Field(default=50)

    # Redis (deduplication)
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    ALERT_DEDUP_TTL_SECONDS: int = Field(
        default=3600,
        ge=60,
        description="TTL in seconds for alert deduplication keys in Redis",
    )

    # PostgreSQL
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://logsentinel:logsentinel_dev@localhost:5432/logsentinel"
    )

    # Alert behaviour
    ALERT_COOLDOWN_SECONDS: int = Field(default=300, ge=0)
    ALERT_MAX_RETRIES: int = Field(default=3, ge=0, le=10)
    ALERT_RETRY_BACKOFF_SECONDS: float = Field(default=1.0, ge=0.0)

    # Slack
    SLACK_WEBHOOK_URL: str = Field(
        default="https://hooks.slack.com/services/PLACEHOLDER"
    )
    SLACK_CHANNEL: str = Field(default="#logsentinel-alerts")
    SLACK_USERNAME: str = Field(default="LogSentinel Bot")
    SLACK_ICON_EMOJI: str = Field(default=":shield:")
    SLACK_ENABLED: bool = Field(default=False)

    # Email (SMTP)
    SMTP_HOST: str = Field(default="smtp.gmail.com")
    SMTP_PORT: int = Field(default=587, ge=1, le=65535)
    SMTP_USERNAME: str | None = Field(default=None)
    SMTP_PASSWORD: str | None = Field(default=None)
    SMTP_FROM_EMAIL: str = Field(default="logsentinel@example.com")
    SMTP_FROM_NAME: str = Field(default="LogSentinel")
    SMTP_TO_EMAILS: str = Field(
        default="ops@example.com",
        description="Comma-separated list of recipient email addresses",
    )
    SMTP_USE_TLS: bool = Field(default=True)
    SMTP_ENABLED: bool = Field(default=False)

    # Prometheus metrics
    METRICS_PORT: int = Field(
        default=9103,
        ge=1,
        le=65535,
        description="Port for the Prometheus metrics HTTP server",
    )

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else v

    @field_validator("KAFKA_BOOTSTRAP_SERVERS")
    @classmethod
    def validate_bootstrap_servers(cls, v: str) -> str:
        brokers = [b.strip() for b in v.split(",") if b.strip()]
        if not brokers:
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS must contain at least one broker")
        return ",".join(brokers)

    @property
    def smtp_to_emails_list(self) -> list[str]:
        """Return SMTP_TO_EMAILS as a list, splitting on commas."""
        return [e.strip() for e in self.SMTP_TO_EMAILS.split(",") if e.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
