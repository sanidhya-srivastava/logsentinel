"""
LogSentinel — Log Processor: Configuration
===========================================
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
    SERVICE_NAME: str = Field(default="log-processor")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    # Kafka — Consumer
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    KAFKA_TOPIC_RAW_LOGS: str = Field(default="raw-logs")
    KAFKA_TOPIC_PROCESSED_LOGS: str = Field(default="processed-logs")
    KAFKA_CONSUMER_GROUP: str = Field(default="log-processor-group")
    KAFKA_AUTO_OFFSET_RESET: str = Field(default="earliest")
    KAFKA_MAX_POLL_RECORDS: int = Field(default=500)
    KAFKA_SESSION_TIMEOUT_MS: int = Field(default=30_000)
    KAFKA_HEARTBEAT_INTERVAL_MS: int = Field(default=3_000)
    KAFKA_FETCH_MAX_WAIT_MS: int = Field(default=500)
    KAFKA_CONSUMER_ENABLE_AUTO_COMMIT: bool = Field(default=False)

    # Kafka — Producer
    KAFKA_PRODUCER_ACKS: str = Field(default="all")
    KAFKA_PRODUCER_COMPRESSION_TYPE: str = Field(default="gzip")
    KAFKA_PRODUCER_LINGER_MS: int = Field(default=5)

    # Elasticsearch
    ELASTICSEARCH_HOST: str = Field(default="localhost")
    ELASTICSEARCH_PORT: int = Field(default=9200)
    ELASTICSEARCH_SCHEME: str = Field(default="http")
    ELASTICSEARCH_USERNAME: str | None = Field(default=None)
    ELASTICSEARCH_PASSWORD: str | None = Field(default=None)
    ELASTICSEARCH_INDEX_LOGS: str = Field(default="logsentinel-logs")
    ELASTICSEARCH_TIMEOUT: int = Field(default=30)
    ELASTICSEARCH_MAX_RETRIES: int = Field(default=3)
    ELASTICSEARCH_BULK_CHUNK_SIZE: int = Field(default=500)

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)

    # Processing
    PROCESSING_BATCH_SIZE: int = Field(default=100)
    PROCESSING_FLUSH_INTERVAL_SECONDS: float = Field(default=5.0)

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
    def elasticsearch_url(self) -> str:
        return f"{self.ELASTICSEARCH_SCHEME}://{self.ELASTICSEARCH_HOST}:{self.ELASTICSEARCH_PORT}"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
