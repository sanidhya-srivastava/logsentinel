"""
LogSentinel — Dashboard Backend: Elasticsearch Client
=====================================================
Re-exports DashboardESClient from redis_cache for clean import paths.
The actual implementation lives in redis_cache.py to colocate all
external-client helpers in one module.
"""

from app.redis_cache import DashboardESClient  # noqa: F401 — re-export

__all__ = ["DashboardESClient"]
