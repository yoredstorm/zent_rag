# =============================================================================
# AI Workflow Automation Studio v2 — motor de ejecución multi-paso con
# disparadores, retries y trazabilidad de runs.
#
# Phase 32A: ejecución unificada sobre Workflow Graph IR (legacy steps[]
# migrados vía LegacyWorkflowAdapter), ExecutionContext explícito
# (organization/workspace/actor/correlation), RBAC por capability,
# schedules v2 (daily/weekly/monthly/cron), dry-run y aprobaciones.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

__all__ = ["httpx", "STEP_TYPES", "TRIGGER_TYPES"]

STEP_TYPES = ("llm", "kb_query", "api_call", "condition", "notify")
TRIGGER_TYPES = ("webhook", "schedule", "event")


class WorkflowAccessError(PermissionError):
    """Denegación de acceso cross-tenant / cross-workspace al ejecutar."""


def _hash_hook_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_json_path(data, path: str):
    if not path or data is None:
        return None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        else:
            return None
    return cur


def _eval_condition(actual, operator: str, value) -> bool:
    actual_s = str(actual if actual is not None else "")
    value_s = str(value)
    if operator == "==":
        return actual_s == value_s
    if operator == "!=":
        return actual_s != value_s
    if operator == "contains":
        return value_s in actual_s
    try:
        left = float(actual_s)
        right = float(value_s)
    except (TypeError, ValueError):
        return False
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    return False


def _clean_steps(steps: list | None) -> list:
    cleaned: list = []
    for step in steps or []:
        if not isinstance(step, dict) or step.get("type") not in STEP_TYPES:
            raise ValueError(f"tipo de paso inválido: {step.get('type') if isinstance(step, dict) else step}")
        item = dict(step)
        if item.get("then") is not None:
            item["then"] = _clean_steps(item.get("then") or [])
        if item.get("else") is not None:
            item["else"] = _clean_steps(item.get("else") or [])
        cleaned.append(item)
    return cleaned


async def _org_config(organization_id: UUID) -> dict:
    """config_json de la org (helper legacy preservado para monkeypatchs)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT config_json FROM organizations WHERE id = :oid"),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    raw = row.config_json if row else {}
    return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# Ejecución segura (Phase 32A)
# ---------------------------------------------------------------------------
async def _load_workflow_row(workflow_id: UUID) -> tuple | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, name, steps, graph, "
                    "workflow_version, graph_source, trigger_type, trigger_config, status "
                    "FROM workflows WHERE id = :wid"
                ),
                {"wid": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return row


async def _audit_run_access(
    *, organization_id: UUID, workflow_id: UUID, action: str, run_id: UUID | None = None, error: str | None = None
) -> None:
    """Auditoría fail-soft de ejecuciones y denegaciones."""
    try:
        from src.core.domain.entities import TenantContext
        from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
        from src.platform.audit.service import AuditLogService

        ctx = TenantContext(
            tenant_id=organization_id,
            user_id=None,
            roles=frozenset(),
            permissions=frozenset(),
            scopes=frozenset(),
            auth_type="workflow_runtime",
        )
        metadata: dict = {"workflow_id": str(workflow_id)}
        if run_id:
            metadata["run_id"] = str(run_id)
        if error:
            metadata["error"] = error
        await AuditLogService(PostgresAuditLogRepository()).write(
            ctx, action, "workflow", workflow_id, metadata=metadata
        )
    except Exception:  # noqa: BLE001
        pass


async def run_workflow(
    workflow_id: UUID,
    payload: dict | None = None,
    trigger: str = "manual",
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    actor_type: str = "system",
    actor_id: UUID | None = None,
    permissions: frozenset[str] | None = None,
    correlation_id: str | None = None,
    simulate: bool = False,
    resume: bool = False,
    run_id: UUID | None = None,
) -> dict:
    """Ejecuta el workflow bajo un ExecutionContext explícito.

    P0: `organization_id`/`workspace_id` explícitos deben coincidir con la
    fila; nunca se confía a ciegas en el UUID del workflow. Legacy: si no se
    pasan, se derivan de la fila (llamadas internas/scheduler/hook).

    `resume=True` reanuda un run existente (aprobación humana) reutilizando
    los pasos persistidos: requiere `run_id` y NO crea un run nuevo."""
    trig = trigger if trigger in ("manual", "schedule", "webhook", "event", "approval") else "manual"
    wf = await _load_workflow_row(workflow_id)
    if wf is None:
        return None
    row_org = wf.organization_id
    row_ws = wf.workspace_id

    if organization_id is not None and UUID(str(organization_id)) != UUID(str(row_org)):
        await _audit_run_access(
            organization_id=UUID(str(organization_id)),
            workflow_id=workflow_id,
            action="workflow.run.cross_tenant_denied",
            error="organization_id no coincide con el workflow",
        )
        raise WorkflowAccessError("workflow no pertenece a la organización")
    if workspace_id is not None and row_ws is not None and UUID(str(workspace_id)) != UUID(str(row_ws)):
        await _audit_run_access(
            organization_id=UUID(str(row_org)),
            workflow_id=workflow_id,
            action="workflow.run.cross_workspace_denied",
            error="workspace_id no coincide con el workflow",
        )
        raise WorkflowAccessError("workflow no pertenece al workspace")

    if wf.status == "paused" and not resume:
        return {"status": "paused", "message": "workflow pausado"}

    eff_org = UUID(str(row_org))
    eff_ws = UUID(str(row_ws)) if row_ws else (workspace_id or None)
    corr = (correlation_id or "").strip() or f"wf:{workflow_id}"

    if resume:
        if run_id is None:
            return {
                "status": "failed",
                "error": "resume requiere run_id",
            }
        # El run ya existe (pending_approval); se reutiliza.
    else:
        run_id = UUID(secrets.token_hex(16))
        corr = corr or f"wf:{workflow_id}:{run_id}"
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO workflow_runs "
                    "(id, workflow_id, organization_id, workspace_id, trigger, "
                    "trigger_payload, correlation_id, actor_type, actor_id, simulate) "
                    "VALUES (:rid, :wid, :oid, :ws, :trig, CAST(:payload AS jsonb), "
                    ":corr, :atype, :aid, :sim)"
                ),
                {
                    "rid": run_id,
                    "wid": workflow_id,
                    "oid": eff_org,
                    "ws": eff_ws,
                    "trig": trig,
                    "payload": json.dumps(payload or {}),
                    "corr": corr[:128],
                    "atype": actor_type[:20],
                    "aid": actor_id,
                    "sim": bool(simulate),
                },
            )
            await session.commit()
        finally:
            await session.close()

    # IR: graph nativo (v2) o adaptación del legacy steps[] (v1).
    from src.platform.workflows.ir import LegacyWorkflowAdapter, WorkflowGraph
    from src.platform.workflows.runtime import ExecutionContext, execute_graph

    if wf.graph:
        try:
            graph = WorkflowGraph.from_dict(dict(wf.graph))
        except Exception as exc:  # noqa: BLE001
            return {
                "run_id": str(run_id),
                "workflow_id": str(workflow_id),
                "status": "failed",
                "error": f"grafo inválido: {str(exc)[:200]}",
            }
    else:
        graph = LegacyWorkflowAdapter.steps_to_graph(
            wf.steps or [], wf.trigger_type, wf.trigger_config
        )

    _SYSTEM_NODE_PERMS = frozenset(
        {
            "workflows:run",
            "agents:execute",
            "external_actions:execute",
            "integrations:use",
            "workflow_secrets:manage",
        }
    )
    perms = frozenset(permissions or _SYSTEM_NODE_PERMS)
    exec_ctx = ExecutionContext(
        organization_id=eff_org,
        workspace_id=eff_ws,
        workflow_id=workflow_id,
        run_id=run_id,
        actor_type=actor_type,
        actor_id=actor_id,
        trigger_type=trig,
        permissions=perms,
        correlation_id=corr,
        simulate=bool(simulate),
    )

    started = datetime.now(timezone.utc)
    result = await execute_graph(graph, exec_ctx, payload or {}, resume=resume)

    duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    if simulate and result.status == "succeeded":
        final_status = "simulated"
    elif simulate:
        final_status = result.status
    else:
        final_status = result.status

    summaries = [
        (e.output or {}).get("text") or (e.output or {}).get("answer")
        for e in result.node_executions.values()
        if (e.output or {}).get("text") or (e.output or {}).get("answer")
    ]
    notifications = [
        {"node_id": nid, "channel": (e.output or {}).get("channel")}
        for nid, e in result.node_executions.items()
        if (e.output or {}).get("sent") is True
    ]

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_runs SET status = :status, completed_at = NOW(), "
                "duration_ms = :dur, error = :err WHERE id = :rid"
            ),
            {"status": final_status[:20], "dur": duration, "err": result.error, "rid": run_id},
        )
        await session.commit()
    finally:
        await session.close()

    await _audit_run_access(
        organization_id=eff_org,
        workflow_id=workflow_id,
        action="workflow.run" if result.status != "failed" else "workflow.run.failed",
        run_id=run_id,
        error=result.error,
    )

    body: dict = {
        "run_id": str(run_id),
        "workflow_id": str(workflow_id),
        "status": final_status,
        "duration_ms": duration,
        "error": result.error,
        "nodes": len(result.node_executions),
        "correlation_id": corr,
        "cost_ms": round(result.cost_ms, 4),
        "simulate": bool(simulate),
    }
    body["result"] = {
        "summary": summaries[:5],
        "structured_output": {
            "nodes": {
                nid: {"status": e.status, "output": e.output.get("output", e.output)}
                for nid, e in result.node_executions.items()
            }
        },
        "evidence": [],
        "notifications": notifications,
        "errors": [
            {"node_id": nid, "error": e.error}
            for nid, e in result.node_executions.items()
            if e.error
        ],
        "cost_ms": round(result.cost_ms, 4),
        "duration_ms": duration,
    }
    if result.planned_effects:
        body["planned_effects"] = result.planned_effects
    return body


# ---------------------------------------------------------------------------
# CRUD workflows
# ---------------------------------------------------------------------------
async def list_workflows(organization_id: UUID, workspace_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT w.id, w.name, w.description, w.trigger_type, w.status, "
            "w.workspace_id, w.workflow_version, w.graph_source, "
            "w.created_at, w.updated_at, "
            "COUNT(r.id) AS runs, "
            "COUNT(r.id) FILTER (WHERE r.status = 'succeeded') AS ok_runs "
            "FROM workflows w LEFT JOIN workflow_runs r ON r.workflow_id = w.id "
            "WHERE w.organization_id = :oid"
        )
        params: dict = {"oid": organization_id}
        if workspace_id is not None:
            sql += " AND (w.workspace_id = :ws OR w.workspace_id IS NULL)"
            params["ws"] = workspace_id
        rows = (
            await session.execute(
                text(sql + " GROUP BY w.id ORDER BY w.created_at DESC"), params
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "workflows": [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "trigger_type": r.trigger_type,
                "status": r.status,
                "workspace_id": str(r.workspace_id) if r.workspace_id else None,
                "workflow_version": int(r.workflow_version or 1),
                "graph_source": r.graph_source,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
                "runs": int(r.runs),
                "ok_runs": int(r.ok_runs),
            }
            for r in rows
        ]
    }


async def create_workflow(
    organization_id: UUID,
    name: str,
    trigger_type: str = "webhook",
    trigger_config: dict | None = None,
    steps: list | None = None,
    description: str | None = None,
    created_by: UUID | None = None,
    editor_state: dict | None = None,
    *,
    workspace_id: UUID | None = None,
    graph: dict | None = None,
    workflow_version: int = 2,
) -> dict:
    if trigger_type not in TRIGGER_TYPES:
        raise ValueError(f"trigger_type debe ser uno de {TRIGGER_TYPES}")
    cleaned = _clean_steps(steps)
    tcfg = dict(trigger_config or {})
    if trigger_type == "schedule":
        tcfg = _normalize_schedule_config(tcfg)
    plain_secret = None
    if trigger_type == "webhook" and not tcfg.get("hook_secret_hash"):
        plain_secret = secrets.token_urlsafe(24)
        tcfg["hook_secret_hash"] = _hash_hook_secret(plain_secret)

    # Grafo nativo o adaptación legacy → siempre persistimos graph.
    from src.platform.workflows.ir import (
        LegacyWorkflowAdapter,
        WorkflowGraph,
        validate_graph,
    )

    if graph:
        parsed = WorkflowGraph.from_dict(dict(graph))
        validate_graph(parsed)
        graph_json = parsed.to_dict()
        graph_json["workflow_version"] = max(2, int(workflow_version or 2))
        graph_source = "graph"
        stored_version = graph_json["workflow_version"]
    else:
        adapted = LegacyWorkflowAdapter.steps_to_graph(cleaned, trigger_type, tcfg)
        graph_json = adapted.to_dict()
        graph_source = "legacy"
        stored_version = 1

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflows (id, organization_id, workspace_id, name, "
                    "description, trigger_type, trigger_config, steps, created_by, "
                    "editor_state, graph, workflow_version, graph_source) "
                    "VALUES (gen_random_uuid(), :oid, :ws, :name, :desc, :ttype, "
                    "CAST(:tcfg AS jsonb), CAST(:steps AS jsonb), :by, CAST(:estate AS jsonb), "
                    "CAST(:graph AS jsonb), :gver, :gsrc) "
                    "RETURNING id, name"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "name": name[:150],
                    "desc": description,
                    "ttype": trigger_type,
                    "tcfg": json.dumps(tcfg),
                    "steps": json.dumps(cleaned),
                    "by": created_by,
                    "estate": json.dumps(editor_state or {}),
                    "graph": json.dumps(graph_json),
                    "gver": int(stored_version),
                    "gsrc": graph_source,
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    out = {"workflow_id": str(row.id), "name": row.name, "workflow_version": int(stored_version)}
    if plain_secret:
        out["hook_secret"] = plain_secret
    return out


def _normalize_schedule_config(tcfg: dict) -> dict:
    """Schedules v2: every_minutes (legacy) o daily/weekly/monthly/cron."""
    every = 0
    try:
        every = int(tcfg.get("every_minutes") or 0)
    except (TypeError, ValueError):
        every = 0
    if every >= 1:
        tcfg["every_minutes"] = min(max(every, 1), 1440)
    elif any(k in tcfg for k in ("daily", "weekly", "monthly", "cron")):
        pass  # schedules v2; la validación de forma la hace next_trigger_at
    else:
        tcfg["every_minutes"] = 5
    return tcfg


def _public_trigger_config(raw) -> dict:
    cfg = dict(raw or {}) if isinstance(raw, dict) else {}
    cfg.pop("hook_secret_hash", None)
    return cfg


async def get_workflow(organization_id: UUID, workflow_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, description, trigger_type, trigger_config, steps, "
                    "status, created_at, updated_at, editor_state, graph, "
                    "workspace_id, workflow_version, graph_source FROM workflows "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    tcfg = row.trigger_config if isinstance(row.trigger_config, dict) else {}
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "trigger_type": row.trigger_type,
        "trigger_config": _public_trigger_config(tcfg),
        "steps": row.steps,
        "graph": row.graph,
        "workflow_version": int(row.workflow_version or 1),
        "graph_source": row.graph_source,
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "status": row.status,
        "editor_state": row.editor_state or {},
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "hook_url": f"/api/v1/public/workflows/{row.id}/hook",
        "has_hook_secret": bool(tcfg.get("hook_secret_hash")),
    }


async def update_workflow(
    organization_id: UUID,
    workflow_id: UUID,
    name: str | None = None,
    description: str | None = None,
    trigger_config: dict | None = None,
    steps: list | None = None,
    editor_state: dict | None = None,
    *,
    graph: dict | None = None,
    workflow_version: int | None = None,
) -> dict | None:
    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                text("SELECT id FROM workflows WHERE id = :wid AND organization_id = :oid"),
                {"wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        if exists is None:
            await session.commit()
            return None
        sets = ["updated_at = NOW()"]
        params: dict = {"wid": workflow_id}
        if name is not None:
            sets.append("name = :name")
            params["name"] = name[:150]
        if description is not None:
            sets.append("description = :desc")
            params["desc"] = description
        if trigger_config is not None:
            existing_cfg = (
                await session.execute(
                    text("SELECT trigger_config FROM workflows WHERE id = :wid"),
                    {"wid": workflow_id},
                )
            ).fetchone()
            merged = dict(existing_cfg.trigger_config or {}) if existing_cfg else {}
            incoming = dict(trigger_config)
            incoming.pop("hook_secret_hash", None)
            merged.update(incoming)
            if merged.get("trigger_type") == "schedule" or "every_minutes" in merged or any(
                k in merged for k in ("daily", "weekly", "monthly", "cron")
            ):
                merged = _normalize_schedule_config(merged)
            sets.append("trigger_config = CAST(:tcfg AS jsonb)")
            params["tcfg"] = json.dumps(merged)
        if steps is not None:
            cleaned = _clean_steps(steps)
            sets.append("steps = CAST(:steps AS jsonb)")
            params["steps"] = json.dumps(cleaned)
        if editor_state is not None:
            sets.append("editor_state = CAST(:estate AS jsonb)")
            params["estate"] = json.dumps(editor_state)
        if graph is not None:
            from src.platform.workflows.ir import WorkflowGraph, validate_graph

            parsed = WorkflowGraph.from_dict(dict(graph))
            validate_graph(parsed)
            sets.append("graph = CAST(:graph AS jsonb)")
            sets.append("graph_source = 'graph'")
            sets.append("workflow_version = :gver")
            params["graph"] = json.dumps(parsed.to_dict())
            params["gver"] = max(2, int(workflow_version or 2))
        elif steps is not None and graph is None:
            # Re-adaptar el grafo legacy (fuente de verdad: steps).
            from src.platform.workflows.ir import LegacyWorkflowAdapter

            ttype_row = (
                await session.execute(
                    text("SELECT trigger_type, trigger_config FROM workflows WHERE id = :wid"),
                    {"wid": workflow_id},
                )
            ).fetchone()
            adapted = LegacyWorkflowAdapter.steps_to_graph(
                cleaned, ttype_row.trigger_type, ttype_row.trigger_config
            )
            sets.append("graph = CAST(:graph AS jsonb)")
            sets.append("graph_source = 'legacy'")
            sets.append("workflow_version = 1")
            params["graph"] = json.dumps(adapted.to_dict())
        await session.execute(
            text(f"UPDATE workflows SET {', '.join(sets)} WHERE id = :wid"),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return {"updated": True}


async def delete_workflow(organization_id: UUID, workflow_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text("DELETE FROM workflows WHERE id = :wid AND organization_id = :oid"),
            {"wid": workflow_id, "oid": organization_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def set_workflow_status(organization_id: UUID, workflow_id: UUID, status: str) -> dict | None:
    if status not in ("active", "paused"):
        raise ValueError("status debe ser active|paused")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "UPDATE workflows SET status = :status, updated_at = NOW() "
                    "WHERE id = :wid AND organization_id = :oid RETURNING status"
                ),
                {"status": status, "wid": workflow_id, "oid": organization_id},
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    if row is None:
        return None
    return {"workflow_id": str(workflow_id), "status": row.status}


# ---------------------------------------------------------------------------
# Plantillas
# ---------------------------------------------------------------------------
async def list_templates() -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT slug, name, description, category, trigger_type, steps "
                    "FROM workflow_templates ORDER BY category, name"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "templates": [
            {
                "slug": r.slug,
                "name": r.name,
                "description": r.description,
                "category": r.category,
                "trigger_type": r.trigger_type,
                "steps": r.steps,
            }
            for r in rows
        ]
    }


async def create_from_template(
    organization_id: UUID,
    slug: str,
    name: str | None = None,
    *,
    workspace_id: UUID | None = None,
) -> dict:
    session = await get_async_session()
    try:
        tpl = (
            await session.execute(
                text(
                    "SELECT name, description, trigger_type, steps, trigger_config "
                    "FROM workflow_templates WHERE slug = :slug"
                ),
                {"slug": slug},
            )
        ).fetchone()
    finally:
        await session.close()
    if tpl is None:
        raise ValueError("plantilla no encontrada")
    tcfg = tpl.trigger_config if isinstance(getattr(tpl, "trigger_config", None), dict) else {}
    return await create_workflow(
        organization_id,
        name or tpl.name,
        tpl.trigger_type,
        tcfg,
        tpl.steps,
        tpl.description,
        workspace_id=workspace_id,
    )


# ---------------------------------------------------------------------------
# Runs y trazabilidad
# ---------------------------------------------------------------------------
async def list_runs(organization_id: UUID, workflow_id: UUID, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT r.id, r.workflow_id, r.status, r.started_at, r.completed_at, "
                    "r.duration_ms, r.error, r.simulate, r.correlation_id, w.name AS workflow_name "
                    "FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id "
                    "WHERE r.workflow_id = :wid AND w.organization_id = :oid "
                    "ORDER BY r.started_at DESC LIMIT :lim"
                ),
                {"wid": workflow_id, "oid": organization_id, "lim": min(int(limit), 200)},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "runs": [
            {
                "id": str(r.id),
                "workflow_id": str(r.workflow_id),
                "workflow_name": r.workflow_name,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "duration_ms": int(r.duration_ms) if r.duration_ms is not None else None,
                "error": r.error,
                "simulate": bool(r.simulate),
                "correlation_id": r.correlation_id,
            }
            for r in rows
        ]
    }


async def run_detail(organization_id: UUID, run_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        run = (
            await session.execute(
                text(
                    "SELECT r.id, r.workflow_id, r.status, r.started_at, r.completed_at, "
                    "r.duration_ms, r.error, r.trigger_payload, r.simulate, r.correlation_id, "
                    "r.workspace_id, w.name AS workflow_name, w.organization_id "
                    "FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id "
                    "WHERE r.id = :rid"
                ),
                {"rid": run_id},
            )
        ).fetchone()
        if run is None or str(run.organization_id) != str(organization_id):
            return None
        steps = (
            await session.execute(
                text(
                    "SELECT step_index, step_type, node_id, node_type, status, input, "
                    "output, error, retries, attempt, idempotency_key, duration_ms "
                    "FROM workflow_run_steps WHERE run_id = :rid ORDER BY step_index"
                ),
                {"rid": run_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(run.id),
        "workflow_id": str(run.workflow_id),
        "workflow_name": run.workflow_name,
        "status": run.status,
        "started_at": run.started_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "duration_ms": int(run.duration_ms) if run.duration_ms is not None else None,
        "error": run.error,
        "trigger_payload": run.trigger_payload,
        "simulate": bool(run.simulate),
        "correlation_id": run.correlation_id,
        "workspace_id": str(run.workspace_id) if run.workspace_id else None,
        "steps": [
            {
                "step_index": int(s.step_index),
                "step_type": s.step_type,
                "node_id": s.node_id,
                "node_type": s.node_type,
                "status": s.status,
                "input": s.input,
                "output": s.output,
                "error": s.error,
                "retries": int(s.retries),
                "attempt": int(s.attempt),
                "idempotency_key": s.idempotency_key,
                "duration_ms": int(s.duration_ms) if s.duration_ms is not None else None,
            }
            for s in steps
        ],
    }


# ---------------------------------------------------------------------------
# Schedules v2
# ---------------------------------------------------------------------------
def _zone(tz_name: str):
    """Zona horaria con fallback UTC (Windows sin tzdata)."""
    try:
        import zoneinfo

        return zoneinfo.ZoneInfo(str(tz_name) or "UTC")
    except Exception:  # noqa: BLE001
        return timezone.utc


def next_trigger_at(trigger_config: dict, since: datetime) -> datetime | None:
    """Próxima ocurrencia de un schedule v2 después de `since`.

    Soporta every_minutes (legacy), daily {time, timezone}, weekly {days,
    time, timezone}, monthly {day, time, timezone} y cron {expr, timezone}
    (5 campos). Devuelve None si no hay próxima ocurrencia.
    """
    tz = _zone(str(trigger_config.get("timezone") or "UTC"))
    since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    local = since_utc.astimezone(tz)

    if trigger_config.get("every_minutes"):
        every = max(1, min(int(trigger_config["every_minutes"]), 1440))
        return local + timedelta(minutes=every)

    daily = trigger_config.get("daily")
    if isinstance(daily, dict) and daily.get("time"):
        t = str(daily["time"])
        hh, mm = _parse_hhmm(t)
        if hh is None:
            return None
        nxt = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if nxt <= local:
            nxt += timedelta(days=1)
        return nxt

    weekly = trigger_config.get("weekly")
    if isinstance(weekly, dict):
        days = weekly.get("days") or []
        t = str(weekly.get("time") or "09:00")
        hh, mm = _parse_hhmm(t)
        if hh is None:
            return None
        wanted = {int(d) for d in days if str(d).isdigit()}  # 0=Lun … 6=Dom
        if not wanted:
            return None
        for offset in range(8):
            candidate = local + timedelta(days=offset)
            if candidate.weekday() in wanted:
                nxt = candidate.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if nxt > local:
                    return nxt
        return None

    monthly = trigger_config.get("monthly")
    if isinstance(monthly, dict):
        day = int(monthly.get("day") or 0)
        t = str(monthly.get("time") or "09:00")
        hh, mm = _parse_hhmm(t)
        if hh is None or day < 1 or day > 31:
            return None
        for offset in range(370):
            candidate = local + timedelta(days=offset)
            if candidate.day == day:
                nxt = candidate.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if nxt > local:
                    return nxt
        return None

    cron = trigger_config.get("cron")
    if isinstance(cron, dict) and cron.get("expr"):
        return _next_cron(str(cron["expr"]), local)

    return None


def _parse_hhmm(t: str) -> tuple[int | None, int | None]:
    parts = str(t).split(":")
    if len(parts) != 2:
        return None, None
    try:
        hh, mm = int(parts[0]), int(parts[1])
    except ValueError:
        return None, None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None, None
    return hh, mm


def _cron_field_matches(pattern: str, value: int, min_v: int, max_v: int) -> bool:
    pat = str(pattern).strip()
    if pat in ("*", "?"):
        return True
    if "/" in pat:
        base, step = pat.split("/", 1)
        try:
            step_n = int(step)
        except ValueError:
            return False
        start = 0 if base in ("*", "?") else int(base)
        return value >= start and (value - start) % step_n == 0 and value <= max_v
    for part in pat.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            try:
                if min_v <= value <= max_v and int(lo) <= value <= int(hi):
                    return True
            except ValueError:
                pass
        elif part.lstrip("-").isdigit():
            lo = int(part)
            if min_v <= lo <= max_v and lo == value:
                return True
    return False


def _cron_matches(expr: str, dt: datetime) -> bool:
    fields = str(expr).split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    if not _cron_field_matches(minute, dt.minute, 0, 59):
        return False
    if not _cron_field_matches(hour, dt.hour, 0, 23):
        return False
    if not _cron_field_matches(dom, dt.day, 1, 31):
        return False
    if not _cron_field_matches(month, dt.month, 1, 12):
        return False
    if not _cron_field_matches(dow, dt.weekday() + 1, 1, 7):  # 1=Lu … 7=Dom
        return False
    return True


def _next_cron(expr: str, since_local: datetime) -> datetime | None:
    """Barre hacia adelante (máx. 14 días) buscando la próxima coincidencia."""
    cursor = since_local.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(14 * 24 * 60):
        if _cron_matches(expr, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    return None


async def run_due_scheduled_workflows(
    now: datetime | None = None,
    organization_id: UUID | None = None,
) -> int:
    """Dispara workflows schedule activos cuya próxima ocurrencia ya venció."""
    now = now or datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, organization_id, workspace_id, trigger_config, last_run_at "
            "FROM workflows WHERE status = 'active' AND trigger_type = 'schedule'"
        )
        params: dict = {}
        if organization_id is not None:
            sql += " AND organization_id = :oid"
            params["oid"] = organization_id
        rows = (await session.execute(text(sql), params)).fetchall()
    finally:
        await session.close()
    fired = 0
    for row in rows:
        cfg = row.trigger_config if isinstance(row.trigger_config, dict) else {}
        last = row.last_run_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        if cfg.get("every_minutes"):
            try:
                every = int(cfg.get("every_minutes") or 0)
            except (TypeError, ValueError):
                continue
            if every < 1:
                continue
            if last is not None and now - last < timedelta(minutes=every):
                continue
            due = True
        else:
            nxt = next_trigger_at(cfg, last or (now - timedelta(seconds=1)))
            due = nxt is not None and nxt <= now
        if not due:
            continue

        try:
            await run_workflow(
                row.id,
                {"scheduled_at": now.isoformat(), "next_trigger_at": _iso(next_trigger_at(cfg, now))},
                trigger="schedule",
                organization_id=row.organization_id,
                workspace_id=row.workspace_id,
                actor_type="scheduler",
                correlation_id=f"sched:{row.id}:{int(now.timestamp())}",
            )
        except WorkflowAccessError:
            continue
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE workflows SET last_run_at = :ts WHERE id = :wid"),
                {"ts": now, "wid": row.id},
            )
            await session.commit()
        finally:
            await session.close()
        fired += 1
    return fired


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def workflow_v2_scheduler_loop() -> None:
    """Cada 60s: ejecuta schedules v2 vencidos."""
    while True:
        try:
            await run_due_scheduled_workflows()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Workflow v2 scheduler iteration failed", error=str(exc)[:200])
        await asyncio.sleep(60)


async def run_workflow_from_hook(workflow_id: UUID, secret: str, payload: dict | None) -> dict:
    """Inbound público: compara secret y dispara el workflow (ExecutionContext
    derivado de la fila — el hook es la única vía que solo lleva UUID + secret)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, workspace_id, status, trigger_type, "
                    "trigger_config FROM workflows WHERE id = :wid"
                ),
                {"wid": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return {"error": "not_found", "status_code": 404}
    if row.status == "paused":
        return {"status": "paused", "message": "workflow pausado"}
    if row.status != "active":
        return {"error": "inactive", "status_code": 409}
    tcfg = row.trigger_config if isinstance(row.trigger_config, dict) else {}
    expected = str(tcfg.get("hook_secret_hash") or "")
    got = _hash_hook_secret(secret or "")
    if not expected or not hmac.compare_digest(expected, got):
        return {"error": "unauthorized", "status_code": 401}
    return await run_workflow(
        workflow_id,
        payload or {},
        trigger="webhook",
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        actor_type="webhook",
        correlation_id=f"hook:{workflow_id}",
    )


# ---------------------------------------------------------------------------
# Aprobaciones humanas (Phase 32A)
# ---------------------------------------------------------------------------
async def list_approvals(organization_id: UUID, run_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, run_id, workflow_id, workspace_id, node_id, action, summary, "
            "status, requested_by, decided_by, decision_comment, requested_at, "
            "decided_at, expires_at FROM workflow_approvals WHERE organization_id = :oid"
        )
        params: dict = {"oid": organization_id}
        if run_id is not None:
            sql += " AND run_id = :rid"
            params["rid"] = run_id
        rows = (await session.execute(text(sql + " ORDER BY requested_at DESC"), params)).fetchall()
    finally:
        await session.close()
    return {
        "approvals": [
            {
                "id": str(r.id),
                "run_id": str(r.run_id),
                "workflow_id": str(r.workflow_id),
                "workspace_id": str(r.workspace_id) if r.workspace_id else None,
                "node_id": r.node_id,
                "action": r.action,
                "summary": r.summary,
                "status": r.status,
                "requested_at": r.requested_at.isoformat(),
                "decided_at": r.decided_at.isoformat() if r.decided_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in rows
        ]
    }


async def decide_approval(
    organization_id: UUID,
    approval_id: UUID,
    decision: str,
    decided_by: UUID | None = None,
    comment: str | None = None,
) -> dict | None:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision debe ser approved|rejected")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, run_id, workflow_id, status FROM workflow_approvals "
                    "WHERE id = :aid AND organization_id = :oid"
                ),
                {"aid": approval_id, "oid": organization_id},
            )
        ).fetchone()
        if row is None:
            await session.commit()
            return None
        if row.status != "pending":
            await session.commit()
            return {"approval_id": str(approval_id), "status": row.status, "already": True}
        await session.execute(
            text(
                "UPDATE workflow_approvals SET status = :dec, decided_by = :by, "
                "decision_comment = :cm, decided_at = NOW() WHERE id = :aid"
            ),
            {"dec": decision, "by": decided_by, "cm": comment, "aid": approval_id},
        )
        await session.commit()
        run_id, workflow_id = row.run_id, row.workflow_id
    finally:
        await session.close()

    if decision == "rejected":
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE workflow_runs SET status = 'failed', completed_at = NOW(), "
                    "error = 'aprobación rechazada' WHERE id = :rid AND status = 'pending_approval'"
                ),
                {"rid": run_id},
            )
            await session.commit()
        finally:
            await session.close()
        return {"approval_id": str(approval_id), "status": "rejected"}

    # Approved → resume del run (reutiliza pasos persistidos; nodos OK no se
    # re-ejecutan).
    session = await get_async_session()
    try:
        wf = (
            await session.execute(
                text(
                    "SELECT organization_id FROM workflows WHERE id = :wid"
                ),
                {"wid": workflow_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if wf is None:
        return {"approval_id": str(approval_id), "status": "approved", "resume": False}
    corr = f"approval:{approval_id}"
    resumed = await run_workflow(
        workflow_id,
        {},
        trigger="approval",
        organization_id=wf.organization_id,
        workspace_id=None,
        actor_type="approval",
        actor_id=decided_by,
        correlation_id=corr,
        resume=True,
        run_id=run_id,
    )
    return {
        "approval_id": str(approval_id),
        "status": "approved",
        "resume": resumed.get("status") if isinstance(resumed, dict) else None,
        "run_id": str(run_id),
    }


# ---------------------------------------------------------------------------
# Dashboard de plataforma
# ---------------------------------------------------------------------------
async def workflows_dashboard() -> dict:
    session = await get_async_session()
    try:
        totals = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS runs, "
                    "COUNT(*) FILTER (WHERE status = 'succeeded') AS ok, "
                    "COUNT(*) FILTER (WHERE status = 'failed') AS failed, "
                    "AVG(duration_ms) AS avg_ms "
                    "FROM workflow_runs"
                )
            )
        ).fetchone()
        by_trigger = (
            await session.execute(
                text(
                    "SELECT w.trigger_type, COUNT(r.id) AS runs, "
                    "COUNT(r.id) FILTER (WHERE r.status = 'succeeded') AS ok "
                    "FROM workflows w LEFT JOIN workflow_runs r ON r.workflow_id = w.id "
                    "GROUP BY w.trigger_type ORDER BY runs DESC"
                )
            )
        ).fetchall()
        recent = (
            await session.execute(
                text(
                    "SELECT w.name, r.status, r.duration_ms, r.started_at "
                    "FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id "
                    "ORDER BY r.started_at DESC LIMIT 10"
                )
            )
        ).fetchall()
        active_wf = (
            await session.execute(text("SELECT COUNT(*) FROM workflows WHERE status = 'active'"))
        ).scalar()
        failed_steps = (
            await session.execute(
                text(
                    "SELECT COALESCE(node_type, step_type) AS step_type, COUNT(*) AS n "
                    "FROM workflow_run_steps WHERE status = 'failed' "
                    "GROUP BY COALESCE(node_type, step_type) ORDER BY n DESC"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    total = int(totals.runs or 0)
    ok = int(totals.ok or 0)
    return {
        "total_runs": total,
        "success_rate": round(ok / total * 100, 1) if total else 0.0,
        "failed_runs": int(totals.failed or 0),
        "avg_duration_ms": int(totals.avg_ms or 0),
        "active_workflows": int(active_wf or 0),
        "by_trigger": [
            {"trigger_type": r.trigger_type, "runs": int(r.runs), "ok": int(r.ok)} for r in by_trigger
        ],
        "recent_runs": [
            {
                "workflow": r.name,
                "status": r.status,
                "duration_ms": int(r.duration_ms) if r.duration_ms is not None else None,
                "started_at": r.started_at.isoformat(),
            }
            for r in recent
        ],
        "failed_steps": [{"step_type": r.step_type, "count": int(r.n)} for r in failed_steps],
    }


# Compatibilidad con imports existentes (helpers usados por nodos).
_org_config = None  # noqa: F841







