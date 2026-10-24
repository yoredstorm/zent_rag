# =============================================================================
# Workflow Instances — procesos de negocio durables sobre el motor v2.
#
# Modelo:
#   WorkflowDefinition (workflows.graph)  — qué debe ocurrir (portable).
#   WorkflowInstance   (workflow_instances) — ESTE proceso vivo, con estado
#                     de negocio durable y definición congelada a su versión.
#   WorkflowRun        (workflow_runs)    — segmento ejecutado entre
#                     checkpoints (WAIT libera el worker; SIGNAL reanuda).
#
# Reglas:
#   - Ningún proceso espera: WAIT suspende, el worker termina el segmento.
#   - La reanudación es un segmento nuevo (run_mode full + preload + edges
#     resueltos): cero re-ejecución de lo ya hecho.
#   - Signals: inbox durable (workflow_signals) con dedupe por constraints;
#     el mismo webhook jamás ejecuta dos veces una operación.
#   - Un único scheduler (workflow_v2_scheduler_loop) barre timeouts y
#     expiración; un único bus (rag:events) alimenta señales.
#   - Todo tenant-scoped por organization_id.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

ACTIVE_STATUSES: tuple[str, ...] = ("NEW", "RUNNING", "WAITING", "SUSPENDED")
TERMINAL_STATUSES: tuple[str, ...] = ("COMPLETED", "FAILED", "CANCELLED", "EXPIRED")

_TIMEOUT_EVENT = "workflow.wait.timeout"
_APPROVAL_EVENT = "approval.decided"
#: Reaper: una instancia RUNNING sin cierre tras este margen se marca FAILED
#: (proceso muerto a mitad de segmento). Conservador: los nodos tienen timeout
#: de hasta 300s; 6h cubre cadenas largas legítimas.
_REAP_MINUTES = 360
#: Retención (fail-soft, por lotes): señales cerradas e instancias terminales.
_SIGNAL_RETENTION_DAYS = 30
_INSTANCE_RETENTION_DAYS = 180

_instance_metrics: dict[str, Any] = {}


def _ensure_metrics() -> None:
    try:
        from prometheus_client import Counter

        _instance_metrics["transitions"] = Counter(
            "workflow_instance_transitions_total",
            "Transiciones de WorkflowInstance",
            ["status"],
        )
        _instance_metrics["signals"] = Counter(
            "workflow_instance_signals_total",
            "Señales procesadas para instancias durables",
            ["status"],
        )
    except Exception:  # noqa: BLE001 — métricas best-effort
        _instance_metrics.clear()


_ensure_metrics()


def _emit_instance_metric(status: str) -> None:
    try:
        counter = _instance_metrics.get("transitions")
        if counter is not None:
            counter.labels(status=str(status)[:30]).inc()
    except Exception:  # noqa: BLE001
        pass
    try:
        from src.platform.workflows.operations import record_transition

        record_transition(status)
    except Exception:  # noqa: BLE001
        pass


def _emit_signal_metric(status: str) -> None:
    try:
        counter = _instance_metrics.get("signals")
        if counter is not None:
            counter.labels(status=str(status)[:30]).inc()
    except Exception:  # noqa: BLE001
        pass

#: Presets de wait_event → event_type por defecto (el nodo puede sobreescribir).
WAIT_PRESET_EVENTS: dict[str, str] = {
    "message": "conversation.message",
    "webhook": "webhook",
    "payment": "payment.succeeded",
    "timer": _TIMEOUT_EVENT,
    "human": _APPROVAL_EVENT,
    "signal": "signal",
}


@dataclass
class InstanceRef:
    """Vista viva de la instancia para los nodos (state durable en memoria)."""

    id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    status: str
    conversation_id: UUID | None
    state: dict[str, Any] = field(default_factory=dict)
    #: Roles congelados al iniciar la instancia (P05). Un cambio de rol en vivo
    #: no amplía permisos de un proceso ya iniciado.
    policy_snapshot: dict[str, Any] = field(default_factory=dict)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def correlation_key(correlation: dict[str, Any] | None) -> str:
    """Normaliza una correlación {clave: valor} a string estable k=v&k2=v2."""
    if not correlation:
        return ""
    parts = [
        f"{str(k)}={str(v)}"
        for k, v in sorted(correlation.items())
        if v is not None and str(v) != ""
    ]
    return "&".join(parts)[:200]


# ---------------------------------------------------------------------------
# Paridad dev/test (la migración 153 manda en prod)
# ---------------------------------------------------------------------------
_INSTANCE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS workflow_instances (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        workspace_id UUID,
        workflow_id UUID NOT NULL,
        workflow_version INT NOT NULL DEFAULT 1,
        definition_snapshot JSONB NOT NULL DEFAULT '{}',
        status VARCHAR(20) NOT NULL DEFAULT 'NEW',
        conversation_id UUID,
        participant_id VARCHAR(160),
        business_key VARCHAR(200),
        current_node_id VARCHAR(80),
        state JSONB NOT NULL DEFAULT '{}',
        state_version INT NOT NULL DEFAULT 0,
        waiting_for JSONB NOT NULL DEFAULT '{}',
        waiting_event_type VARCHAR(120),
        waiting_correlation_key VARCHAR(200),
        wait_deadline TIMESTAMPTZ,
        wait_seq INT NOT NULL DEFAULT 0,
        last_run_id UUID,
        run_seq INT NOT NULL DEFAULT 0,
        started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMPTZ,
        expires_at TIMESTAMPTZ,
        correlation_id VARCHAR(128),
        ingress_key VARCHAR(200),
        created_by UUID,
        error TEXT,
        status_reason VARCHAR(200)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_signals (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        organization_id UUID NOT NULL,
        event_type VARCHAR(120) NOT NULL,
        external_event_id VARCHAR(200),
        idempotency_key VARCHAR(200),
        correlation_key VARCHAR(200),
        payload JSONB NOT NULL DEFAULT '{}',
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        instance_id UUID,
        instance_run_id UUID,
        source VARCHAR(40) NOT NULL DEFAULT 'internal',
        received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        claimed_at TIMESTAMPTZ,
        consumed_at TIMESTAMPTZ,
        discarded_reason VARCHAR(200)
    )
    """,
    "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS instance_id UUID",
    "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS instance_seq INT",
    "ALTER TABLE workflow_run_events ADD COLUMN IF NOT EXISTS instance_id UUID",
    "ALTER TABLE workflow_instances ADD COLUMN IF NOT EXISTS ingress_key VARCHAR(200)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_instances_ingress "
    "ON workflow_instances(organization_id, workflow_id, ingress_key) "
    "WHERE ingress_key IS NOT NULL",
)


async def ensure_instance_tables() -> None:
    """DDL fail-soft para dev/test; en prod la migración 153/154 manda."""
    session = await get_async_session()
    try:
        for ddl in _INSTANCE_DDL:
            await session.execute(text(ddl))
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — paridad best-effort
        await session.rollback()
        logger.warning("ensure_instance_tables failed", error=str(exc)[:200])
    finally:
        await session.close()


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------
def _instance_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "workflow_id": str(row.workflow_id),
        "workflow_version": int(row.workflow_version or 1),
        "definition_snapshot": dict(row.definition_snapshot or {}),
        "status": str(row.status),
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "participant_id": row.participant_id,
        "business_key": row.business_key,
        "current_node_id": row.current_node_id,
        "state": dict(row.state or {}),
        "state_version": int(row.state_version or 0),
        "waiting_for": dict(row.waiting_for or {}),
        "waiting_event_type": row.waiting_event_type,
        "waiting_correlation_key": row.waiting_correlation_key,
        "wait_deadline": row.wait_deadline.isoformat() if row.wait_deadline else None,
        "wait_seq": int(row.wait_seq or 0),
        "last_run_id": str(row.last_run_id) if row.last_run_id else None,
        "run_seq": int(row.run_seq or 0),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "correlation_id": row.correlation_id,
        "ingress_key": getattr(row, "ingress_key", None),
        "created_by": str(row.created_by) if row.created_by else None,
        "error": row.error,
        "status_reason": row.status_reason,
    }


_INSTANCE_COLUMNS = (
    "id, organization_id, workspace_id, workflow_id, workflow_version, "
    "definition_snapshot, status, conversation_id, participant_id, business_key, "
    "current_node_id, state, state_version, waiting_for, waiting_event_type, "
    "waiting_correlation_key, wait_deadline, wait_seq, last_run_id, run_seq, "
    "started_at, updated_at, completed_at, expires_at, correlation_id, "
    "ingress_key, created_by, error, status_reason"
)


async def load_instance_ref(organization_id: UUID, instance_id: UUID) -> InstanceRef | None:
    """Vista mínima para el runtime (state en memoria; mutar via mutate_instance_state)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, status, conversation_id, state, "
                    "definition_snapshot FROM workflow_instances "
                    "WHERE id = :iid AND organization_id = :oid"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    snapshot = row.definition_snapshot if isinstance(row.definition_snapshot, dict) else {}
    return InstanceRef(
        id=UUID(str(row.id)),
        organization_id=UUID(str(row.organization_id)),
        workspace_id=_uid(row.workspace_id),
        status=str(row.status),
        conversation_id=_uid(row.conversation_id),
        state=dict(row.state or {}),
        policy_snapshot=dict(snapshot.get("policy_snapshot") or {}),
    )


async def get_instance(
    organization_id: UUID,
    instance_id: UUID,
    *,
    workspace_id: UUID | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        sql = (
            f"SELECT {_INSTANCE_COLUMNS} FROM workflow_instances "
            "WHERE id = :iid AND organization_id = :oid"
        )
        params: dict[str, Any] = {
            "iid": str(instance_id),
            "oid": str(organization_id),
        }
        if workspace_id is not None:
            sql += " AND workspace_id = :ws"
            params["ws"] = str(workspace_id)
        row = (await session.execute(text(sql), params)).fetchone()
    finally:
        await session.close()
    return _instance_row(row) if row else None


async def list_instances(
    organization_id: UUID,
    *,
    workflow_id: UUID | None = None,
    conversation_id: UUID | None = None,
    business_key: str | None = None,
    status: str | None = None,
    workspace_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    filters = ["organization_id = :oid"]
    params: dict[str, Any] = {"oid": str(organization_id), "lim": min(int(limit), 200), "off": max(int(offset), 0)}
    if workflow_id:
        filters.append("workflow_id = :wid")
        params["wid"] = str(workflow_id)
    if conversation_id:
        filters.append("conversation_id = :cid")
        params["cid"] = str(conversation_id)
    if business_key:
        filters.append("business_key = :bkey")
        params["bkey"] = business_key
    if status:
        filters.append("status = :st")
        params["st"] = status
    if workspace_id is not None:
        filters.append("workspace_id = :ws")
        params["ws"] = str(workspace_id)
    where = " AND ".join(filters)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    f"SELECT {_INSTANCE_COLUMNS} FROM workflow_instances WHERE {where} "
                    "ORDER BY started_at DESC LIMIT :lim OFFSET :off"
                ),
                params,
            )
        ).fetchall()
        total = (
            await session.execute(
                text(f"SELECT COUNT(*) AS n FROM workflow_instances WHERE {where}"),
                params,
            )
        ).fetchone()
    finally:
        await session.close()
    return {"instances": [_instance_row(r) for r in rows], "total": int(total.n if total else 0)}


async def find_waiting_instance_by_conversation(
    organization_id: UUID, conversation_id: UUID
) -> dict | None:
    """Instancia viva esperando un mensaje de esta conversación (Conversation Router)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_INSTANCE_COLUMNS} FROM workflow_instances "
                    "WHERE organization_id = :oid AND conversation_id = :cid "
                    "AND status = 'WAITING' AND waiting_event_type = 'conversation.message' "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"oid": str(organization_id), "cid": str(conversation_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    return _instance_row(row) if row else None


async def load_instance_preload(
    organization_id: UUID, instance_id: UUID, *, scope: list[str] | None = None
) -> dict[str, tuple[str, dict, str | None, int]]:
    """Union de steps exitosos de TODOS los segmentos: checkpoint acumulado.

    `scope` acota el checkpoint a un conjunto de nodos: lo usa la re-entrada de
    bucle, que re-ejecuta el cuerpo del bucle y conserva el resto del proceso.
    """
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT s.node_id, s.status, s.output, s.error, s.retries "
                    "FROM workflow_run_steps s JOIN workflow_runs r ON r.id = s.run_id "
                    "WHERE r.instance_id = :iid AND r.organization_id = :oid "
                    "AND s.node_id IS NOT NULL AND s.status IN ('succeeded', 'simulated', 'approved') "
                    "ORDER BY r.started_at, s.step_index"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    allowed = set(scope) if scope is not None else None
    return {
        str(r.node_id): (str(r.status), dict(r.output or {}), r.error, int(r.retries or 0))
        for r in rows
        if allowed is None or str(r.node_id) in allowed
    }


async def instance_timeline(organization_id: UUID, instance_id: UUID) -> dict:
    """Timeline de la instancia: runs (segmentos), signals y eventos."""
    session = await get_async_session()
    try:
        runs = (
            await session.execute(
                text(
                    "SELECT id, status, trigger, instance_seq, started_at, completed_at, "
                    "duration_ms, error, correlation_id FROM workflow_runs "
                    "WHERE instance_id = :iid AND organization_id = :oid ORDER BY started_at"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchall()
        signals = (
            await session.execute(
                text(
                    "SELECT id, event_type, external_event_id, correlation_key, payload, status, "
                    "source, received_at, consumed_at FROM workflow_signals "
                    "WHERE instance_id = :iid AND organization_id = :oid ORDER BY received_at"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchall()
        events = (
            await session.execute(
                text(
                    "SELECT e.id, e.run_id, e.kind, e.node_id, e.payload, e.created_at "
                    "FROM workflow_run_events e "
                    "WHERE e.instance_id = :iid AND e.organization_id = :oid "
                    "ORDER BY e.seq LIMIT 1000"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "runs": [
            {
                "run_id": str(r.id),
                "status": r.status,
                "trigger": r.trigger,
                "instance_seq": r.instance_seq,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in runs
        ],
        "signals": [
            {
                "signal_id": str(s.id),
                "event_type": s.event_type,
                "external_event_id": s.external_event_id,
                "correlation_key": s.correlation_key,
                "payload": dict(s.payload or {}),
                "status": s.status,
                "source": s.source,
                "received_at": s.received_at.isoformat() if s.received_at else None,
                "consumed_at": s.consumed_at.isoformat() if s.consumed_at else None,
            }
            for s in signals
        ],
        "events": [
            {
                "id": str(e.id),
                "run_id": str(e.run_id),
                "kind": e.kind,
                "node_id": e.node_id,
                "payload": dict(e.payload or {}),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------
async def start_workflow_instance(
    *,
    workflow_id: UUID,
    organization_id: UUID,
    workspace_id: UUID | None = None,
    trigger: str = "manual",
    payload: dict | None = None,
    conversation_id: UUID | None = None,
    participant_id: str | None = None,
    business_key: str | None = None,
    ingress_key: str | None = None,
    actor_type: str = "system",
    actor_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    system_context: bool = False,
    correlation_id: str | None = None,
    expires_at: datetime | None = None,
) -> dict:
    """Crea la instancia (definición congelada) y ejecuta el primer segmento.

    `business_key` es idempotente: si existe una instancia activa con la misma
    clave (tenant scope) se reutiliza en vez de duplicar el proceso."""
    from src.platform.workflows.engine import WorkflowAccessError

    await ensure_instance_tables()
    session = await get_async_session()
    try:
        wf = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, name, description, steps, graph, "
                    "workflow_version, graph_source, trigger_type, trigger_config, status, "
                    "editor_state FROM workflows WHERE id = :wid"
                ),
                {"wid": str(workflow_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if wf is None:
        return {"status": "failed", "error": "workflow no existe"}
    if UUID(str(wf.organization_id)) != UUID(str(organization_id)):
        raise WorkflowAccessError("workflow no pertenece a la organización")
    if (
        workspace_id is not None
        and wf.workspace_id is not None
        and UUID(str(workspace_id)) != UUID(str(wf.workspace_id))
    ):
        raise WorkflowAccessError("workflow no pertenece al workspace")
    if str(wf.status) == "paused":
        return {"status": "paused", "message": "workflow pausado"}

    org = UUID(str(wf.organization_id))
    ws = _uid(wf.workspace_id) or _uid(workspace_id)
    graph = dict(wf.graph) if wf.graph else None
    if graph is None:
        from src.platform.workflows.ir import LegacyWorkflowAdapter

        graph = LegacyWorkflowAdapter.steps_to_graph(
            wf.steps or [], str(wf.trigger_type or "webhook"), dict(wf.trigger_config or {})
        ).to_dict()

    if ingress_key:
        existing = await _find_by_ingress(org, workflow_id, ingress_key)
        if existing is not None:
            return {
                "status": existing["status"],
                "instance_id": existing["id"],
                "reused": True,
                "instance": existing,
            }
    if business_key:
        active = await _find_active_by_business_key(org, business_key)
        if active is not None:
            return {
                "status": active["status"],
                "instance_id": active["id"],
                "reused": True,
                "instance": active,
            }

    snapshot = {
        "name": wf.name,
        "description": wf.description,
        "graph": graph,
        "workflow_version": int(wf.workflow_version or 1),
        "graph_source": str(wf.graph_source or "graph"),
        "steps": list(wf.steps or []),
        "trigger_type": str(wf.trigger_type or "manual"),
        "trigger_config": dict(wf.trigger_config or {}),
        "editor_state": dict(wf.editor_state or {}),
        "ingress": {
            "trigger": trigger,
            "ingress_key": ingress_key,
            "business_key": business_key,
        },
        "policy_snapshot": await _build_policy_snapshot(org, graph),
    }
    instance_id = _new_uuid()
    corr = (correlation_id or "").strip() or ingress_key or f"inst:{instance_id}"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_instances "
                "(id, organization_id, workspace_id, workflow_id, workflow_version, "
                "definition_snapshot, status, conversation_id, participant_id, business_key, "
                "expires_at, correlation_id, ingress_key, created_by) "
                "VALUES (:iid, :oid, :ws, :wid, :ver, CAST(:snap AS jsonb), 'RUNNING', :cid, :pid, "
                ":bkey, :expires, :corr, :ikey, :uid)"
            ),
            {
                "iid": str(instance_id),
                "oid": str(org),
                "ws": str(ws) if ws else None,
                "wid": str(wf.id),
                "ver": int(wf.workflow_version or 1),
                "snap": json.dumps(snapshot, ensure_ascii=False, default=str),
                "cid": str(conversation_id) if conversation_id else None,
                "pid": participant_id,
                "bkey": business_key,
                "expires": expires_at,
                "corr": corr[:128],
                "ikey": ingress_key,
                "uid": str(actor_id) if actor_id else None,
            },
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if ingress_key:
            existing = await _find_by_ingress(org, workflow_id, ingress_key)
            if existing is not None:
                return {
                    "status": existing["status"],
                    "instance_id": existing["id"],
                    "reused": True,
                    "instance": existing,
                }
        if business_key:
            active = await _find_active_by_business_key(org, business_key)
            if active is not None:
                return {
                    "status": active["status"],
                    "instance_id": active["id"],
                    "reused": True,
                    "instance": active,
                }
        raise
    finally:
        await session.close()

    from src.platform.workflows.context_store import append_run_event as _append

    instance = await get_instance(org, instance_id)
    if instance is None:
        return {"status": "failed", "error": "instancia no creada"}
    try:
        await _append(
            org,
            instance_id,
            "instance_started",
            payload={"workflow_id": str(workflow_id), "trigger": trigger, "business_key": business_key},
            instance_id=instance_id,
        )
    except Exception as exc:  # noqa: BLE001 — timeline best-effort
        logger.warning("instance event failed", error=str(exc)[:200])

    result = await _run_instance_segment(
        instance,
        trigger=trigger,
        payload=payload or {},
        actor_type=actor_type,
        permissions=permissions,
        system_context=system_context,
        correlation=correlation_id,
    )
    fresh = await get_instance(org, instance_id)
    return {
        "status": "running",
        "instance_id": str(instance_id),
        "run": result,
        "instance": fresh,
    }


def _new_uuid() -> UUID:
    import uuid as _uuid

    return _uuid.uuid4()


async def _build_policy_snapshot(
    organization_id: UUID, graph: dict[str, Any]
) -> dict[str, Any]:
    """Congela rol/versión de cada agente LLM al iniciar la instancia."""
    agent_ids = sorted(
        {
            str((node.get("config") or {}).get("agent_id"))
            for node in graph.get("nodes") or []
            if isinstance(node, dict)
            and node.get("type") == "llm"
            and (node.get("config") or {}).get("agent_id")
        }
    )
    if not agent_ids:
        return {"agents": []}
    from src.platform.studio.roles import get_role

    agents: list[dict[str, Any]] = []
    session = await get_async_session()
    try:
        for agent_id in agent_ids:
            row = (
                await session.execute(
                    text(
                        "SELECT id, role_profile_id, is_active FROM agents "
                        "WHERE id = :aid AND organization_id = :oid"
                    ),
                    {"aid": agent_id, "oid": organization_id},
                )
            ).fetchone()
            if row is None:
                continue
            role = (
                await get_role(organization_id, UUID(str(row.role_profile_id)))
                if row.role_profile_id
                else None
            )
            agents.append(
                {
                    "agent_id": str(row.id),
                    "is_active": bool(row.is_active),
                    "role_profile_id": (
                        str(row.role_profile_id) if row.role_profile_id else None
                    ),
                    "role": role,
                }
            )
    finally:
        await session.close()
    return {"agents": agents}


async def find_by_ingress(
    organization_id: UUID, workflow_id: UUID, ingress_key: str
) -> dict | None:
    return await _find_by_ingress(organization_id, workflow_id, ingress_key)


async def _find_by_ingress(
    organization_id: UUID, workflow_id: UUID, ingress_key: str
) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_INSTANCE_COLUMNS} FROM workflow_instances "
                    "WHERE organization_id = :oid AND workflow_id = :wid "
                    "AND ingress_key = :ikey LIMIT 1"
                ),
                {"oid": str(organization_id), "wid": str(workflow_id), "ikey": ingress_key},
            )
        ).fetchone()
    finally:
        await session.close()
    return _instance_row(row) if row else None


async def _find_active_by_business_key(organization_id: UUID, business_key: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"SELECT {_INSTANCE_COLUMNS} FROM workflow_instances "
                    "WHERE organization_id = :oid AND business_key = :bkey "
                    "AND status IN ('NEW', 'RUNNING', 'WAITING', 'SUSPENDED') LIMIT 1"
                ),
                {"oid": str(organization_id), "bkey": business_key},
            )
        ).fetchone()
    finally:
        await session.close()
    return _instance_row(row) if row else None


async def _claim_instance(organization_id: UUID, instance_id: UUID) -> dict | None:
    """Claim atómico WAITING→RUNNING: exactly-one-winner por construcción."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    f"UPDATE workflow_instances SET status = 'RUNNING', updated_at = NOW() "
                    "WHERE id = :iid AND organization_id = :oid AND status = 'WAITING' "
                    f"RETURNING {_INSTANCE_COLUMNS}"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return _instance_row(row) if row else None


async def _run_instance_segment(
    instance: dict[str, Any],
    *,
    trigger: str,
    payload: dict[str, Any],
    actor_type: str = "signal",
    permissions: frozenset[str] | None = None,
    system_context: bool = True,
    correlation: str | None = None,
    preload_ports: dict[str, str] | None = None,
    preload_scope: list[str] | None = None,
    run_seq: int | None = None,
) -> dict:
    """Ejecuta un segmento de la instancia reutilizando run_workflow."""
    from src.platform.workflows.engine import run_workflow

    org = UUID(str(instance["organization_id"]))
    iid = UUID(str(instance["id"]))
    seq = int(run_seq if run_seq is not None else int(instance.get("run_seq") or 0) + 1)
    graph = (instance.get("definition_snapshot") or {}).get("graph")
    return await run_workflow(
        UUID(str(instance["workflow_id"])),
        payload or {},
        trigger=trigger,
        organization_id=org,
        workspace_id=_uid(instance.get("workspace_id")),
        actor_type=actor_type,
        system_context=system_context,
        permissions=permissions,
        correlation_id=correlation or f"inst:{iid}:r{seq}",
        run_mode="full",
        source_run_id=_uid(instance.get("last_run_id")),
        graph_override=dict(graph) if graph else None,
        workflow_version_override=int(instance.get("workflow_version") or 1),
        instance_id=iid,
        instance_seq=seq,
        preload_ports=preload_ports,
        preload_scope=preload_scope,
    )


async def handle_segment_result(
    *,
    instance_id: UUID,
    organization_id: UUID,
    run_id: UUID,
    instance_seq: int,
    status: str,
    error: str | None,
    waiting: dict[str, Any] | None,
    wait_node_id: str | None,
    wait_port: str,
    looping: dict[str, Any] | None = None,
    loop_node_id: str | None = None,
) -> None:
    """Cierre de segmento: WAITING (checkpoint) o terminal. Nunca deja proceso vivo."""
    org = UUID(str(organization_id))
    iid = UUID(str(instance_id))
    if status == "looping":
        logger.info(
            "instance loop segment", instance_id=str(iid), spec=dict(looping or {})
        )
    if status == "looping" and looping:
        await _continue_loop(
            org=org,
            iid=iid,
            run_id=UUID(str(run_id)),
            instance_seq=instance_seq,
            loop_spec=looping,
            loop_node_id=loop_node_id or "",
        )
        return
    if status == "waiting" and waiting:
        await _enter_wait(
            org=org,
            iid=iid,
            run_id=UUID(str(run_id)),
            instance_seq=instance_seq,
            wait_node_id=wait_node_id or "",
            waiting=waiting,
        )
        return
    if status == "pending_approval":
        # Aprobación humana (legacy control): también es un wait durable.
        await _enter_wait(
            org=org,
            iid=iid,
            run_id=UUID(str(run_id)),
            instance_seq=instance_seq,
            wait_node_id=wait_node_id or "",
            waiting={
                "event_type": _APPROVAL_EVENT,
                "correlation": {"run_id": str(run_id)},
                "timeout_seconds": None,
                "port": "out",
                "preset": "human",
            },
        )
        return
    if status in ("succeeded", "simulated"):
        await _finalize_instance(
            org=org,
            iid=iid,
            run_id=UUID(str(run_id)),
            instance_seq=instance_seq,
            new_status="COMPLETED",
            reason="simulated" if status == "simulated" else None,
            error=None,
        )
        return
    if status == "stopped":
        await _finalize_instance(
            org=org,
            iid=iid,
            run_id=UUID(str(run_id)),
            instance_seq=instance_seq,
            new_status="COMPLETED",
            reason="stopped",
            error=None,
        )
        return
    if status == "failed":
        await _finalize_instance(
            org=org,
            iid=iid,
            run_id=UUID(str(run_id)),
            instance_seq=instance_seq,
            new_status="FAILED",
            reason="segment_failed",
            error=error,
        )


async def _run_trigger_payload(org: UUID, run_id: UUID) -> dict[str, Any]:
    """Payload del segmento que pidió la re-entrada (continuidad del trigger)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT trigger_payload FROM workflow_runs WHERE id = :rid AND organization_id = :oid"
                ),
                {"rid": str(run_id), "oid": str(org)},
            )
        ).fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.warning("loop trigger payload lookup failed", error=str(exc)[:160])
        row = None
    finally:
        await session.close()
    return dict(row.trigger_payload or {}) if row else {}


def _loop_body(graph: dict[str, Any], target: str, loop_node_id: str) -> set[str]:
    """Nodos que se re-ejecutan: alcanzables desde `target` que vuelven al loop."""
    edges = list(graph.get("edges") or [])
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for edge in edges:
        src, dst = str(edge.get("from_node")), str(edge.get("to_node"))
        forward.setdefault(src, set()).add(dst)
        backward.setdefault(dst, set()).add(src)

    def _walk(start: str, graph_map: dict[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            for nxt in graph_map.get(node, set()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        return seen

    from_target = _walk(target, forward) | {target}
    to_loop = _walk(loop_node_id, backward) | {loop_node_id}
    return (from_target & to_loop) or {target, loop_node_id}


async def _continue_loop(
    *,
    org: UUID,
    iid: UUID,
    run_id: UUID,
    instance_seq: int,
    loop_spec: dict[str, Any],
    loop_node_id: str,
) -> None:
    """Re-entrada de bucle: repite el cuerpo sin re-ejecutar el resto del proceso.

    El grafo sigue siendo acíclico; lo que se acota es el checkpoint: el cuerpo
    del bucle queda fuera del preload del nuevo segmento y todo lo demás se
    conserva (contexto, carrito, orden, datos ya resueltos).
    """
    instance = await get_instance(org, iid)
    if instance is None:
        return
    status = str(instance.get("status") or "")
    if status not in ("NEW", "RUNNING", "WAITING", "SUSPENDED"):
        return  # CANCELLED/terminal: el cierre no revive procesos
    graph = (instance.get("definition_snapshot") or {}).get("graph") or {}
    target = str(loop_spec.get("target") or "")
    node_ids = {str(n.get("id")) for n in (graph.get("nodes") or [])}
    if not target or target not in node_ids:
        await _finalize_instance(
            org=org,
            iid=iid,
            run_id=run_id,
            instance_seq=instance_seq,
            new_status="FAILED",
            reason="loop_target_missing",
            error=f"nodo de re-entrada inexistente: {target}",
        )
        return
    body = _loop_body(graph, target, loop_node_id)
    full = await load_instance_preload(org, iid)
    scope = [nid for nid in full if nid not in body]
    payload = await _run_trigger_payload(org, run_id)
    from src.platform.workflows.context_store import append_run_event

    await append_run_event(
        org,
        run_id,
        "loop_reentered",
        node_id=loop_node_id or None,
        payload={
            "target": target,
            "iteration": loop_spec.get("iteration"),
            "reset_nodes": sorted(body),
            "segment_seq": instance_seq,
        },
        instance_id=iid,
    )
    # El segmento nuevo cierra por sí mismo (wait / loop / terminal): el cierre
    # de instancia lo hace `handle_segment_result` dentro de run_workflow.
    await _run_instance_segment(
        instance,
        trigger="loop",
        payload=payload,
        correlation=f"inst:{iid}:r{instance_seq + 1}",
        preload_scope=scope,
        run_seq=instance_seq + 1,
    )
    _emit_instance_metric("LOOP")


async def _enter_wait(
    *,
    org: UUID,
    iid: UUID,
    run_id: UUID,
    instance_seq: int,
    wait_node_id: str,
    waiting: dict[str, Any],
) -> None:
    event_type = str(waiting.get("event_type") or "signal")[:120]
    ck = correlation_key(waiting.get("correlation") or {})
    timeout_seconds = waiting.get("timeout_seconds")
    deadline = None
    try:
        if timeout_seconds:
            deadline = _now() + timedelta(seconds=int(timeout_seconds))
    except (TypeError, ValueError):
        deadline = None
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_instances SET status = 'WAITING', current_node_id = :nid, "
                "waiting_for = CAST(:wait AS jsonb), waiting_event_type = :et, "
                "waiting_correlation_key = :ck, wait_deadline = :deadline, "
                "last_run_id = :rid, run_seq = :seq, wait_seq = wait_seq + 1, updated_at = NOW() "
                "WHERE id = :iid AND organization_id = :oid AND status IN ('NEW', 'RUNNING')"
            ),
            {
                "nid": wait_node_id[:80] if wait_node_id else None,
                "wait": json.dumps(waiting, ensure_ascii=False, default=str),
                "et": event_type,
                "ck": ck or None,
                "deadline": deadline,
                "rid": str(run_id),
                "seq": int(instance_seq or 0),
                "iid": str(iid),
                "oid": str(org),
            },
        )
        await session.commit()
    finally:
        await session.close()
    try:
        from src.platform.workflows.context_store import append_run_event

        await append_run_event(
            org,
            run_id,
            "wait_entered",
            node_id=wait_node_id or None,
            payload={"event_type": event_type, "correlation": waiting.get("correlation") or {}},
            instance_id=iid,
        )
    except Exception as exc:  # noqa: BLE001 — timeline best-effort
        logger.warning("wait event failed", error=str(exc)[:200])
    _emit_instance_metric("WAITING")
    # Race webhook-antes-de-WAIT: señales ya recibidas se consumen al llegar al wait.
    if event_type != _APPROVAL_EVENT:
        try:
            await _consume_pending_for_instance(org, iid)
        except Exception as exc:  # noqa: BLE001 — el siguiente signal reintenta
            logger.warning("pending signal pickup failed", error=str(exc)[:200])


async def _finalize_instance(
    *,
    org: UUID,
    iid: UUID,
    run_id: UUID,
    instance_seq: int,
    new_status: str,
    reason: str | None,
    error: str | None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_instances SET status = :st, completed_at = NOW(), "
                "last_run_id = :rid, run_seq = :seq, updated_at = NOW(), "
                "status_reason = :reason, error = :err, "
                "waiting_for = '{}'::jsonb, waiting_event_type = NULL, "
                "waiting_correlation_key = NULL, wait_deadline = NULL "
                "WHERE id = :iid AND organization_id = :oid AND status IN ('NEW', 'RUNNING', 'WAITING')"
            ),
            {
                "st": new_status,
                "rid": str(run_id),
                "seq": int(instance_seq or 0),
                "reason": reason,
                "err": (error or None),
                "iid": str(iid),
                "oid": str(org),
            },
        )
        await session.commit()
    finally:
        await session.close()
    try:
        from src.platform.workflows.context_store import append_run_event

        kind = {
            "COMPLETED": "instance_completed",
            "FAILED": "instance_failed",
            "CANCELLED": "instance_cancelled",
            "EXPIRED": "instance_expired",
        }.get(new_status, "instance_updated")
        await append_run_event(
            org,
            run_id,
            kind,
            payload={"status": new_status, "reason": reason, "error": error},
            instance_id=iid,
        )
    except Exception as exc:  # noqa: BLE001 — timeline best-effort
        logger.warning("instance finalize event failed", error=str(exc)[:200])
    _emit_instance_metric(new_status)


# ---------------------------------------------------------------------------
# Signals (inbox durable)
# ---------------------------------------------------------------------------
async def signal_workflow_instance(
    *,
    organization_id: UUID,
    event_type: str,
    correlation: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
    external_event_id: str | None = None,
    idempotency_key: str | None = None,
    source: str = "internal",
    instance_id: UUID | None = None,
    workflow_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> dict:
    """Registra un evento y reanuda las instancias WAITING compatibles.

    Idempotente por constraints: mismo external_event_id/idempotency_key jamás
    se procesa dos veces. Sin instancias compatibles el signal queda pending
    (cubre el caso webhook-antes-de-WAIT)."""
    await ensure_instance_tables()
    org = UUID(str(organization_id))
    if instance_id is not None and workspace_id is not None:
        scoped = await get_instance(org, instance_id, workspace_id=workspace_id)
        if scoped is None:
            return {"status": "not_found", "signal_id": None, "resumed": False}
    et = str(event_type)[:120]
    ck = correlation_key(correlation or {})
    session = await get_async_session()
    try:
        inserted = (
            await session.execute(
                text(
                    "INSERT INTO workflow_signals "
                    "(organization_id, event_type, external_event_id, idempotency_key, "
                    "correlation_key, payload, source) "
                    "VALUES (:oid, :et, :ext, :idem, :ck, CAST(:payload AS jsonb), :src) "
                    "ON CONFLICT DO NOTHING RETURNING id"
                ),
                {
                    "oid": str(org),
                    "et": et,
                    "ext": (external_event_id or None),
                    "idem": (idempotency_key or None),
                    "ck": ck or None,
                    "payload": json.dumps(payload or {}, ensure_ascii=False, default=str),
                    "src": str(source)[:40],
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if inserted is None:
        existing = await _find_duplicate_signal(org, et, external_event_id, idempotency_key)
        _emit_signal_metric("duplicate")
        return {
            "status": "duplicate",
            "signal_id": existing.get("id") if existing else None,
            "consumed": bool(existing and existing.get("status") == "consumed"),
            "resumed": False,
        }
    signal_id = str(inserted.id)

    instances: list[dict[str, Any]] = []
    if instance_id is not None:
        inst = await get_instance(org, UUID(str(instance_id)))
        if inst is not None and inst["status"] == "WAITING":
            if workflow_id is not None and str(inst.get("workflow_id")) != str(workflow_id):
                return {
                    "status": "workflow_mismatch",
                    "signal_id": signal_id,
                    "resumed": False,
                }
            wait_ck = inst.get("waiting_correlation_key") or ""
            if et != _TIMEOUT_EVENT and ck != wait_ck:
                # Correlación incorrecta: la instancia no se despierta.
                return {
                    "status": "correlation_mismatch",
                    "signal_id": signal_id,
                    "resumed": False,
                    "expected_correlation": wait_ck,
                }
            wait_et = str(inst.get("waiting_event_type") or "")
            if et != _TIMEOUT_EVENT and wait_et and et != wait_et:
                # Tipo de evento incorrecto: un `payment.failed` no puede
                # despertar un wait de `payment.succeeded` (jamás convierte un
                # fallo en una venta). El signal queda en el inbox.
                return {
                    "status": "event_mismatch",
                    "signal_id": signal_id,
                    "resumed": False,
                    "expected_event_type": wait_et,
                }
            instances = [inst]
    else:
        session = await get_async_session()
        try:
            sql = (
                f"SELECT {_INSTANCE_COLUMNS} FROM workflow_instances "
                "WHERE organization_id = :oid AND status = 'WAITING' "
                "AND waiting_event_type = :et "
                "AND COALESCE(waiting_correlation_key, '') = :ck "
            )
            params: dict[str, Any] = {"oid": str(org), "et": et, "ck": ck}
            if workflow_id is not None:
                sql += "AND workflow_id = :wid "
                params["wid"] = str(workflow_id)
            if workspace_id is not None:
                sql += "AND workspace_id = :ws "
                params["ws"] = str(workspace_id)
            sql += "ORDER BY updated_at ASC LIMIT 10"
            rows = (await session.execute(text(sql), params)).fetchall()
        finally:
            await session.close()
        instances = [_instance_row(r) for r in rows]

    if not instances:
        _emit_signal_metric("queued")
        return {"status": "queued", "signal_id": signal_id, "resumed": False}

    resumed: list[dict[str, Any]] = []
    for inst in instances:
        port = "timeout" if et == _TIMEOUT_EVENT else "out"
        out = await _claim_and_resume(inst, signal_row={"id": signal_id, "payload": payload or {}}, port=port)
        resumed.append({"instance_id": inst["id"], **out})
        if out.get("status") == "payload_invalid":
            return {
                "status": "payload_invalid",
                "signal_id": signal_id,
                "resumed": False,
                "errors": out.get("errors") or [],
                "results": resumed,
            }
        if out.get("claimed"):
            break
    _emit_signal_metric("resumed" if any(r.get("claimed") for r in resumed) else "duplicate")
    return {
        "status": "resumed" if any(r.get("claimed") for r in resumed) else "duplicate",
        "signal_id": signal_id,
        "resumed": any(r.get("claimed") for r in resumed),
        "results": resumed,
    }


async def _find_duplicate_signal(
    org: UUID, event_type: str, external_event_id: str | None, idempotency_key: str | None
) -> dict | None:
    session = await get_async_session()
    try:
        if external_event_id:
            row = (
                await session.execute(
                    text(
                        "SELECT id, status FROM workflow_signals WHERE organization_id = :oid "
                        "AND event_type = :et AND external_event_id = :ext LIMIT 1"
                    ),
                    {"oid": str(org), "et": event_type, "ext": external_event_id},
                )
            ).fetchone()
        elif idempotency_key:
            row = (
                await session.execute(
                    text(
                        "SELECT id, status FROM workflow_signals WHERE organization_id = :oid "
                        "AND idempotency_key = :idem LIMIT 1"
                    ),
                    {"oid": str(org), "idem": idempotency_key},
                )
            ).fetchone()
        else:
            row = None
    finally:
        await session.close()
    return {"id": str(row.id), "status": str(row.status)} if row else None


async def signal_instance_from_hook(workflow_id: UUID, secret: str, body: dict[str, Any]) -> dict:
    """Inbound público: valida el secret del workflow (mismo canal que el hook
    de arranque) y emite una señal para sus instancias durables.

    Acepta: {event_type|event, correlation, payload, external_event_id,
    idempotency_key, instance_id}. Sin `instance_id` despierta instancias
    WAITING de ESTE workflow compatibles con event_type + correlation."""
    import hmac as _hmac

    from src.platform.workflows.engine import _hash_hook_secret

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, status, trigger_config "
                    "FROM workflows WHERE id = :wid"
                ),
                {"wid": str(workflow_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"error": "not_found"}
    if str(row.status) == "paused":
        return {"status": "paused", "message": "workflow pausado"}
    if str(row.status) != "active":
        return {"error": "inactive"}
    tcfg = row.trigger_config if isinstance(row.trigger_config, dict) else {}
    expected = str(tcfg.get("hook_secret_hash") or "")
    got = _hash_hook_secret(secret or "")
    if not expected or not _hmac.compare_digest(expected, got):
        return {"error": "unauthorized"}
    event_type = str(body.get("event_type") or body.get("event") or "").strip()
    if not event_type:
        return {"error": "missing_event_type"}
    correlation = body.get("correlation") if isinstance(body.get("correlation"), dict) else {}
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    external_event_id = str(body.get("external_event_id") or "").strip() or None
    idempotency_key = str(body.get("idempotency_key") or "").strip() or None
    instance_id = _uid(body.get("instance_id"))
    out = await signal_workflow_instance(
        organization_id=UUID(str(row.organization_id)),
        event_type=event_type,
        correlation=correlation,
        payload=payload,
        external_event_id=external_event_id,
        idempotency_key=idempotency_key,
        source="webhook",
        instance_id=instance_id,
        workflow_id=UUID(str(row.id)),
    )
    if out.get("status") == "workflow_mismatch":
        return {"error": "not_found"}
    return out


async def _mark_signal_consumed(org: UUID, signal_id: str, iid: UUID, run_id: UUID | None) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_signals SET status = 'consumed', claimed_at = COALESCE(claimed_at, NOW()), "
                "consumed_at = NOW(), instance_id = COALESCE(instance_id, :iid), "
                "instance_run_id = COALESCE(instance_run_id, :rid) "
                "WHERE id = :sid AND organization_id = :oid"
            ),
            {"sid": str(signal_id), "oid": str(org), "iid": str(iid), "rid": str(run_id) if run_id else None},
        )
        await session.commit()
    finally:
        await session.close()


async def _consume_pending_for_instance(org: UUID, iid: UUID) -> dict | None:
    """Consume el signal pending más antiguo que matchee el wait actual."""
    inst = await get_instance(org, iid)
    if inst is None or inst["status"] != "WAITING":
        return None
    et = inst.get("waiting_event_type") or ""
    ck = inst.get("waiting_correlation_key") or ""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, event_type, payload, external_event_id, correlation_key "
                    "FROM workflow_signals WHERE organization_id = :oid AND status = 'pending' "
                    "AND event_type = :et AND COALESCE(correlation_key, '') = :ck "
                    "ORDER BY received_at ASC LIMIT 1"
                ),
                {"oid": str(org), "et": et, "ck": ck},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    port = "timeout" if str(row.event_type) == _TIMEOUT_EVENT else "out"
    return await _claim_and_resume(
        inst,
        signal_row={"id": str(row.id), "payload": dict(row.payload or {})},
        port=port,
    )


def _targets_for_port(graph: dict[str, Any] | None, wait_node: str | None, port: str) -> list[str]:
    if not graph or not wait_node:
        return []
    return [
        str(edge.get("to_node"))
        for edge in (graph.get("edges") or [])
        if str(edge.get("from_node")) == str(wait_node) and str(edge.get("from_port") or "out") == port
    ]


def _payload_schema_errors(
    schema: dict[str, Any], payload: Any, *, path: str = ""
) -> list[str]:
    """Validador acotado de JSON Schema para señales (sin dependencia extra)."""
    errors: list[str] = []
    expected_type = schema.get("type")
    type_map = {
        "object": dict,
        "array": list,
        "string": str,
        "number": (int, float),
        "integer": int,
        "boolean": bool,
        "null": type(None),
    }
    if isinstance(expected_type, str) and expected_type in type_map:
        expected = type_map[expected_type]
        if not isinstance(payload, expected) or (
            expected_type in ("number", "integer") and isinstance(payload, bool)
        ):
            errors.append(f"{path or '$'}: se esperaba {expected_type}")
            return errors
    if isinstance(payload, dict):
        for required in schema.get("required") or []:
            if required not in payload:
                errors.append(f"{path or '$'}: falta {required}")
        properties = schema.get("properties") or {}
        if isinstance(properties, dict):
            for key, child in properties.items():
                if key in payload and isinstance(child, dict):
                    errors.extend(
                        _payload_schema_errors(
                            child, payload[key], path=f"{path}.{key}" if path else key
                        )
                    )
    elif isinstance(payload, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(payload[:20]):
            errors.extend(
                _payload_schema_errors(
                    schema["items"], item, path=f"{path}[{index}]"
                )
            )
    return errors


async def _claim_and_resume(
    instance: dict[str, Any], *, signal_row: dict[str, Any] | None, port: str
) -> dict:
    """Claim atómico + segmento nuevo. Un solo ganador; el resto queda pending."""
    if signal_row is not None:
        expected_schema = (instance.get("waiting_for") or {}).get(
            "expected_payload_schema"
        )
        if isinstance(expected_schema, dict) and expected_schema:
            errors = _payload_schema_errors(
                expected_schema, dict(signal_row.get("payload") or {})
            )
            if errors:
                return {
                    "claimed": False,
                    "status": "payload_invalid",
                    "errors": [error[:200] for error in errors[:5]],
                }
    org = UUID(str(instance["organization_id"]))
    iid = UUID(str(instance["id"]))
    claimed = await _claim_instance(org, iid)
    if claimed is None:
        return {"claimed": False, "reason": "already_claimed"}
    _emit_instance_metric("RUNNING")
    if signal_row is not None:
        try:
            await _mark_signal_consumed(org, signal_row["id"], iid, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("signal consume mark failed", error=str(exc)[:200])

    graph = (claimed.get("definition_snapshot") or {}).get("graph")
    wait_node = claimed.get("current_node_id")
    waiting = claimed.get("waiting_for") or {}
    effective_port = port
    if port == "timeout":
        on_timeout = str(waiting.get("on_timeout") or "")
        has_timeout_edge = bool(_targets_for_port(graph, wait_node, "timeout"))
        if on_timeout == "expire" or (not on_timeout and not has_timeout_edge):
            await _expire_instance(org, iid, "wait_timeout")
            return {"claimed": True, "status": "EXPIRED", "reason": "wait_timeout"}
        if on_timeout == "fail":
            await _finalize_instance(
                org=org,
                iid=iid,
                run_id=_uid(claimed.get("last_run_id")) or iid,
                instance_seq=int(claimed.get("run_seq") or 0),
                new_status="FAILED",
                reason="wait_timeout",
                error="timeout de espera",
            )
            return {"claimed": True, "status": "FAILED", "reason": "wait_timeout"}
        if on_timeout == "continue" or not has_timeout_edge:
            effective_port = "out"

    targets = _targets_for_port(graph, wait_node, effective_port)
    if not targets:
        # El flujo terminó tras el wait.
        if port == "timeout":
            await _expire_instance(org, iid, "wait_timeout")
            return {"claimed": True, "status": "EXPIRED", "reason": "wait_timeout"}
        await _finalize_instance(
            org=org,
            iid=iid,
            run_id=_uid(claimed.get("last_run_id")) or iid,
            instance_seq=int(claimed.get("run_seq") or 0),
            new_status="COMPLETED",
            reason="after_wait",
            error=None,
        )
        return {"claimed": True, "status": "COMPLETED", "reason": "after_wait"}

    # El puerto real del wait queda persistido: si mañana hay otro segmento, la
    # re-derivación de edges conoce qué rama se tomó históricamente.
    await _record_wait_port(org, _uid(claimed.get("last_run_id")), wait_node, effective_port)
    await _record_wait_payload(
        org,
        _uid(claimed.get("last_run_id")),
        wait_node,
        dict((signal_row or {}).get("payload") or {}),
        effective_port,
    )

    payload = dict((signal_row or {}).get("payload") or {})
    result = await _run_instance_segment(
        claimed,
        trigger="signal",
        payload=payload,
        actor_type="signal",
        system_context=True,
        preload_ports={str(wait_node): effective_port} if wait_node else None,
    )
    # El run puede haber vuelto a WAITING (handle_segment_result ya corrió).
    fresh = await get_instance(org, iid)
    return {
        "claimed": True,
        "status": (fresh or {}).get("status") if fresh else None,
        "run": result,
    }


async def _record_wait_payload(
    org: UUID,
    run_id: UUID | None,
    wait_node: str | None,
    payload: dict[str, Any],
    port: str,
) -> None:
    """Expone el payload del signal como salida del nodo WAIT reanudado.

    Sin esto, los pasos posteriores solo verían `{"waiting": true}` y no la
    respuesta del cliente/pago. El preload del segmento nuevo lee este output.
    """
    if run_id is None or not wait_node:
        return
    patch = {**payload, "port": port, "signal_received": True}
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_run_steps SET output = COALESCE(output, '{}'::jsonb) "
                "|| CAST(:patch AS jsonb) WHERE run_id = :rid AND node_id = :nid"
            ),
            {
                "patch": json.dumps(patch, ensure_ascii=False, default=str),
                "rid": str(run_id),
                "nid": wait_node,
            },
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — la reanudación no depende de esto
        logger.warning("wait payload record failed", error=str(exc)[:200])
    finally:
        await session.close()


async def _record_wait_port(org: UUID, run_id: UUID | None, wait_node: str | None, port: str) -> None:
    """Persiste el puerto real tomado por el wait en el step del segmento previo."""
    if run_id is None or not wait_node:
        return
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_run_steps SET output = COALESCE(output, '{}'::jsonb) "
                "|| CAST(:patch AS jsonb) "
                "WHERE run_id = :rid AND node_id = :nid"
            ),
            {"patch": json.dumps({"port": port}), "rid": str(run_id), "nid": wait_node},
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — la reanudación no depende de esto
        logger.warning("wait port record failed", error=str(exc)[:200])
    finally:
        await session.close()


async def _expire_instance(org: UUID, iid: UUID, reason: str) -> None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_instances SET status = 'EXPIRED', completed_at = NOW(), "
                    "updated_at = NOW(), status_reason = :reason "
                    "WHERE id = :iid AND organization_id = :oid AND status = 'RUNNING' "
                    "RETURNING last_run_id"
                ),
                {"iid": str(iid), "oid": str(org), "reason": reason},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is not None and row.last_run_id:
        try:
            from src.platform.workflows.context_store import append_run_event

            await append_run_event(
                org,
                UUID(str(row.last_run_id)),
                "instance_expired",
                payload={"reason": reason},
                instance_id=iid,
            )
        except Exception as exc:  # noqa: BLE001 — timeline best-effort
            logger.warning("instance expire event failed", error=str(exc)[:200])


# ---------------------------------------------------------------------------
# Operaciones manuales
# ---------------------------------------------------------------------------
async def cancel_instance(organization_id: UUID, instance_id: UUID, *, reason: str = "manual") -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_instances SET status = 'CANCELLED', completed_at = NOW(), "
                    "updated_at = NOW(), status_reason = :reason, waiting_for = '{}'::jsonb, "
                    "waiting_event_type = NULL, waiting_correlation_key = NULL, wait_deadline = NULL "
                    "WHERE id = :iid AND organization_id = :oid "
                    "AND status IN ('NEW', 'RUNNING', 'WAITING', 'SUSPENDED') "
                    "RETURNING last_run_id"
                ),
                {"iid": str(instance_id), "oid": str(organization_id), "reason": reason[:200]},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return {"status": "not_cancellable"}
    if row.last_run_id:
        try:
            from src.platform.workflows.context_store import append_run_event

            await append_run_event(
                organization_id,
                UUID(str(row.last_run_id)),
                "instance_cancelled",
                payload={"reason": reason},
                instance_id=instance_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cancel event failed", error=str(exc)[:200])
    return {"status": "CANCELLED"}


async def suspend_instance(organization_id: UUID, instance_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_instances SET status = 'SUSPENDED', updated_at = NOW(), "
                    "status_reason = 'suspended' "
                    "WHERE id = :iid AND organization_id = :oid AND status = 'WAITING' "
                    "RETURNING id"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"status": "SUSPENDED" if row else "not_suspendable"}


async def resume_suspended_instance(organization_id: UUID, instance_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflow_instances SET status = 'WAITING', updated_at = NOW(), "
                    "status_reason = NULL "
                    "WHERE id = :iid AND organization_id = :oid AND status = 'SUSPENDED' "
                    "RETURNING id"
                ),
                {"iid": str(instance_id), "oid": str(organization_id)},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return {"status": "not_suspended"}
    return {"status": "WAITING"}


async def fail_waiting_instance(
    organization_id: UUID, instance_id: UUID, *, reason: str, error: str | None = None
) -> dict:
    """Cierra la instancia como FAILED desde WAITING (p. ej. aprobación rechazada)."""
    claimed = await _claim_instance(organization_id, instance_id)
    if claimed is None:
        return {"status": "not_waiting"}
    await _finalize_instance(
        org=UUID(str(organization_id)),
        iid=UUID(str(instance_id)),
        run_id=_uid(claimed.get("last_run_id")) or UUID(str(instance_id)),
        instance_seq=int(claimed.get("run_seq") or 0),
        new_status="FAILED",
        reason=reason,
        error=error,
    )
    return {"status": "FAILED"}


# ---------------------------------------------------------------------------
# State de negocio (durable) — nodos state.*
# ---------------------------------------------------------------------------
class InstanceStateError(Exception):
    pass


def _state_get(state: dict[str, Any], path: str) -> Any:
    cur: Any = state
    for part in [p for p in path.split(".") if p]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and 0 <= int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _state_set(state: dict[str, Any], path: str, value: Any) -> None:
    parts = [p for p in path.split(".") if p]
    if not parts:
        raise InstanceStateError("path vacío")
    cur = state
    for part in parts[:-1]:
        nxt = cur.get(part) if isinstance(cur, dict) else None
        if not isinstance(nxt, (dict, list)):
            nxt = {}
            if isinstance(cur, dict):
                cur[part] = nxt
            else:
                raise InstanceStateError(f"path no navegable: {path}")
        cur = nxt
    last = parts[-1]
    if isinstance(cur, dict):
        cur[last] = value
    elif isinstance(cur, list) and last.isdigit():
        idx = int(last)
        while len(cur) <= idx:
            cur.append(None)
        cur[idx] = value
    else:
        raise InstanceStateError(f"path no asignable: {path}")


def _state_remove(state: dict[str, Any], path: str) -> None:
    parts = [p for p in path.split(".") if p]
    if not parts:
        return
    parent = _state_get(state, ".".join(parts[:-1])) if len(parts) > 1 else state
    last = parts[-1]
    if isinstance(parent, dict):
        parent.pop(last, None)
    elif isinstance(parent, list) and last.isdigit():
        idx = int(last)
        if 0 <= idx < len(parent):
            parent.pop(idx)


def apply_state_op(state: dict[str, Any], op: str, path: str, value: Any = None) -> Any:
    """Operaciones deterministas del business state. El LLM propone; el
    workflow aplica. `merge`/`append` requieren value; `remove` borra el path."""
    if op == "get":
        return _state_get(state, path)
    if op == "set":
        _state_set(state, path, value)
        return value
    if op == "merge":
        if not isinstance(value, dict):
            raise InstanceStateError("merge requiere un objeto")
        current = _state_get(state, path)
        if current is None:
            _state_set(state, path, dict(value))
        elif isinstance(current, dict):
            current.update(value)
        else:
            raise InstanceStateError(f"merge sobre no-objeto: {path}")
        return _state_get(state, path)
    if op == "append":
        current = _state_get(state, path)
        if current is None:
            current = []
            _state_set(state, path, current)
        if not isinstance(current, list):
            raise InstanceStateError(f"append sobre no-lista: {path}")
        if isinstance(value, list):
            current.extend(value)
        else:
            current.append(value)
        return current
    if op == "remove":
        current = _state_get(state, path)
        if value is not None and isinstance(current, list):
            for item in (value if isinstance(value, list) else [value]):
                if item in current:
                    current.remove(item)
            return current
        _state_remove(state, path)
        return None
    raise InstanceStateError(f"operación desconocida: {op}")


async def mutate_instance_state(
    organization_id: UUID,
    instance_id: UUID,
    *,
    op: str,
    path: str,
    value: Any = None,
) -> dict[str, Any]:
    """Aplica una operación sobre el state durable con CAS sobre state_version."""
    last_error: Exception | None = None
    for _ in range(4):
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT state, state_version FROM workflow_instances "
                        "WHERE id = :iid AND organization_id = :oid "
                        "AND status IN ('NEW', 'RUNNING', 'WAITING', 'SUSPENDED')"
                    ),
                    {"iid": str(instance_id), "oid": str(organization_id)},
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None:
            raise InstanceStateError("instancia no encontrada o terminada")
        state = dict(row.state or {})
        applied = apply_state_op(state, op, path, value)
        session = await get_async_session()
        try:
            updated = (
                await session.execute(
                    text(
                        "UPDATE workflow_instances SET state = CAST(:state AS jsonb), "
                        "state_version = state_version + 1, updated_at = NOW() "
                        "WHERE id = :iid AND organization_id = :oid AND state_version = :ver "
                        "RETURNING state_version"
                    ),
                    {
                        "state": json.dumps(state, ensure_ascii=False, default=str),
                        "iid": str(instance_id),
                        "oid": str(organization_id),
                        "ver": int(row.state_version or 0),
                    },
                )
            ).fetchone()
            await session.commit()
        finally:
            await session.close()
        if updated is not None:
            return {"state_version": int(updated.state_version), "value": applied, "state": state}
        last_error = InstanceStateError("conflicto de versión de estado")
    raise last_error or InstanceStateError("conflicto de versión de estado")


# ---------------------------------------------------------------------------
# Bus de eventos → señales (lo llama el consumer único de rag:events)
# ---------------------------------------------------------------------------
CORRELATION_HINTS: tuple[str, ...] = (
    "conversation_id",
    "payment_reference",
    "order_id",
    "cart_id",
    "lead_id",
    "customer_id",
    "participant_id",
    "reference",
)


async def signal_instances_from_event(event_type: str, payload: dict[str, Any]) -> dict:
    """Deriva correlaciones estándar del payload y despierta instancias WAITING.

    Un evento con `conversation_id`, `payment_reference`, `order_id`, ... genera
    señales dirigidas; sin claves conocidas se emite una señal sin correlación
    (matchea waits sin correlación declarada)."""
    org_raw = payload.get("organization_id") or payload.get("organizationId")
    if not org_raw:
        return {"status": "skipped", "reason": "no organization_id"}
    try:
        org = UUID(str(org_raw))
    except (ValueError, TypeError):
        return {"status": "skipped", "reason": "invalid organization_id"}
    external = str(
        payload.get("event_id") or payload.get("id") or payload.get("external_event_id") or ""
    ).strip() or None
    body = {
        k: v
        for k, v in payload.items()
        if k not in ("organization_id", "organizationId", "_wf_chain")
    }
    candidates: list[dict[str, str]] = []
    for key in CORRELATION_HINTS:
        value = payload.get(key)
        if value:
            candidates.append({key: str(value)})
    if not candidates:
        candidates = [{}]
    statuses: list[str] = []
    for correlation in candidates[:3]:
        key_suffix = "+".join(correlation.keys()) or "any"
        try:
            out = await signal_workflow_instance(
                organization_id=org,
                event_type=str(event_type),
                correlation=correlation,
                payload=body,
                idempotency_key=(f"evt:{external}:{key_suffix}" if external else None),
                source="event_bus",
            )
            statuses.append(str(out.get("status")))
        except Exception as exc:  # noqa: BLE001 — un candidato fallido no rompe el bus
            logger.warning("event signal candidate failed", key=key_suffix, error=str(exc)[:200])
    return {"status": "ok", "candidates": statuses}


# ---------------------------------------------------------------------------
# Sweep (lo llama el scheduler único: engine.workflow_v2_scheduler_loop)
# ---------------------------------------------------------------------------
async def sweep_waiting_instances(*, limit: int = 50) -> dict:
    """Timeouts de waits, expiración global, reaper y retención. Cero
    procesos en memoria; lo llama el scheduler único."""
    await ensure_instance_tables()
    stats = {
        "waits_timed_out": 0,
        "instances_expired": 0,
        "instances_reaped": 0,
        "signals_pruned": 0,
        "instances_pruned": 0,
    }
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, organization_id, wait_seq FROM workflow_instances "
                    "WHERE status = 'WAITING' AND wait_deadline IS NOT NULL "
                    "AND wait_deadline <= NOW() LIMIT :lim"
                ),
                {"lim": int(limit)},
            )
        ).fetchall()
    finally:
        await session.close()
    for r in rows:
        try:
            out = await signal_workflow_instance(
                organization_id=UUID(str(r.organization_id)),
                event_type=_TIMEOUT_EVENT,
                correlation={"instance_id": str(r.id)},
                payload={"expired": True},
                idempotency_key=f"timeout:{r.id}:{r.wait_seq}",
                source="scheduler",
                instance_id=UUID(str(r.id)),
            )
            if out.get("resumed"):
                stats["waits_timed_out"] += 1
        except Exception as exc:  # noqa: BLE001 — el sweep nunca rompe el loop
            logger.warning("wait timeout sweep failed", instance_id=str(r.id), error=str(exc)[:200])

    session = await get_async_session()
    try:
        expired = (
            await session.execute(
                text(
                    "UPDATE workflow_instances SET status = 'EXPIRED', completed_at = NOW(), "
                    "updated_at = NOW(), status_reason = 'expires_at' "
                    "WHERE id IN ("
                    "  SELECT id FROM workflow_instances WHERE expires_at IS NOT NULL "
                    "  AND expires_at <= NOW() AND status IN ('NEW', 'WAITING', 'SUSPENDED') "
                    "  LIMIT :lim"
                    ") RETURNING id, organization_id, last_run_id"
                ),
                {"lim": int(limit)},
            )
        ).fetchall()
        await session.commit()
    finally:
        await session.close()
    for r in expired:
        stats["instances_expired"] += 1
        if r.last_run_id:
            try:
                from src.platform.workflows.context_store import append_run_event

                await append_run_event(
                    UUID(str(r.organization_id)),
                    UUID(str(r.last_run_id)),
                    "instance_expired",
                    payload={"reason": "expires_at"},
                    instance_id=UUID(str(r.id)),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("expire event failed", error=str(exc)[:200])

    # Reaper: instancias RUNNING sin cierre (proceso muerto a mitad de segmento).
    session = await get_async_session()
    try:
        reaped = (
            await session.execute(
                text(
                    "UPDATE workflow_instances SET status = 'FAILED', completed_at = NOW(), "
                    "updated_at = NOW(), status_reason = 'stale_segment', "
                    "error = 'segmento interrumpido (proceso no disponible)' "
                    "WHERE id IN ("
                    "  SELECT id FROM workflow_instances WHERE status = 'RUNNING' "
                    "  AND updated_at < NOW() - make_interval(mins => :cutoff) LIMIT :lim"
                    ") RETURNING id, organization_id, last_run_id"
                ),
                {"cutoff": int(_REAP_MINUTES), "lim": int(limit)},
            )
        ).fetchall()
        await session.commit()
    finally:
        await session.close()
    for r in reaped:
        stats["instances_reaped"] += 1
        try:
            from src.platform.workflows.context_store import append_run_event

            if r.last_run_id:
                await append_run_event(
                    UUID(str(r.organization_id)),
                    UUID(str(r.last_run_id)),
                    "instance_failed",
                    payload={"reason": "stale_segment"},
                    instance_id=UUID(str(r.id)),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reaper event failed", error=str(exc)[:200])

    # Retención por lotes (fail-soft): señales cerradas e instancias terminales.
    session = await get_async_session()
    try:
        pruned_signals = await session.execute(
            text(
                "DELETE FROM workflow_signals WHERE id IN ("
                "  SELECT id FROM workflow_signals "
                "  WHERE status IN ('consumed', 'discarded') "
                "  AND received_at < NOW() - make_interval(days => :days) LIMIT :lim"
                ")"
            ),
            {"days": int(_SIGNAL_RETENTION_DAYS), "lim": int(limit) * 10},
        )
        pruned_instances = await session.execute(
            text(
                "DELETE FROM workflow_instances WHERE id IN ("
                "  SELECT id FROM workflow_instances "
                "  WHERE status IN ('COMPLETED', 'FAILED', 'CANCELLED', 'EXPIRED') "
                "  AND completed_at IS NOT NULL "
                "  AND completed_at < NOW() - make_interval(days => :days) LIMIT :lim"
                ")"
            ),
            {"days": int(_INSTANCE_RETENTION_DAYS), "lim": int(limit) * 4},
        )
        await session.commit()
        stats["signals_pruned"] = int(pruned_signals.rowcount or 0)
        stats["instances_pruned"] = int(pruned_instances.rowcount or 0)
    except Exception as exc:  # noqa: BLE001 — la retención nunca rompe el sweep
        logger.warning("retention prune failed", error=str(exc)[:200])
    finally:
        await session.close()
    return stats
