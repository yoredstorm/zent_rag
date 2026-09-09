# =============================================================================
# AI Workflow Automation Studio v2 — motor de ejecución multi-paso con
# disparadores, retries y trazabilidad de runs.
# =============================================================================
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

STEP_TYPES = ("llm", "kb_query", "api_call", "condition", "notify")
TRIGGER_TYPES = ("webhook", "schedule", "event")


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


def _resolve_references(value, ctx: dict):
    """Resuelve {{trigger.X}} y {{steps.N.output.Y}} en strings/dicts."""
    if isinstance(value, str):
        def repl(match):
            ref = match.group(1)
            parts = ref.split(".")
            if parts[0] == "trigger":
                cur = ctx.get("trigger", {})
                for p in parts[1:]:
                    if isinstance(cur, dict):
                        cur = cur.get(p)
                    else:
                        return match.group(0)
                return (
            json.dumps(cur, ensure_ascii=False)
            if isinstance(cur, (dict, list))
            else str(cur if cur is not None else "")
        )
            if parts[0] == "steps":
                try:
                    idx = int(parts[1])
                except (ValueError, IndexError):
                    return match.group(0)
                step = ctx.get("steps", {}).get(idx)
                if step is None:
                    return match.group(0)
                cur = step.get("output", {})
                rest = parts[2:]
                if rest and rest[0] == "output":
                    rest = rest[1:]
                for p in rest:
                    if isinstance(cur, dict):
                        cur = cur.get(p)
                    else:
                        return match.group(0)
                return (
            json.dumps(cur, ensure_ascii=False)
            if isinstance(cur, (dict, list))
            else str(cur if cur is not None else "")
        )
            return match.group(0)

        return re.sub(r"\{\{([^}]+)\}\}", repl, value)
    if isinstance(value, dict):
        return {k: _resolve_references(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_references(v, ctx) for v in value]
    return value


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


async def _org_config(organization_id: UUID) -> dict:
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


async def _exec_kb_query(config: dict, organization_id: UUID) -> dict:
    query = config.get("query") or ""
    limit = min(int(config.get("limit", 5) or 5), 20)
    kb_raw = config.get("knowledge_base_id")
    if kb_raw:
        try:
            kb_id = UUID(str(kb_raw))
        except ValueError:
            return {"error": "knowledge_base_id inválido"}
        session = await get_async_session()
        try:
            owned = (
                await session.execute(
                    text(
                        "SELECT id FROM knowledge_bases "
                        "WHERE id = :kid AND organization_id = :oid"
                    ),
                    {"kid": kb_id, "oid": organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if owned is None:
            return {"error": "knowledge_base_id no pertenece al tenant"}
        try:
            from src.api.deps import get_retriever
            from src.rag.retrieval.models import RetrievalQuery

            retriever = get_retriever()
            context = await retriever.retrieve(
                RetrievalQuery(
                    query=query,
                    organization_id=organization_id,
                    knowledge_base_id=kb_id,
                    top_k=limit,
                    effective_top_k=limit,
                )
            )
            chunks = [
                {
                    "title": (c.metadata or {}).get("title") or "",
                    "text": (c.content or "")[:800],
                }
                for c in (context.chunks or [])[:limit]
            ]
            return {"output": {"chunks": chunks, "count": len(chunks), "documents": chunks}}
        except Exception as exc:  # noqa: BLE001
            logger.warning("kb_query retrieval failed", error=str(exc)[:200])
            return {"output": {"chunks": [], "count": 0, "documents": []}}
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, title FROM documents WHERE organization_id = :oid "
                    "AND (title ILIKE :pattern OR metadata_json::text ILIKE :pattern) "
                    "LIMIT :lim"
                ),
                {"oid": organization_id, "pattern": f"%{query}%", "lim": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    docs = [{"id": str(r.id), "title": r.title} for r in rows]
    return {"output": {"documents": docs, "count": len(docs)}}


async def _exec_api_call(config: dict, organization_id: UUID) -> dict:
    url = config.get("url") or ""
    if not url:
        return {"error": "api_call requiere url"}
    from urllib.parse import urlparse

    from src.agents.tools.base import ToolError
    from src.agents.tools.tools_builtin import CallApiTool

    org_cfg = await _org_config(organization_id)
    allowlist = ((org_cfg.get("agent") or {}).get("api_allowlist") or [])
    if not allowlist:
        return {"error": "call_api blocked: no api_allowlist configured for tenant"}
    try:
        parsed = urlparse(str(url))
    except ValueError as exc:
        return {"error": f"Invalid URL: {exc}"}
    if parsed.scheme not in ("https", "http"):
        return {"error": f"Blocked URL scheme: {parsed.scheme}"}
    if not parsed.hostname:
        return {"error": "URL without host"}
    if not CallApiTool._host_allowed(parsed.hostname, allowlist):
        return {"error": f"Host '{parsed.hostname}' not in tenant api_allowlist"}
    try:
        CallApiTool._ssrf_check(parsed.hostname)
    except ToolError as exc:
        return {"error": str(exc)}
    method = (config.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        return {"error": "method debe ser GET o POST"}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            if method == "POST":
                resp = await client.post(url, json=config.get("json_body") or {})
            else:
                resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:300]}
    body_text = resp.text[:4000]
    try:
        parsed_json = json.loads(resp.text)
    except (json.JSONDecodeError, ValueError):
        parsed_json = None
    extracted = _extract_json_path(parsed_json, str(config.get("json_path") or ""))
    return {
        "output": {
            "url": url,
            "status_code": resp.status_code,
            "ok": 200 <= resp.status_code < 300,
            "body": body_text,
            "json": parsed_json,
            "extracted": extracted,
        }
    }


async def _resolve_agent_id(organization_id: UUID, agent_id: str | None) -> UUID | None:
    if not agent_id:
        return None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM agents WHERE id = :aid AND organization_id = :oid "
                    "AND status IN ('configured', 'ready', 'deployed')"
                ),
                {"aid": UUID(agent_id), "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return row.id if row else None


async def _exec_step(
    step_type: str, config: dict, ctx: dict, organization_id: UUID
) -> dict:
    """Ejecuta un paso y devuelve {"output": ..., "error": ...}."""
    if step_type == "llm":
        agent_id = await _resolve_agent_id(organization_id, config.get("agent_id"))
        prompt = config.get("prompt") or config.get("message") or ""
        if agent_id:
            from src.platform.agents.agent_runtime import run_agent

            result = await run_agent(
                agent_id=agent_id,
                organization_id=organization_id,
                query=prompt,
                user_id=None,
            )
            return {"output": {"text": result.get("answer") or result.get("output") or "", "agent_id": str(agent_id)}}
        model = config.get("model", "gpt-4o-mini")
        if config.get("fail_once"):
            return {"error": "llm fallo simulado (retry)"}
        return {"output": {"text": f"[{model}] {prompt[:300]}", "model": model}}
    if step_type == "kb_query":
        return await _exec_kb_query(config, organization_id)
    if step_type == "api_call":
        return await _exec_api_call(config, organization_id)
    if step_type == "condition":
        field = config.get("field", "")
        operator = config.get("operator", "==")
        value = config.get("value", "")
        if field.startswith(("trigger.", "steps.")):
            actual = _resolve_references("{{" + field + "}}", ctx)
        else:
            actual = str(field)
        result = _eval_condition(actual, operator, value)
        return {"output": {"condition": f"{field} {operator} {value}", "result": result}}
    if step_type == "notify":
        from src.platform.notifyv2.notifications import notify

        channel = config.get("channel") or "in_app"
        wanted = None if channel == "all" else {str(channel)}
        data = dict(config.get("data") or {}) if isinstance(config.get("data"), dict) else {}
        data.setdefault("workflow_id", str(ctx.get("workflow_id") or ""))
        data.setdefault("run_id", str(ctx.get("run_id") or ""))
        sent = await notify(
            organization_id=organization_id,
            event_type="workflow.run",
            title=config.get("title") or "Workflow",
            body=config.get("message") or "Notificación de workflow",
            data=data,
            channels=wanted,
        )
        return {"output": {"sent": True, "channel": channel, "result": sent}}
    return {"error": f"tipo de paso desconocido: {step_type}"}


async def _persist_step(
    run_id: UUID,
    index: int,
    step_type: str,
    status: str,
    config: dict,
    output: dict,
    error: str | None,
    retries: int,
    started: datetime,
    duration_ms: int,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_run_steps (id, run_id, step_index, step_type, "
                "status, input, output, error, retries, started_at, completed_at, duration_ms) "
                "VALUES (gen_random_uuid(), :rid, :idx, :stype, :status, "
                "CAST(:input AS jsonb), CAST(:output AS jsonb), :error, :retries, "
                ":s_at, :c_at, :dur)"
            ),
            {
                "rid": run_id,
                "idx": index,
                "stype": str(step_type)[:20],
                "status": status,
                "input": json.dumps(config or {}),
                "output": json.dumps(output or {}),
                "error": error,
                "retries": retries,
                "s_at": started,
                "c_at": datetime.now(timezone.utc),
                "dur": duration_ms,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _run_step_list(
    steps: list,
    ctx: dict,
    organization_id: UUID,
    run_id: UUID,
    db_index: int,
    assign_ctx: bool,
) -> tuple[int, bool, str | None]:
    """Ejecuta una lista de pasos. Si assign_ctx, escribe ctx['steps'][i] por índice de lista."""
    overall_failed = False
    overall_error = None
    for index, step in enumerate(steps or []):
        step_type = step.get("type", "")
        max_retries = int(step.get("retries", 0) or 0)
        on_error = step.get("on_error", "fail")
        attempts = 0
        step_status = "succeeded"
        step_error = None
        step_output: dict = {}
        step_started = datetime.now(timezone.utc)

        while True:
            attempts += 1
            attempt_config = _resolve_references(step.get("config") or {}, ctx)
            if attempts > 1 and isinstance(attempt_config, dict):
                attempt_config.pop("fail_once", None)
            result = await _exec_step(step_type, attempt_config, ctx, organization_id)
            if "error" in result:
                step_error = result["error"]
                if attempts <= max_retries:
                    continue
                step_status = "failed"
                break
            step_output = result.get("output") or {}
            if step_type == "condition" and step_output.get("result") is False:
                step_status = "skipped"
                step_error = None
            break

        if assign_ctx:
            ctx["steps"][index] = {"output": step_output}
        elapsed = int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000)
        await _persist_step(
            run_id,
            db_index,
            step_type,
            step_status,
            step.get("config") or {},
            step_output,
            step_error,
            max(0, attempts - 1),
            step_started,
            elapsed,
        )
        db_index += 1

        if step_type == "condition" and step_status != "failed":
            branch = step.get("then") if step_output.get("result") else step.get("else")
            db_index, branch_failed, branch_error = await _run_step_list(
                branch or [],
                ctx,
                organization_id,
                run_id,
                db_index,
                assign_ctx=False,
            )
            if branch_failed:
                overall_failed = True
                overall_error = branch_error
                break

        if step_status == "failed" and on_error != "continue":
            overall_failed = True
            overall_error = step_error
            break
    return db_index, overall_failed, overall_error


async def run_workflow(
    workflow_id: UUID,
    payload: dict | None = None,
    trigger: str = "manual",
) -> dict:
    """Ejecuta los pasos del workflow de forma secuencial y trazable."""
    trig = trigger if trigger in ("manual", "schedule", "webhook", "event") else "manual"
    session = await get_async_session()
    try:
        wf = (
            await session.execute(
                text(
                    "SELECT id, organization_id, name, steps, status "
                    "FROM workflows WHERE id = :wid"
                ),
                {"wid": workflow_id},
            )
        ).fetchone()
        if wf is None:
            return None
        if wf.status == "paused":
            return {"status": "paused", "message": "workflow pausado"}
        steps = wf.steps or []
        run_id = (
            await session.execute(
                text(
                    "INSERT INTO workflow_runs (id, workflow_id, organization_id, trigger, "
                    "trigger_payload) "
                    "VALUES (gen_random_uuid(), :wid, :oid, :trig, "
                    "CAST(:payload AS jsonb)) RETURNING id"
                ),
                {
                    "wid": workflow_id,
                    "oid": wf.organization_id,
                    "trig": trig,
                    "payload": json.dumps(payload or {}),
                },
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()

    ctx = {
        "trigger": payload or {},
        "steps": {},
        "workflow_id": str(workflow_id),
        "run_id": str(run_id),
    }
    started = datetime.now(timezone.utc)
    _db_index, overall_failed, overall_error = await _run_step_list(
        steps, ctx, wf.organization_id, run_id, 0, assign_ctx=True
    )

    duration = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    final_status = "failed" if overall_failed else "succeeded"
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_runs SET status = :status, completed_at = NOW(), "
                "duration_ms = :dur, error = :err WHERE id = :rid"
            ),
            {"status": final_status, "dur": duration, "err": overall_error, "rid": run_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "run_id": str(run_id),
        "workflow_id": str(workflow_id),
        "status": final_status,
        "duration_ms": duration,
        "error": overall_error,
        "steps": len(ctx["steps"]),
    }


# ---------------------------------------------------------------------------
# CRUD workflows
# ---------------------------------------------------------------------------
async def list_workflows(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT w.id, w.name, w.description, w.trigger_type, w.status, "
                    "w.created_at, w.updated_at, "
                    "COUNT(r.id) AS runs, "
                    "COUNT(r.id) FILTER (WHERE r.status = 'succeeded') AS ok_runs "
                    "FROM workflows w LEFT JOIN workflow_runs r ON r.workflow_id = w.id "
                    "WHERE w.organization_id = :oid "
                    "GROUP BY w.id ORDER BY w.created_at DESC"
                ),
                {"oid": organization_id},
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
) -> dict:
    if trigger_type not in TRIGGER_TYPES:
        raise ValueError(f"trigger_type debe ser uno de {TRIGGER_TYPES}")
    cleaned = _clean_steps(steps)
    tcfg = dict(trigger_config or {})
    if trigger_type == "schedule":
        every = int(tcfg.get("every_minutes") or 0)
        if every < 1:
            tcfg["every_minutes"] = 5
        else:
            tcfg["every_minutes"] = min(max(every, 1), 1440)
    plain_secret = None
    if trigger_type == "webhook" and not tcfg.get("hook_secret_hash"):
        plain_secret = secrets.token_urlsafe(24)
        tcfg["hook_secret_hash"] = _hash_hook_secret(plain_secret)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO workflows (id, organization_id, name, description, "
                    "trigger_type, trigger_config, steps, created_by, editor_state) "
                    "VALUES (gen_random_uuid(), :oid, :name, :desc, :ttype, "
                    "CAST(:tcfg AS jsonb), CAST(:steps AS jsonb), :by, CAST(:estate AS jsonb)) "
                    "RETURNING id, name"
                ),
                {
                    "oid": organization_id,
                    "name": name[:150],
                    "desc": description,
                    "ttype": trigger_type,
                    "tcfg": json.dumps(tcfg),
                    "steps": json.dumps(cleaned),
                    "by": created_by,
                    "estate": json.dumps(editor_state or {}),
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    out = {"workflow_id": str(row.id), "name": row.name}
    if plain_secret:
        out["hook_secret"] = plain_secret
    return out


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
                    "status, created_at, updated_at, editor_state FROM workflows "
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
            sets.append("trigger_config = CAST(:tcfg AS jsonb)")
            params["tcfg"] = json.dumps(merged)
        if steps is not None:
            cleaned = _clean_steps(steps)
            sets.append("steps = CAST(:steps AS jsonb)")
            params["steps"] = json.dumps(cleaned)
        if editor_state is not None:
            sets.append("editor_state = CAST(:estate AS jsonb)")
            params["estate"] = json.dumps(editor_state)
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


async def create_from_template(organization_id: UUID, slug: str, name: str | None = None) -> dict:
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
                    "r.duration_ms, r.error, w.name AS workflow_name "
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
                    "r.duration_ms, r.error, r.trigger_payload, w.name AS workflow_name, "
                    "w.organization_id "
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
                    "SELECT step_index, step_type, status, input, output, error, retries, "
                    "duration_ms FROM workflow_run_steps WHERE run_id = :rid ORDER BY step_index"
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
        "steps": [
            {
                "step_index": int(s.step_index),
                "step_type": s.step_type,
                "status": s.status,
                "input": s.input,
                "output": s.output,
                "error": s.error,
                "retries": int(s.retries),
                "duration_ms": int(s.duration_ms) if s.duration_ms is not None else None,
            }
            for s in steps
        ],
    }


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
                    "SELECT step_type, COUNT(*) AS n FROM workflow_run_steps "
                    "WHERE status = 'failed' GROUP BY step_type ORDER BY n DESC"
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


async def run_due_scheduled_workflows(
    now: datetime | None = None,
    organization_id: UUID | None = None,
) -> int:
    """Dispara workflows schedule activos cuyo every_minutes ya venció."""
    now = now or datetime.now(timezone.utc)
    session = await get_async_session()
    try:
        sql = (
            "SELECT id, trigger_config, last_run_at FROM workflows "
            "WHERE status = 'active' AND trigger_type = 'schedule'"
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
        try:
            every = int(cfg.get("every_minutes") or 0)
        except (TypeError, ValueError):
            continue
        if every < 1:
            continue
        last = row.last_run_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < timedelta(minutes=every):
                continue
        await run_workflow(row.id, {"scheduled_at": now.isoformat()}, trigger="schedule")
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


async def workflow_v2_scheduler_loop() -> None:
    """Cada 60s: ejecuta schedules v2 vencidos."""
    while True:
        try:
            await run_due_scheduled_workflows()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Workflow v2 scheduler iteration failed", error=str(exc)[:200])
        await asyncio.sleep(60)


async def run_workflow_from_hook(workflow_id: UUID, secret: str, payload: dict | None) -> dict:
    """Inbound público: compara secret y dispara el workflow."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, status, trigger_type, trigger_config FROM workflows WHERE id = :wid"
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
    return await run_workflow(workflow_id, payload or {}, trigger="webhook")
