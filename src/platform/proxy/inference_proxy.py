# =============================================================================
# Multitenant LLM Proxy — cola por plan, routing por capacidad, rate limits
# por deployment, inference logs y métricas de performance.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

PLAN_PRIORITY = {"trial": 1, "starter": 2, "pro": 3, "enterprise": 4}


def _inflight_key(model: str) -> str:
    return f"rag:llm:inflight:{model}"


def _queue_key(plan: str, model: str) -> str:
    return f"rag:llm:queue:{plan}:{model}"


# ---------------------------------------------------------------------------
# Cola por plan + routing por capacidad
# ---------------------------------------------------------------------------
async def queue_snapshot() -> dict:
    """Profundidad de cola por (plan, modelo) y prioridad."""
    client = await _get_redis()
    keys = await client.keys("rag:llm:queue:*")
    queues: list[dict] = []
    for key in keys:
        raw = key if isinstance(key, str) else key.decode()
        parts = raw.split(":")
        plan, model = parts[3], parts[4]
        depth = int(await client.get(key) or 0)
        if depth:
            queues.append(
                {
                    "plan": plan,
                    "model": model,
                    "depth": depth,
                    "priority": PLAN_PRIORITY.get(plan, 1),
                }
            )
    queues.sort(key=lambda q: (-q["priority"], q["depth"]))
    return {"queues": queues, "count": len(queues)}


async def enqueue(plan: str, model: str) -> None:
    try:
        client = await _get_redis()
        key = _queue_key(plan, model)
        await client.incr(key)
        await client.expire(key, 300)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Proxy enqueue failed", error=str(exc)[:150])


async def dequeue(plan: str, model: str) -> None:
    try:
        client = await _get_redis()
        await client.decr(_queue_key(plan, model))
    except Exception:  # noqa: BLE001
        pass


async def inflight(model: str) -> int:
    try:
        client = await _get_redis()
        return int(await client.get(_inflight_key(model)) or 0)
    except Exception:  # noqa: BLE001
        return 0


async def acquire_slot(model: str) -> bool:
    """Slot de concurrencia por modelo (con TTL de seguridad)."""
    client = await _get_redis()
    key = _inflight_key(model)
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, 600)
        capacity = await _model_capacity(model)
        if count > capacity:
            await client.decr(key)
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Proxy acquire failed", error=str(exc)[:150])
        return True  # fail-open si Redis falla


async def release_slot(model: str) -> None:
    try:
        client = await _get_redis()
        await client.decr(_inflight_key(model))
    except Exception:  # noqa: BLE001
        pass


async def _model_capacity(model: str) -> int:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT capacity FROM inference_models "
                    "WHERE model_name = :m AND status = 'active'"
                ),
                {"m": model},
            )
        ).fetchone()
        return int(row.capacity) if row else 50
    except Exception:  # noqa: BLE001
        return 50
    finally:
        await session.close()


async def estimate_wait_ms(plan: str, model: str, avg_latency_ms: float = 900.0) -> int:
    """Estimación: (cola + inflight) × latencia media / concurrencia efectiva."""
    depth = int(await _queue_depth(plan, model))
    in_f = await inflight(model)
    capacity = await _model_capacity(model)
    if depth == 0 and in_f < capacity:
        return 0
    return int((depth + max(0, in_f - capacity + 1)) * avg_latency_ms / max(capacity, 1))


async def _queue_depth(plan: str, model: str) -> int:
    try:
        client = await _get_redis()
        return int(await client.get(_queue_key(plan, model)) or 0)
    except Exception:  # noqa: BLE001
        return 0


async def admit(plan: str, model: str) -> dict:
    """Admisión al proxy: slot de capacidad + cola; el run debe hacer
    enqueue/dequeue alrededor de la inferencia."""
    capacity = await _model_capacity(model)
    if await acquire_slot(model):
        return {"admitted": True, "wait_ms": 0, "capacity": capacity}
    await enqueue(plan, model)
    wait = await estimate_wait_ms(plan, model)
    return {"admitted": False, "wait_ms": wait, "capacity": capacity}


# ---------------------------------------------------------------------------
# Rate limit por deployment
# ---------------------------------------------------------------------------
async def enforce_deployment_rate_limit(
    deployment_id: UUID, path: str, org_plan: str | None = None
) -> bool:
    """True si está DENTRO del límite de la regla del deployment."""
    session = await get_async_session()
    try:
        rule = (
            await session.execute(
                text(
                    "SELECT id, limit_per_minute, burst FROM rate_limit_rules "
                    "WHERE deployment_id = :dep AND enabled "
                    "ORDER BY priority DESC LIMIT 1"
                ),
                {"dep": deployment_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if rule is None:
        return True
    client = await _get_redis()
    key = f"rag:rl:dep:{deployment_id}:{rule.id}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 60)
    return count <= int(rule.limit_per_minute) + int(rule.burst)


# ---------------------------------------------------------------------------
# Inference logs + performance
# ---------------------------------------------------------------------------
async def log_inference(
    *,
    organization_id: UUID,
    deployment_id: UUID | None,
    agent_id: UUID | None,
    model: str,
    backend: str | None,
    status: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    queue_wait_ms: float = 0.0,
    cost: float = 0.0,
    region: str | None = None,
) -> None:
    try:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO inference_logs (id, organization_id, deployment_id, "
                    "agent_id, model, backend, status, prompt_tokens, completion_tokens, "
                    "total_tokens, latency_ms, queue_wait_ms, cost, region) "
                    "VALUES (gen_random_uuid(), :oid, :dep, :agent, :model, :backend, "
                    ":status, :prompt, :completion, :total, :lat, :qw, :cost, :region)"
                ),
                {
                    "oid": organization_id,
                    "dep": deployment_id,
                    "agent": agent_id,
                    "model": model,
                    "backend": backend,
                    "status": status,
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                    "total": prompt_tokens + completion_tokens,
                    "lat": latency_ms,
                    "qw": queue_wait_ms,
                    "cost": cost,
                    "region": region,
                },
            )
            await session.commit()
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Inference log failed", error=str(exc)[:150])


async def list_logs(
    organization_id: UUID | None = None,
    deployment_id: UUID | None = None,
    model: str | None = None,
    hours: int = 24,
    limit: int = 100,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        where = ["created_at >= :since"]
        params: dict = {"since": since, "limit": limit}
        if organization_id:
            where.append("organization_id = :oid")
            params["oid"] = organization_id
        if deployment_id:
            where.append("deployment_id = :dep")
            params["dep"] = deployment_id
        if model:
            where.append("model = :model")
            params["model"] = model
        sql = (  # noqa: S608 — WHERE armado desde lista estática de cláusulas
            "SELECT id, organization_id, deployment_id, agent_id, model, backend, "  # noqa: S608
            "status, prompt_tokens, completion_tokens, total_tokens, latency_ms, "
            "queue_wait_ms, cost, created_at FROM inference_logs "
            f"WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT :limit"
        )
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    return {
        "logs": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "deployment_id": str(r.deployment_id) if r.deployment_id else None,
                "agent_id": str(r.agent_id) if r.agent_id else None,
                "model": r.model,
                "backend": r.backend,
                "status": r.status,
                "prompt_tokens": int(r.prompt_tokens),
                "completion_tokens": int(r.completion_tokens),
                "total_tokens": int(r.total_tokens),
                "latency_ms": round(float(r.latency_ms), 1),
                "queue_wait_ms": round(float(r.queue_wait_ms), 1),
                "cost": round(float(r.cost), 6),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def performance(model: str | None = None, hours: int = 24) -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    session = await get_async_session()
    try:
        where = ["created_at >= :since"]
        params: dict = {"since": since}
        if model:
            where.append("model = :model")
            params["model"] = model
        rows = (
            await session.execute(  # noqa: S608
                text(  # noqa: S608
                    "SELECT model, backend, "
                    "COUNT(*) AS requests, "
                    "SUM(total_tokens) AS tokens, "
                    "SUM(cost) AS cost, "
                    "AVG(latency_ms) AS avg_latency_ms, "
                    "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95, "
                    "AVG(queue_wait_ms) AS avg_queue_ms, "
                    "COUNT(*) FILTER (WHERE status <> 'completed') AS errors "
                    f"FROM inference_logs WHERE {' AND '.join(where)} "  # noqa: S608
                    "GROUP BY model, backend ORDER BY requests DESC"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    minutes = max(hours * 60, 1)
    models = []
    for r in rows:
        models.append(
            {
                "model": r.model,
                "backend": r.backend,
                "requests": int(r.requests),
                "tokens": int(r.tokens),
                "cost": round(float(r.cost), 4),
                "avg_latency_ms": round(float(r.avg_latency_ms), 1),
                "p95_latency_ms": round(float(r.p95), 1),
                "avg_queue_ms": round(float(r.avg_queue_ms), 1),
                "throughput_per_min": round(int(r.requests) / minutes, 2),
                "errors": int(r.errors),
            }
        )
    return {"window_hours": hours, "models": models, "count": len(models)}


# ---------------------------------------------------------------------------
# Catálogo de modelos del proxy
# ---------------------------------------------------------------------------
async def list_models() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, model_name, backend, capacity, status FROM inference_models "
                    "ORDER BY created_at"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "models": [
            {
                "id": str(r.id),
                "model_name": r.model_name,
                "backend": r.backend,
                "capacity": int(r.capacity),
                "status": r.status,
            }
            for r in rows
        ]
    }


async def upsert_model(
    model_name: str, backend: str, capacity: int, status: str = "active"
) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO inference_models (model_name, backend, capacity, status) "
                    "VALUES (:m, :b, :c, :s) "
                    "ON CONFLICT (model_name) DO UPDATE SET backend = EXCLUDED.backend, "
                    "capacity = EXCLUDED.capacity, status = EXCLUDED.status "
                    "RETURNING id, model_name, backend, capacity, status"
                ),
                {"m": model_name, "b": backend, "c": capacity, "s": status},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "model_name": row.model_name,
        "backend": row.backend,
        "capacity": int(row.capacity),
        "status": row.status,
    }
