# =============================================================================
# System health — DB, Redis, Qdrant, ingestion worker, LLM provider
# =============================================================================
from __future__ import annotations

import time

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


async def system_health() -> dict:
    """Probes a los servicios; status global ok | degraded | down."""
    checks: list[dict] = []
    started = time.monotonic()

    # 1) Database
    t0 = time.monotonic()
    try:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            await session.execute(text("SELECT 1"))
        finally:
            await session.close()
        checks.append(
            {
                "name": "database",
                "status": "ok",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": "PostgreSQL reachable",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "database",
                "status": "down",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": str(exc)[:200],
            }
        )

    # 2) Redis
    t0 = time.monotonic()
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        await client.ping()
        checks.append(
            {
                "name": "redis",
                "status": "ok",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": "PING ok",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "redis",
                "status": "down",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": str(exc)[:200],
            }
        )

    # 3) Qdrant
    t0 = time.monotonic()
    try:
        from src.infrastructure.qdrant.vector_store import (
            RAG_DOCUMENTS_COLLECTION,
            _get_client,
        )

        client = await _get_client()
        await client.collection_exists(RAG_DOCUMENTS_COLLECTION)
        checks.append(
            {
                "name": "qdrant",
                "status": "ok",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": "collection reachable",
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "qdrant",
                "status": "down",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": str(exc)[:200],
            }
        )

    # 4) Ingestion worker (heartbeat)
    t0 = time.monotonic()
    settings = get_settings()
    try:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT last_seen_at FROM worker_heartbeats "
                        "WHERE worker_name = 'ingestion'"
                    )
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None:
            checks.append(
                {
                    "name": "ingestion_worker",
                    "status": "degraded",
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "detail": "sin heartbeat registrado",
                }
            )
        else:
            from datetime import datetime, timedelta, timezone

            age = datetime.now(timezone.utc) - row.last_seen_at
            stale = age > timedelta(minutes=settings.OBS_WORKER_STALE_MINUTES)
            checks.append(
                {
                    "name": "ingestion_worker",
                    "status": "degraded" if stale else "ok",
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                    "detail": f"last_seen hace {int(age.total_seconds())}s",
                }
            )
    except Exception as exc:
        checks.append(
            {
                "name": "ingestion_worker",
                "status": "degraded",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "detail": str(exc)[:200],
            }
        )

    # 5) LLM provider (config)
    if settings.LITELLM_API_BASE and settings.LITELLM_API_KEY:
        checks.append(
            {
                "name": "llm_provider",
                "status": "ok",
                "latency_ms": 0.0,
                "detail": f"litellm={settings.LITELLM_API_BASE}",
            }
        )
    else:
        checks.append(
            {
                "name": "llm_provider",
                "status": "degraded",
                "latency_ms": 0.0,
                "detail": "LITELLM_API_BASE / LITELLM_API_KEY no configurados",
            }
        )

    statuses = [c["status"] for c in checks]
    if "down" in statuses:
        overall = "down"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return {
        "status": overall,
        "checked_at": __import__(
            "datetime"
        ).datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "total_ms": round((time.monotonic() - started) * 1000, 1),
        "checks": checks,
    }
