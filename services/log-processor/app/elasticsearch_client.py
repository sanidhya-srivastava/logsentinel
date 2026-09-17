"""
LogSentinel — Log Processor: Elasticsearch Client
==================================================
Async Elasticsearch client for indexing processed log documents.

Responsibilities:
  - Connect to Elasticsearch on startup
  - Create index templates on startup (consistent field mappings)
  - Index individual log documents into daily rolling indices
  - Bulk index batches of log documents efficiently
  - Expose connection status for health checks

Index naming convention: logsentinel-logs-YYYY.MM.DD
This enables time-based index lifecycle management (ILM).

Usage:
    es = ElasticsearchClient(host="elasticsearch", port=9200)
    await es.start()
    await es.ensure_index_template()
    await es.index_log(processed_log_dict)
    await es.stop()
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Index template: defines field mappings for all logsentinel-logs-* indices
# ---------------------------------------------------------------------------
INDEX_TEMPLATE_NAME = "logsentinel-logs-template"
INDEX_PATTERN = "logsentinel-logs-*"

INDEX_TEMPLATE_BODY: dict[str, Any] = {
    "index_patterns": [INDEX_PATTERN],
    "priority": 100,
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 1,
            "refresh_interval": "5s",
            "codec": "best_compression",
            "index": {
                "lifecycle": {
                    "name": "logsentinel-logs-policy",
                    "rollover_alias": "logsentinel-logs",
                }
            },
        },
        "mappings": {
            "dynamic": "true",
            "dynamic_date_formats": [
                "strict_date_optional_time",
                "yyyy/MM/dd HH:mm:ss",
            ],
            "properties": {
                # --- Identity ---
                "log_id": {"type": "keyword"},
                "ingested_at": {"type": "date"},
                "processed_at": {"type": "date"},
                "@timestamp": {"type": "date"},
                "timestamp": {"type": "date"},
                # --- Log core fields ---
                "service": {"type": "keyword"},
                "level": {"type": "keyword"},
                "host": {"type": "keyword"},
                "message": {
                    "type": "text",
                    "fields": {
                        "keyword": {
                            "type": "keyword",
                            "ignore_above": 512,
                        }
                    },
                },
                # --- Numeric fields ---
                "response_time_ms": {"type": "float"},
                "error_code": {"type": "integer"},
                # --- ML feature vector ---
                "features": {
                    "type": "object",
                    "properties": {
                        "hour_of_day": {"type": "integer"},
                        "response_time_ms": {"type": "float"},
                        "error_code": {"type": "integer"},
                        "log_level_encoded": {"type": "integer"},
                        "request_count_last_60s": {"type": "integer"},
                        "service_id_encoded": {"type": "integer"},
                    },
                },
                # --- Metadata (flexible key-value) ---
                "metadata": {"type": "object", "dynamic": True},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Elasticsearch Client
# ---------------------------------------------------------------------------


class ElasticsearchClient:
    """
    Async Elasticsearch client for the log-processor service.

    Uses the official elasticsearch-py async client (elasticsearch[async]).
    All operations are async and use the AsyncElasticsearch class.

    Args:
        host:     Elasticsearch hostname.
        port:     Elasticsearch HTTP port (default: 9200).
        scheme:   URL scheme ('http' or 'https').
        username: Basic auth username (optional).
        password: Basic auth password (optional).
        timeout:  Request timeout in seconds.
        index_prefix: Prefix for daily rolling index names.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        scheme: str = "http",
        username: str | None = None,
        password: str | None = None,
        timeout: int = 30,
        index_prefix: str = "logsentinel-logs",
        max_retries: int = 3,
        retry_on_timeout: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._scheme = scheme
        self._username = username
        self._password = password
        self._timeout = timeout
        self._index_prefix = index_prefix
        self._max_retries = max_retries
        self._retry_on_timeout = retry_on_timeout

        self._client = None  # AsyncElasticsearch instance
        self._started: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if the client has been started."""
        return self._started and self._client is not None

    def _current_index(self) -> str:
        """
        Return the daily rolling index name for the current UTC date.
        Format: logsentinel-logs-YYYY.MM.DD
        """
        today = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        return f"{self._index_prefix}-{today}"

    def _index_for_timestamp(self, timestamp_str: str | None) -> str:
        """
        Return the daily rolling index name for a given ISO 8601 timestamp.
        Falls back to current date if parsing fails.
        """
        if timestamp_str:
            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                return f"{self._index_prefix}-{dt.strftime('%Y.%m.%d')}"
            except (ValueError, AttributeError):
                pass
        return self._current_index()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Create and connect the AsyncElasticsearch client.

        Raises:
            ImportError:   If elasticsearch[async] is not installed.
            ConnectionError: If the cluster is unreachable after retries.
        """
        if self._started:
            logger.debug("Elasticsearch client already started — skipping")
            return

        try:
            from elasticsearch import AsyncElasticsearch
        except ImportError as exc:
            raise ImportError(
                "elasticsearch[async] is required. "
                "Run: pip install 'elasticsearch[async]'"
            ) from exc

        # Build the hosts list
        host_entry: dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "scheme": self._scheme,
        }

        # Build auth tuple if credentials provided
        http_auth = None
        if self._username and self._password:
            http_auth = (self._username, self._password)

        logger.info(
            "Connecting to Elasticsearch",
            extra={
                "host": self._host,
                "port": self._port,
                "scheme": self._scheme,
            },
        )

        self._client = AsyncElasticsearch(
            hosts=[host_entry],
            http_auth=http_auth,
            request_timeout=self._timeout,
            max_retries=self._max_retries,
            retry_on_timeout=self._retry_on_timeout,
            # Sniffing is disabled in containerised environments
            # because pod IPs are ephemeral
            sniff_on_start=False,
            sniff_on_node_failure=False,
        )

        # Verify connectivity with a cluster health check
        try:
            info = await self._client.cluster.health(timeout="10s")
            cluster_status = info.get("status", "unknown")
            logger.info(
                "Elasticsearch connected",
                extra={
                    "cluster_name": info.get("cluster_name"),
                    "status": cluster_status,
                    "number_of_nodes": info.get("number_of_nodes"),
                },
            )
            if cluster_status == "red":
                logger.warning(
                    "Elasticsearch cluster status is RED — indexing may fail"
                )
        except Exception as exc:
            logger.error(
                "Elasticsearch connectivity check failed",
                extra={"error": str(exc)},
            )
            # Non-fatal on startup: let the service start and retry on first index
            # The health check endpoint will surface the degraded state.

        self._started = True

    async def stop(self) -> None:
        """Close the Elasticsearch client connection."""
        if not self._started or self._client is None:
            return
        try:
            await self._client.close()
            logger.info("Elasticsearch client closed")
        except Exception as exc:
            logger.error(
                "Error closing Elasticsearch client",
                extra={"error": str(exc)},
            )
        finally:
            self._client = None
            self._started = False

    # ------------------------------------------------------------------
    # Index template management
    # ------------------------------------------------------------------

    async def ensure_index_template(self) -> None:
        """
        Create or update the Elasticsearch index template for log indices.

        Uses the composable index template API (PUT /_index_template/).
        Idempotent — safe to call on every service startup.
        """
        if self._client is None:
            logger.warning("Cannot ensure index template — client not connected")
            return

        try:
            await self._client.indices.put_index_template(
                name=INDEX_TEMPLATE_NAME,
                body=INDEX_TEMPLATE_BODY,
            )
            logger.info(
                "Elasticsearch index template applied",
                extra={
                    "template_name": INDEX_TEMPLATE_NAME,
                    "index_pattern": INDEX_PATTERN,
                },
            )
        except Exception as exc:
            # Non-fatal: documents can still be indexed without the template;
            # mappings will be auto-detected by Elasticsearch.
            logger.error(
                "Failed to apply index template — continuing without it",
                extra={
                    "template_name": INDEX_TEMPLATE_NAME,
                    "error": str(exc),
                },
            )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    async def index_log(self, document: dict[str, Any]) -> bool:
        """
        Index a single processed log document into Elasticsearch.

        The target index is determined by the document's @timestamp field
        (daily rolling index). Falls back to today's index on parse failure.

        Args:
            document: A fully processed log dict with all fields populated.

        Returns:
            True on success, False on failure.
        """
        if self._client is None:
            logger.warning(
                "Elasticsearch client not connected — skipping index operation",
                extra={"log_id": document.get("log_id")},
            )
            return False

        index_name = self._index_for_timestamp(document.get("@timestamp"))
        log_id = document.get("log_id")

        try:
            response = await self._client.index(
                index=index_name,
                id=log_id,  # Use log_id as document ID for idempotency
                document=document,
            )
            result = (
                response.get("result") if isinstance(response, dict) else str(response)
            )
            logger.debug(
                "Log indexed in Elasticsearch",
                extra={
                    "log_id": log_id,
                    "index": index_name,
                    "result": result,
                },
            )
            return True

        except Exception as exc:
            logger.error(
                "Failed to index log document in Elasticsearch",
                extra={
                    "log_id": log_id,
                    "index": index_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return False

    async def bulk_index_logs(self, documents: list[dict[str, Any]]) -> tuple[int, int]:
        """
        Bulk index multiple processed log documents.

        Uses the Elasticsearch bulk API for efficiency (one HTTP round-trip
        per batch instead of one per document).

        Args:
            documents: List of processed log dicts to index.

        Returns:
            Tuple of (success_count, failure_count).
        """
        if not documents:
            return 0, 0

        if self._client is None:
            logger.warning("Elasticsearch client not connected — skipping bulk index")
            return 0, len(documents)

        # Build bulk operations list
        # Format: alternating action metadata + source document
        bulk_ops: list[dict[str, Any]] = []
        for doc in documents:
            log_id = doc.get("log_id")
            index_name = self._index_for_timestamp(doc.get("@timestamp"))
            # Action metadata
            bulk_ops.append({"index": {"_index": index_name, "_id": log_id}})
            # Document body
            bulk_ops.append(doc)

        try:
            from elasticsearch.helpers import async_bulk

            success, failures = await async_bulk(
                client=self._client,
                actions=self._build_bulk_actions(documents),
                raise_on_error=False,
                raise_on_exception=False,
                stats_only=False,
                max_retries=2,
                initial_backoff=0.5,
                max_backoff=10,
            )

            if failures:
                logger.warning(
                    "Some bulk index operations failed",
                    extra={
                        "success": success,
                        "failures": len(failures),
                        "first_error": str(failures[0])[:200] if failures else None,
                    },
                )
            else:
                logger.debug(
                    "Bulk index complete",
                    extra={"success": success, "total": len(documents)},
                )

            return success, len(failures)

        except Exception as exc:
            logger.error(
                "Bulk index operation failed entirely",
                extra={"error": str(exc), "document_count": len(documents)},
                exc_info=True,
            )
            return 0, len(documents)

    def _build_bulk_actions(self, documents: list[dict[str, Any]]):
        """
        Generator that yields elasticsearch-py bulk action dicts.
        Each action includes the index metadata embedded in the document.
        """
        for doc in documents:
            log_id = doc.get("log_id")
            index_name = self._index_for_timestamp(doc.get("@timestamp"))
            yield {
                "_index": index_name,
                "_id": log_id,
                "_source": doc,
            }

    # ------------------------------------------------------------------
    # Search helpers (used by dashboard-backend)
    # ------------------------------------------------------------------

    async def search_logs(
        self,
        *,
        query: dict[str, Any] | None = None,
        page: int = 1,
        size: int = 20,
        sort_field: str = "@timestamp",
        sort_order: str = "desc",
    ) -> dict[str, Any]:
        """
        Execute a paginated search against all log indices.

        Args:
            query:      Elasticsearch query dict. Defaults to match_all.
            page:       1-based page number.
            size:       Number of results per page.
            sort_field: Field to sort by.
            sort_order: 'asc' or 'desc'.

        Returns:
            Dict with keys: total, hits, page, size.
        """
        if self._client is None:
            return {"total": 0, "hits": [], "page": page, "size": size}

        from_offset = (page - 1) * size
        search_query = query or {"match_all": {}}

        try:
            response = await self._client.search(
                index=f"{self._index_prefix}-*",
                body={
                    "query": search_query,
                    "sort": [{sort_field: {"order": sort_order}}],
                    "from": from_offset,
                    "size": size,
                    "track_total_hits": True,
                },
            )

            total = response["hits"]["total"]["value"]
            hits = [h["_source"] for h in response["hits"]["hits"]]

            return {
                "total": total,
                "hits": hits,
                "page": page,
                "size": size,
            }

        except Exception as exc:
            logger.error(
                "Elasticsearch search failed",
                extra={"error": str(exc)},
            )
            return {"total": 0, "hits": [], "page": page, "size": size}

    async def count_logs(
        self,
        *,
        index_pattern: str | None = None,
        query: dict[str, Any] | None = None,
    ) -> int:
        """Return the document count matching the given query."""
        if self._client is None:
            return 0
        pattern = index_pattern or f"{self._index_prefix}-*"
        try:
            response = await self._client.count(
                index=pattern,
                body={"query": query or {"match_all": {}}},
            )
            return int(response.get("count", 0))
        except Exception as exc:
            logger.error(
                "Elasticsearch count failed",
                extra={"error": str(exc)},
            )
            return 0

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "ElasticsearchClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    def __repr__(self) -> str:
        return (
            f"ElasticsearchClient("
            f"host={self._host}:{self._port}, "
            f"scheme={self._scheme!r}, "
            f"connected={self.is_connected})"
        )
