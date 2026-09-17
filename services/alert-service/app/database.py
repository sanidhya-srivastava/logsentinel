"""
LogSentinel — Alert Service: Database Client
=============================================
Async PostgreSQL client for persisting alert records.

Uses asyncpg directly (via SQLAlchemy async engine) to store all
anomaly alerts — including deduplicated ones — for historical querying
and audit purposes.

Schema (auto-created on startup):
  Table: alerts
    id              UUID PRIMARY KEY (auto)
    alert_id        UUID UNIQUE NOT NULL
    log_id          UUID
    service         VARCHAR(255)
    level           VARCHAR(20)
    message         TEXT
    anomaly_score   FLOAT
    host            VARCHAR(255)
    response_time_ms FLOAT
    error_code      INTEGER
    detected_at     TIMESTAMPTZ
    slack_sent      BOOLEAN DEFAULT FALSE
    email_sent      BOOLEAN DEFAULT FALSE
    deduplicated    BOOLEAN DEFAULT FALSE
    notification_channels TEXT[]
    features        JSONB
    created_at      TIMESTAMPTZ DEFAULT NOW()

Usage:
    db = DatabaseClient(database_url="postgresql+asyncpg://...")
    await db.start()
    await db.ensure_tables()
    await db.save_alert(alert_dict)
    alerts = await db.get_recent_alerts(limit=50)
    await db.stop()
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL — table creation SQL
# ---------------------------------------------------------------------------

CREATE_ALERTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS alerts (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id             UUID UNIQUE NOT NULL,
    log_id               UUID,
    service              VARCHAR(255),
    level                VARCHAR(20),
    message              TEXT,
    anomaly_score        DOUBLE PRECISION,
    host                 VARCHAR(255),
    response_time_ms     DOUBLE PRECISION,
    error_code           INTEGER,
    detected_at          TIMESTAMPTZ,
    slack_sent           BOOLEAN DEFAULT FALSE,
    email_sent           BOOLEAN DEFAULT FALSE,
    deduplicated         BOOLEAN DEFAULT FALSE,
    notification_channels TEXT[],
    features             JSONB,
    created_at           TIMESTAMPTZ DEFAULT NOW()
);
"""

CREATE_ALERTS_INDEXES_SQL = [
    # Index on service for filtering by service name
    """
    CREATE INDEX IF NOT EXISTS idx_alerts_service
        ON alerts (service);
    """,
    # Index on detected_at for time-range queries
    """
    CREATE INDEX IF NOT EXISTS idx_alerts_detected_at
        ON alerts (detected_at DESC);
    """,
    # Index on level for filtering by log severity
    """
    CREATE INDEX IF NOT EXISTS idx_alerts_level
        ON alerts (level);
    """,
    # Composite index for the most common dashboard query pattern
    """
    CREATE INDEX IF NOT EXISTS idx_alerts_service_detected_at
        ON alerts (service, detected_at DESC);
    """,
    # Index on deduplicated flag for quick counting
    """
    CREATE INDEX IF NOT EXISTS idx_alerts_deduplicated
        ON alerts (deduplicated);
    """,
]

INSERT_ALERT_SQL = """
INSERT INTO alerts (
    alert_id,
    log_id,
    service,
    level,
    message,
    anomaly_score,
    host,
    response_time_ms,
    error_code,
    detected_at,
    slack_sent,
    email_sent,
    deduplicated,
    notification_channels,
    features
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
    $11, $12, $13, $14, $15
)
ON CONFLICT (alert_id) DO UPDATE SET
    slack_sent           = EXCLUDED.slack_sent,
    email_sent           = EXCLUDED.email_sent,
    deduplicated         = EXCLUDED.deduplicated,
    notification_channels = EXCLUDED.notification_channels;
"""

SELECT_RECENT_ALERTS_SQL = """
SELECT
    id::text,
    alert_id::text,
    log_id::text,
    service,
    level,
    message,
    anomaly_score,
    host,
    response_time_ms,
    error_code,
    detected_at,
    slack_sent,
    email_sent,
    deduplicated,
    notification_channels,
    features,
    created_at
FROM alerts
ORDER BY detected_at DESC
LIMIT $1 OFFSET $2;
"""

SELECT_ALERTS_BY_SERVICE_SQL = """
SELECT
    id::text,
    alert_id::text,
    log_id::text,
    service,
    level,
    message,
    anomaly_score,
    detected_at,
    slack_sent,
    email_sent,
    deduplicated,
    created_at
FROM alerts
WHERE service = $1
ORDER BY detected_at DESC
LIMIT $2 OFFSET $3;
"""

SELECT_ALERTS_BY_TIME_RANGE_SQL = """
SELECT
    id::text,
    alert_id::text,
    log_id::text,
    service,
    level,
    message,
    anomaly_score,
    host,
    response_time_ms,
    error_code,
    detected_at,
    slack_sent,
    email_sent,
    deduplicated,
    notification_channels,
    features,
    created_at
FROM alerts
WHERE detected_at BETWEEN $1 AND $2
ORDER BY detected_at DESC
LIMIT $3 OFFSET $4;
"""

COUNT_ALERTS_SQL = """
SELECT COUNT(*) FROM alerts WHERE deduplicated = FALSE;
"""

COUNT_ALERTS_LAST_HOUR_SQL = """
SELECT COUNT(*) FROM alerts
WHERE detected_at >= NOW() - INTERVAL '1 hour'
  AND deduplicated = FALSE;
"""


# ---------------------------------------------------------------------------
# Database Client
# ---------------------------------------------------------------------------


class DatabaseClient:
    """
    Async PostgreSQL client for the alert service.

    Uses asyncpg directly for high-performance async database operations.
    Connection pooling is managed by asyncpg's built-in pool.

    Features:
      - Auto-creates the alerts table and indexes on startup
      - Upserts alerts (idempotent on alert_id conflict)
      - Provides paginated query methods for the dashboard API
      - Handles JSON serialisation for the features JSONB column

    Args:
        database_url:    SQLAlchemy-style async DSN
                         (e.g. "postgresql+asyncpg://user:pass@host:5432/db").
                         The "+asyncpg" dialect prefix is stripped internally
                         since we use asyncpg directly.
        min_pool_size:   Minimum number of connections to keep in the pool.
        max_pool_size:   Maximum number of connections in the pool.
        command_timeout: Per-query timeout in seconds.
    """

    def __init__(
        self,
        database_url: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
        command_timeout: float = 30.0,
    ) -> None:
        # Convert SQLAlchemy-style URL to asyncpg-native URL
        self._database_url = database_url.replace(
            "postgresql+asyncpg://", "postgresql://"
        ).replace("postgres+asyncpg://", "postgresql://")
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._command_timeout = command_timeout

        self._pool: Any = None  # asyncpg.Pool
        self._started: bool = False

        logger.debug(
            "DatabaseClient initialised",
            extra={
                "min_pool_size": min_pool_size,
                "max_pool_size": max_pool_size,
            },
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """True if the connection pool is initialised."""
        return self._started and self._pool is not None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Create the asyncpg connection pool.

        Raises:
            ImportError:   If asyncpg is not installed.
            Exception:     If the database is unreachable.
        """
        if self._started:
            logger.debug("DatabaseClient already started — skipping")
            return

        try:
            import asyncpg  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "asyncpg is required for the database client. Run: pip install asyncpg"
            ) from exc

        logger.info(
            "Connecting to PostgreSQL",
            extra={"min_size": self._min_pool_size, "max_size": self._max_pool_size},
        )

        try:
            self._pool = await asyncpg.create_pool(
                dsn=self._database_url,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
                command_timeout=self._command_timeout,
                # Register a JSON codec so JSONB columns return dicts
                init=_init_connection,
            )
            self._started = True
            logger.info("PostgreSQL connection pool established")
        except Exception as exc:
            self._pool = None
            self._started = False
            logger.error(
                "Failed to connect to PostgreSQL",
                extra={"error": str(exc)},
            )
            raise

    async def stop(self) -> None:
        """Close all connections in the pool."""
        if not self._started or self._pool is None:
            return
        try:
            await self._pool.close()
            logger.info("PostgreSQL connection pool closed")
        except Exception as exc:
            logger.error(
                "Error closing PostgreSQL pool",
                extra={"error": str(exc)},
            )
        finally:
            self._pool = None
            self._started = False

    # ------------------------------------------------------------------
    # Schema management
    # ------------------------------------------------------------------

    async def ensure_tables(self) -> None:
        """
        Create the alerts table and indexes if they do not already exist.

        Idempotent — safe to call on every service startup.
        Uses IF NOT EXISTS so it never fails on an already-initialised database.
        """
        if self._pool is None:
            logger.warning("Cannot ensure tables — database not connected")
            return

        async with self._pool.acquire() as conn:
            # Create the pgcrypto extension for gen_random_uuid()
            try:
                await conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
            except Exception as exc:
                logger.warning(
                    (
                        "Could not create pgcrypto extension "
                        "(may already exist or insufficient permissions)"
                    ),
                    extra={"error": str(exc)},
                )

            # Create table
            await conn.execute(CREATE_ALERTS_TABLE_SQL)
            logger.info("alerts table verified/created")

            # Create indexes
            for idx_sql in CREATE_ALERTS_INDEXES_SQL:
                try:
                    await conn.execute(idx_sql)
                except Exception as exc:
                    logger.warning(
                        "Index creation skipped (may already exist)",
                        extra={"error": str(exc)},
                    )

            logger.info("Database schema initialised")

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def save_alert(self, alert: dict[str, Any]) -> bool:
        """
        Persist an anomaly alert to the PostgreSQL alerts table.

        Uses INSERT ... ON CONFLICT DO UPDATE (upsert) so that if the same
        alert_id is processed twice (e.g. after a consumer restart), the
        notification status fields are simply updated.

        Args:
            alert: The processed alert dict. Required fields:
                   alert_id, service, level, message, anomaly_score,
                   detected_at. All other fields are optional.

        Returns:
            True on success, False on failure.
        """
        if self._pool is None:
            logger.warning(
                "Cannot save alert — database not connected",
                extra={"alert_id": alert.get("alert_id")},
            )
            return False

        try:
            import json
            import uuid

            # Parse alert_id — must be a valid UUID
            raw_alert_id = alert.get("alert_id")
            try:
                alert_id = uuid.UUID(str(raw_alert_id))
            except (ValueError, AttributeError):
                import uuid as uuid_module

                alert_id = uuid_module.uuid4()
                logger.warning(
                    "Invalid alert_id — generated new UUID",
                    extra={"raw_alert_id": str(raw_alert_id)},
                )

            # Parse log_id
            raw_log_id = alert.get("log_id")
            try:
                log_id = uuid.UUID(str(raw_log_id)) if raw_log_id else None
            except (ValueError, AttributeError):
                log_id = None

            # Parse detected_at
            detected_at_raw = alert.get("detected_at")
            try:
                if isinstance(detected_at_raw, str):
                    detected_at = datetime.fromisoformat(
                        detected_at_raw.replace("Z", "+00:00")
                    )
                elif isinstance(detected_at_raw, datetime):
                    detected_at = detected_at_raw
                else:
                    detected_at = datetime.now(timezone.utc)
            except (ValueError, AttributeError):
                detected_at = datetime.now(timezone.utc)

            # Notification channel flags
            channels: list[str] = alert.get("notification_channels") or []
            slack_sent = "slack" in channels
            email_sent = "email" in channels
            deduplicated = bool(alert.get("deduplicated", False))

            # features JSONB — serialise to JSON string for asyncpg
            features = alert.get("features")
            features_json = json.dumps(features) if features else None

            # Safely cast numeric fields
            anomaly_score = _safe_float(alert.get("anomaly_score"))
            response_time_ms = _safe_float(alert.get("response_time_ms"))
            error_code = _safe_int(alert.get("error_code"))

            async with self._pool.acquire() as conn:
                await conn.execute(
                    INSERT_ALERT_SQL,
                    alert_id,  # $1  alert_id UUID
                    log_id,  # $2  log_id UUID
                    _safe_str(alert.get("service")),  # $3  service
                    _safe_str(alert.get("level")),  # $4  level
                    _safe_str(alert.get("message")),  # $5  message
                    anomaly_score,  # $6  anomaly_score
                    _safe_str(alert.get("host")),  # $7  host
                    response_time_ms,  # $8  response_time_ms
                    error_code,  # $9  error_code
                    detected_at,  # $10 detected_at
                    slack_sent,  # $11 slack_sent
                    email_sent,  # $12 email_sent
                    deduplicated,  # $13 deduplicated
                    channels or None,  # $14 notification_channels TEXT[]
                    features_json,  # $15 features JSONB
                )

            logger.debug(
                "Alert persisted to PostgreSQL",
                extra={
                    "alert_id": str(alert_id),
                    "service": alert.get("service"),
                    "deduplicated": deduplicated,
                    "slack_sent": slack_sent,
                    "email_sent": email_sent,
                },
            )
            return True

        except Exception as exc:
            logger.error(
                "Failed to save alert to PostgreSQL",
                extra={
                    "alert_id": str(alert.get("alert_id")),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_recent_alerts(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Return the most recent alerts ordered by detected_at descending.

        Args:
            limit:  Maximum number of records to return (default: 50).
            offset: Number of records to skip for pagination (default: 0).

        Returns:
            List of alert dicts. Empty list on error or no results.
        """
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(SELECT_RECENT_ALERTS_SQL, limit, offset)
                return [dict(row) for row in rows]
        except Exception as exc:
            logger.error(
                "Failed to fetch recent alerts",
                extra={"error": str(exc)},
            )
            return []

    async def get_alerts_by_service(
        self,
        service: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return alerts for a specific service."""
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    SELECT_ALERTS_BY_SERVICE_SQL, service, limit, offset
                )
                return [dict(row) for row in rows]
        except Exception as exc:
            logger.error(
                "Failed to fetch alerts by service",
                extra={"service": service, "error": str(exc)},
            )
            return []

    async def get_alerts_by_time_range(
        self,
        start: datetime,
        end: datetime,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Return alerts detected within a time range.

        Args:
            start:  Start of the time range (inclusive).
            end:    End of the time range (inclusive).
            limit:  Maximum records to return.
            offset: Pagination offset.

        Returns:
            List of alert dicts.
        """
        if self._pool is None:
            return []
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    SELECT_ALERTS_BY_TIME_RANGE_SQL, start, end, limit, offset
                )
                return [dict(row) for row in rows]
        except Exception as exc:
            logger.error(
                "Failed to fetch alerts by time range",
                extra={"error": str(exc)},
            )
            return []

    async def count_alerts(self) -> int:
        """Return the total count of non-deduplicated alerts."""
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(COUNT_ALERTS_SQL)
                return int(row[0]) if row else 0
        except Exception as exc:
            logger.error(
                "Failed to count alerts",
                extra={"error": str(exc)},
            )
            return 0

    async def count_alerts_last_hour(self) -> int:
        """Return the count of unique alerts detected in the last hour."""
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(COUNT_ALERTS_LAST_HOUR_SQL)
                return int(row[0]) if row else 0
        except Exception as exc:
            logger.error(
                "Failed to count alerts in last hour",
                extra={"error": str(exc)},
            )
            return 0

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "DatabaseClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"DatabaseClient("
            f"connected={self.is_connected}, "
            f"pool_min={self._min_pool_size}, "
            f"pool_max={self._max_pool_size})"
        )


# ---------------------------------------------------------------------------
# asyncpg helpers
# ---------------------------------------------------------------------------


async def _init_connection(conn: Any) -> None:
    """
    Connection initialiser for the asyncpg pool.

    Registers codecs so that:
      - JSONB columns are automatically decoded to Python dicts
      - UUID columns are returned as strings (not uuid.UUID objects)
        for JSON serialisation convenience
    """
    import json

    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


# ---------------------------------------------------------------------------
# Safe cast helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    """Cast to float; return None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    """Cast to int; return None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_str(value: Any, max_len: int = 255) -> str | None:
    """Cast to stripped string; return None if blank."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]
