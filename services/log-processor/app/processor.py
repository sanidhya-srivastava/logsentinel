"""
LogSentinel — Log Processor: Core Processing Logic
====================================================
Responsible for transforming a raw log dict (as consumed from Kafka)
into a fully structured, enriched document ready for:
  - Elasticsearch indexing
  - Kafka 'processed-logs' publishing
  - ML feature extraction

Processing steps:
  1. Validate required fields (log_id, service, level, message)
  2. Normalise log level to canonical uppercase string
  3. Normalise timestamp to ISO 8601 UTC string
  4. Sanitise service name (strip, lowercase)
  5. Extract ML feature vector via FeatureExtractor
  6. Build final ProcessedLog document

Usage:
    processor = LogProcessor(feature_extractor=extractor)
    processed_doc = await processor.process(raw_log_dict)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.feature_extractor import FeatureExtractor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Log level normalisation map
# Maps any variant the client might send → our canonical value
# ---------------------------------------------------------------------------
_LEVEL_NORMALISE: dict[str, str] = {
    "DEBUG": "DEBUG",
    "TRACE": "DEBUG",  # treat TRACE as DEBUG
    "INFO": "INFO",
    "INFORMATION": "INFO",
    "WARN": "WARN",
    "WARNING": "WARN",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "CRITICAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "FATAL": "CRITICAL",
    "EMERGENCY": "CRITICAL",
    "ALERT": "CRITICAL",
}

_DEFAULT_LEVEL = "INFO"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MalformedLogError(ValueError):
    """Raised when a raw log dict is missing required fields or is unparseable."""


# ---------------------------------------------------------------------------
# ProcessedLog document builder
# ---------------------------------------------------------------------------


class LogProcessor:
    """
    Transforms a raw Kafka log dict into a fully enriched ProcessedLog document.

    The processor is stateless with respect to individual log entries — all
    stateful operations (rolling counters, service ID encoding) are delegated
    to the FeatureExtractor, which owns the Redis connection.

    Args:
        feature_extractor: An initialised FeatureExtractor instance.
    """

    def __init__(self, feature_extractor: FeatureExtractor) -> None:
        self._extractor = feature_extractor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(self, raw: dict[str, Any]) -> dict[str, Any]:
        """
        Process a single raw log dict from Kafka.

        Args:
            raw: Dict decoded from the Kafka message value (JSON).

        Returns:
            A ProcessedLog dict containing all original fields plus:
              - features          : dict of 6 ML feature values
              - level             : normalised canonical level string
              - timestamp         : ISO 8601 UTC string
              - processed_at      : ISO 8601 UTC string (server-side)
              - log_id            : preserved from raw, or generated if missing

        Raises:
            MalformedLogError: If the dict is missing critical required fields
                               that cannot be defaulted.
        """
        if not isinstance(raw, dict):
            raise MalformedLogError(
                f"Expected a dict, got {type(raw).__name__}: {str(raw)[:120]}"
            )

        # ------------------------------------------------------------------
        # Step 1: Ensure a log_id exists
        # ------------------------------------------------------------------
        log_id = raw.get("log_id")
        if not log_id or not str(log_id).strip():
            log_id = str(uuid.uuid4())
            logger.warning(
                "Raw log missing log_id — generated new UUID",
                extra={"generated_log_id": log_id},
            )
        log_id = str(log_id).strip()

        # ------------------------------------------------------------------
        # Step 2: Validate and sanitise 'service'
        # ------------------------------------------------------------------
        service_raw = raw.get("service")
        if not service_raw or not str(service_raw).strip():
            raise MalformedLogError(
                f"Log {log_id!r} is missing required field 'service'"
            )
        service = str(service_raw).strip().lower()

        # ------------------------------------------------------------------
        # Step 3: Normalise 'level'
        # ------------------------------------------------------------------
        level_raw = raw.get("level", _DEFAULT_LEVEL)
        level = _normalise_level(level_raw)

        # ------------------------------------------------------------------
        # Step 4: Validate 'message'
        # ------------------------------------------------------------------
        message_raw = raw.get("message")
        if message_raw is None:
            raise MalformedLogError(
                f"Log {log_id!r} is missing required field 'message'"
            )
        message = str(message_raw).strip()
        if not message:
            raise MalformedLogError(f"Log {log_id!r} has an empty 'message' field")

        # ------------------------------------------------------------------
        # Step 5: Normalise 'timestamp'
        # ------------------------------------------------------------------
        timestamp_raw = raw.get("timestamp")
        timestamp_iso = _normalise_timestamp(timestamp_raw)

        # ------------------------------------------------------------------
        # Step 6: Optional numeric fields — safe cast with defaults
        # ------------------------------------------------------------------
        response_time_ms = _safe_float(raw.get("response_time_ms"), default=0.0)
        if response_time_ms < 0:
            response_time_ms = 0.0

        error_code = _safe_int(raw.get("error_code"), default=None)
        if error_code is not None and error_code < 0:
            error_code = None

        # ------------------------------------------------------------------
        # Step 7: Optional string fields
        # ------------------------------------------------------------------
        host = _safe_str(raw.get("host"), max_len=253)
        metadata = (
            raw.get("metadata") if isinstance(raw.get("metadata"), dict) else None
        )
        ingested_at = _safe_str(raw.get("ingested_at"))

        # ------------------------------------------------------------------
        # Step 8: Extract ML features
        # ------------------------------------------------------------------
        # Build an intermediate dict representing the normalised log so the
        # feature extractor receives consistent types.
        normalised_for_features: dict[str, Any] = {
            "service": service,
            "level": level,
            "timestamp": timestamp_iso,
            "response_time_ms": response_time_ms,
            "error_code": error_code,
        }

        try:
            features = await self._extractor.extract(normalised_for_features)
        except Exception as exc:
            # Feature extraction failure is non-fatal — use zero-vector
            logger.error(
                "Feature extraction failed — using zero feature vector",
                extra={
                    "log_id": log_id,
                    "error": str(exc),
                },
                exc_info=True,
            )
            features = _zero_feature_vector()

        # ------------------------------------------------------------------
        # Step 9: Build the final ProcessedLog document
        # ------------------------------------------------------------------
        processed_at = datetime.now(timezone.utc).isoformat()

        processed: dict[str, Any] = {
            # Identity
            "log_id": log_id,
            "ingested_at": ingested_at,
            "processed_at": processed_at,
            # Core log fields (normalised)
            "service": service,
            "level": level,
            "message": message,
            "host": host,
            "timestamp": timestamp_iso,
            # Numeric fields
            "response_time_ms": response_time_ms,
            "error_code": error_code,
            # Passthrough metadata
            "metadata": metadata,
            # ML feature vector
            "features": features,
            # Elasticsearch routing helper — index per day
            "@timestamp": timestamp_iso,
        }

        logger.debug(
            "Log entry processed",
            extra={
                "log_id": log_id,
                "service": service,
                "level": level,
                "features": features,
            },
        )

        return processed


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _normalise_level(raw: Any) -> str:
    """
    Normalise a raw log level value to one of:
    DEBUG, INFO, WARN, ERROR, CRITICAL.

    - Accepts strings case-insensitively
    - Unknown values default to INFO and log a warning
    """
    if raw is None:
        return _DEFAULT_LEVEL

    candidate = str(raw).strip().upper()
    normalised = _LEVEL_NORMALISE.get(candidate)

    if normalised is None:
        logger.warning(
            "Unknown log level — defaulting to INFO",
            extra={"raw_level": candidate},
        )
        return _DEFAULT_LEVEL

    return normalised


def _normalise_timestamp(raw: Any) -> str:
    """
    Normalise a timestamp to an ISO 8601 UTC string.

    Accepts:
      - datetime objects (naive assumed UTC, aware preserved)
      - ISO 8601 strings (with or without timezone)
      - Unix epoch int/float (seconds since epoch)
      - None → current UTC time

    Always returns a timezone-aware ISO 8601 string ending in '+00:00'.
    """
    if raw is None:
        return datetime.now(timezone.utc).isoformat()

    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            raw = raw.replace(tzinfo=timezone.utc)
        return raw.isoformat()

    if isinstance(raw, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(raw), tz=timezone.utc)
            return dt.isoformat()
        except (OSError, OverflowError, ValueError):
            return datetime.now(timezone.utc).isoformat()

    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return datetime.now(timezone.utc).isoformat()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass

        # Try common non-ISO formats as a last resort
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%b/%Y:%H:%M:%S %z",  # Common Log Format
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue

        logger.warning(
            "Unrecognised timestamp format — using current UTC time",
            extra={"raw_timestamp": s[:80]},
        )
        return datetime.now(timezone.utc).isoformat()

    # Unsupported type
    logger.warning(
        "Unsupported timestamp type — using current UTC time",
        extra={"type": type(raw).__name__},
    )
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, *, default: float = 0.0) -> float:
    """Cast value to float, returning default on failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int | None = None) -> int | None:
    """Cast value to int, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, *, max_len: int = 1024) -> str | None:
    """Cast value to a trimmed string, returning None if blank or None."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]


def _zero_feature_vector() -> dict[str, Any]:
    """Return a zero-filled feature vector used as a safe fallback."""
    return {
        "hour_of_day": 0,
        "response_time_ms": 0.0,
        "error_code": 0,
        "log_level_encoded": 1,  # INFO
        "request_count_last_60s": 0,
        "service_id_encoded": 0,
    }
