# =============================================================================
# Real-Time Analytics & Streaming
# Canal Redis rag:events (pub/sub) → SSE para el CC, summary en vivo,
# series temporales y consumidor de corrección automática.
# =============================================================================
from __future__ import annotations

import asyncio
import csv
import io
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

EVENTS_CHANNEL = "rag:events"
_HEARTBEAT_SECONDS = 15
_ERROR_WINDOW_SECONDS = 120
_ERROR_THRESHOLD = 5

# Corrección automática (global; OFF por defecto).
_auto_correction_enabled = False


def set_auto_correction(enabled: bool) -> None:
    global _auto_correction_enabled
    _auto_correction_enabled = enabled


def auto_correction_enabled() -> bool:
    return _auto_correction_enabled


async def publish_event(event_type: str, payload: dict) -> None:
    """Publica un evento en el canal en tiempo real (fail-soft)."""
    try:
        client = await _get_redis()
        message = json.dumps(
            {
                "event": event_type,
                "ts": datetime.now(timezone.utc).isoformat(),
                **payload,
            },
            default=str,
        )
        await client.publish(EVENTS_CHANNEL, message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Realtime publish failed", error=str(exc)[:150])


async def publish_agent_run(
    organization_id: UUID,
    agent_id: UUID | None,
    deployment_id: UUID | None,
    model: str | None,
    tokens: int,
    cost: float,
    latency_ms: float,
    status: str,
    run_id: UUID | None = None,
) -> None:
    from src.platform.metering.metering import record as _meter

    try:
        await _meter(
            organization_id,
            tokens=tokens,
            cost=cost,
            model=model,
            status=status,
        )
    except Exception:  # noqa: BLE001
        pass
    await publish_event(
        "agent_run",
        {
            "organization_id": str(organization_id),
            "agent_id": str(agent_id) if agent_id else None,
            "deployment_id": str(deployment_id) if deployment_id else None,
            "run_id": str(run_id) if run_id else None,
            "model": model,
            "tokens": tokens,
            "cost": round(cost, 6),
            "latency_ms": round(latency_ms, 1),
            "status": status,
        },
    )


async def publish_api_query(
    organization_id: UUID,
    deployment_id: UUID | None,
    status: int,
    latency_ms: float,
    tokens: int,
    cost: float,
) -> None:
    from src.platform.metering.metering import record as _meter

    try:
        await _meter(
            organization_id,
            tokens=tokens,
            cost=cost,
            status=str(status),
        )
    except Exception:  # noqa: BLE001
        pass
    await publish_event(
        "api_query",
        {
            "organization_id": str(organization_id),
            "deployment_id": str(deployment_id) if deployment_id else None,
            "status": status,
            "latency_ms": round(latency_ms, 1),
            "tokens": tokens,
            "cost": round(cost, 6),
        },
    )


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------
async def event_source(organization_id: str | None = None):
    """Generador SSE: suscribe al canal y emite eventos (con heartbeat)."""
    client = await _get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    try:
        it = pubsub.listen().__aiter__()
        while True:
            try:
                message = await asyncio.wait_for(it.__anext__(), timeout=_HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield "event: heartbeat\ndata: {}\n\n"
                continue
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, json.JSONDecodeError):
                continue
            if organization_id and payload.get("organization_id") != organization_id:
                continue
            yield f"event: {payload.get('event', 'event')}\ndata: {json.dumps(payload)}\n\n"
    finally:
        try:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Summary en vivo + series temporales
# ---------------------------------------------------------------------------
async def live_summary(minutes: int = 15) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT "
                    "COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS errors, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost, "
                    "COUNT(DISTINCT organization_id)::int AS orgs "
                    "FROM usage_events WHERE created_at > NOW() - MAKE_INTERVAL(mins => :mins)"
                ),
                {"mins": max(1, min(minutes, 1440))},
            )
        ).fetchone()
        by_model = (
            await session.execute(
                text(
                    "SELECT COALESCE(model, 'unknown') AS model, COUNT(*)::int AS n "
                    "FROM usage_events WHERE created_at > NOW() - MAKE_INTERVAL(mins => :mins) "
                    "GROUP BY 1 ORDER BY n DESC LIMIT 8"
                ),
                {"mins": max(1, min(minutes, 1440))},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "window_minutes": minutes,
        "requests": int(rows.requests or 0),
        "errors": int(rows.errors or 0),
        "error_rate_pct": round(float(rows.errors or 0) / max(int(rows.requests or 0), 1) * 100, 2),
        "tokens": int(rows.tokens or 0),
        "cost": round(float(rows.cost or 0), 4),
        "active_organizations": int(rows.orgs or 0),
        "by_model": [{"model": r.model, "requests": int(r.n)} for r in by_model],
    }


async def timeseries(hours: int = 24, format: str = "json") -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT DATE_TRUNC('hour', created_at) AS bucket, "
                    "COUNT(*)::int AS requests, "
                    "COUNT(*) FILTER (WHERE status IN ('error','failed'))::int AS errors, "
                    "COALESCE(SUM(COALESCE(actual_cost, estimated_cost)), 0)::float AS cost "
                    "FROM usage_events "
                    "WHERE created_at > NOW() - MAKE_INTERVAL(hours => :hours) "
                    "GROUP BY 1 ORDER BY 1"
                ),
                {"hours": max(1, min(hours, 720))},
            )
        ).fetchall()
    finally:
        await session.close()
    points = [
        {
            "bucket": r.bucket.isoformat(),
            "requests": int(r.requests),
            "errors": int(r.errors),
            "cost": round(float(r.cost or 0), 4),
        }
        for r in rows
    ]
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["bucket", "requests", "errors", "cost"])
        for p in points:
            writer.writerow([p["bucket"], p["requests"], p["errors"], p["cost"]])
        return {"content_type": "text/csv", "filename": "zent-realtime-timeseries.csv", "payload": buffer.getvalue()}
    return {"points": points, "count": len(points)}


# ---------------------------------------------------------------------------
# Consumidor en tiempo real: spike de errores → incident + auto-corrección
# ---------------------------------------------------------------------------
class _SpikeTracker:
    """Ventana deslizante de errores por deployment (2 min)."""

    def __init__(self) -> None:
        self._errors: dict[str, deque] = defaultdict(deque)
        self._last_alert: dict[str, datetime] = {}

    def record(self, deployment_id: str | None, status: str) -> bool:
        if deployment_id is None:
            return False
        key = str(deployment_id)
        now = datetime.now(timezone.utc)
        if status in ("error", "failed", "5xx", "500", "429"):
            self._errors[key].append(now)
        cutoff = now - timedelta(seconds=_ERROR_WINDOW_SECONDS)
        while self._errors[key] and self._errors[key][0] < cutoff:
            self._errors[key].popleft()
        if len(self._errors[key]) >= _ERROR_THRESHOLD:
            # Cooldown: no re-alertar el mismo deployment en 2 min.
            last = self._last_alert.get(key)
            if last is None or now - last > timedelta(seconds=_ERROR_WINDOW_SECONDS):
                self._last_alert[key] = now
                self._errors[key].clear()
                return True
        return False


_tracker = _SpikeTracker()


async def _handle_spike(deployment_id: str, organization_id: str, errors_in_window: int) -> None:
    from src.platform.observability.alerts import _insert_alert

    await _insert_alert(
        UUID(organization_id),
        "realtime_error_spike",
        "critical",
        f"Spike en tiempo real del deployment {deployment_id[:8]}: {errors_in_window} errores "
        f"en {_ERROR_WINDOW_SECONDS // 60} min",
        threshold_value=_ERROR_THRESHOLD,
        actual_value=errors_in_window,
        deployment_id=UUID(deployment_id),
    )
    logger.warning(
        "Realtime error spike",
        deployment_id=deployment_id,
        organization_id=organization_id,
        errors=errors_in_window,
    )


async def _auto_rollback(organization_id: UUID, deployment_id: UUID) -> None:
    """Revierte al último deployment bueno (corrección automática)."""
    from src.infrastructure.postgres.relational_db import PostgresDeploymentRepository
    from src.platform.deployments.deployments import rollback_deployment

    try:
        deployment = await rollback_deployment(
            PostgresDeploymentRepository(), organization_id, deployment_id
        )
        logger.info("Auto-correction: deployment rolled back", deployment_id=str(deployment.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Auto-correction rollback failed", error=str(exc)[:200])


async def realtime_consumer_loop() -> None:
    """Consume rag:events: detecta spikes de error y aplica corrección si está activa."""
    while True:
        try:
            client = await _get_redis()
            pubsub = client.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)
            it = pubsub.listen().__aiter__()
            try:
                while True:
                    try:
                        message = await asyncio.wait_for(it.__anext__(), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue
                    if message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    deployment_id = payload.get("deployment_id")
                    status = payload.get("status")
                    if deployment_id is None:
                        continue
                    if _tracker.record(deployment_id, str(status)):
                        await _handle_spike(deployment_id, payload["organization_id"], _ERROR_THRESHOLD)
                        if auto_correction_enabled():
                            await _auto_rollback(
                                UUID(payload["organization_id"]), UUID(deployment_id)
                            )
            finally:
                try:
                    await pubsub.unsubscribe(EVENTS_CHANNEL)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("Realtime consumer iteration failed", error=str(exc)[:200])
            await asyncio.sleep(5)
