"""
LogSentinel — Dashboard Backend: Redis Cache + DB + ES Clients + Metrics + Logger
"""

import json
import logging
import logging.config
import os
from datetime import datetime, timezone
from typing import Any, Optional

from prometheus_client import Counter, Histogram
from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
_SERVICE_NAME = os.getenv("SERVICE_NAME", "dashboard-backend")
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


class _JsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = (
            datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S."
            )
            + f"{record.created % 1 * 1000:.0f}Z"
        )
        log_record["level"] = record.levelname
        log_record["service"] = _SERVICE_NAME
        log_record["environment"] = _ENVIRONMENT
        log_record["logger"] = record.name
        log_record.pop("levelname", None)
        log_record.pop("name", None)
        log_record.pop("taskName", None)
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            record.exc_info = None


_logging_configured = False


def _setup_logging():
    global _logging_configured
    if _logging_configured:
        return
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": _JsonFormatter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                }
            },
            "root": {"level": _LOG_LEVEL, "handlers": ["stdout"]},
            "loggers": {
                "elasticsearch": {
                    "level": "WARNING",
                    "handlers": ["stdout"],
                    "propagate": False,
                },
                "elastic_transport": {
                    "level": "WARNING",
                    "handlers": ["stdout"],
                    "propagate": False,
                },
                "aiokafka": {
                    "level": "WARNING",
                    "handlers": ["stdout"],
                    "propagate": False,
                },
                "asyncio": {
                    "level": "WARNING",
                    "handlers": ["stdout"],
                    "propagate": False,
                },
            },
        }
    )
    _logging_configured = True


_setup_logging()


def get_logger(name: str) -> logging.Logger:
    _setup_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "dashboard_http_requests_total",
    "Total HTTP requests handled by the Dashboard Backend",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "dashboard_http_request_duration_seconds",
    "HTTP request latency for the Dashboard Backend",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

ES_QUERY_DURATION = Histogram(
    "dashboard_es_query_duration_seconds",
    "Elasticsearch query duration from Dashboard Backend",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

DB_QUERY_DURATION = Histogram(
    "dashboard_db_query_duration_seconds",
    "PostgreSQL query duration from Dashboard Backend",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

CACHE_HITS = Counter(
    "dashboard_cache_hits_total",
    "Total Redis cache hits for /stats endpoint",
)

CACHE_MISSES = Counter(
    "dashboard_cache_misses_total",
    "Total Redis cache misses for /stats endpoint",
)

# ---------------------------------------------------------------------------
# Redis Cache
# ---------------------------------------------------------------------------

_log = get_logger(__name__)


class RedisCache:
    """Simple async Redis cache wrapper for dashboard stats."""

    def __init__(
        self, redis_url: str = "redis://localhost:6379/0", default_ttl: int = 10
    ):
        self._redis_url = redis_url
        self._default_ttl = default_ttl
        self._redis: Any = None
        self._started = False

    @property
    def is_connected(self) -> bool:
        return self._started and self._redis is not None

    async def start(self) -> None:
        if self._started:
            return
        try:
            import redis.asyncio as aioredis

            self._redis = await aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self._redis.ping()
            self._started = True
            _log.info("Redis cache connected", extra={"redis_url": self._redis_url})
        except Exception as exc:
            _log.warning(
                "Redis cache unavailable — stats will not be cached",
                extra={"error": str(exc)},
            )
            self._redis = None

    async def stop(self) -> None:
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
            self._started = False

    async def get(self, key: str) -> Optional[dict]:
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(key)
            if raw:
                CACHE_HITS.inc()
                return json.loads(raw)
            CACHE_MISSES.inc()
            return None
        except Exception as exc:
            _log.warning("Redis GET error", extra={"key": key, "error": str(exc)})
            return None

    async def set(self, key: str, value: dict, ttl: Optional[int] = None) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(
                key, json.dumps(value, default=str), ex=ttl or self._default_ttl
            )
        except Exception as exc:
            _log.warning("Redis SET error", extra={"key": key, "error": str(exc)})


# ---------------------------------------------------------------------------
# Elasticsearch Client (Dashboard read-only)
# ---------------------------------------------------------------------------


class DashboardESClient:
    """Lightweight async Elasticsearch client for dashboard read queries."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        scheme: str = "http",
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 30,
        index_prefix: str = "logsentinel-logs",
    ):
        self._host = host
        self._port = port
        self._scheme = scheme
        self._username = username
        self._password = password
        self._timeout = timeout
        self._index_prefix = index_prefix
        self._client: Any = None
        self._started = False

    @property
    def is_connected(self) -> bool:
        return self._started and self._client is not None

    async def start(self) -> None:
        if self._started:
            return
        try:
            from elasticsearch import AsyncElasticsearch

            http_auth = (self._username, self._password) if self._username else None
            self._client = AsyncElasticsearch(
                hosts=[
                    {"host": self._host, "port": self._port, "scheme": self._scheme}
                ],
                http_auth=http_auth,
                request_timeout=self._timeout,
                max_retries=3,
                retry_on_timeout=True,
                sniff_on_start=False,
                sniff_on_node_failure=False,
            )
            await self._client.cluster.health(timeout="10s")
            self._started = True
            _log.info(
                "Elasticsearch connected",
                extra={"host": self._host, "port": self._port},
            )
        except Exception as exc:
            _log.error("Elasticsearch connection failed", extra={"error": str(exc)})

    async def stop(self) -> None:
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._started = False

    async def search_logs(
        self,
        query: Optional[dict] = None,
        page: int = 1,
        size: int = 20,
        sort_field: str = "@timestamp",
        sort_order: str = "desc",
    ) -> dict:
        if not self._client:
            return {"total": 0, "hits": [], "page": page, "size": size}
        import time

        start = time.perf_counter()
        try:
            response = await self._client.search(
                index=f"{self._index_prefix}-*",
                body={
                    "query": query or {"match_all": {}},
                    "sort": [{sort_field: {"order": sort_order}}],
                    "from": (page - 1) * size,
                    "size": size,
                    "track_total_hits": True,
                },
            )
            ES_QUERY_DURATION.observe(time.perf_counter() - start)
            total = response["hits"]["total"]["value"]
            hits = [h["_source"] for h in response["hits"]["hits"]]
            return {"total": total, "hits": hits, "page": page, "size": size}
        except Exception as exc:
            _log.error("Elasticsearch search failed", extra={"error": str(exc)})
            return {"total": 0, "hits": [], "page": page, "size": size}

    async def count_logs(
        self, query: Optional[dict] = None, index_pattern: Optional[str] = None
    ) -> int:
        if not self._client:
            return 0
        try:
            response = await self._client.count(
                index=index_pattern or f"{self._index_prefix}-*",
                body={"query": query or {"match_all": {}}},
            )
            return int(response.get("count", 0))
        except Exception as exc:
            _log.error("Elasticsearch count failed", extra={"error": str(exc)})
            return 0


# ---------------------------------------------------------------------------
# PostgreSQL Client (Dashboard read + alert queries)
# ---------------------------------------------------------------------------


class DashboardDB:
    """Async PostgreSQL client for alert queries in the dashboard backend."""

    def __init__(
        self, database_url: str, min_pool_size: int = 1, max_pool_size: int = 5
    ):
        self._database_url = database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        self._min = min_pool_size
        self._max = max_pool_size
        self._pool: Any = None
        self._started = False

    @property
    def is_connected(self) -> bool:
        return self._started and self._pool is not None

    async def start(self) -> None:
        if self._started:
            return
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                dsn=self._database_url,
                min_size=self._min,
                max_size=self._max,
                command_timeout=30.0,
            )
            self._started = True
            _log.info("PostgreSQL connected (dashboard)")
        except Exception as exc:
            _log.error(
                "PostgreSQL connection failed (dashboard)", extra={"error": str(exc)}
            )

    async def stop(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None
            self._started = False

    async def get_recent_alerts(self, limit: int = 50, offset: int = 0) -> list[dict]:
        if not self._pool:
            return []
        import time

        start = time.perf_counter()
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id::text, alert_id::text, log_id::text, service, level,
                           message, anomaly_score, host, response_time_ms, error_code,
                           detected_at, slack_sent, email_sent, deduplicated,
                           notification_channels, features, created_at
                    FROM alerts ORDER BY detected_at DESC LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                )
                DB_QUERY_DURATION.observe(time.perf_counter() - start)
                return [dict(r) for r in rows]
        except Exception as exc:
            _log.error("DB get_recent_alerts failed", extra={"error": str(exc)})
            return []

    async def get_alerts_by_service(
        self, service: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id::text, alert_id::text, service, level, message,
                           anomaly_score, detected_at, deduplicated, created_at
                    FROM alerts WHERE service = $1 ORDER BY detected_at DESC LIMIT $2 OFFSET $3
                    """,
                    service,
                    limit,
                    offset,
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            _log.error("DB get_alerts_by_service failed", extra={"error": str(exc)})
            return []

    async def get_alerts_by_time_range(
        self, start: datetime, end: datetime, limit: int = 100, offset: int = 0
    ) -> list[dict]:
        if not self._pool:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id::text, alert_id::text, log_id::text, service, level,
                           message, anomaly_score, detected_at, deduplicated,
                           notification_channels, created_at
                    FROM alerts WHERE detected_at BETWEEN $1 AND $2
                    ORDER BY detected_at DESC LIMIT $3 OFFSET $4
                    """,
                    start,
                    end,
                    limit,
                    offset,
                )
                return [dict(r) for r in rows]
        except Exception as exc:
            _log.error("DB get_alerts_by_time_range failed", extra={"error": str(exc)})
            return []

    async def count_alerts(self) -> int:
        if not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) FROM alerts WHERE deduplicated = FALSE"
                )
                return int(row[0]) if row else 0
        except Exception:
            return 0

    async def count_alerts_last_hour(self) -> int:
        if not self._pool:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    (
                        "SELECT COUNT(*) FROM alerts WHERE detected_at >= NOW() "
                        "- INTERVAL '1 hour' AND deduplicated = FALSE"
                    )
                )
                return int(row[0]) if row else 0
        except Exception:
            return 0
