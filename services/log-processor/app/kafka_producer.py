"""
LogSentinel — Log Ingestion API: Kafka Producer Client
=======================================================
Async Kafka producer wrapper using aiokafka.

Responsibilities:
  - Maintain a persistent async Kafka producer connection
  - Serialize log entry dicts to JSON bytes before publishing
  - Handle reconnection on transient failures using tenacity
  - Expose connection status for health checks
  - Emit structured log lines on all state transitions

Usage:
    producer = KafkaProducerClient(
        bootstrap_servers="kafka:9092",
        topic="raw-logs",
    )
    await producer.start()
    await producer.send({"log_id": "...", "service": "auth", ...})
    await producer.stop()
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from aiokafka import AIOKafkaProducer
from aiokafka.errors import (
    KafkaConnectionError,
    KafkaError,
    KafkaTimeoutError,
    NodeNotReadyError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class KafkaProducerNotStartedError(RuntimeError):
    """Raised when send() is called before start() has been awaited."""


class KafkaPublishError(RuntimeError):
    """Raised when a message cannot be published after all retries."""


# ---------------------------------------------------------------------------
# JSON Serialiser
# ---------------------------------------------------------------------------


def _json_serialiser(value: Any) -> bytes:
    """
    Serialise a Python dict to UTF-8 encoded JSON bytes.

    Handles non-serialisable types gracefully:
      - datetime objects → ISO 8601 string
      - Everything else  → str(value)
    """

    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    return json.dumps(value, default=_default, ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# Kafka Producer Client
# ---------------------------------------------------------------------------


class KafkaProducerClient:
    """
    Async Kafka producer client wrapping aiokafka.AIOKafkaProducer.

    Features:
      - Async context manager support (async with KafkaProducerClient(...))
      - Automatic retry with exponential back-off on transient errors
      - Graceful start / stop lifecycle management
      - Thread-safe singleton pattern via a lock on start/stop
      - Metrics-friendly: all state changes emit structured log lines
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        *,
        acks: str = "all",
        compression_type: str = "gzip",
        max_batch_size: int = 16_384,
        linger_ms: int = 5,
        request_timeout_ms: int = 30_000,
        retry_backoff_ms: int = 300,
        max_retries: int = 5,
        enable_idempotence: bool = True,
    ) -> None:
        """
        Initialise the producer client.

        Args:
            bootstrap_servers: Comma-separated Kafka broker addresses
                               (e.g. "kafka:9092" or "b1:9092,b2:9092").
            topic:             Default Kafka topic to publish messages to.
            acks:              Producer acknowledgement mode ('all', '1', '0').
            compression_type:  Message compression ('gzip', 'snappy', 'lz4',
                               'zstd', 'none').
            max_batch_size:    Max size in bytes of a producer batch.
            linger_ms:         Milliseconds to wait before flushing a batch.
            request_timeout_ms: Timeout in ms for broker requests.
            retry_backoff_ms:  Backoff in ms between internal aiokafka retries.
            max_retries:       Number of application-level send retry attempts.
            enable_idempotence: Enable idempotent producer (exactly-once
                               semantics for single-partition writes).
        """
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._acks = acks
        self._compression_type = compression_type
        self._max_batch_size = max_batch_size
        self._linger_ms = linger_ms
        self._request_timeout_ms = request_timeout_ms
        self._retry_backoff_ms = retry_backoff_ms
        self._max_retries = max_retries
        self._enable_idempotence = enable_idempotence

        self._producer: AIOKafkaProducer | None = None
        self._started: bool = False
        self._lock = asyncio.Lock()

        logger.debug(
            "KafkaProducerClient initialised",
            extra={
                "bootstrap_servers": self._bootstrap_servers,
                "topic": self._topic,
                "acks": self._acks,
                "compression_type": self._compression_type,
            },
        )

    # -----------------------------------------------------------------------
    # Properties
    # -----------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if the producer has been started and not yet stopped."""
        return self._started and self._producer is not None

    @property
    def topic(self) -> str:
        """The default Kafka topic this producer publishes to."""
        return self._topic

    # -----------------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the Kafka producer and establish a connection to the cluster.

        This method is idempotent — calling it on an already-started producer
        is a no-op. Uses a lock to prevent concurrent startup races.

        Raises:
            KafkaConnectionError: If the broker is unreachable after retries.
        """
        async with self._lock:
            if self._started:
                logger.debug("Kafka producer already started — skipping")
                return

            logger.info(
                "Starting Kafka producer",
                extra={
                    "bootstrap_servers": self._bootstrap_servers,
                    "topic": self._topic,
                },
            )

            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                value_serializer=_json_serialiser,
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks=self._acks,
                compression_type=self._compression_type,
                max_batch_size=self._max_batch_size,
                linger_ms=self._linger_ms,
                request_timeout_ms=self._request_timeout_ms,
                retry_backoff_ms=self._retry_backoff_ms,
                enable_idempotence=self._enable_idempotence,
            )

            try:
                await self._producer.start()
                self._started = True
                logger.info(
                    "Kafka producer started successfully",
                    extra={
                        "bootstrap_servers": self._bootstrap_servers,
                        "topic": self._topic,
                    },
                )
            except KafkaConnectionError as exc:
                self._producer = None
                self._started = False
                logger.error(
                    "Kafka producer failed to connect",
                    extra={
                        "bootstrap_servers": self._bootstrap_servers,
                        "error": str(exc),
                    },
                )
                raise
            except Exception as exc:
                self._producer = None
                self._started = False
                logger.error(
                    "Unexpected error starting Kafka producer",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
                raise

    async def stop(self) -> None:
        """
        Flush pending messages and stop the Kafka producer cleanly.

        This method is idempotent — calling it on an already-stopped producer
        is a no-op.
        """
        async with self._lock:
            if not self._started or self._producer is None:
                logger.debug("Kafka producer already stopped — skipping")
                return

            logger.info("Stopping Kafka producer — flushing pending messages")
            try:
                await self._producer.flush()
                await self._producer.stop()
                logger.info("Kafka producer stopped cleanly")
            except Exception as exc:
                logger.error(
                    "Error during Kafka producer shutdown",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
            finally:
                self._producer = None
                self._started = False

    # -----------------------------------------------------------------------
    # Publishing
    # -----------------------------------------------------------------------

    async def send(
        self,
        value: dict[str, Any],
        *,
        key: str | None = None,
        topic: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """
        Publish a single message to Kafka.

        Args:
            value:   The message payload as a Python dict. Will be JSON-serialised.
            key:     Optional Kafka message key (used for partition routing).
                     Defaults to the 'service' field from the value dict.
            topic:   Override the default topic for this specific message.
            headers: Optional dict of string key-value headers to attach.

        Raises:
            KafkaProducerNotStartedError: Producer was not started.
            KafkaPublishError:            All retry attempts failed.
        """
        if not self.is_connected or self._producer is None:
            raise KafkaProducerNotStartedError(
                "Kafka producer is not started. Call start() before send()."
            )

        target_topic = topic or self._topic

        # Use service name as the partition key if no explicit key is provided.
        # This ensures all logs from the same service go to the same partition,
        # preserving ordering within a service.
        message_key = key or value.get("service")

        # Convert headers dict to aiokafka's expected format: list of (key, bytes)
        kafka_headers = None
        if headers:
            kafka_headers = [
                (k, v.encode("utf-8") if isinstance(v, str) else v)
                for k, v in headers.items()
            ]

        await self._send_with_retry(
            topic=target_topic,
            value=value,
            key=message_key,
            headers=kafka_headers,
        )

    @retry(
        retry=retry_if_exception_type(
            (KafkaTimeoutError, NodeNotReadyError, KafkaConnectionError)
        ),
        wait=wait_exponential(multiplier=0.3, min=0.3, max=10),
        stop=stop_after_attempt(5),
        reraise=False,
    )
    async def _send_with_retry(
        self,
        *,
        topic: str,
        value: dict[str, Any],
        key: str | None,
        headers: list | None,
    ) -> None:
        """
        Internal send method with automatic retry on transient Kafka errors.

        The @retry decorator handles:
          - KafkaTimeoutError  — broker didn't respond in time
          - NodeNotReadyError  — broker node not yet ready
          - KafkaConnectionError — lost connection to broker

        Non-transient errors (e.g. serialization failures) are NOT retried
        and propagate immediately.
        """
        try:
            await self._producer.send_and_wait(
                topic,
                value=value,
                key=key,
                headers=headers,
            )
            logger.debug(
                "Message published to Kafka",
                extra={
                    "topic": topic,
                    "key": key,
                    "log_id": value.get("log_id"),
                    "service": value.get("service"),
                },
            )
        except (KafkaTimeoutError, NodeNotReadyError, KafkaConnectionError) as exc:
            logger.warning(
                "Transient Kafka error — will retry",
                extra={
                    "topic": topic,
                    "key": key,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise  # tenacity will catch and retry
        except KafkaError as exc:
            # Non-transient Kafka error — do not retry
            logger.error(
                "Non-transient Kafka error — aborting publish",
                extra={
                    "topic": topic,
                    "key": key,
                    "log_id": value.get("log_id"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise KafkaPublishError(
                f"Failed to publish message to Kafka topic '{topic}': {exc}"
            ) from exc
        except Exception as exc:
            logger.error(
                "Unexpected error publishing to Kafka",
                extra={
                    "topic": topic,
                    "key": key,
                    "error": str(exc),
                },
                exc_info=True,
            )
            raise KafkaPublishError(
                f"Unexpected error publishing to Kafka: {exc}"
            ) from exc

    async def send_batch(
        self,
        messages: list[dict[str, Any]],
        *,
        topic: str | None = None,
    ) -> tuple[int, int]:
        """
        Publish a list of messages to Kafka.

        Processes each message individually so a single failure doesn't
        block the rest of the batch.

        Args:
            messages: List of message payload dicts.
            topic:    Override the default topic for all messages in this batch.

        Returns:
            Tuple of (success_count, failure_count).
        """
        success = 0
        failure = 0

        for msg in messages:
            try:
                await self.send(msg, topic=topic)
                success += 1
            except (KafkaPublishError, KafkaProducerNotStartedError) as exc:
                failure += 1
                logger.error(
                    "Failed to publish batch message",
                    extra={
                        "log_id": msg.get("log_id"),
                        "service": msg.get("service"),
                        "error": str(exc),
                    },
                )

        logger.info(
            "Batch publish complete",
            extra={
                "total": len(messages),
                "success": success,
                "failure": failure,
                "topic": topic or self._topic,
            },
        )
        return success, failure

    # -----------------------------------------------------------------------
    # Async context manager support
    # -----------------------------------------------------------------------

    async def __aenter__(self) -> "KafkaProducerClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    # -----------------------------------------------------------------------
    # Diagnostics
    # -----------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """
        Return a dict describing the current producer state.
        Useful for health check endpoints.
        """
        return {
            "connected": self.is_connected,
            "bootstrap_servers": self._bootstrap_servers,
            "topic": self._topic,
            "acks": self._acks,
            "compression_type": self._compression_type,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"KafkaProducerClient("
            f"servers={self._bootstrap_servers!r}, "
            f"topic={self._topic!r}, "
            f"connected={self.is_connected})"
        )
