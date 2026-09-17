"""
LogSentinel — Log Ingestion API: Configuration
===============================================
All configuration is loaded from environment variables using pydantic-settings.
This follows the 12-factor app methodology — no hardcoded config in source code.

Usage:
    from app.config import settings
    print(settings.KAFKA_BOOTSTRAP_SERVERS)
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    All fields have sensible defaults for local development.
    In production, override via environment or Kubernetes ConfigMap/Secret.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # ignore unknown env vars gracefully
    )

    # -----------------------------------------------------------------------
    # General
    # -----------------------------------------------------------------------
    SERVICE_NAME: str = Field(
        default="log-ingestion-api",
        description="Name of this service (used in logs and metrics labels)",
    )

    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development",
        description="Deployment environment",
    )

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Python logging level",
    )

    SECRET_KEY: str = Field(
        default="change-me-in-production-use-a-long-random-string",
        description="Application secret key (not used for auth in v1, reserved)",
    )

    # -----------------------------------------------------------------------
    # Server
    # -----------------------------------------------------------------------
    INGESTION_API_HOST: str = Field(
        default="0.0.0.0",
        description="Host to bind the Uvicorn server to",
    )

    INGESTION_API_PORT: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port to bind the Uvicorn server to",
    )

    INGESTION_API_WORKERS: int = Field(
        default=1,
        ge=1,
        le=32,
        description="Number of Uvicorn worker processes",
    )

    # -----------------------------------------------------------------------
    # Kafka
    # -----------------------------------------------------------------------
    KAFKA_BOOTSTRAP_SERVERS: str = Field(
        default="localhost:9092",
        description=(
            "Comma-separated list of Kafka broker addresses. "
            "Example: 'kafka:9092' or 'broker1:9092,broker2:9092'"
        ),
    )

    KAFKA_TOPIC_RAW_LOGS: str = Field(
        default="raw-logs",
        description="Kafka topic to publish raw log entries to",
    )

    KAFKA_PRODUCER_ACKS: str = Field(
        default="all",
        description=(
            "Kafka producer acknowledgement mode. "
            "'all' = strongest durability guarantee (wait for all replicas). "
            "'1'   = wait for leader only. "
            "'0'   = fire and forget."
        ),
    )

    KAFKA_PRODUCER_RETRIES: int = Field(
        default=5,
        ge=0,
        description="Number of times the Kafka producer retries a failed send",
    )

    KAFKA_PRODUCER_RETRY_BACKOFF_MS: int = Field(
        default=300,
        ge=0,
        description="Backoff time in milliseconds between Kafka producer retries",
    )

    KAFKA_PRODUCER_REQUEST_TIMEOUT_MS: int = Field(
        default=30_000,
        ge=1_000,
        description="Timeout in milliseconds for Kafka producer requests",
    )

    KAFKA_PRODUCER_MAX_BLOCK_MS: int = Field(
        default=10_000,
        ge=1_000,
        description=(
            "Maximum time in milliseconds to block when the Kafka send buffer is full. "
            "After this, a KafkaTimeoutError is raised."
        ),
    )

    KAFKA_PRODUCER_COMPRESSION_TYPE: Literal[
        "none", "gzip", "snappy", "lz4", "zstd"
    ] = Field(
        default="gzip",
        description="Compression algorithm for Kafka messages",
    )

    KAFKA_PRODUCER_LINGER_MS: int = Field(
        default=5,
        ge=0,
        description=(
            "Milliseconds to wait before sending a batch, to allow more messages to accumulate. "
            "Higher values increase throughput at the cost of latency."
        ),
    )

    KAFKA_PRODUCER_BATCH_SIZE: int = Field(
        default=16_384,
        ge=1,
        description="Maximum size in bytes of a Kafka producer batch",
    )

    # -----------------------------------------------------------------------
    # Ingestion limits
    # -----------------------------------------------------------------------
    INGESTION_MAX_BATCH_SIZE: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of log entries per batch ingest request",
    )

    INGESTION_MAX_MESSAGE_SIZE_BYTES: int = Field(
        default=10_240,  # 10 KB per individual message
        ge=512,
        description="Maximum size in bytes of a single log entry message body",
    )

    # -----------------------------------------------------------------------
    # Prometheus metrics
    # -----------------------------------------------------------------------
    METRICS_ENABLED: bool = Field(
        default=True,
        description="Enable or disable Prometheus metrics endpoint",
    )

    METRICS_PATH: str = Field(
        default="/metrics",
        description="URL path for the Prometheus metrics endpoint",
    )

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------

    @field_validator("KAFKA_BOOTSTRAP_SERVERS")
    @classmethod
    def validate_bootstrap_servers(cls, v: str) -> str:
        """
        Ensure KAFKA_BOOTSTRAP_SERVERS is a non-empty, comma-separated list
        of host:port pairs. Strips whitespace around each broker entry.
        """
        if not v or not v.strip():
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS must not be empty")

        brokers = [b.strip() for b in v.split(",") if b.strip()]
        if not brokers:
            raise ValueError(
                "KAFKA_BOOTSTRAP_SERVERS contains no valid broker addresses"
            )

        for broker in brokers:
            if ":" not in broker:
                raise ValueError(
                    f"Broker address '{broker}' is missing a port. "
                    "Expected format: 'host:port'"
                )

        # Return cleaned, whitespace-stripped version
        return ",".join(brokers)

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        """Accept log levels case-insensitively."""
        if isinstance(v, str):
            return v.upper()
        return v

    # -----------------------------------------------------------------------
    # Computed properties
    # -----------------------------------------------------------------------

    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        """
        Return KAFKA_BOOTSTRAP_SERVERS as a Python list.
        Useful for aiokafka which accepts a list of brokers.
        """
        return [b.strip() for b in self.KAFKA_BOOTSTRAP_SERVERS.split(",")]

    @property
    def is_production(self) -> bool:
        """True when running in the production environment."""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """True when running in the development environment."""
        return self.ENVIRONMENT == "development"

    def __repr__(self) -> str:
        return (
            f"Settings("
            f"service={self.SERVICE_NAME!r}, "
            f"environment={self.ENVIRONMENT!r}, "
            f"kafka={self.KAFKA_BOOTSTRAP_SERVERS!r}, "
            f"topic={self.KAFKA_TOPIC_RAW_LOGS!r}"
            f")"
        )


# ---------------------------------------------------------------------------
# Singleton accessor — cached so Settings() is only instantiated once
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.
    Use this in dependency injection contexts where you need a fresh
    instance per test (call get_settings.cache_clear() in test teardown).
    """
    return Settings()


# Module-level singleton for direct import convenience:
#   from app.config import settings
settings: Settings = get_settings()
