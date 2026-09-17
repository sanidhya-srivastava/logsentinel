"""
LogSentinel — Kafka Consumer Client
=====================================
Async Kafka consumer wrapper using aiokafka.

Responsibilities:
  - Maintain a persistent async Kafka consumer connection
  - Deserialise JSON message bytes to Python dicts
  - Manually commit offsets after successful processing
  - Yield messages via an async generator for clean consumer loops
  - Handle reconnection and transient errors gracefully
  - Expose connection status for health checks

Usage:
    consumer = KafkaConsumerClient(
        bootstrap_servers="kafka:9092",
        topic="raw-logs",
        group_id="log-processor-group",
    )
    await consumer.start()
    async for message in consumer.consume(shutdown_event=event):
        await process(message)
    await consumer.stop()
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import ConsumerStoppedError, KafkaConnectionError, KafkaError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class KafkaConsumerNotStartedError(RuntimeError):
    """Raised when consume() is called before start() has been awaited."""


# ---------------------------------------------------------------------------
# JSON Deserialiser
# ---------------------------------------------------------------------------


def _json_deserialiser(data: bytes) -> dict[str, Any] | None:
    """
    Deserialise UTF-8 JSON bytes to a Python dict.
    Returns None on decode or parse failure (caller skips the message).
    """
    if not data:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(
            "Failed to deserialise Kafka message",
            extra={"error": str(exc), "raw_bytes_preview": repr(data[:120])},
        )
        return None


# ---------------------------------------------------------------------------
# Kafka Consumer Client
# ---------------------------------------------------------------------------


class KafkaConsumerClient:
    """
    Async Kafka consumer client wrapping aiokafka.AIOKafkaConsumer.

    Features:
      - Single-topic consumer with manual offset commit
      - Async generator interface (async for message in consumer.consume(...))
      - Graceful shutdown via an asyncio.Event
      - Auto-skip of unparseable messages (logs error, commits offset)
      - Connection status property for health checks
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        *,
        auto_offset_reset: str = "earliest",
        session_timeout_ms: int = 30_000,
        heartbeat_interval_ms: int = 3_000,
        max_poll_records: int = 500,
        fetch_max_wait_ms: int = 500,
        fetch_min_bytes: int = 1,
        enable_auto_commit: bool = False,
        request_timeout_ms: int = 40_000,
        retry_backoff_ms: int = 300,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._auto_offset_reset = auto_offset_reset
        self._session_timeout_ms = session_timeout_ms
        self._heartbeat_interval_ms = heartbeat_interval_ms
        self._max_poll_records = max_poll_records
        self._fetch_max_wait_ms = fetch_max_wait_ms
        self._fetch_min_bytes = fetch_min_bytes
        self._enable_auto_commit = enable_auto_commit
        self._request_timeout_ms = request_timeout_ms
        self._retry_backoff_ms = retry_backoff_ms

        self._consumer: AIOKafkaConsumer | None = None
        self._started: bool = False
        self._lock = asyncio.Lock()

        logger.debug(
            "KafkaConsumerClient initialised",
            extra={
                "bootstrap_servers": self._bootstrap_servers,
                "topic": self._topic,
                "group_id": self._group_id,
                "auto_offset_reset": self._auto_offset_reset,
            },
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if the consumer has been started and not yet stopped."""
        return self._started and self._consumer is not None

    @property
    def topic(self) -> str:
        return self._topic

    @property
    def group_id(self) -> str:
        return self._group_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the Kafka consumer and join the consumer group.

        Idempotent — calling on an already-started consumer is a no-op.

        Raises:
            KafkaConnectionError: If the broker is unreachable.
        """
        async with self._lock:
            if self._started:
                logger.debug("Kafka consumer already started — skipping")
                return

            logger.info(
                "Starting Kafka consumer",
                extra={
                    "bootstrap_servers": self._bootstrap_servers,
                    "topic": self._topic,
                    "group_id": self._group_id,
                },
            )

            self._consumer = AIOKafkaConsumer(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._group_id,
                auto_offset_reset=self._auto_offset_reset,
                enable_auto_commit=self._enable_auto_commit,
                session_timeout_ms=self._session_timeout_ms,
                heartbeat_interval_ms=self._heartbeat_interval_ms,
                max_poll_records=self._max_poll_records,
                fetch_max_wait_ms=self._fetch_max_wait_ms,
                fetch_min_bytes=self._fetch_min_bytes,
                request_timeout_ms=self._request_timeout_ms,
                retry_backoff_ms=self._retry_backoff_ms,
                # Deserialise value bytes → dict (key kept as bytes)
                value_deserializer=_json_deserialiser,
                # Isolation level: read only committed messages
                isolation_level="read_committed",
            )

            try:
                await self._consumer.start()
                self._started = True
                logger.info(
                    "Kafka consumer started successfully",
                    extra={
                        "topic": self._topic,
                        "group_id": self._group_id,
                    },
                )
            except KafkaConnectionError as exc:
                self._consumer = None
                self._started = False
                logger.error(
                    "Kafka consumer failed to connect",
                    extra={
                        "bootstrap_servers": self._bootstrap_servers,
                        "error": str(exc),
                    },
                )
                raise
            except Exception as exc:
                self._consumer = None
                self._started = False
                logger.error(
                    "Unexpected error starting Kafka consumer",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
                raise

    async def stop(self) -> None:
        """
        Stop the Kafka consumer cleanly.

        Commits any pending offsets, leaves the consumer group, and
        closes the connection. Idempotent.
        """
        async with self._lock:
            if not self._started or self._consumer is None:
                logger.debug("Kafka consumer already stopped — skipping")
                return

            logger.info(
                "Stopping Kafka consumer",
                extra={"topic": self._topic, "group_id": self._group_id},
            )
            try:
                await self._consumer.stop()
                logger.info("Kafka consumer stopped cleanly")
            except Exception as exc:
                logger.error(
                    "Error stopping Kafka consumer",
                    extra={"error": str(exc)},
                    exc_info=True,
                )
            finally:
                self._consumer = None
                self._started = False

    # ------------------------------------------------------------------
    # Consume
    # ------------------------------------------------------------------

    async def consume(
        self,
        shutdown_event: asyncio.Event | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Async generator that yields one deserialized message dict at a time.

        Behaviour:
          - Polls Kafka in a loop until shutdown_event is set or consumer stops.
          - After each successful yield+return from the caller, commits the offset.
          - Skips (but still commits) messages that fail JSON deserialisation.
          - On ConsumerStoppedError or asyncio.CancelledError, exits cleanly.
          - On other KafkaErrors, logs the error and continues after a backoff.

        Args:
            shutdown_event: An asyncio.Event that — when set — causes the
                            generator to exit cleanly after the current message.

        Yields:
            dict[str, Any]: A single deserialized log message payload.

        Example:
            shutdown = asyncio.Event()
            async for msg in consumer.consume(shutdown_event=shutdown):
                await handle(msg)
                # offset is committed automatically after handle() returns
        """
        if not self.is_connected or self._consumer is None:
            raise KafkaConsumerNotStartedError(
                "Kafka consumer is not started. Call start() before consume()."
            )

        logger.info(
            "Starting consume loop",
            extra={"topic": self._topic, "group_id": self._group_id},
        )

        _shutdown = shutdown_event or asyncio.Event()
        messages_consumed = 0
        messages_skipped = 0

        try:
            while not _shutdown.is_set():
                try:
                    # getmany() returns a dict of {TopicPartition: [records]}
                    # timeout_ms prevents blocking forever when shutdown_event is set
                    records = await self._consumer.getmany(
                        timeout_ms=1_000,
                        max_records=self._max_poll_records,
                    )
                except ConsumerStoppedError:
                    logger.info("Consumer stopped — exiting consume loop")
                    break
                except asyncio.CancelledError:
                    logger.info("Consume loop cancelled")
                    break
                except KafkaError as exc:
                    logger.error(
                        "Kafka error in consume loop — backing off",
                        extra={"error": str(exc)},
                    )
                    await asyncio.sleep(2.0)
                    continue
                except Exception as exc:
                    logger.error(
                        "Unexpected error in consume loop — backing off",
                        extra={"error": str(exc)},
                        exc_info=True,
                    )
                    await asyncio.sleep(2.0)
                    continue

                if not records:
                    # No messages available — poll again
                    continue

                for tp, msgs in records.items():
                    for msg in msgs:
                        if _shutdown.is_set():
                            logger.info("Shutdown event set mid-batch — stopping")
                            return

                        value = msg.value  # already deserialized by value_deserializer

                        if value is None:
                            # Deserialisation failed — skip but commit offset
                            messages_skipped += 1
                            logger.warning(
                                "Skipping unparseable message",
                                extra={
                                    "topic": msg.topic,
                                    "partition": msg.partition,
                                    "offset": msg.offset,
                                },
                            )
                            if not self._enable_auto_commit:
                                try:
                                    await self._consumer.commit()
                                except Exception as commit_exc:
                                    logger.error(
                                        "Failed to commit offset for skipped message",
                                        extra={"error": str(commit_exc)},
                                    )
                            continue

                        logger.debug(
                            "Message received",
                            extra={
                                "topic": msg.topic,
                                "partition": msg.partition,
                                "offset": msg.offset,
                                "key": msg.key.decode("utf-8") if msg.key else None,
                                "log_id": value.get("log_id"),
                            },
                        )

                        # Yield to caller — processing happens in the caller
                        yield value
                        messages_consumed += 1

                        # Commit offset after caller has processed the message
                        # This ensures at-least-once delivery semantics:
                        # if the service crashes during processing, the message
                        # will be redelivered on restart.
                        if not self._enable_auto_commit:
                            try:
                                await self._consumer.commit()
                            except Exception as commit_exc:
                                logger.error(
                                    "Failed to commit offset",
                                    extra={
                                        "topic": msg.topic,
                                        "partition": msg.partition,
                                        "offset": msg.offset,
                                        "error": str(commit_exc),
                                    },
                                )

        except asyncio.CancelledError:
            logger.info("Consume generator cancelled")
        finally:
            logger.info(
                "Consume loop exited",
                extra={
                    "messages_consumed": messages_consumed,
                    "messages_skipped": messages_skipped,
                    "topic": self._topic,
                    "group_id": self._group_id,
                },
            )

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "KafkaConsumerClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a dict describing the current consumer state."""
        return {
            "connected": self.is_connected,
            "bootstrap_servers": self._bootstrap_servers,
            "topic": self._topic,
            "group_id": self._group_id,
            "auto_offset_reset": self._auto_offset_reset,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def __repr__(self) -> str:
        return (
            f"KafkaConsumerClient("
            f"servers={self._bootstrap_servers!r}, "
            f"topic={self._topic!r}, "
            f"group_id={self._group_id!r}, "
            f"connected={self.is_connected})"
        )
