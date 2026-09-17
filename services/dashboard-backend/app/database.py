"""
LogSentinel — Dashboard Backend: PostgreSQL Database Client
===========================================================
Async PostgreSQL client (asyncpg) for querying alert/anomaly history.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)


class DashboardDB:
    """Async PostgreSQL client for reading alert data."""

    def __init__(self, database_url: str) -> None:
        # asyncpg uses postgresql:// not postgresql+asyncpg://
        self._url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        self._pool: Optional[asyncpg.Pool] = None
        self.is_connected: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the connection pool and ensure tables exist."""
        try:
            self._pool = await asyncpg.create_pool(
                self._url,
                min_size=1,
                max_size=5,
                command_timeout=30,
            )
            await self._ensure_tables()
            self.is_connected = True
            logger.info("PostgreSQL pool created", extra={"dsn": self._url[:40]})
        except Exception as exc:
            logger.error("PostgreSQL connection failed", extra={"error": str(exc)})
            self.is_connected = False
            raise

    async def stop(self) -> None:
        """Close the connection pool gracefully."""
        if self._pool:
            await self._pool.close()
            self._pool = None
        self.is_connected = False
        logger.info("PostgreSQL pool closed")

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    async def _ensure_tables(self) -> None:
        """Create alerts table if it doesn't already exist."""
        ddl = """
        CREATE TABLE IF NOT EXISTS alerts (
            id          SERIAL PRIMARY KEY,
            alert_id    TEXT UNIQUE NOT NULL,
            log_id      TEXT,
            service     TEXT,
            level       TEXT,
            message     TEXT,
            score       DOUBLE PRECISION,
            anomaly_features JSONB,
            notified_via TEXT[],
            detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_detected_at ON alerts (detected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_service     ON alerts (service);
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)
        logger.debug("Alert table verified")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_recent_alerts(
        self, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Return the most recent *limit* alerts ordered by detected_at DESC."""
        assert self._pool is not None
        sql = """
            SELECT id, alert_id, log_id, service, level, message,
                   score, anomaly_features, notified_via, detected_at, created_at
            FROM alerts
            ORDER BY detected_at DESC
            LIMIT $1 OFFSET $2
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, limit, offset)
        return [dict(r) for r in rows]

    async def get_alerts_by_service(
        self, service: str, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Return alerts filtered by service name."""
        assert self._pool is not None
        sql = """
            SELECT id, alert_id, log_id, service, level, message,
                   score, anomaly_features, notified_via, detected_at, created_at
            FROM alerts
            WHERE service = $1
            ORDER BY detected_at DESC
            LIMIT $2 OFFSET $3
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, service, limit, offset)
        return [dict(r) for r in rows]

    async def get_alerts_by_time_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return alerts within the given UTC time range."""
        assert self._pool is not None
        sql = """
            SELECT id, alert_id, log_id, service, level, message,
                   score, anomaly_features, notified_via, detected_at, created_at
            FROM alerts
            WHERE detected_at >= $1 AND detected_at <= $2
            ORDER BY detected_at DESC
            LIMIT $3 OFFSET $4
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, start, end, limit, offset)
        return [dict(r) for r in rows]

    async def count_alerts(self) -> int:
        """Return total number of alerts ever recorded."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM alerts")

    async def count_alerts_last_hour(self) -> int:
        """Return number of alerts in the last hour."""
        assert self._pool is not None
        sql = """
            SELECT COUNT(*) FROM alerts
            WHERE detected_at >= now() - INTERVAL '1 hour'
        """
        async with self._pool.acquire() as conn:
            return await conn.fetchval(sql)

    async def get_alert_by_id(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Return a single alert by its string alert_id field."""
        assert self._pool is not None
        sql = """
            SELECT id, alert_id, log_id, service, level, message,
                   score, anomaly_features, notified_via, detected_at, created_at
            FROM alerts
            WHERE alert_id = $1
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, alert_id)
        return dict(row) if row else None
