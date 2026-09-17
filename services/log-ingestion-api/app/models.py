"""
LogSentinel — Log Ingestion API: Pydantic Models
=================================================
Data validation models for all request and response payloads
in the Log Ingestion API.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LogLevel(str, Enum):
    """Supported log severity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"  # alias — normalised to WARN downstream
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    FATAL = "FATAL"  # alias — normalised to CRITICAL downstream


# ---------------------------------------------------------------------------
# Core log entry model
# ---------------------------------------------------------------------------


class LogEntry(BaseModel):
    """
    A single structured log entry submitted to the ingestion API.

    Required fields: service, level, message
    Optional fields: host, response_time_ms, error_code, timestamp, metadata
    """

    service: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Name of the originating service (e.g. 'auth-service')",
        examples=["auth-service", "payment-gateway", "api-gateway"],
    )

    level: LogLevel = Field(
        ...,
        description="Log severity level",
        examples=["INFO", "ERROR", "WARN"],
    )

    message: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The log message text",
        examples=["Database connection timeout after 5000ms"],
    )

    host: str | None = Field(
        default=None,
        max_length=253,
        description="Hostname or pod name that emitted the log",
        examples=["pod-abc123", "worker-node-01"],
    )

    response_time_ms: float | None = Field(
        default=None,
        ge=0.0,
        le=300_000.0,  # cap at 5 minutes — anything higher is likely bad data
        description="Response or operation time in milliseconds",
        examples=[145.3, 4500.0],
    )

    error_code: int | None = Field(
        default=None,
        ge=0,
        le=99999,
        description="HTTP status code or application-specific error code",
        examples=[200, 404, 500, 503],
    )

    timestamp: datetime | None = Field(
        default=None,
        description=(
            "ISO 8601 UTC timestamp when the log was emitted by the source. "
            "If omitted, the ingestion server timestamp is used."
        ),
        examples=["2024-01-15T03:22:14.512Z"],
    )

    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Arbitrary key-value metadata (trace IDs, user IDs, etc.)",
        examples=[{"trace_id": "abc123", "user_id": "u-456"}],
    )

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------

    @field_validator("service")
    @classmethod
    def service_must_be_slug(cls, v: str) -> str:
        """
        Normalise the service name: strip whitespace, lowercase.
        Rejects service names that are entirely whitespace.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("service name must not be blank")
        return stripped.lower()

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message must not be blank or whitespace only")
        return stripped

    @field_validator("level", mode="before")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        """
        Accept level values case-insensitively.
        e.g. 'error', 'ERROR', 'Error' are all valid.
        """
        if isinstance(v, str):
            return v.upper()
        return v

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v):
        """
        Accept timestamps as ISO 8601 strings or datetime objects.
        Ensures timezone-aware datetimes; naive datetimes are assumed UTC.
        """
        if v is None:
            return None
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v
        if isinstance(v, str):
            try:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError as exc:
                raise ValueError(
                    f"Invalid timestamp format '{v}'. "
                    "Expected ISO 8601, e.g. '2024-01-15T03:22:14.512Z'"
                ) from exc
        raise ValueError(f"Unsupported timestamp type: {type(v)}")

    @model_validator(mode="after")
    def set_default_timestamp(self) -> "LogEntry":
        """
        If no timestamp was provided by the client, default to now (UTC).
        This runs after all field validators.
        """
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "service": "auth-service",
                "level": "ERROR",
                "message": "Database connection timeout after 5000ms",
                "host": "pod-abc123",
                "response_time_ms": 5000.0,
                "error_code": 503,
                "timestamp": "2024-01-15T03:22:14.512Z",
                "metadata": {
                    "trace_id": "4bf92f3577b34da6",
                    "user_id": "u-001",
                },
            }
        }
    }


# ---------------------------------------------------------------------------
# Batch ingestion request
# ---------------------------------------------------------------------------


class BatchIngestRequest(BaseModel):
    """
    Request body for POST /ingest/batch.
    Accepts between 1 and 100 log entries in a single request.
    """

    logs: list[LogEntry] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="List of log entries to ingest (1–100 per request)",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "logs": [
                    {
                        "service": "auth-service",
                        "level": "INFO",
                        "message": "User login successful",
                        "response_time_ms": 42.1,
                        "error_code": 200,
                    },
                    {
                        "service": "payment-gateway",
                        "level": "ERROR",
                        "message": "Payment processing failed: timeout",
                        "response_time_ms": 30000.0,
                        "error_code": 504,
                    },
                ]
            }
        }
    }


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class IngestResponse(BaseModel):
    """
    Response body for POST /ingest (single entry).
    """

    log_id: str = Field(
        ...,
        description="Server-assigned unique identifier (UUID v4) for the log entry",
    )

    status: str = Field(
        default="accepted",
        description="Processing status of the submitted log entry",
    )

    message: str = Field(
        ...,
        description="Human-readable status message",
    )

    ingested_at: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of when the log was accepted by the server",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "log_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                "status": "accepted",
                "message": "Log entry accepted and queued for processing.",
                "ingested_at": "2024-01-15T03:22:14.600Z",
            }
        }
    }


class BatchIngestResponse(BaseModel):
    """
    Response body for POST /ingest/batch.
    """

    accepted: int = Field(
        ...,
        ge=0,
        description="Number of log entries successfully published to Kafka",
    )

    rejected: int = Field(
        ...,
        ge=0,
        description="Number of log entries that failed to publish",
    )

    log_ids: list[str] = Field(
        default_factory=list,
        description="List of server-assigned log IDs for accepted entries (in submission order)",
    )

    rejected_details: list[dict[str, Any]] | None = Field(
        default=None,
        description="Details about rejected entries (index + reason), if any",
    )

    message: str = Field(
        ...,
        description="Human-readable summary of the batch operation",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "accepted": 2,
                "rejected": 0,
                "log_ids": [
                    "f47ac10b-58cc-4372-a567-0e02b2c3d479",
                    "3d2e1f0a-89bb-4d21-b8c3-111222333444",
                ],
                "rejected_details": None,
                "message": "Batch processed: 2 accepted, 0 rejected.",
            }
        }
    }


# ---------------------------------------------------------------------------
# Health check response
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response model for GET /health."""

    status: str = Field(
        ...,
        description="Overall service status: 'healthy' or 'degraded'",
    )

    service: str = Field(
        ...,
        description="Name of this service",
    )

    version: str = Field(
        ...,
        description="Service version string",
    )

    timestamp: str = Field(
        ...,
        description="Current UTC timestamp",
    )

    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Per-dependency health check results",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "service": "log-ingestion-api",
                "version": "1.0.0",
                "timestamp": "2024-01-15T03:22:14.600Z",
                "checks": {
                    "kafka": "connected",
                },
            }
        }
    }


# ---------------------------------------------------------------------------
# Kafka message envelope
# ---------------------------------------------------------------------------


class KafkaLogMessage(BaseModel):
    """
    Internal model representing a log entry as published to Kafka.
    Extends LogEntry with server-assigned fields added at ingestion time.
    This is NOT exposed via the API — used for internal serialisation only.
    """

    log_id: str = Field(..., description="Server-assigned UUID v4")
    ingested_at: str = Field(..., description="ISO 8601 UTC ingestion timestamp")

    # All original LogEntry fields
    service: str
    level: str  # stored as normalised string, not enum
    message: str
    host: str | None = None
    response_time_ms: float | None = None
    error_code: int | None = None
    timestamp: str | None = None  # serialised as ISO 8601 string
    metadata: dict[str, Any] | None = None
