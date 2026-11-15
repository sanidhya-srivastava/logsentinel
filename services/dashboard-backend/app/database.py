"""
LogSentinel — Dashboard Backend: PostgreSQL Database Client
===========================================================
Async PostgreSQL client (asyncpg) for querying alert/anomaly history.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None

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
        if asyncpg is None:
            logger.warning("asyncpg not installed — PostgreSQL database disabled")
            self.is_connected = False
            return
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

    _ALERT_COLS = """
        id, alert_id, log_id, service, level, message,
        anomaly_score, anomaly_score AS score,
        host, response_time_ms, error_code, detected_at,
        slack_sent, email_sent, deduplicated,
        notification_channels, notification_channels AS notified_via,
        features, features AS anomaly_features, created_at
    """

    async def _ensure_tables(self) -> None:
        """Create alerts table matching infra/postgres/init.sql if absent."""
        if not self._pool:
            return
        ddl = """
        CREATE TABLE IF NOT EXISTS alerts (
            id                    SERIAL PRIMARY KEY,
            alert_id              TEXT UNIQUE NOT NULL,
            log_id                TEXT,
            service               TEXT,
            level                 TEXT,
            message               TEXT,
            anomaly_score         DOUBLE PRECISION,
            host                  TEXT,
            response_time_ms      DOUBLE PRECISION,
            error_code            INTEGER,
            detected_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            slack_sent            BOOLEAN NOT NULL DEFAULT FALSE,
            email_sent            BOOLEAN NOT NULL DEFAULT FALSE,
            deduplicated          BOOLEAN NOT NULL DEFAULT FALSE,
            notification_channels TEXT[],
            features              JSONB,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_detected_at ON alerts (detected_at DESC);
        CREATE INDEX IF NOT EXISTS idx_alerts_service     ON alerts (service);
        """
        async with self._pool.acquire() as conn:
            await conn.execute(ddl)
        logger.debug("Alert table verified")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def _fetch_all(self, sql: str, *args: Any) -> List[Dict[str, Any]]:
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def get_recent_alerts(
        self, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Return the most recent *limit* alerts ordered by detected_at DESC."""
        sql = f"SELECT {self._ALERT_COLS} FROM alerts ORDER BY detected_at DESC LIMIT $1 OFFSET $2"
        return await self._fetch_all(sql, limit, offset)

    async def get_alerts_by_service(
        self, service: str, limit: int = 20, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Return alerts filtered by service name."""
        sql = f"SELECT {self._ALERT_COLS} FROM alerts WHERE service = $1 ORDER BY detected_at DESC LIMIT $2 OFFSET $3"
        return await self._fetch_all(sql, service, limit, offset)

    async def get_alerts_by_time_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Return alerts within the given UTC time range."""
        sql = f"SELECT {self._ALERT_COLS} FROM alerts WHERE detected_at >= $1 AND detected_at <= $2 ORDER BY detected_at DESC LIMIT $3 OFFSET $4"
        return await self._fetch_all(sql, start, end, limit, offset)

    async def count_alerts(self) -> int:
        """Return total number of alerts ever recorded."""
        if not self._pool:
            return 0
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM alerts") or 0)

    async def count_alerts_last_hour(self) -> int:
        """Return number of alerts in the last hour."""
        if not self._pool:
            return 0
        sql = """
            SELECT COUNT(*) FROM alerts
            WHERE detected_at >= now() - INTERVAL '1 hour'
        """
        async with self._pool.acquire() as conn:
            return int(await conn.fetchval(sql) or 0)

    async def get_alert_by_id(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Return a single alert by its string alert_id field."""
        if not self._pool:
            return None
        sql = f"SELECT {self._ALERT_COLS} FROM alerts WHERE alert_id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, alert_id)
        return dict(row) if row else None
