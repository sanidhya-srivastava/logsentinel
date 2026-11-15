"""
LogSentinel — Dashboard Backend: Redis Cache
============================================
Async Redis cache wrapper for system stats and caching.
"""

import json
from typing import Any, Optional
from app.logger import get_logger
from app.metrics import CACHE_HIT_COUNT, CACHE_MISS_COUNT

logger = get_logger(__name__)


class RedisCache:
    """Async Redis cache wrapper for dashboard stats."""

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
            logger.info("Redis cache connected", extra={"redis_url": self._redis_url})
        except Exception as exc:
            logger.warning(
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
                CACHE_HIT_COUNT.inc()
                return json.loads(raw)
            CACHE_MISS_COUNT.inc()
            return None
        except Exception as exc:
            logger.warning("Redis GET error", extra={"key": key, "error": str(exc)})
            return None

    async def set(self, key: str, value: dict, ttl: Optional[int] = None) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(
                key, json.dumps(value, default=str), ex=ttl or self._default_ttl
            )
        except Exception as exc:
            logger.warning("Redis SET error", extra={"key": key, "error": str(exc)})
