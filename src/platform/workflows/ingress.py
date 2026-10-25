# =============================================================================
# Ingress Router — una sola entrada para manual, schedule, webhook, event y
# provider. La identidad del evento se resuelve por fuente; el payload no es
# identidad por defecto.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.event_identity import (
    IngressEnvelope,
    normalize_ingress_key,
    payload_hash,
    resolve_identity,
)

logger = get_logger(__name__)

DURABLE_NODE_TYPES = frozenset({"wait_event", "human_approval", "loop"})
_CLAIM_STALE_MINUTES = 5
_LEASE_MINUTES = 5
_MAX_ATTEMPTS_DEFAULT = 8

_INGRESS_DDL = (
    """
    CREATE TABLE IF NOT EXISTS workflow_ingress_events (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        workflow_id UUID NOT NULL,
        trigger_type VARCHAR(40) NOT NULL,
        source VARCHAR(40),
        event_type VARCHAR(120),
        ingress_key VARCHAR(200) NOT NULL,
        dedupe_key VARCHAR(240),
        dedupe_mode VARCHAR(30) NOT NULL DEFAULT 'legacy',
        provider_event_id VARCHAR(200),
        external_event_id VARCHAR(200),
        business_key VARCHAR(200),
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        payload_hash VARCHAR(64) NOT NULL DEFAULT '',
        envelope JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        instance_id UUID,
        run_id UUID,
        attempts INT NOT NULL DEFAULT 0,
        max_attempts INT NOT NULL DEFAULT 8,
        last_error VARCHAR(400),
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        claimed_at TIMESTAMPTZ,
        heartbeat_at TIMESTAMPTZ,
        lease_expires_at TIMESTAMPTZ,
        next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        dead_letter_at TIMESTAMPTZ,
        processed_at TIMESTAMPTZ,
        effect_status VARCHAR(20) NOT NULL DEFAULT 'none',
        UNIQUE (organization_id, workflow_id, ingress_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_wf_ingress_status "
    "ON workflow_ingress_events(organization_id, status, received_at)",
    "CREATE INDEX IF NOT EXISTS idx_wf_ingress_workflow "
    "ON workflow_ingress_events(organization_id, workflow_id, received_at DESC)",
)

_ENSURED = False


class IdempotencyConflict(RuntimeError):
    """Misma clave de idempotencia con payload distinto."""

    def __init__(self, message: str, *, code: str = "idempotency_conflict"):
        self.code = code
        self.status_code = 409
        super().__init__(message)


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
        # Paridad dev sobre tablas creadas antes de la migración 171.
        for column, definition in (
            ("source", "VARCHAR(40)"),
            ("event_type", "VARCHAR(120)"),
            ("dedupe_key", "VARCHAR(240)"),
            ("dedupe_mode", "VARCHAR(30) NOT NULL DEFAULT 'legacy'"),
            ("provider_event_id", "VARCHAR(200)"),
            ("payload_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
            ("envelope", "JSONB NOT NULL DEFAULT '{}'::jsonb"),
            ("run_id", "UUID"),
            ("heartbeat_at", "TIMESTAMPTZ"),
            ("lease_expires_at", "TIMESTAMPTZ"),
            ("next_attempt_at", "TIMESTAMPTZ NOT NULL DEFAULT NOW()"),
            ("max_attempts", "INT NOT NULL DEFAULT 8"),
            ("dead_letter_at", "TIMESTAMPTZ"),
            ("effect_status", "VARCHAR(20) NOT NULL DEFAULT 'none'"),
        ):
            await session.execute(
                text(
                    f"ALTER TABLE workflow_ingress_events "
                    f"ADD COLUMN IF NOT EXISTS {column} {definition}"
                )
            )
        await session.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_ingress_dedupe "
                "ON workflow_ingress_events(organization_id, workflow_id, source, dedupe_key) "
                "WHERE dedupe_key IS NOT NULL"
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_wf_ingress_drain "
                "ON workflow_ingress_events(status, next_attempt_at, received_at) "
                "WHERE status IN ('pending', 'failed')"
            )
        )
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


def _event_row(row: Any) -> dict[str, Any]:
    return {
        "event_id": str(row.id),
        "status": str(row.status),
        "instance_id": str(row.instance_id) if row.instance_id else None,
        "run_id": str(getattr(row, "run_id", None)) if getattr(row, "run_id", None) else None,
        "ingress_key": row.ingress_key,
        "dedupe_key": getattr(row, "dedupe_key", None) or row.ingress_key,
        "source": getattr(row, "source", None),
        "dedupe_mode": getattr(row, "dedupe_mode", None),
        "payload_hash": getattr(row, "payload_hash", "") or "",
        "attempts": int(row.attempts or 0),
        "last_error": row.last_error,
        "dead_letter_at": (
            row.dead_letter_at.isoformat() if getattr(row, "dead_letter_at", None) else None
        ),
    }


async def _record_event(
    envelope: IngressEnvelope,
    *,
    trigger: str,
    identity,
) -> tuple[dict[str, Any], bool]:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflow_ingress_events "
                    "(organization_id, workspace_id, workflow_id, trigger_type, source, "
                    "event_type, ingress_key, dedupe_key, dedupe_mode, provider_event_id, "
                    "external_event_id, business_key, payload, payload_hash, envelope, status) "
                    "VALUES (:oid, :ws, :wid, :trigger, :source, :etype, :key, :dkey, :mode, "
                    ":provider, :external, :bkey, CAST(:payload AS jsonb), :phash, "
                    "CAST(:envelope AS jsonb), 'pending') "
                    "ON CONFLICT DO NOTHING "
                    "RETURNING *"
                ),
                {
                    "oid": envelope.organization_id,
                    "ws": envelope.workspace_id,
                    "wid": envelope.workflow_id,
                    "trigger": trigger[:40],
                    "source": identity.source,
                    "etype": (envelope.event_type or "")[:120] or None,
                    "key": identity.dedupe_key,
                    "dkey": identity.dedupe_key,
                    "mode": identity.dedupe_mode,
                    "provider": (envelope.provider_event_id or "")[:200] or None,
                    "external": (envelope.provider_event_id or "")[:200] or None,
                    "bkey": (envelope.business_key or "")[:200] or None,
                    "payload": json.dumps(envelope.payload or {}, default=str),
                    "phash": identity.payload_hash,
                    "envelope": json.dumps(envelope.model_dump(mode="json"), default=str),
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
                    "SELECT * FROM workflow_ingress_events "
                    "WHERE organization_id = :oid AND workflow_id = :wid AND ingress_key = :key"
                ),
                {
                    "oid": envelope.organization_id,
                    "wid": envelope.workflow_id,
                    "key": identity.dedupe_key,
                },
            )
        ).fetchone()
        if existing is None:
            raise IdempotencyConflict(
                "no se pudo registrar el evento de ingreso",
                code="ingress_record_failed",
            )
        existing_hash = str(getattr(existing, "payload_hash", "") or "")
        if existing_hash and existing_hash != identity.payload_hash:
            raise IdempotencyConflict(
                "la misma clave de idempotencia llegó con un payload distinto"
            )
        if not existing_hash and str(existing.status) not in ("pending", "failed"):
            raise IdempotencyConflict(
                "la clave colisiona con un evento legacy sin hash verificable",
                code="idempotency_legacy_conflict",
            )
        return _event_row(existing), True
    finally:
        await session.close()


async def _claim_event(organization_id: UUID, event_id: str) -> dict[str, Any] | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_ingress_events SET status = 'processing', "
                    "attempts = attempts + 1, claimed_at = NOW(), heartbeat_at = NOW(), "
                    "lease_expires_at = NOW() + make_interval(mins => :lease), "
                    "last_error = NULL "
                    "WHERE id = :eid AND organization_id = :oid "
                    "AND status IN ('pending', 'failed') "
                    "AND dead_letter_at IS NULL "
                    "AND (next_attempt_at IS NULL OR next_attempt_at <= NOW()) "
                    "RETURNING *"
                ),
                {
                    "eid": event_id,
                    "oid": organization_id,
                    "lease": _LEASE_MINUTES,
                },
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
    run_id: str | None = None,
    error: str | None = None,
    attempts: int = 0,
    max_attempts: int = _MAX_ATTEMPTS_DEFAULT,
) -> None:
    session = await get_async_session()
    try:
        backoff = min(3600, 2 ** min(max(int(attempts), 0), 10))
        await session.execute(
            text(
                "UPDATE workflow_ingress_events SET status = :status, "
                "instance_id = COALESCE(:iid, instance_id), "
                "run_id = COALESCE(:rid, run_id), last_error = :error, "
                "processed_at = CASE WHEN :is_processed THEN NOW() ELSE processed_at END, "
                "lease_expires_at = NULL, heartbeat_at = NULL, "
                "next_attempt_at = CASE WHEN :is_failed THEN "
                "NOW() + make_interval(secs => CAST(:backoff AS DOUBLE PRECISION)) "
                "ELSE next_attempt_at END, "
                "dead_letter_at = CASE WHEN :is_failed "
                "AND CAST(:attempts AS INTEGER) >= CAST(:max_attempts AS INTEGER) "
                "THEN NOW() ELSE dead_letter_at END "
                "WHERE id = :eid AND organization_id = :oid"
            ),
            {
                "status": status,
                "iid": instance_id,
                "rid": run_id,
                "error": (error or "")[:400] or None,
                "is_processed": status == "processed",
                "is_failed": status == "failed",
                "backoff": backoff,
                "attempts": int(attempts),
                "max_attempts": int(max_attempts),
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


async def _definition_for(
    row: Any,
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    require_active: bool,
) -> dict[str, Any]:
    from src.platform.workflows.definition import PublishedDefinitionError, resolve_definition

    source = "published" if (require_active or str(row.status) == "active") else "draft"
    try:
        return await resolve_definition(
            organization_id,
            UUID(str(row.id)),
            source=source,
            workspace_id=workspace_id,
            require_active=require_active,
        )
    except PublishedDefinitionError as exc:
        raise IdempotencyConflict(exc.message, code=exc.code) from exc


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
    provider_event_id: str | None = None,
    source: str | None = None,
    event_type: str | None = None,
    occurred_at: datetime | None = None,
    signature_verified: bool = False,
    dedupe_mode: str | None = None,
) -> dict[str, Any]:
    """Entrada única. Efímero → run; durable → WorkflowInstance."""
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

    eff_ws = wf_ws or workspace_id
    resolved_source = (
        source
        or ("event" if trigger == "event" else None)
        or ("schedule" if trigger == "schedule" else None)
        or ("webhook" if trigger == "webhook" else None)
        or ("manual" if trigger == "manual" else None)
        or ("provider" if provider_event_id else "client")
    )
    envelope = IngressEnvelope(
        organization_id=organization_id,
        workspace_id=eff_ws,
        workflow_id=workflow_id,
        source=resolved_source,
        event_type=event_type,
        provider_event_id=provider_event_id or external_event_id,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        payload=payload or {},
        business_key=business_key,
        idempotency_key=idempotency_key,
        dedupe_mode=dedupe_mode,
        signature_verified=signature_verified,
    )
    identity = resolve_identity(envelope)
    try:
        event, duplicate = await _record_event(
            envelope, trigger=trigger, identity=identity
        )
    except IdempotencyConflict as exc:
        logger.warning(
            "ingress.idempotency_conflict",
            workflow_id=str(workflow_id),
            organization_id=str(organization_id),
            source=identity.source,
            ingress_key=identity.dedupe_key,
            payload_hash=identity.payload_hash[:16],
            code=exc.code,
        )
        return {
            "error": exc.code,
            "message": str(exc),
            "status_code": 409,
            "ingress_key": identity.dedupe_key,
        }
    logger.info(
        "ingress.event_recorded",
        workflow_id=str(workflow_id),
        organization_id=str(organization_id),
        workspace_id=str(eff_ws) if eff_ws else None,
        source=identity.source,
        trigger=trigger,
        ingress_key=identity.dedupe_key,
        payload_hash=identity.payload_hash[:16],
        event_id=event.get("event_id"),
        duplicate=duplicate,
        correlation_id=correlation_id,
    )
    if duplicate and str(event.get("status") or "") not in ("pending", "failed"):
        from src.platform.workflows.instances import find_by_ingress

        instance = await find_by_ingress(organization_id, workflow_id, identity.dedupe_key)
        return {
            "status": "duplicate" if (instance or event.get("run_id")) else "processing",
            "duplicate": True,
            "ingress_key": identity.dedupe_key,
            "ingress_event": event,
            "instance_id": instance["id"] if instance else None,
            "run_id": event.get("run_id"),
            "instance": instance,
            "durable": bool(instance),
        }
    claimed = await _claim_event(organization_id, event["event_id"])
    if claimed is None:
        return {
            "status": "processing",
            "duplicate": True,
            "ingress_key": identity.dedupe_key,
            "ingress_event": event,
            "durable": False,
        }

    try:
        definition = await _definition_for(
            row,
            organization_id=organization_id,
            workspace_id=eff_ws,
            require_active=require_active,
        )
        graph = dict(definition.get("graph") or {})
        if not is_durable_graph(graph):
            from src.platform.workflows.engine import run_workflow

            result = await run_workflow(
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
                definition_source=definition["definition_source"],
            )
            await _finish_event(
                organization_id,
                event["event_id"],
                status="processed",
                run_id=str(result.get("run_id")) if result.get("run_id") else None,
                attempts=int(claimed.get("attempts") or 0),
                max_attempts=int(event.get("max_attempts") or _MAX_ATTEMPTS_DEFAULT),
            )
            result["durable"] = False
            result["ingress_key"] = identity.dedupe_key
            result["ingress_event_id"] = event["event_id"]
            return result

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
            ingress_key=identity.dedupe_key,
            actor_type=actor_type,
            actor_id=actor_id,
            permissions=permissions,
            system_context=system_context,
            correlation_id=correlation_id,
            definition=definition,
        )
        instance_id = result.get("instance_id")
        run_id = (result.get("run") or {}).get("run_id") if isinstance(result.get("run"), dict) else None
        await _finish_event(
            organization_id,
            event["event_id"],
            status="processed",
            instance_id=str(instance_id) if instance_id else None,
            run_id=str(run_id) if run_id else None,
            attempts=int(claimed.get("attempts") or 0),
            max_attempts=int(event.get("max_attempts") or _MAX_ATTEMPTS_DEFAULT),
        )
        result["durable"] = True
        result["ingress_key"] = identity.dedupe_key
        result["ingress_event_id"] = event["event_id"]
        return result
    except IdempotencyConflict as exc:
        await _finish_event(
            organization_id,
            event["event_id"],
            status="failed",
            error=str(exc)[:400],
            attempts=int(claimed.get("attempts") or 0),
            max_attempts=int(event.get("max_attempts") or _MAX_ATTEMPTS_DEFAULT),
        )
        return {
            "error": exc.code,
            "message": str(exc),
            "status_code": exc.status_code,
            "ingress_key": identity.dedupe_key,
            "ingress_event_id": event["event_id"],
        }
    except Exception as exc:  # noqa: BLE001
        await _finish_event(
            organization_id,
            event["event_id"],
            status="failed",
            error=str(exc)[:400],
            attempts=int(claimed.get("attempts") or 0),
            max_attempts=int(event.get("max_attempts") or _MAX_ATTEMPTS_DEFAULT),
        )
        raise


async def drain_ingress_events(*, limit: int = 50) -> dict[str, int]:
    """Worker de inbox: drena pendientes/fallidos con payload persistido."""
    await ensure_ingress_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id FROM workflow_ingress_events "
                    "WHERE status IN ('pending', 'failed') AND dead_letter_at IS NULL "
                    "AND (next_attempt_at IS NULL OR next_attempt_at <= NOW()) "
                    "ORDER BY received_at LIMIT :lim FOR UPDATE SKIP LOCKED"
                ),
                {"lim": max(1, min(int(limit), 200))},
            )
        ).fetchall()
        await session.commit()
    finally:
        await session.close()

    processed = failed = 0
    for candidate in rows:
        claimed = await _claim_event(
            UUID(str(candidate.organization_id)), str(candidate.id)
        )
        if claimed is None:
            continue
        session = await get_async_session()
        try:
            event = (
                await session.execute(
                    text("SELECT * FROM workflow_ingress_events WHERE id = :eid"),
                    {"eid": claimed["event_id"]},
                )
            ).fetchone()
        finally:
            await session.close()
        if event is None:
            continue
        organization_id = UUID(str(event.organization_id))
        try:
            row = await _load_workflow(UUID(str(event.workflow_id)))
            if row is None:
                raise IdempotencyConflict("workflow inexistente", code="not_found")
            envelope_data = getattr(event, "envelope", None) or {}
            if envelope_data:
                envelope = IngressEnvelope.model_validate(envelope_data)
            else:
                envelope = IngressEnvelope(
                    organization_id=organization_id,
                    workspace_id=UUID(str(event.workspace_id)) if event.workspace_id else None,
                    workflow_id=UUID(str(event.workflow_id)),
                    source="legacy",
                    payload=dict(event.payload or {}),
                    idempotency_key=event.ingress_key,
                )
            definition = await _definition_for(
                row,
                organization_id=organization_id,
                workspace_id=UUID(str(event.workspace_id)) if event.workspace_id else None,
                require_active=True,
            )
            graph = dict(definition.get("graph") or {})
            if is_durable_graph(graph):
                from src.platform.workflows.instances import start_workflow_instance

                result = await start_workflow_instance(
                    workflow_id=UUID(str(event.workflow_id)),
                    organization_id=organization_id,
                    workspace_id=UUID(str(event.workspace_id)) if event.workspace_id else None,
                    trigger=str(event.trigger_type or "event"),
                    payload=envelope.payload,
                    business_key=envelope.business_key,
                    ingress_key=envelope.idempotency_key or event.ingress_key,
                    correlation_id=envelope.correlation_id,
                    definition=definition,
                )
                await _finish_event(
                    organization_id,
                    str(event.id),
                    status="processed",
                    instance_id=str(result.get("instance_id")) if result.get("instance_id") else None,
                    run_id=(
                        str((result.get("run") or {}).get("run_id"))
                        if isinstance(result.get("run"), dict)
                        and (result.get("run") or {}).get("run_id")
                        else None
                    ),
                    attempts=int(claimed.get("attempts") or 0),
                    max_attempts=int(getattr(event, "max_attempts", _MAX_ATTEMPTS_DEFAULT) or _MAX_ATTEMPTS_DEFAULT),
                )
            else:
                from src.platform.workflows.engine import SYSTEM_NODE_PERMS, run_workflow

                result = await run_workflow(
                    UUID(str(event.workflow_id)),
                    envelope.payload,
                    trigger=str(event.trigger_type or "event"),
                    organization_id=organization_id,
                    workspace_id=UUID(str(event.workspace_id)) if event.workspace_id else None,
                    permissions=SYSTEM_NODE_PERMS,
                    system_context=True,
                    correlation_id=envelope.correlation_id,
                    definition_source=definition["definition_source"],
                )
                await _finish_event(
                    organization_id,
                    str(event.id),
                    status="processed",
                    run_id=str(result.get("run_id")) if result.get("run_id") else None,
                    attempts=int(claimed.get("attempts") or 0),
                    max_attempts=int(getattr(event, "max_attempts", _MAX_ATTEMPTS_DEFAULT) or _MAX_ATTEMPTS_DEFAULT),
                )
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            await _finish_event(
                organization_id,
                str(event.id),
                status="failed",
                error=str(exc)[:400],
                attempts=int(claimed.get("attempts") or 0),
                max_attempts=int(getattr(event, "max_attempts", _MAX_ATTEMPTS_DEFAULT) or _MAX_ATTEMPTS_DEFAULT),
            )
            logger.warning(
                "workflow ingress drain failed",
                event_id=str(event.id),
                workflow_id=str(event.workflow_id),
                error=str(exc)[:200],
            )
    return {"claimed": len(rows), "processed": processed, "failed": failed}


async def sweep_ingress_events(*, stale_minutes: int = _CLAIM_STALE_MINUTES) -> dict[str, int]:
    """Devuelve a pending los leases vencidos; no crea instancias por sí solo."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, stale_minutes))
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE workflow_ingress_events SET status = 'pending', "
                "next_attempt_at = NOW(), lease_expires_at = NULL, heartbeat_at = NULL, "
                "last_error = 'claim huérfano; reintento recuperable' "
                "WHERE status = 'processing' AND instance_id IS NULL AND run_id IS NULL "
                "AND (lease_expires_at < NOW() "
                "OR (lease_expires_at IS NULL AND claimed_at < :cutoff))"
            ),
            {"cutoff": cutoff},
        )
        await session.commit()
        return {"requeued": int(result.rowcount or 0)}
    finally:
        await session.close()


__all__ = [
    "DURABLE_NODE_TYPES",
    "IdempotencyConflict",
    "drain_ingress_events",
    "durable_reasons",
    "ensure_ingress_tables",
    "is_durable_graph",
    "normalize_ingress_key",
    "payload_hash",
    "route_ingress",
    "sweep_ingress_events",
]
