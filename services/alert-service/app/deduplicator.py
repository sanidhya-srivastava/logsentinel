"""
LogSentinel — Alert Service: Alert Deduplicator
================================================
Redis-based alert deduplication using TTL keys.

Deduplication logic:
  - A deduplication key is derived from: service + error_code + level
  - If the key exists in Redis, the alert is a duplicate (suppress notifications)
  - If the key does not exist, the alert is unique (send notifications)
  - After marking as seen, the key expires after ALERT_DEDUP_TTL_SECONDS (default: 1 hour)

This prevents alert storms where the same underlying issue generates
thousands of identical anomaly alerts within a short time window.

Usage:
    deduplicator = AlertDeduplicator(redis_url="redis://localhost:6379/0", ttl_seconds=3600)
    await deduplicator.start()

    is_dup = await deduplicator.is_duplicate(alert_dict)
    if not is_dup:
        await deduplicator.mark_seen(alert_dict)
        # send notifications...

    await deduplicator.stop()
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key namespace
# ---------------------------------------------------------------------------
_NS = "logsentinel:alert:dedup:"


def _build_dedup_key(alert: dict[str, Any]) -> str:
    """
    Build a stable Redis deduplication key for an alert.

    The key is derived from the combination of:
      - service name
      - log level
      - error_code (raw, not bucket-encoded)
      - anomaly_score bucket (rounded to 1 decimal place to group similar scores)

    Using a hash keeps Redis key lengths short and consistent regardless
    of service name length. SHA-256 is used purely for key derivation —
    not for any security purpose.

    Args:
        alert: A dict from the Kafka anomaly-alerts topic.

    Returns:
        A namespaced Redis key string.
    """
    service = (alert.get("service") or "unknown").strip().lower()
    level = (alert.get("level") or "UNKNOWN").strip().upper()
    error_code = str(alert.get("error_code") or "0")
    # Bucket the anomaly score to 1 decimal place so that very similar
    # scores (e.g. -0.31 and -0.32) are grouped together
    score = alert.get("anomaly_score", 0.0)
    score_bucket = f"{round(float(score), 1)}"

    raw_key = f"{service}:{level}:{error_code}:{score_bucket}"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    return f"{_NS}{key_hash}"


# ---------------------------------------------------------------------------
# Alert Deduplicator
# ---------------------------------------------------------------------------


class AlertDeduplicator:
    """
    Redis-based alert deduplicator using TTL-keyed existence checks.

    Two-step usage pattern:
      1. Call is_duplicate(alert) to check if a suppression key exists.
      2. If NOT a duplicate, call mark_seen(alert) to set the key with TTL.

    This two-step approach allows the caller to persist the alert to the
    database regardless of duplicate status, while only sending notifications
    for unique alerts.

    Degraded mode:
      If Redis is unavailable, is_duplicate() returns False (never suppress)
      and mark_seen() is a no-op. This ensures no alerts are silently lost
      if Redis goes down, at the cost of potential duplicate notifications.

    Args:
        redis_url:   Redis connection URL (e.g. "redis://redis:6379/0").
        ttl_seconds: How long (seconds) to suppress identical alerts.
                     Default: 3600 (1 hour).
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        ttl_seconds: int = 3600,
    ) -> None:
        self._redis_url = redis_url
        self._ttl_seconds = ttl_seconds
        self._redis: Any = None
        self._started: bool = False

        logger.debug(
            "AlertDeduplicator initialised",
            extra={
                "redis_url": self._redis_url,
                "ttl_seconds": self._ttl_seconds,
            },
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if Redis is connected and operational."""
        return self._started and self._redis is not None

    @property
    def ttl_seconds(self) -> int:
        """Current deduplication TTL in seconds."""
        return self._ttl_seconds

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Connect to Redis.

        Non-fatal on failure — the deduplicator will run in degraded mode
        (no suppression) if Redis is unavailable.
        """
        if self._started:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore[import]

            self._redis = await aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            # Verify connectivity
            await self._redis.ping()
            self._started = True
            logger.info(
                "AlertDeduplicator connected to Redis",
                extra={"redis_url": self._redis_url, "ttl_seconds": self._ttl_seconds},
            )
        except Exception as exc:
            logger.error(
                "AlertDeduplicator failed to connect to Redis — "
                "running in degraded mode (no deduplication)",
                extra={"error": str(exc)},
            )
            self._redis = None
            self._started = False

    async def stop(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
                logger.info("AlertDeduplicator Redis connection closed")
            except Exception as exc:
                logger.warning(
                    "Error closing Redis connection",
                    extra={"error": str(exc)},
                )
            finally:
                self._redis = None
                self._started = False

    # ------------------------------------------------------------------
    # Core deduplication logic
    # ------------------------------------------------------------------

    async def is_duplicate(self, alert: dict[str, Any]) -> bool:
        """
        Check whether an alert has already been seen recently.

        Returns True if a deduplication key for this alert exists in Redis,
        meaning a notification was already sent within the TTL window.

        Returns False if:
          - No key exists (new/unique alert)
          - Redis is unavailable (fail-open: treat as new to avoid lost alerts)

        Args:
            alert: The anomaly alert dict from Kafka.

        Returns:
            bool: True if this is a duplicate (suppress), False if unique (send).
        """
        if self._redis is None:
            logger.warning(
                "Redis unavailable — treating alert as unique (fail-open)",
                extra={"alert_id": alert.get("alert_id")},
            )
            return False

        key = _build_dedup_key(alert)

        try:
            exists = await self._redis.exists(key)
            is_dup = bool(exists)

            logger.debug(
                "Deduplication check",
                extra={
                    "alert_id": alert.get("alert_id"),
                    "service": alert.get("service"),
                    "key": key,
                    "is_duplicate": is_dup,
                },
            )
            return is_dup

        except Exception as exc:
            logger.error(
                "Redis dedup check error — treating alert as unique (fail-open)",
                extra={
                    "alert_id": alert.get("alert_id"),
                    "key": key,
                    "error": str(exc),
                },
            )
            return False

    async def mark_seen(self, alert: dict[str, Any]) -> bool:
        """
        Mark an alert as seen in Redis so future identical alerts are suppressed.

        Sets the deduplication key with an EX (expire) TTL.
        The stored value includes a timestamp for debugging purposes.

        Args:
            alert: The anomaly alert dict from Kafka.

        Returns:
            bool: True if successfully marked, False on Redis error.
        """
        if self._redis is None:
            logger.warning(
                "Redis unavailable — cannot mark alert as seen",
                extra={"alert_id": alert.get("alert_id")},
            )
            return False

        key = _build_dedup_key(alert)
        value = (
            f"{alert.get('alert_id', 'unknown')}:"
            f"{datetime.now(timezone.utc).isoformat()}"
        )

        try:
            # SET key value EX ttl NX (only set if not exists — avoids resetting TTL
            # if another instance raced us between is_duplicate and mark_seen)
            set_result = await self._redis.set(
                key,
                value,
                ex=self._ttl_seconds,
                nx=True,  # Only set if key does not already exist
            )

            if set_result:
                logger.debug(
                    "Alert marked as seen in Redis",
                    extra={
                        "alert_id": alert.get("alert_id"),
                        "service": alert.get("service"),
                        "key": key,
                        "ttl_seconds": self._ttl_seconds,
                    },
                )
            else:
                # Key was set by another instance between our is_duplicate check
                # and mark_seen call — this is a normal race condition
                logger.debug(
                    "Alert dedup key already set by another instance",
                    extra={"alert_id": alert.get("alert_id"), "key": key},
                )
            return True

        except Exception as exc:
            logger.error(
                "Redis mark_seen error",
                extra={
                    "alert_id": alert.get("alert_id"),
                    "key": key,
                    "error": str(exc),
                },
            )
            return False

    async def clear(self, alert: dict[str, Any]) -> bool:
        """
        Manually clear the deduplication key for an alert.

        Useful for testing or forcing re-notification after an acknowledged incident.

        Args:
            alert: The anomaly alert dict.

        Returns:
            bool: True if key was deleted (or didn't exist), False on error.
        """
        if self._redis is None:
            return False

        key = _build_dedup_key(alert)
        try:
            await self._redis.delete(key)
            logger.info(
                "Dedup key cleared",
                extra={"alert_id": alert.get("alert_id"), "key": key},
            )
            return True
        except Exception as exc:
            logger.error(
                "Failed to clear dedup key",
                extra={"key": key, "error": str(exc)},
            )
            return False

    async def get_ttl_remaining(self, alert: dict[str, Any]) -> int:
        """
        Return the remaining TTL (seconds) for an alert's dedup key.

        Returns -1 if the key does not exist or Redis is unavailable.

        Args:
            alert: The anomaly alert dict.

        Returns:
            int: Remaining TTL in seconds, or -1 if not found.
        """
        if self._redis is None:
            return -1

        key = _build_dedup_key(alert)
        try:
            ttl = await self._redis.ttl(key)
            return int(ttl)
        except Exception:
            return -1

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AlertDeduplicator":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AlertDeduplicator("
            f"redis_url={self._redis_url!r}, "
            f"ttl_seconds={self._ttl_seconds}, "
            f"connected={self.is_connected})"
        )
