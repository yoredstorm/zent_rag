# =============================================================================
# Multi-Region & Edge Caching — cache de respuestas en el edge (Redis +
# headers CDN-friendly) y failover regional con healthchecks.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

PLAN_CACHE_TTL = {"trial": 60, "starter": 300, "pro": 900, "enterprise": 1800}
DEFAULT_CACHE_TTL = 300


# ---------------------------------------------------------------------------
# Edge cache (Redis)
# ---------------------------------------------------------------------------
def cache_key(organization_id: UUID, deployment_id: UUID, version_id: UUID, input_text: str) -> str:
    digest = hashlib.sha256(input_text.encode("utf-8")).hexdigest()[:24]
    return f"rag:edge:{organization_id}:{deployment_id}:{version_id}:{digest}"


def bypass_requested(request) -> bool:
    cache_control = request.headers.get("cache-control", "")
    return "no-cache" in cache_control or request.query_params.get("cache") == "false"


async def ttl_for_org(organization_id: UUID) -> int:
    session = await get_async_session()
    try:
        plan = (
            await session.execute(
                text(
                    "SELECT p.name FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid "
                    "AND s.status IN ('trialing', 'active') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        return PLAN_CACHE_TTL.get(plan or "", DEFAULT_CACHE_TTL)
    except Exception:  # noqa: BLE001
        return DEFAULT_CACHE_TTL
    finally:
        await session.close()


async def get_cached(key: str) -> dict | None:
    try:
        client = await _get_redis()
        raw = await client.get(key)
        if not raw:
            return None
        return json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


async def set_cached(key: str, payload: dict, ttl: int) -> None:
    try:
        client = await _get_redis()
        await client.set(key, json.dumps(payload, default=str), ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Edge cache set failed", error=str(exc)[:150])


async def bump_stats(hit: bool) -> None:
    try:
        client = await _get_redis()
        await client.incr("rag:edge:hits" if hit else "rag:edge:misses")
    except Exception:  # noqa: BLE001
        pass


async def cache_stats() -> dict:
    try:
        client = await _get_redis()
        hits = int(await client.get("rag:edge:hits") or 0)
        misses = int(await client.get("rag:edge:misses") or 0)
    except Exception:  # noqa: BLE001
        hits = misses = 0
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "total": total,
        "hit_ratio": round(hits / total, 4) if total else 0.0,
    }


# ---------------------------------------------------------------------------
# Regiones + replicas + failover
# ---------------------------------------------------------------------------
async def list_regions() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT r.id, r.code, r.name, r.status, r.priority, "
                    "rr.id AS replica_id, rr.kind, rr.endpoint, rr.healthy, "
                    "rr.last_latency_ms, rr.last_health_at "
                    "FROM regions r LEFT JOIN region_replicas rr ON rr.region_id = r.id "
                    "ORDER BY r.priority, r.code"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    regions: dict[str, dict] = {}
    for r in rows:
        entry = regions.setdefault(
            r.code,
            {
                "id": str(r.id),
                "code": r.code,
                "name": r.name,
                "status": r.status,
                "priority": int(r.priority),
                "replicas": [],
            },
        )
        if r.replica_id:
            entry["replicas"].append(
                {
                    "id": str(r.replica_id),
                    "kind": r.kind,
                    "endpoint": r.endpoint,
                    "healthy": bool(r.healthy),
                    "last_latency_ms": round(float(r.last_latency_ms), 1)
                    if r.last_latency_ms is not None
                    else None,
                    "last_health_at": r.last_health_at.isoformat()
                    if r.last_health_at
                    else None,
                }
            )
    return {"regions": list(regions.values()), "count": len(regions)}


async def _health_check_region(region_code: str) -> tuple[bool, float]:
    """Probe de latencia de la réplica postgres (endpoint 'local' → DB principal)."""
    start = datetime.now(timezone.utc)
    try:
        session = await get_async_session()
        try:
            await session.execute(text("SELECT 1"))
            latency = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            return True, latency
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Region healthcheck failed", region=region_code, error=str(exc)[:150])
        return False, 0.0


async def run_healthcheck(regions: list[str] | None = None) -> dict:
    """Actualiza healthy/latencia de las réplicas de cada región."""
    session = await get_async_session()
    try:
        region_rows = (
            await session.execute(
                text("SELECT id, code FROM regions WHERE status = 'active'")
            )
        ).fetchall()
        results: dict[str, dict] = {}
        for region_row in region_rows:
            code = region_row.code
            if regions and code not in regions:
                continue
            healthy, latency = await _health_check_region(code)
            await session.execute(
                text(
                    "UPDATE region_replicas SET healthy = :h, last_latency_ms = :lat, "
                    "last_health_at = NOW() WHERE region_id = :rid"
                ),
                {"h": healthy, "lat": latency, "rid": region_row.id},
            )
            results[code] = {"healthy": healthy, "latency_ms": round(latency, 1)}
        await session.commit()
    finally:
        await session.close()
    return results


async def region_status() -> dict:
    """Health + latencia por región (con cache de 15 s)."""
    try:
        client = await _get_redis()
        cached = await client.get("rag:regions:status")
        if cached:
            return json.loads(cached if isinstance(cached, str) else cached.decode("utf-8"))
    except Exception:  # noqa: BLE001
        pass
    payload = await list_regions()
    try:
        client = await _get_redis()
        await client.set("rag:regions:status", json.dumps(payload, default=str), ex=15)
    except Exception:  # noqa: BLE001
        pass
    return payload


async def resolve_region(organization_id: UUID) -> dict:
    """Región primaria de la org; si su réplica no está healthy → failover a la
    siguiente región healthy por prioridad (resolución cacheada 60 s)."""
    try:
        client = await _get_redis()
        cached = await client.get(f"rag:region:resolve:{organization_id}")
        if cached:
            return json.loads(cached if isinstance(cached, str) else cached.decode("utf-8"))
    except Exception:  # noqa: BLE001
        pass

    session = await get_async_session()
    try:
        primary = (
            await session.execute(
                text(
                    "SELECT r.code, r.priority, rr.healthy FROM organizations o "
                    "JOIN regions r ON r.id = o.primary_region_id "
                    "LEFT JOIN region_replicas rr ON rr.region_id = r.id "
                    "WHERE o.id = :oid ORDER BY rr.kind = 'postgres' DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
        if primary is None:
            return {"region": "us-east-1", "failed_over": False, "source": "default"}
        if primary.healthy:
            payload = {"region": primary.code, "failed_over": False, "source": "primary"}
        else:
            fallback = (
                await session.execute(
                    text(
                        "SELECT r.code FROM regions r "
                        "WHERE r.status = 'active' AND r.code <> :code "
                        "AND EXISTS (SELECT 1 FROM region_replicas rr "
                        "WHERE rr.region_id = r.id AND rr.healthy) "
                        "ORDER BY r.priority LIMIT 1"
                    ),
                    {"code": primary.code},
                )
            ).scalar()
            payload = {
                "region": fallback or primary.code,
                "failed_over": fallback is not None,
                "source": "failover" if fallback else "primary_unhealthy",
            }
    finally:
        await session.close()

    try:
        client = await _get_redis()
        await client.set(
            f"rag:region:resolve:{organization_id}",
            json.dumps(payload),
            ex=60,
        )
    except Exception:  # noqa: BLE001
        pass
    return payload


async def set_region_health(region_code: str, healthy: bool) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE region_replicas rr SET healthy = :h, last_health_at = NOW() "
                "FROM regions r WHERE r.id = rr.region_id AND r.code = :code"
            ),
            {"h": healthy, "code": region_code},
        )
        await session.commit()
    finally:
        await session.close()
    try:
        client = await _get_redis()
        keys = await client.keys("rag:region:resolve:*")
        for key in keys:
            await client.delete(key)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Latencia por región (inference_logs.region)
# ---------------------------------------------------------------------------
async def latency_by_region(hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT COALESCE(region, 'unknown') AS region, "
                    "COUNT(*) AS requests, "
                    "AVG(latency_ms) AS avg_latency_ms, "
                    "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95 "
                    "FROM inference_logs WHERE created_at >= :since "
                    "GROUP BY region ORDER BY requests DESC"
                ),
                {"since": since},
            )
        ).fetchall()
    finally:
        await session.close()
    regions = [
        {
            "region": r.region,
            "requests": int(r.requests),
            "avg_latency_ms": round(float(r.avg_latency_ms), 1),
            "p95_latency_ms": round(float(r.p95), 1),
        }
        for r in rows
    ]
    return {"window_hours": hours, "regions": regions, "count": len(regions)}
