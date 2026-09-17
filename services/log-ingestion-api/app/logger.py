"""
LogSentinel — Log Ingestion API: Structured Logger
===================================================
Configures Python's standard logging to emit structured JSON log lines.

Every log record includes:
  - timestamp   : ISO 8601 UTC
  - level       : DEBUG / INFO / WARNING / ERROR / CRITICAL
  - service     : service name (from settings)
  - logger      : logger name (module path)
  - message     : the log message
  - environment : deployment environment
  - extra fields: any kwargs passed via the `extra={}` argument

Usage:
    from app.logger import get_logger
    logger = get_logger(__name__)
    logger.info("User login", extra={"user_id": "u-123", "ip": "10.0.0.1"})

Output (JSON, one line per record):
    {
      "timestamp": "2024-01-15T03:22:14.512Z",
      "level": "INFO",
      "service": "log-ingestion-api",
      "environment": "production",
      "logger": "app.main",
      "message": "User login",
      "user_id": "u-123",
      "ip": "10.0.0.1"
    }
"""

import logging
import logging.config
import os
from typing import Any

from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SERVICE_NAME: str = os.getenv("SERVICE_NAME", "log-ingestion-api")
_ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
_LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# Suppress noisy third-party loggers in production
_QUIET_LOGGERS: list[str] = [
    "aiokafka",
    "kafka",
    "uvicorn.access",
    "uvicorn.error",
    "httpcore",
    "httpx",
    "asyncio",
]


# ---------------------------------------------------------------------------
# Custom JSON Formatter
# ---------------------------------------------------------------------------


class LogSentinelJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON log formatter that:
      - Renames default fields to match our schema
      - Injects static service metadata into every log record
      - Promotes all `extra` kwargs to top-level JSON keys
      - Formats timestamp as ISO 8601 UTC with 'Z' suffix
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Define the fields to include in every log line, in order.
        # Additional fields from `extra={}` are appended automatically.
        fmt = (
            "%(timestamp)s %(level)s %(service)s %(environment)s %(logger)s %(message)s"
        )
        super().__init__(fmt, *args, **kwargs)

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        """
        Override to inject custom fields and rename standard ones.
        Called by pythonjsonlogger for every log record.
        """
        super().add_fields(log_record, record, message_dict)

        # --- Rename / normalise standard fields ---
        # 'asctime' → 'timestamp' in ISO 8601 format
        log_record["timestamp"] = self.formatTime(record, datefmt=None)
        log_record.pop("asctime", None)

        # 'levelname' → 'level'
        log_record["level"] = record.levelname
        log_record.pop("levelname", None)

        # 'name' → 'logger'
        log_record["logger"] = record.name
        log_record.pop("name", None)

        # Remove 'taskName' added by Python 3.12+ asyncio — it's noisy
        log_record.pop("taskName", None)

        # --- Inject static service metadata ---
        log_record["service"] = _SERVICE_NAME
        log_record["environment"] = _ENVIRONMENT

        # --- Inject exception info if present ---
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            # Clear exc_info so it isn't double-printed
            record.exc_info = None
            record.exc_text = None

        # --- Inject source location in non-production environments ---
        if _ENVIRONMENT != "production":
            log_record["location"] = f"{record.pathname}:{record.lineno}"
            log_record["function"] = record.funcName

    def formatTime(
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:  # noqa: N802
        """
        Format the log record timestamp as ISO 8601 UTC with milliseconds.
        Example: '2024-01-15T03:22:14.512Z'
        """
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------


def _build_logging_config(level: str) -> dict[str, Any]:
    """
    Build a logging.config.dictConfig-compatible configuration dict.

    - All loggers use the JSON formatter in production.
    - Console output is always to stdout (container-friendly).
    - Third-party loggers are quieted to WARNING level.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": LogSentinelJsonFormatter,
            },
            # Plain text formatter for local development readability
            "plain": {
                "format": ("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"),
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                # Use JSON formatter always — Fluentd/Logstash will parse it
                "formatter": "json",
            },
        },
        "root": {
            "level": level,
            "handlers": ["stdout"],
        },
        "loggers": {
            # Silence noisy third-party libraries
            **{
                name: {
                    "level": "WARNING",
                    "handlers": ["stdout"],
                    "propagate": False,
                }
                for name in _QUIET_LOGGERS
            },
            # Keep our own loggers at the configured level
            "app": {
                "level": level,
                "handlers": ["stdout"],
                "propagate": False,
            },
            "__main__": {
                "level": level,
                "handlers": ["stdout"],
                "propagate": False,
            },
        },
    }


# ---------------------------------------------------------------------------
# Module-level initialisation
# ---------------------------------------------------------------------------

_logging_configured: bool = False


def setup_logging(level: str | None = None) -> None:
    """
    Configure the Python logging system with the LogSentinel JSON formatter.

    This function is idempotent — calling it multiple times has no effect
    after the first call. This is important because FastAPI and Uvicorn
    may both attempt to configure logging on startup.

    Args:
        level: Override the log level. Defaults to LOG_LEVEL env var or INFO.
    """
    global _logging_configured

    if _logging_configured:
        return

    effective_level = (level or _LOG_LEVEL).upper()

    # Validate level
    numeric_level = getattr(logging, effective_level, None)
    if not isinstance(numeric_level, int):
        effective_level = "INFO"

    config = _build_logging_config(effective_level)
    logging.config.dictConfig(config)

    _logging_configured = True

    # Log the setup completion using the newly configured logger
    _init_logger = logging.getLogger("app.logger")
    _init_logger.info(
        "Logging configured",
        extra={
            "log_level": effective_level,
            "service": _SERVICE_NAME,
            "environment": _ENVIRONMENT,
        },
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger, ensuring logging is configured first.

    This is the primary entry point for obtaining loggers throughout
    the application. Always use this instead of logging.getLogger()
    directly to guarantee consistent formatting.

    Args:
        name: Logger name — typically __name__ from the calling module.

    Returns:
        A configured logging.Logger instance.

    Example:
        from app.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Service started", extra={"port": 8000})
    """
    setup_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Initialise logging when this module is first imported
# ---------------------------------------------------------------------------
setup_logging()
