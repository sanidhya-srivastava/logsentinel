"""
LogSentinel — Dashboard Backend
=================================
FastAPI application providing query endpoints for Grafana and frontend.

Endpoints:
  GET  /logs        — paginated log search from Elasticsearch
  GET  /anomalies   — list of detected anomalies from PostgreSQL
  GET  /stats       — system stats (log rate, anomaly rate)
  GET  /health      — liveness/readiness probe
  GET  /metrics     — Prometheus metrics
"""

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.database import DashboardDB
from app.elasticsearch_client import DashboardESClient
from app.logger import get_logger
from app.metrics import REQUEST_COUNT, REQUEST_LATENCY
from app.redis_cache import RedisCache
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import make_asgi_app

logger = get_logger(__name__)

es_client: Optional[DashboardESClient] = None
db_client: Optional[DashboardDB] = None
cache: Optional[RedisCache] = None
FRONTEND_DIR = Path(__file__).parent / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global es_client, db_client, cache

    logger.info("Starting Dashboard Backend", extra={"service": settings.SERVICE_NAME})

    es_client = DashboardESClient(
        host=settings.ELASTICSEARCH_HOST,
        port=settings.ELASTICSEARCH_PORT,
        scheme=settings.ELASTICSEARCH_SCHEME,
    )
    db_client = DashboardDB(database_url=settings.DATABASE_URL)
    cache = RedisCache(
        redis_url=settings.REDIS_URL, default_ttl=settings.DASHBOARD_STATS_CACHE_TTL
    )

    for name, client in [
        ("elasticsearch", es_client),
        ("database", db_client),
        ("cache", cache),
    ]:
        try:
            await client.start()
            logger.info(f"{name} connected")
        except Exception as exc:
            logger.error(f"Failed to connect {name}", extra={"error": str(exc)})

    yield

    for name, client in [
        ("cache", cache),
        ("database", db_client),
        ("elasticsearch", es_client),
    ]:
        if client:
            try:
                await client.stop()
            except Exception:
                pass

    logger.info("Dashboard Backend shut down")


app = FastAPI(
    title="LogSentinel — Dashboard Backend",
    description=(
        "Query API for Grafana dashboards and frontend. "
        "Provides log search, anomaly listing, and system stats."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(method=request.method, endpoint=request.url.path).observe(
        duration
    )
    return response


metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/", tags=["Frontend"], include_in_schema=False)
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/dashboard", tags=["Frontend"], include_in_schema=False)
async def dashboard():
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/api", tags=["Meta"])
async def api_meta():
    return {
        "service": "LogSentinel Dashboard Backend",
        "version": "1.0.0",
        "docs": "/docs",
        "frontend": "/",
        "dashboard": "/dashboard",
    }


@app.get("/health", tags=["Meta"])
async def health():
    es_ok = es_client is not None and es_client.is_connected
    db_ok = db_client is not None and db_client.is_connected
    cache_ok = cache is not None and cache.is_connected
    all_ok = es_ok and db_ok
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status": "healthy" if all_ok else "degraded",
            "service": settings.SERVICE_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {
                "elasticsearch": "connected" if es_ok else "disconnected",
                "database": "connected" if db_ok else "disconnected",
                "cache": "connected" if cache_ok else "disconnected",
            },
        },
    )


@app.get("/logs", tags=["Logs"])
async def get_logs(
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    size: int = Query(default=20, ge=1, le=100, description="Results per page"),
    level: Optional[str] = Query(
        default=None, description="Filter by log level (INFO, ERROR, etc.)"
    ),
    service: Optional[str] = Query(default=None, description="Filter by service name"),
    start: Optional[str] = Query(
        default=None, description="Start time ISO 8601 (e.g. 2024-01-01T00:00:00Z)"
    ),
    end: Optional[str] = Query(default=None, description="End time ISO 8601"),
    q: Optional[str] = Query(default=None, description="Full-text search query"),
):
    """
    Paginated log search from Elasticsearch.
    Supports filtering by level, service, time range, and full-text search.
    """
    if es_client is None:
        raise HTTPException(status_code=503, detail="Elasticsearch not available")

    must_clauses = []

    if level:
        must_clauses.append({"term": {"level": level.upper()}})
    if service:
        must_clauses.append({"term": {"service": service.lower()}})
    if q:
        must_clauses.append({"match": {"message": q}})

    range_filter = {}
    if start:
        range_filter["gte"] = start
    if end:
        range_filter["lte"] = end
    if range_filter:
        must_clauses.append({"range": {"@timestamp": range_filter}})

    query = {"bool": {"must": must_clauses}} if must_clauses else {"match_all": {}}

    result = await es_client.search_logs(query=query, page=page, size=size)

    return {
        "page": page,
        "size": size,
        "total": result.get("total", 0),
        "items": result.get("hits", []),
    }


@app.get("/anomalies", tags=["Anomalies"])
async def get_anomalies(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    service: Optional[str] = Query(default=None),
    start: Optional[str] = Query(default=None, description="ISO 8601 start time"),
    end: Optional[str] = Query(default=None, description="ISO 8601 end time"),
):
    """
    Paginated list of detected anomalies from PostgreSQL.
    Ordered by detected_at descending.
    """
    if db_client is None:
        raise HTTPException(status_code=503, detail="Database not available")

    offset = (page - 1) * size

    if start or end:
        try:
            start_dt = (
                datetime.fromisoformat(start.replace("Z", "+00:00"))
                if start
                else datetime(2000, 1, 1, tzinfo=timezone.utc)
            )
            end_dt = (
                datetime.fromisoformat(end.replace("Z", "+00:00"))
                if end
                else datetime.now(timezone.utc)
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid datetime format: {exc}"
            )
        alerts = await db_client.get_alerts_by_time_range(
            start_dt, end_dt, limit=size, offset=offset
        )
    elif service:
        alerts = await db_client.get_alerts_by_service(
            service=service, limit=size, offset=offset
        )
    else:
        alerts = await db_client.get_recent_alerts(limit=size, offset=offset)

    total = await db_client.count_alerts()

    return {
        "page": page,
        "size": size,
        "total": total,
        "items": [_serialise_alert(a) for a in alerts],
    }


@app.get("/stats", tags=["Stats"])
async def get_stats(
    window_minutes: int = Query(
        default=60,
        ge=1,
        le=1440,
        description="Time window in minutes for rate calculations",
    ),
):
    """
    System-wide statistics: log rate, anomaly rate, top services.
    Response is cached in Redis for DASHBOARD_STATS_CACHE_TTL seconds.
    """
    cache_key = f"stats:{window_minutes}"

    # Try cache first
    if cache and cache.is_connected:
        cached = await cache.get(cache_key)
        if cached:
            logger.debug("Stats served from cache", extra={"cache_key": cache_key})
            return cached

    # Build fresh stats
    stats = {
        "window_minutes": window_minutes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Log counts from Elasticsearch
    if es_client and es_client.is_connected:
        logs_last_minute = await es_client.count_logs(
            query={"range": {"@timestamp": {"gte": "now-1m"}}}
        )
        logs_last_hour = await es_client.count_logs(
            query={"range": {"@timestamp": {"gte": "now-1h"}}}
        )
        logs_window = await es_client.count_logs(
            query={"range": {"@timestamp": {"gte": f"now-{window_minutes}m"}}}
        )
        stats.update(
            {
                "logs_last_minute": logs_last_minute,
                "logs_last_hour": logs_last_hour,
                f"logs_last_{window_minutes}m": logs_window,
                "log_rate_per_second": round(logs_last_minute / 60, 2),
            }
        )
    else:
        stats.update(
            {"logs_last_minute": 0, "logs_last_hour": 0, "log_rate_per_second": 0}
        )

    # Anomaly counts from PostgreSQL
    if db_client and db_client.is_connected:
        anomalies_last_hour = await db_client.count_alerts_last_hour()
        total_anomalies = await db_client.count_alerts()
        anomaly_rate = round(
            anomalies_last_hour / max(stats.get("logs_last_hour", 1), 1) * 100, 2
        )
        stats.update(
            {
                "anomalies_last_hour": anomalies_last_hour,
                "total_anomalies": total_anomalies,
                "anomaly_rate_percent": anomaly_rate,
            }
        )
    else:
        stats.update(
            {"anomalies_last_hour": 0, "total_anomalies": 0, "anomaly_rate_percent": 0}
        )

    # Cache the result
    if cache and cache.is_connected:
        await cache.set(cache_key, stats)

    return stats


def _serialise_alert(alert: dict) -> dict:
    """Convert asyncpg Record / dict to JSON-serialisable dict."""
    result = {}
    for k, v in alert.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception",
        extra={"path": request.url.path, "error": str(exc)},
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500, content={"detail": "An internal server error occurred."}
    )
