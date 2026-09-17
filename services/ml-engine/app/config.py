"""
LogSentinel — ML Engine: Configuration
=======================================
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
    SERVICE_NAME: str = Field(default="ml-engine")
    ENVIRONMENT: Literal["development", "staging", "production"] = Field(
        default="development"
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO"
    )

    # Server
    ML_ENGINE_HOST: str = Field(default="0.0.0.0")
    ML_ENGINE_PORT: int = Field(default=8001, ge=1, le=65535)
    ML_ENGINE_WORKERS: int = Field(default=1, ge=1, le=32)

    # Kafka — Consumer
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")
    KAFKA_TOPIC_PROCESSED_LOGS: str = Field(default="processed-logs")
    KAFKA_TOPIC_ANOMALY_ALERTS: str = Field(default="anomaly-alerts")
    KAFKA_CONSUMER_GROUP: str = Field(default="ml-engine-group")
    KAFKA_AUTO_OFFSET_RESET: str = Field(default="earliest")
    KAFKA_SESSION_TIMEOUT_MS: int = Field(default=30_000)
    KAFKA_HEARTBEAT_INTERVAL_MS: int = Field(default=3_000)
    KAFKA_MAX_POLL_RECORDS: int = Field(default=100)

    # Kafka — Producer
    KAFKA_PRODUCER_ACKS: str = Field(default="all")
    KAFKA_PRODUCER_COMPRESSION_TYPE: str = Field(default="gzip")
    KAFKA_PRODUCER_LINGER_MS: int = Field(default=5)

    # ML Model
    ML_MODEL_PATH: str = Field(
        default="/app/models/isolation_forest.joblib",
        description="Filesystem path to the trained IsolationForest joblib file",
    )
    ML_SCALER_PATH: str = Field(
        default="/app/models/scaler.joblib",
        description="Filesystem path to the fitted StandardScaler joblib file",
    )
    ML_CONTAMINATION: float = Field(
        default=0.05,
        ge=0.0,
        le=0.5,
        description="Expected fraction of anomalies (used at training time)",
    )
    ML_N_ESTIMATORS: int = Field(default=100, ge=1)
    ML_RANDOM_STATE: int = Field(default=42)
    ML_ANOMALY_SCORE_THRESHOLD: float = Field(
        default=0.0,
        description=(
            "Decision score threshold: samples with score < threshold are anomalies. "
            "IsolationForest decision_function returns negative values for anomalies."
        ),
    )

    # Inference
    ML_BATCH_MAX_SIZE: int = Field(
        default=500,
        ge=1,
        le=10_000,
        description="Maximum batch size for POST /predict/batch",
    )
    ML_INFERENCE_TIMEOUT_SECONDS: float = Field(
        default=5.0,
        description="Maximum time allowed for a single inference call before timeout",
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
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def kafka_bootstrap_servers_list(self) -> list[str]:
        return [b.strip() for b in self.KAFKA_BOOTSTRAP_SERVERS.split(",")]

    def __repr__(self) -> str:
        return (
            f"Settings("
            f"service={self.SERVICE_NAME!r}, "
            f"environment={self.ENVIRONMENT!r}, "
            f"model_path={self.ML_MODEL_PATH!r})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
