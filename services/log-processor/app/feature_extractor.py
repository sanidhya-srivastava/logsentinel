"""
LogSentinel — Log Processor: Feature Extractor
===============================================
Extracts structured ML feature vectors from raw parsed log entries.

Features extracted per log entry:
  - hour_of_day           : int   (0–23)  extracted from timestamp
  - response_time_ms      : float         raw or defaulted to 0.0
  - error_code            : int           HTTP/app error code, bucket-encoded
  - log_level_encoded     : int           DEBUG=0 INFO=1 WARN=2 ERROR=3 CRITICAL=4
  - request_count_last_60s: int           per-service rolling 60s window (Redis)
  - service_id_encoded    : int           label-encoded service name (Redis dict)

Redis is used for two purposes:
  1. Rolling 60-second request count per service (sliding window counter)
  2. Service name → integer label mapping (persistent dictionary)

All Redis keys are namespaced under "logsentinel:" to avoid collisions.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Log level encoding map
# ---------------------------------------------------------------------------
LOG_LEVEL_ENCODING: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARN": 2,
    "WARNING": 2,  # alias
    "ERROR": 3,
    "CRITICAL": 4,
    "FATAL": 4,  # alias
}


# ---------------------------------------------------------------------------
# Error code bucket encoding
# Converts raw HTTP/application codes to a small integer category
# ---------------------------------------------------------------------------
def _encode_error_code(code: int | None) -> int:
    """
    Map a raw error/status code to a small integer bucket:
      0 → no code / unknown
      1 → 2xx  success
      2 → 3xx  redirect
      3 → 4xx  client error
      4 → 5xx  server error
      5 → other non-standard code
    """
    if code is None or code == 0:
        return 0
    if 200 <= code < 300:
        return 1
    if 300 <= code < 400:
        return 2
    if 400 <= code < 500:
        return 3
    if 500 <= code < 600:
        return 4
    return 5


# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------
_NS = "logsentinel:"
_SERVICE_MAP_KEY = f"{_NS}service_id_map"  # Hash: service_name → int id
_SERVICE_COUNTER_KEY = f"{_NS}service_id_counter"  # Int: next service id
_ROLLING_WINDOW_SECONDS = 60


def _rolling_key(service: str) -> str:
    """Redis sorted-set key for the per-service rolling 60s request counter."""
    return f"{_NS}rolling:{service}"


# ---------------------------------------------------------------------------
# Feature Extractor
# ---------------------------------------------------------------------------


class FeatureExtractor:
    """
    Extracts the 6 ML input features from a raw (parsed) log entry dict.

    Requires a running Redis instance for:
      - Service name label encoding (persisted across restarts)
      - Per-service rolling 60-second request count (sliding window)

    Usage:
        extractor = FeatureExtractor(redis_url="redis://localhost:6379/0")
        await extractor.start()
        features = await extractor.extract(log_dict)
        await extractor.stop()
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0") -> None:
        self._redis_url = redis_url
        self._redis: Any = None  # aioredis.Redis instance
        self._started = False

        # Local in-memory cache of service_name → id to reduce Redis RTTs.
        # Redis remains the source of truth; this is a read-through cache.
        self._service_cache: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect to Redis. Must be called before extract()."""
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
            )
            # Warm up the local cache from Redis
            await self._warm_cache()
            self._started = True
            logger.info(
                "FeatureExtractor connected to Redis",
                extra={"redis_url": self._redis_url},
            )
        except Exception as exc:
            logger.error(
                "FeatureExtractor failed to connect to Redis — "
                "rolling counts will default to 0",
                extra={"error": str(exc)},
            )
            # Non-fatal: proceed without Redis; features degrade gracefully

    async def stop(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
                logger.info("FeatureExtractor Redis connection closed")
            except Exception as exc:
                logger.warning(
                    "Error closing Redis connection",
                    extra={"error": str(exc)},
                )
            finally:
                self._redis = None
                self._started = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract(self, log_entry: dict[str, Any]) -> dict[str, Any]:
        """
        Extract the 6 ML feature values from a raw log entry dict.

        Args:
            log_entry: A parsed log dict with at minimum:
                       service, level, timestamp (ISO 8601 str or datetime),
                       response_time_ms (optional), error_code (optional)

        Returns:
            A dict with keys:
              hour_of_day, response_time_ms, error_code,
              log_level_encoded, request_count_last_60s, service_id_encoded
        """
        service = (log_entry.get("service") or "unknown").strip().lower()
        level_raw = (log_entry.get("level") or "INFO").strip().upper()
        timestamp_raw = log_entry.get("timestamp")
        response_time_raw = log_entry.get("response_time_ms")
        error_code_raw = log_entry.get("error_code")

        # 1. hour_of_day
        hour_of_day = self._extract_hour(timestamp_raw)

        # 2. response_time_ms — clamp negatives to 0
        try:
            response_time_ms = (
                max(0.0, float(response_time_raw))
                if response_time_raw is not None
                else 0.0
            )
        except (TypeError, ValueError):
            response_time_ms = 0.0

        # 3. error_code (bucket-encoded)
        try:
            raw_code = int(error_code_raw) if error_code_raw is not None else None
        except (TypeError, ValueError):
            raw_code = None
        error_code_encoded = _encode_error_code(raw_code)

        # 4. log_level_encoded
        log_level_encoded = LOG_LEVEL_ENCODING.get(level_raw, 1)  # default INFO=1

        # 5. request_count_last_60s (rolling window via Redis)
        request_count_last_60s = await self._increment_and_count(service)

        # 6. service_id_encoded
        service_id_encoded = await self._get_or_create_service_id(service)

        features = {
            "hour_of_day": hour_of_day,
            "response_time_ms": response_time_ms,
            "error_code": error_code_encoded,
            "log_level_encoded": log_level_encoded,
            "request_count_last_60s": request_count_last_60s,
            "service_id_encoded": service_id_encoded,
        }

        logger.debug(
            "Features extracted",
            extra={
                "service": service,
                "level": level_raw,
                "features": features,
            },
        )
        return features

    # ------------------------------------------------------------------
    # Feature helpers
    # ------------------------------------------------------------------

    def _extract_hour(self, timestamp_raw: Any) -> int:
        """
        Parse the timestamp and return the hour of the day (0–23, UTC).
        Falls back to the current UTC hour if parsing fails.
        """
        if timestamp_raw is None:
            return datetime.now(timezone.utc).hour

        if isinstance(timestamp_raw, datetime):
            dt = timestamp_raw
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.hour

        if isinstance(timestamp_raw, (int, float)):
            # Unix epoch seconds
            try:
                return datetime.fromtimestamp(timestamp_raw, tz=timezone.utc).hour
            except (OSError, OverflowError, ValueError):
                return datetime.now(timezone.utc).hour

        if isinstance(timestamp_raw, str):
            try:
                dt = datetime.fromisoformat(timestamp_raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.hour
            except (ValueError, AttributeError):
                pass

        logger.warning(
            "Could not parse timestamp — defaulting hour_of_day to current UTC hour",
            extra={"timestamp_raw": str(timestamp_raw)[:80]},
        )
        return datetime.now(timezone.utc).hour

    # ------------------------------------------------------------------
    # Redis: rolling 60-second counter
    # ------------------------------------------------------------------

    async def _increment_and_count(self, service: str) -> int:
        """
        Increment the per-service request counter and return the total
        number of requests from that service in the last 60 seconds.

        Implementation: Redis sorted set (ZSET) with timestamp scores.
          - ZADD  : add current timestamp as both score and member
          - ZREMRANGEBYSCORE : prune entries older than 60s
          - ZCARD : count remaining entries in the window

        This gives an O(log N) sliding-window counter without Lua scripts.
        """
        if self._redis is None:
            return 0

        key = _rolling_key(service)
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff = now_ts - _ROLLING_WINDOW_SECONDS

        try:
            pipe = self._redis.pipeline(transaction=False)
            # Add current event; use timestamp + tiny random jitter as member
            # to allow multiple events at the exact same millisecond.
            member = f"{now_ts:.6f}"
            pipe.zadd(key, {member: now_ts})
            # Remove events older than the 60s window
            pipe.zremrangebyscore(key, "-inf", cutoff)
            # Count events remaining in window
            pipe.zcard(key)
            # Set TTL so keys for inactive services expire automatically
            pipe.expire(key, _ROLLING_WINDOW_SECONDS * 2)
            results = await pipe.execute()
            count = results[2]  # zcard result
            return int(count)
        except Exception as exc:
            logger.warning(
                "Redis rolling counter error — returning 0",
                extra={"service": service, "error": str(exc)},
            )
            return 0

    # ------------------------------------------------------------------
    # Redis: service label encoding
    # ------------------------------------------------------------------

    async def _get_or_create_service_id(self, service: str) -> int:
        """
        Return a stable integer ID for a service name.

        IDs are stored in a Redis Hash so they persist across restarts.
        New services are assigned the next available integer ID atomically.

        Falls back to hash-based ID if Redis is unavailable.
        """
        # Check local in-memory cache first
        if service in self._service_cache:
            return self._service_cache[service]

        if self._redis is None:
            # Fallback: deterministic hash (no Redis)
            return abs(hash(service)) % 10_000

        try:
            # Try to get existing mapping
            existing = await self._redis.hget(_SERVICE_MAP_KEY, service)
            if existing is not None:
                service_id = int(existing)
                self._service_cache[service] = service_id
                return service_id

            # Atomically increment counter and assign new ID
            new_id = await self._redis.incr(_SERVICE_COUNTER_KEY)
            # Use HSETNX (set if not exists) to handle race conditions:
            # if another instance already assigned an ID between our HGET
            # and INCR, prefer the existing one.
            set_result = await self._redis.hsetnx(_SERVICE_MAP_KEY, service, new_id)
            if set_result:
                # We successfully set the new ID
                service_id = new_id
            else:
                # Another instance beat us — fetch the winning value
                existing = await self._redis.hget(_SERVICE_MAP_KEY, service)
                service_id = int(existing) if existing else new_id

            self._service_cache[service] = service_id
            logger.info(
                "New service registered",
                extra={"service": service, "service_id": service_id},
            )
            return service_id

        except Exception as exc:
            logger.warning(
                "Redis service ID lookup error — using hash fallback",
                extra={"service": service, "error": str(exc)},
            )
            fallback_id = abs(hash(service)) % 10_000
            self._service_cache[service] = fallback_id
            return fallback_id

    # ------------------------------------------------------------------
    # Cache warm-up
    # ------------------------------------------------------------------

    async def _warm_cache(self) -> None:
        """
        Load all known service → ID mappings from Redis into local cache.
        Called once on startup to avoid cold-start Redis RTTs.
        """
        if self._redis is None:
            return
        try:
            mapping = await self._redis.hgetall(_SERVICE_MAP_KEY)
            for svc, sid in mapping.items():
                try:
                    self._service_cache[svc] = int(sid)
                except (ValueError, TypeError):
                    pass
            logger.debug(
                "Service cache warmed from Redis",
                extra={"service_count": len(self._service_cache)},
            )
        except Exception as exc:
            logger.warning(
                "Could not warm service cache from Redis",
                extra={"error": str(exc)},
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def known_services(self) -> dict[str, int]:
        """Return a snapshot of the current service → ID mapping cache."""
        return dict(self._service_cache)

    def __repr__(self) -> str:
        return (
            f"FeatureExtractor("
            f"redis_url={self._redis_url!r}, "
            f"started={self._started}, "
            f"cached_services={len(self._service_cache)})"
        )
