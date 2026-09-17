"""
LogSentinel — Log Processor: Structured Logger
===============================================
Configures Python's standard logging to emit structured JSON log lines.
Identical pattern to log-ingestion-api/app/logger.py — each service
owns its own copy so it can be containerised independently.

Usage:
    from app.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Processing log", extra={"log_id": "abc", "service": "auth"})
"""

import logging
import logging.config
import os
from typing import Any

from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_SERVICE_NAME: str = os.getenv("SERVICE_NAME", "log-processor")
_ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
_LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

_QUIET_LOGGERS: list[str] = [
    "aiokafka",
    "kafka",
    "elastic_transport",
    "elasticsearch",
    "httpcore",
    "httpx",
    "asyncio",
    "urllib3",
]


# ---------------------------------------------------------------------------
# Custom JSON Formatter
# ---------------------------------------------------------------------------


class LogSentinelJsonFormatter(jsonlogger.JsonFormatter):
    """Structured JSON formatter — emits one JSON object per log record."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
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
        super().add_fields(log_record, record, message_dict)

        log_record["timestamp"] = self.formatTime(record, datefmt=None)
        log_record.pop("asctime", None)

        log_record["level"] = record.levelname
        log_record.pop("levelname", None)

        log_record["logger"] = record.name
        log_record.pop("name", None)

        log_record.pop("taskName", None)

        log_record["service"] = _SERVICE_NAME
        log_record["environment"] = _ENVIRONMENT

        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            record.exc_info = None
            record.exc_text = None

        if _ENVIRONMENT != "production":
            log_record["location"] = f"{record.pathname}:{record.lineno}"
            log_record["function"] = record.funcName

    def formatTime(
        self, record: logging.LogRecord, datefmt: str | None = None
    ) -> str:  # noqa: N802
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------


def _build_logging_config(level: str) -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": LogSentinelJsonFormatter},
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
            },
        },
        "root": {
            "level": level,
            "handlers": ["stdout"],
        },
        "loggers": {
            **{
                name: {
                    "level": "WARNING",
                    "handlers": ["stdout"],
                    "propagate": False,
                }
                for name in _QUIET_LOGGERS
            },
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


_logging_configured: bool = False


def setup_logging(level: str | None = None) -> None:
    """Configure logging with JSON formatter. Idempotent."""
    global _logging_configured
    if _logging_configured:
        return

    effective_level = (level or _LOG_LEVEL).upper()
    if not isinstance(getattr(logging, effective_level, None), int):
        effective_level = "INFO"

    logging.config.dictConfig(_build_logging_config(effective_level))
    _logging_configured = True

    logging.getLogger("app.logger").info(
        "Logging configured",
        extra={"log_level": effective_level, "service": _SERVICE_NAME},
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger, ensuring logging is configured first.

    Args:
        name: Logger name — typically __name__ from the calling module.

    Returns:
        A configured logging.Logger instance.
    """
    setup_logging()
    return logging.getLogger(name)


# Initialise on import
setup_logging()
