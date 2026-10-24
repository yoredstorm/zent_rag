# =============================================================================
# Ingress Router — una sola entrada para manual, schedule, webhook y event.
#
# Decide ejecución efímera vs WorkflowInstance durable sin crear un segundo
# scheduler. Los triggers durables pasan por un inbox Postgres con clave de
# ingreso idempotente; el evento de negocio (business_key) sigue separado.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

DURABLE_NODE_TYPES = frozenset({"wait_event", "human_approval", "loop"})
_CLAIM_STALE_MINUTES = 5

_INGRESS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS workflow_ingress_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        workflow_id UUID NOT NULL,
        trigger_type VARCHAR(40) NOT NULL,
        ingress_key VARCHAR(200) NOT NULL,
        external_event_id VARCHAR(200),
        business_key VARCHAR(200),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        instance_id UUID,
        attempts INT NOT NULL DEFAULT 0,
        last_error VARCHAR(400),
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        claimed_at TIMESTAMPTZ,
        processed_at TIMESTAMPTZ,
        UNIQUE (organization_id, workflow_id, ingress_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wf_ingress_status "
    "ON workflow_ingress_events(organization_id, status, received_at)",
    "CREATE INDEX IF NOT EXISTS idx_wf_ingress_workflow "
    "ON workflow_ingress_events(organization_id, workflow_id, received_at DESC)",
)

_ENSURED = False


async def ensure_ingress_tables() -> None:
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "ALTER TABLE workflow_instances ADD COLUMN IF NOT EXISTS ingress_key VARCHAR(200)"
            )
        )
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_instances_ingress "
                "ON workflow_instances(organization_id, workflow_id, ingress_key) "
                "WHERE ingress_key IS NOT NULL"
            )
        )
        for ddl in _INGRESS_DDL:
            await session.execute(text(ddl))
        await session.commit()
        _ENSURED = True
    except Exception as exc:  # noqa: BLE001 — paridad dev; migración manda
        await session.rollback()
        logger.warning("ensure_ingress_tables failed", error=str(exc)[:200])
    finally:
        await session.close()


def durable_reasons(graph: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    for node in (graph or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        if node_type in DURABLE_NODE_TYPES:
            reasons.append(f"{node_type}:{node.get('id')}")
    return reasons


def is_durable_graph(graph: dict[str, Any] | None) -> bool:
    return bool(durable_reasons(graph))


def _payload_hash(payload: dict[str, Any] | None) -> str:
    blob = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_ingress_key(
    trigger: str,
    *,
    explicit: str | None,
    workflow_id: UUID,
    payload: dict[str, Any] | None,
    conversation_id: UUID | None = None,
) -> str | None:
    candidate = (explicit or "").strip()
    if candidate:
        return candidate[:200]
    if trigger in ("webhook", "event"):
        return f"{trigger}:{workflow_id}:{_payload_hash(payload)}"[:200]
    if trigger == "conversation.message" and conversation_id:
        return f"conversation:{conversation_id}:{_payload_hash(payload)}"[:200]
    return None


def _event_row(row: Any) -> dict[str, Any]:
    return {
        "event_id": str(row.id),
        "status": str(row.status),
        "instance_id": str(row.instance_id) if row.instance_id else None,
        "ingress_key": row.ingress_key,
        "attempts": int(row.attempts or 0),
        "last_error": row.last_error,
    }


async def _record_event(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workflow_id: UUID,
    trigger: str,
    ingress_key: str,
    payload: dict[str, Any],
    external_event_id: str | None,
    business_key: str | None,
) -> tuple[dict[str, Any], bool]:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_ingress_events "
                    "(organization_id, workspace_id, workflow_id, trigger_type, "
                    "ingress_key, external_event_id, business_key, payload, status) "
                    "VALUES (:oid, :ws, :wid, :trigger, :key, :external, :bkey, "
                    "CAST(:payload AS jsonb), 'pending') "
                    "ON CONFLICT (organization_id, workflow_id, ingress_key) DO NOTHING "
                    "RETURNING id, status, instance_id, ingress_key, attempts, last_error"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "wid": workflow_id,
                    "trigger": trigger[:40],
                    "key": ingress_key,
                    "external": (external_event_id or "")[:200] or None,
                    "bkey": (business_key or "")[:200] or None,
                    "payload": json.dumps(payload or {}, default=str),
                },
            )
        ).fetchone()
        if row is not None:
            await session.commit()
            return _event_row(row), False
        await session.rollback()
        existing = (
            await session.execute(
                text(
                    "SELECT id, status, instance_id, ingress_key, attempts, last_error "
                    "FROM workflow_ingress_events "
                    "WHERE organization_id = :oid AND workflow_id = :wid AND ingress_key = :key"
                ),
                {"oid": organization_id, "wid": workflow_id, "key": ingress_key},
            )
        ).fetchone()
        return (_event_row(existing), True) if existing else ({}, True)
    finally:
        await session.close()


async def _claim_event(organization_id: UUID, event_id: str) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_ingress_events SET status = 'processing', "
                    "attempts = attempts + 1, claimed_at = NOW(), last_error = NULL "
                    "WHERE id = :eid AND organization_id = :oid "
                    "AND status IN ('pending', 'failed') "
                    "RETURNING id, status, instance_id, ingress_key, attempts, last_error"
                ),
                {"eid": event_id, "oid": organization_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return _event_row(row) if row else None


async def _finish_event(
    organization_id: UUID,
    event_id: str,
    *,
    status: str,
    instance_id: str | None = None,
    error: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_ingress_events SET status = :status, "
                "instance_id = COALESCE(:iid, instance_id), last_error = :error, "
                "processed_at = CASE WHEN :is_processed THEN NOW() ELSE processed_at END "
                "WHERE id = :eid AND organization_id = :oid"
            ),
            {
                "status": status,
                "iid": instance_id,
                "error": (error or "")[:400] or None,
                "is_processed": status == "processed",
                "eid": event_id,
                "oid": organization_id,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _load_workflow(workflow_id: UUID) -> Any:
    session = await get_async_session()
    try:
        return (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, name, description, steps, graph, "
                    "workflow_version, graph_source, trigger_type, trigger_config, status "
                    "FROM workflows WHERE id = :wid"
                ),
                {"wid": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()


def _graph_of(row: Any) -> dict[str, Any]:
    if row.graph:
        return dict(row.graph)
    from src.platform.workflows.ir import LegacyWorkflowAdapter

    return LegacyWorkflowAdapter.steps_to_graph(
        row.steps or [], str(row.trigger_type or "webhook"), dict(row.trigger_config or {})
    ).to_dict()


async def route_ingress(
    *,
    workflow_id: UUID,
    organization_id: UUID,
    trigger: str,
    payload: dict[str, Any] | None = None,
    workspace_id: UUID | None = None,
    idempotency_key: str | None = None,
    business_key: str | None = None,
    conversation_id: UUID | None = None,
    participant_id: str | None = None,
    actor_type: str = "system",
    actor_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    system_context: bool = False,
    correlation_id: str | None = None,
    require_active: bool = True,
    external_event_id: str | None = None,
) -> dict[str, Any]:
    """Entrada única. Efímero → run_workflow; durable → WorkflowInstance."""
    await ensure_ingress_tables()
    row = await _load_workflow(workflow_id)
    if row is None:
        return {"error": "not_found", "status_code": 404}
    if UUID(str(row.organization_id)) != UUID(str(organization_id)):
        return {"error": "organization_mismatch", "status_code": 403}
    wf_ws = UUID(str(row.workspace_id)) if row.workspace_id else None
    if wf_ws is not None and workspace_id != wf_ws:
        return {"error": "workspace_mismatch", "status_code": 403}
    if str(row.status) == "paused":
        return {"status": "paused", "message": "workflow pausado"}
    if require_active and str(row.status) != "active":
        return {"error": "inactive", "status_code": 409}

    graph = _graph_of(row)
    eff_ws = wf_ws or workspace_id
    if not is_durable_graph(graph):
        from src.platform.workflows.engine import run_workflow

        return await run_workflow(
            workflow_id,
            payload or {},
            trigger=trigger,
            organization_id=organization_id,
            workspace_id=eff_ws,
            actor_type=actor_type,
            actor_id=actor_id,
            permissions=permissions,
            system_context=system_context,
            correlation_id=correlation_id,
        )

    key = normalize_ingress_key(
        trigger,
        explicit=idempotency_key,
        workflow_id=workflow_id,
        payload=payload,
        conversation_id=conversation_id,
    )
    if key is None:
        key = f"manual:{workflow_id}:{uuid4().hex}"
    event, duplicate = await _record_event(
        organization_id=organization_id,
        workspace_id=eff_ws,
        workflow_id=workflow_id,
        trigger=trigger,
        ingress_key=key,
        payload=payload or {},
        external_event_id=external_event_id,
        business_key=business_key,
    )
    if duplicate and str(event.get("status") or "") not in ("pending", "failed"):
        from src.platform.workflows.instances import find_by_ingress

        instance = await find_by_ingress(organization_id, workflow_id, key)
        return {
            "status": "duplicate" if instance else "processing",
            "duplicate": True,
            "ingress_key": key,
            "ingress_event": event,
            "instance_id": instance["id"] if instance else None,
            "instance": instance,
            "durable": True,
        }
    claimed = await _claim_event(organization_id, event["event_id"])
    if claimed is None:
        return {
            "status": "processing",
            "duplicate": True,
            "ingress_key": key,
            "ingress_event": event,
            "durable": True,
        }
    try:
        from src.platform.workflows.instances import start_workflow_instance

        result = await start_workflow_instance(
            workflow_id=workflow_id,
            organization_id=organization_id,
            workspace_id=eff_ws,
            trigger=trigger,
            payload=payload or {},
            conversation_id=conversation_id,
            participant_id=participant_id,
            business_key=business_key,
            ingress_key=key,
            actor_type=actor_type,
            actor_id=actor_id,
            permissions=permissions,
            system_context=system_context,
            correlation_id=correlation_id,
        )
        instance_id = result.get("instance_id")
        await _finish_event(
            organization_id,
            event["event_id"],
            status="processed",
            instance_id=str(instance_id) if instance_id else None,
        )
        result["durable"] = True
        result["ingress_key"] = key
        result["ingress_event_id"] = event["event_id"]
        return result
    except Exception as exc:  # noqa: BLE001
        await _finish_event(
            organization_id,
            event["event_id"],
            status="failed",
            error=str(exc)[:400],
        )
        raise


async def sweep_ingress_events(*, stale_minutes: int = _CLAIM_STALE_MINUTES) -> dict[str, int]:
    """Devuelve a pending los claims huérfanos; no crea instancias por sí solo."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, stale_minutes))
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE workflow_ingress_events SET status = 'pending', "
                "last_error = 'claim huérfano; reintento recuperable' "
                "WHERE status = 'processing' AND instance_id IS NULL "
                "AND claimed_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        await session.commit()
        return {"requeued": int(result.rowcount or 0)}
    finally:
        await session.close()


__all__ = [
    "DURABLE_NODE_TYPES",
    "durable_reasons",
    "ensure_ingress_tables",
    "is_durable_graph",
    "normalize_ingress_key",
    "route_ingress",
    "sweep_ingress_events",
]
