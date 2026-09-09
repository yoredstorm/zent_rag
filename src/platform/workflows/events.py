# =============================================================================
# Phase 32A — Workflow Event Dispatcher
#
# Reutiliza el bus existente (canal Redis `rag:events` en
# src/platform/realtime/stream.py) — NO introduce un segundo message bus.
# Los módulos de Zent publican eventos normalizados con publish_event();
# los workflows con trigger_type='event' se suscriben vía
# workflow_event_triggers (event_type + filtros) y un consumer loop dispara
# run_workflow con ExecutionContext explícito.
# =============================================================================
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# Eventos normalizados que los módulos pueden publicar (catálogo).
STANDARD_EVENTS = (
    "source.connected",
    "source.synced",
    "document.uploaded",
    "document.processed",
    "entity.created",
    "entity.updated",
    "semantic.mapping.approved",
    "agent.run.completed",
    "invoice.detected",
    "customer.created",
    "sales.closed",
    "workflow.completed",
    "integration.connected",
    "workflow.run",
)


def _filters_match(filters: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Filtro simple: cada clave presente en filters debe existir e igualar."""
    for key, expected in (filters or {}).items():
        if key not in payload:
            return False
        actual = payload.get(key)
        if isinstance(expected, str) and str(actual) != str(expected):
            return False
        if not isinstance(expected, str) and actual != expected:
            return False
    return True


async def list_event_triggers(organization_id: UUID, workspace_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, workflow_id, workspace_id, event_type, filters, status, created_at "
            "FROM workflow_event_triggers WHERE organization_id = :oid"
        )
        params: dict[str, Any] = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (workspace_id = :ws OR workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (await session.execute(text(sql + " ORDER BY created_at DESC"), params)).fetchall()
    finally:
        await session.close()
    return {
        "triggers": [
            {
                "id": str(r.id),
                "workflow_id": str(r.workflow_id),
                "workspace_id": str(r.workspace_id) if r.workspace_id else None,
                "event_type": r.event_type,
                "filters": r.filters,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


async def create_event_trigger(
    organization_id: UUID,
    workflow_id: UUID,
    workspace_id: UUID | None,
    event_type: str,
    filters: dict[str, Any] | None = None,
) -> dict:
    if event_type not in STANDARD_EVENTS and "custom." not in event_type:
        # Permitimos eventos del catálogo estándar o custom.* de integraciones.
        raise ValueError("event_type debe pertenecer al catálogo o empezar por custom.")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_event_triggers "
                    "(organization_id, workspace_id, workflow_id, event_type, filters) "
                    "VALUES (:oid, :ws, :wid, :etype, CAST(:f AS jsonb)) "
                    "ON CONFLICT (workflow_id, event_type) DO UPDATE SET "
                    "filters = EXCLUDED.filters, status = 'active' "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "etype": event_type,
                    "f": json.dumps(filters or {}),
                },
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()
    return {"trigger_id": str(row)}


async def delete_event_trigger(
    organization_id: UUID, trigger_id: UUID
) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "DELETE FROM workflow_event_triggers "
                "WHERE id = :tid AND organization_id = :oid"
            ),
            {"tid": trigger_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def dispatch_event_to_workflows(event_type: str, payload: dict[str, Any]) -> int:
    """Empareja un evento publicado contra los triggers activos y dispara los
    workflows (fail-soft). Retorna cuántos workflows se dispararon.

    Anti-loop (32C): depth máxima de encadenamiento workflow→evento→workflow
    y dedupe por fingerprint del evento."""

    # Protección de bucles recursivos: rastrear cadena en el payload.
    chain = payload.get("_wf_chain") or []
    if isinstance(chain, list) and len(chain) >= 4:
        logger.info("workflow event loop guard: max depth alcanzado", depth=len(chain))
        return 0
    if not isinstance(chain, list):
        chain = []

    from src.platform.workflows.engine import run_workflow

    org_raw = payload.get("organization_id")
    if not org_raw:
        return 0
    try:
        organization_id = UUID(str(org_raw))
    except ValueError:
        return 0
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, workflow_id, workspace_id, event_type, filters "
                    "FROM workflow_event_triggers "
                    "WHERE organization_id = :oid AND event_type = :etype "
                    "AND status = 'active'"
                ),
                {"oid": organization_id, "etype": event_type},
            )
        ).fetchall()
    finally:
        await session.close()
    fired = 0
    fingerprint = f"{event_type}:{org_raw}:{str(payload.get('entity_id') or payload.get('id') or '')}"
    for row in rows:
        if not _filters_match(row.filters, payload):
            continue
        try:
            event_id = payload.get("event_id") or payload.get("ts") or fingerprint
            dedupe_key = f"mkt:wfevt:{row.workflow_id}:{fingerprint}"
            deduped = await _mark_event_processed(organization_id, dedupe_key)
            if deduped:
                logger.info("workflow event dedupe", event_type=event_type, workflow_id=str(row.workflow_id))
                continue
            child_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
            child_payload["_wf_chain"] = chain + [str(row.workflow_id)]
            await run_workflow(
                row.workflow_id,
                child_payload,
                trigger="event",
                organization_id=organization_id,
                workspace_id=row.workspace_id,
                actor_type="event_dispatcher",
                correlation_id=f"evt:{event_type}:{event_id}",
            )
            fired += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "event trigger run failed",
                workflow_id=str(row.workflow_id),
                event_type=event_type,
                error=str(exc)[:200],
            )
    return fired


async def _mark_event_processed(organization_id: UUID, dedupe_key: str) -> bool:
    """Dedupe best-effort con expiración corta (TTL 60s) vía Redis."""
    try:
        from src.infrastructure.redis.cache import _get_redis

        client = await _get_redis()
        key = f"{dedupe_key}:{organization_id.hex}"
        seen = await client.get(key)
        if seen:
            return True
        await client.set(key, "1", ex=60)
        return False
    except Exception:  # noqa: BLE001
        return False


async def workflow_event_consumer_loop() -> None:
    """Consume el canal rag:events (bus existente) y despacha a workflows."""
    from src.infrastructure.redis.cache import _get_redis
    from src.platform.realtime import stream as realtime

    while True:
        try:
            client = await _get_redis()
            pubsub = client.pubsub()
            await pubsub.subscribe(realtime.EVENTS_CHANNEL)
            it = pubsub.listen().__aiter__()
            try:
                while True:
                    try:
                        message = await asyncio.wait_for(it.__anext__(), timeout=5.0)
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        # El pubsub perdió la conexión (idle/reconnect) → el
                        # finally cierra y el bucle externo reconecta en silencio.
                        break
                    if message.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(message["data"])
                    except (TypeError, json.JSONDecodeError):
                        continue
                    event_type = payload.get("event")
                    if not event_type:
                        continue
                    try:
                        await dispatch_event_to_workflows(event_type, payload)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "workflow event dispatch failed",
                            event_type=event_type,
                            error=str(exc)[:200],
                        )
            finally:
                try:
                    await pubsub.unsubscribe(realtime.EVENTS_CHANNEL)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await pubsub.aclose()  # libera la conexión del pool en cada ciclo
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow event consumer iteration failed", error=str(exc)[:200])
            await asyncio.sleep(5)
