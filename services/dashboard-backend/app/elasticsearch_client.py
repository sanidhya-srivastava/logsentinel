"""
LogSentinel — Dashboard Backend: Elasticsearch Client
=====================================================
Lightweight async Elasticsearch client for dashboard log queries.
"""

import logging
from typing import Any, Optional
from app.logger import get_logger
from app.metrics import ES_QUERY_LATENCY

logger = get_logger(__name__)


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

            kwargs: dict[str, Any] = {
                "hosts": [f"{self._scheme}://{self._host}:{self._port}"],
                "request_timeout": self._timeout,
                "max_retries": 3,
                "retry_on_timeout": True,
            }
            if self._username and self._password:
                kwargs["basic_auth"] = (self._username, self._password)

            self._client = AsyncElasticsearch(**kwargs)
            await self._client.cluster.health(timeout="10s")
            self._started = True
            logger.info("Elasticsearch connected", extra={"host": self._host, "port": self._port})
        except Exception as exc:
            logger.error("Elasticsearch connection failed", extra={"error": str(exc)})

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
                ignore_unavailable=True,
                allow_no_indices=True,
                body={
                    "query": query or {"match_all": {}},
                    "sort": [{sort_field: {"order": sort_order, "unmapped_type": "date"}}],
                    "from": (page - 1) * size,
                    "size": size,
                    "track_total_hits": True,
                },
            )
            ES_QUERY_LATENCY.labels(operation="search").observe(time.perf_counter() - start)
            total = response["hits"]["total"]["value"]
            hits = [h["_source"] for h in response["hits"]["hits"]]
            return {"total": total, "hits": hits, "page": page, "size": size}
        except Exception as exc:
            logger.error("Elasticsearch search failed", extra={"error": str(exc)})
            return {"total": 0, "hits": [], "page": page, "size": size}

    async def count_logs(
        self, query: Optional[dict] = None, index_pattern: Optional[str] = None
    ) -> int:
        if not self._client:
            return 0
        try:
            response = await self._client.count(
                index=index_pattern or f"{self._index_prefix}-*",
                ignore_unavailable=True,
                allow_no_indices=True,
                body={"query": query or {"match_all": {}}},
            )
            return int(response.get("count", 0))
        except Exception as exc:
            logger.error("Elasticsearch count failed", extra={"error": str(exc)})
            return 0
