"""
LogSentinel — Dashboard Backend: Logging Configuration
=======================================================
Structured JSON-capable logger with configurable level.
"""

import logging
import sys
from functools import lru_cache


class _JSONFormatter(logging.Formatter):
    """Simple structured formatter that emits key=value pairs."""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extra_parts = []
        skip = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in skip and not key.startswith("_"):
                extra_parts.append(f"{key}={value!r}")
        if extra_parts:
            return f"{base} | {' '.join(extra_parts)}"
        return base


@lru_cache(maxsize=None)
def get_logger(name: str) -> logging.Logger:
    """Return a cached, configured logger for *name*."""
    from app.config import settings  # lazy import to avoid circular deps

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
        handler.setFormatter(_JSONFormatter(fmt=fmt, datefmt="%Y-%m-%dT%H:%M:%SZ"))
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(getattr(logging, settings.LOG_LEVEL, logging.INFO))
    return logger
