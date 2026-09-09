# =============================================================================
# Phase 32A — WorkflowNodeHandler registry
#
# Arquitectura extensible: cada tipo de nodo se registra con schema de entrada/
# salida, capabilities, risk_level y execute(). El runtime solo despacha por
# registry — sin if/elif gigantes.
# =============================================================================
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Capabilities declarativas por nodo.
READ_DB = "reads_db"
WRITE_DB = "writes_db"
CALLS_EXTERNAL = "calls_external"
CALLS_AGENT = "calls_agent"
SENDS_NOTIFICATION = "sends_notification"
NEEDS_APPROVAL = "needs_approval"
IS_LOGIC = "is_logic"
IS_TRIGGER = "is_trigger"
VIRTUAL = "virtual"

# Permisos exigidos por capability (verificados en runtime contra
# ExecutionContext.permissions).
_CAPABILITY_PERMISSION = {
    CALLS_EXTERNAL: "external_actions:execute",
    CALLS_AGENT: "agents:execute",
    "uses_integration": "integrations:use",
}


@dataclass(frozen=True)
class NodeTypeDef:
    node_type: str
    version: int
    label: str
    category: str  # trigger | data | ai | integration | logic | control | output
    risk_level: str  # info | normal | elevated | critical
    capabilities: frozenset[str]
    inputs: dict[str, dict] = field(default_factory=dict)
    outputs: dict[str, dict] = field(default_factory=dict)
    execute: Callable[["NodeContext"], Awaitable["NodeOutcome"]] | None = None

    @property
    def simulated(self) -> bool:
        """Nodos con efectos de lado se simulan en dry-run (no se ejecutan)."""
        return bool(
            self.capabilities
            & {WRITE_DB, CALLS_EXTERNAL, SENDS_NOTIFICATION, NEEDS_APPROVAL}
            or self.risk_level in ("elevated", "critical")
        )


@dataclass
class NodeOutcome:
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    simulated: bool = False
    planned: dict[str, Any] = field(default_factory=dict)
    control: str | None = None  # None | "stop_success" | "stop_fail" | "wait_approval"
    cost_ms: float = 0.0


@dataclass
class NodeContext:
    """Contexto de ejecución de un nodo (runtime inyecta todo lo necesario)."""

    execution: "ExecutionContext"  # noqa: F821 — import diferido por ciclo
    node: "WorkflowNode"  # noqa: F821
    node_type: NodeTypeDef
    node_id: str
    inputs: dict[str, Any]  # puerto → data resuelta
    trigger: dict[str, Any]
    payload: dict[str, Any]
    variables: dict[str, Any]  # variables del grafo (mutable)
    node_outputs: dict[str, dict[str, Any]]  # outputs de nodos ya ejecutados
    idempotency_key: str | None
    simulate: bool = False
    run_branch: Callable[[list[str], Any], Awaitable[dict[str, NodeOutcome]]] | None = None
    cached: dict[str, dict[str, Any]] = field(default_factory=dict)  # resume/approval
    legacy_index_map: dict[str, str] = field(default_factory=dict)  # steps.N → node id

    @property
    def organization_id(self) -> UUID:
        return self.execution.organization_id

    @property
    def workspace_id(self) -> UUID | None:
        return self.execution.workspace_id

    @property
    def permissions(self) -> frozenset[str]:
        return self.execution.permissions


class NodeRegistry:
    def __init__(self) -> None:
        self._defs: dict[str, NodeTypeDef] = {}

    def register(self, node_type: str, version: int = 1, **kwargs: Any) -> NodeTypeDef:
        if node_type in self._defs:
            raise ValueError(f"nodo ya registrado: {node_type}")
        d = NodeTypeDef(node_type=node_type, version=version, **kwargs)
        self._defs[node_type] = d
        return d

    def get(self, node_type: str) -> NodeTypeDef | None:
        return self._defs.get(node_type)

    def require(self, node_type: str) -> NodeTypeDef:
        d = self._defs.get(node_type)
        if d is None:
            raise KeyError(f"tipo de nodo desconocido: {node_type}")
        return d

    def all(self) -> list[NodeTypeDef]:
        return sorted(self._defs.values(), key=lambda d: (d.category, d.label))


registry = NodeRegistry()


# ---------------------------------------------------------------------------
# Referencias y helpers compartidos
# ---------------------------------------------------------------------------
def _resolve_ref(value: Any, rctx: NodeContext) -> Any:
    from src.platform.workflows.ir import resolve_stable_references

    if isinstance(value, str):
        resolved = resolve_stable_references(value, rctx.node_outputs, rctx.trigger)
        if isinstance(resolved, str) and "{{" not in resolved:
            v = resolved
            if v.lower() in ("true",):
                return True
            if v.lower() in ("false",):
                return False
            try:
                return float(v) if "." in v or "e" in v.lower() else int(v) if v.lstrip("-").isdigit() else v
            except ValueError:
                return v
        return resolved
    return resolve_stable_references(value, rctx.node_outputs)


def _deny(outcome: NodeOutcome, permission: str, node_type: str) -> NodeOutcome:
    logger.warning("workflow node permission denied", permission=permission, node=node_type)
    outcome.error = f"permiso insuficiente: {permission}"
    return outcome


async def _run_with_permission(rctx: NodeContext, perm: str, coro: Awaitable[NodeOutcome]) -> NodeOutcome:
    if perm not in rctx.permissions:
        return _deny(NodeOutcome(), perm, rctx.node_type.node_type)
    return await coro


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def _exec_api_call(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    url = str(_resolve_ref(cfg.get("url", ""), rctx) or "")
    if not url:
        return NodeOutcome(error="api_call requiere url")
    from urllib.parse import urlparse

    from src.agents.tools.base import ToolError
    from src.agents.tools.tools_builtin import CallApiTool

    async def _org_config(organization_id: UUID) -> dict:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

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

    org_cfg = await _org_config(rctx.organization_id)
    allowlist = ((org_cfg.get("agent") or {}).get("api_allowlist") or [])
    if not allowlist:
        return NodeOutcome(error="call_api blocked: no api_allowlist configured for tenant")
    try:
        parsed = urlparse(str(url))
    except ValueError as exc:
        return NodeOutcome(error=f"Invalid URL: {exc}")
    if parsed.scheme not in ("https", "http"):
        return NodeOutcome(error=f"Blocked URL scheme: {parsed.scheme}")
    if not parsed.hostname:
        return NodeOutcome(error="URL without host")
    if not CallApiTool._host_allowed(parsed.hostname, allowlist):
        return NodeOutcome(error=f"Host '{parsed.hostname}' not in tenant api_allowlist")
    try:
        CallApiTool._ssrf_check(parsed.hostname)
    except ToolError as exc:
        return NodeOutcome(error=str(exc))
    method = (cfg.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        return NodeOutcome(error="method debe ser GET o POST")
    body = _resolve_ref(cfg.get("json_body") or {}, rctx)
    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={
                "kind": "http",
                "method": method,
                "url": url,
                "body_keys": sorted((body or {}).keys()) if isinstance(body, dict) else None,
            },
            output={"simulated": True, "method": method, "url": url},
        )
    try:
        from src.platform.workflows import engine as wf_engine

        async with wf_engine.httpx.AsyncClient(follow_redirects=False, timeout=10.0) as client:
            if method == "POST":
                resp = await client.post(url, json=body or {})
            else:
                resp = await client.get(url)
    except Exception as exc:  # noqa: BLE001
        return NodeOutcome(error=str(exc)[:300])
    try:
        parsed_json = json.loads(resp.text)
    except (json.JSONDecodeError, ValueError):
        parsed_json = None
    json_path = str(cfg.get("json_path") or "")
    extracted = None
    if json_path and parsed_json is not None:
        from src.platform.workflows.engine import _extract_json_path as _extract

        extracted = _extract(parsed_json, json_path)
    return NodeOutcome(
        output={
            "url": url,
            "status_code": resp.status_code,
            "ok": 200 <= resp.status_code < 300,
            "body": resp.text[:4000],
            "json": parsed_json,
            "extracted": extracted,
            "idempotency_key": rctx.idempotency_key,
        }
    )


async def _exec_kb_query(rctx: NodeContext) -> NodeOutcome:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    cfg = rctx.node.config
    query = str(_resolve_ref(cfg.get("query", ""), rctx) or "")
    limit = min(int(cfg.get("limit", 5) or 5), 20)
    kb_raw = cfg.get("knowledge_base_id")
    if kb_raw:
        try:
            kb_id = UUID(str(kb_raw))
        except ValueError:
            return NodeOutcome(error="knowledge_base_id inválido")
        session = await get_async_session()
        try:
            owned = (
                await session.execute(
                    text(
                        "SELECT id FROM knowledge_bases "
                        "WHERE id = :kid AND organization_id = :oid"
                    ),
                    {"kid": kb_id, "oid": rctx.organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if owned is None:
            return NodeOutcome(error="knowledge_base_id no pertenece al tenant")
        try:
            from src.api.deps import get_retriever
            from src.rag.retrieval.models import RetrievalQuery

            retriever = get_retriever()
            context = await retriever.retrieve(
                RetrievalQuery(
                    query=query,
                    organization_id=rctx.organization_id,
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
            return NodeOutcome(output={"chunks": chunks, "count": len(chunks), "documents": chunks})
        except Exception as exc:  # noqa: BLE001
            logger.warning("kb_query retrieval failed", error=str(exc)[:200])
            return NodeOutcome(output={"chunks": [], "count": 0, "documents": []})
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, title FROM documents WHERE organization_id = :oid "
                    "AND (title ILIKE :pattern OR metadata_json::text ILIKE :pattern) "
                    "LIMIT :lim"
                ),
                {"oid": rctx.organization_id, "pattern": f"%{query}%", "lim": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    docs = [{"id": str(r.id), "title": r.title} for r in rows]
    return NodeOutcome(output={"documents": docs, "count": len(docs)})


async def _exec_llm(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    prompt = str(_resolve_ref(cfg.get("prompt") or cfg.get("message") or "", rctx) or "")
    agent_id_raw = cfg.get("agent_id")
    agent_id: UUID | None = None
    if agent_id_raw:
        try:
            agent_id = UUID(str(agent_id_raw))
        except ValueError:
            agent_id = None
    if cfg.get("fail_once"):
        return NodeOutcome(error="llm fallo simulado (retry)")

    async def _agent_run() -> NodeOutcome:
        if agent_id is None:
            raise LookupError()
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id FROM agents WHERE id = :aid AND organization_id = :oid "
                        "AND status IN ('configured', 'ready', 'deployed')"
                    ),
                    {"aid": agent_id, "oid": rctx.organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None:
            raise LookupError()
        from src.agents.runtime.agent_runtime import AgentRunRequest
        from src.api.deps import get_agent_repo, get_agent_runtime

        agent = await get_agent_repo().get_agent(agent_id)
        if agent is None:
            raise LookupError()
        org_config = await _org_config_json(rctx.organization_id)
        result = await get_agent_runtime().run(
            AgentRunRequest(
                agent=agent,
                message=prompt,
                user_id=rctx.execution.actor_id,
                role="admin",
                permissions=rctx.permissions,
                org_config=org_config,
                trace_id=rctx.execution.correlation_id,
            )
        )
        return NodeOutcome(
            output={
                "text": result.answer or result.message or "",
                "agent_id": str(agent_id),
                "model": result.model,
                "cost": result.cost,
            },
            cost_ms=float(result.cost or 0.0),
        )

    async def _echo() -> NodeOutcome:
        model = cfg.get("model", "gpt-4o-mini")
        return NodeOutcome(output={"text": f"[{model}] {prompt[:300]}", "model": model})

    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={"kind": "llm", "agent_id": str(agent_id) if agent_id else None, "prompt_preview": prompt[:120]},
            output={"simulated": True},
        )
    if "agents:execute" not in rctx.permissions:
        return _deny(NodeOutcome(), "agents:execute", "llm")
    if agent_id is None:
        return await _echo()
    try:
        return await _agent_run()
    except Exception:  # noqa: BLE001
        return await _echo()


async def _org_config_json(organization_id: UUID) -> dict:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

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


async def _exec_condition(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    from src.platform.workflows.engine import _eval_condition as _eval

    field = str(cfg.get("field", ""))
    operator = str(cfg.get("operator", "=="))
    value = _resolve_ref(cfg.get("value", ""), rctx)
    field = str(field)

    if field.startswith("trigger."):
        # {{trigger.<path>}} → lookup directo sobre el payload.
        actual = _trigger_field(field, rctx.trigger)
        if actual is None:
            actual = ""
    elif field.startswith("nodes."):
        resolved = _resolve_ref("{{" + field + "}}", rctx)
        actual = None if "{{" in str(resolved) else resolved
    elif field.startswith("steps."):
        import re as _re

        m = _re.match(r"steps\.(\d+)\.output\.(.*)", field)
        nid = rctx.legacy_index_map.get(m.group(1), f"n{m.group(1)}") if m else None
        actual = None
        if nid is not None:
            out = (rctx.node_outputs.get(nid) or {}).get("output", {})
            if isinstance(out, dict):
                cur: Any = out
                for part in m.group(2).split(".") if m else []:
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        cur = None
                        break
                actual = cur
    else:
        actual = str(field)
    result = _eval(actual, operator, value)
    return NodeOutcome(output={"condition": f"{field} {operator} {value}", "result": result})


def _trigger_field(field: str, trigger: dict) -> Any:
    cur = trigger
    for part in field.split(".")[1:]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


async def _exec_notify(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    from src.platform.notifyv2.notifications import notify

    channel = str(cfg.get("channel") or "in_app")
    wanted = None if channel == "all" else {str(channel)}
    data = dict(cfg.get("data") or {}) if isinstance(cfg.get("data"), dict) else {}
    data = _resolve_ref(data, rctx)
    if isinstance(data, dict):
        data.setdefault("workflow_id", str(rctx.execution.workflow_id))
        data.setdefault("run_id", str(rctx.execution.run_id))
    title = str(_resolve_ref(cfg.get("title") or "Workflow", rctx) or "Workflow")
    message = str(_resolve_ref(cfg.get("message") or "Notificación de workflow", rctx) or "")
    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={"kind": "notification", "channel": channel, "title": title},
            output={"simulated": True, "channel": channel, "title": title},
        )
    sent = await notify(
        organization_id=rctx.organization_id,
        event_type="workflow.run",
        title=title,
        body=message,
        data=data,
        channels=wanted,
    )
    return NodeOutcome(output={"sent": True, "channel": channel, "result": sent})


async def _exec_query_business_data(rctx: NodeContext) -> NodeOutcome:
    """Consultas de negocio en lenguaje natural → pipeline semántico completo
    (semantic compiler, text-to-SQL, answerability, evidence) vía orchestrator."""
    cfg = rctx.node.config
    ask = str(_resolve_ref(cfg.get("ask") or cfg.get("question") or "", rctx) or "")
    if not ask:
        return NodeOutcome(error="query_business_data requiere ask")
    if rctx.simulate:
        return NodeOutcome(
            simulated=False,
            planned={"kind": "business_query", "question": ask[:160]},
            output={"simulated": False},
        )

    def _get_orchestrator():
        from src.api.deps import get_rag_orchestrator

        try:
            from src.api.main import app

            override = app.dependency_overrides.get(get_rag_orchestrator)
            if override is not None:
                return override()
        except Exception:  # noqa: BLE001
            pass
        return get_rag_orchestrator()

    try:
        orch = _get_orchestrator()
        meta = {}
        if rctx.workspace_id is not None:
            meta["workspace_id"] = str(rctx.workspace_id)
        result = await orch.execute(
            organization_id=rctx.organization_id,
            user_id=rctx.execution.actor_id,
            query=ask,
            role="admin",
            language="es",
            metadata_filters=meta or None,
            trace_id=rctx.execution.correlation_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("query_business_data failed", error=str(exc)[:200])
        return NodeOutcome(error=f"query_business_data falló: {str(exc)[:200]}")

    structured = getattr(result, "structured_output", None)
    outcome: dict[str, Any] = {
        "query_id": str(result.query_id) if getattr(result, "query_id", None) else None,
        "answer": (result.llm_response.content if getattr(result, "llm_response", None) else None),
        "method": getattr(result, "method", None),
        "sql_query": getattr(result, "sql_query", None),
        "metrics": {
            "latency_ms": float(getattr(result, "total_latency_ms", 0.0) or 0.0),
        },
        "evidence": [],
    }
    if structured is not None:
        outcome["rows"] = structured.get("rows", [])
        outcome["columns"] = structured.get("columns", [])
    ab = getattr(result, "answerability", None)
    if ab is not None:
        outcome["evidence"] = [
            {"source": s} for s in (getattr(ab, "sources", None) or [])
        ]
        outcome["metrics"]["answerable"] = bool(getattr(ab, "answerable", False))
    rc = getattr(result, "retrieval_context", None)
    if rc is not None:
        chunks = getattr(rc, "chunks", None) or []
        if chunks:
            outcome["evidence"] = [
                {
                    "source": (c.metadata or {}).get("source")
                    or (c.source if getattr(c, "source", None) else "")
                }
                for c in chunks[:5]
            ]
            outcome["metrics"]["documents_used"] = len(chunks)
    outcome["source_freshness"] = {
        "ingested": bool(getattr(result, "lazy_ingested", False)),
        "rows_indexed": int(getattr(result, "lazy_rows_indexed", 0) or 0),
    }
    return NodeOutcome(output=outcome)


async def _exec_for_each(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    # Branch declarado en config (canvas) o en metadata (MVP tests/legacy).
    branch: list[str] = list(
        cfg.get("_branch")
        or (rctx.node.metadata or {}).get("_branch")
        or []
    )
    collection = _resolve_ref(cfg.get("collection", "[]"), rctx)
    if not isinstance(collection, list):
        try:
            parsed = json.loads(str(collection))
            collection = parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            collection = []
    max_iter = min(max(int(cfg.get("max_iterations", 100) or 100), 1), 500)
    concurrency = min(max(int(cfg.get("concurrency", 1) or 1), 1), 16)
    fail_policy = str(cfg.get("fail_policy", "fail"))
    if rctx.run_branch is None:
        return NodeOutcome(error="for_each sin subgrafo (run_branch no disponible)")
    items = collection[:max_iter]
    outcomes: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, Any]] = []
    started = time.monotonic()

    sem = asyncio.Semaphore(concurrency)

    async def _one(item: Any, idx: int) -> None:
        async with sem:
            try:
                res = await rctx.run_branch(branch, item)  # type: ignore[arg-type]
                for nid, oc in res.items():
                    outcomes.setdefault(nid, []).append(oc.output)
                    if oc.error:
                        errors.append({"item": idx, "node": nid, "error": oc.error})
            except Exception as exc:  # noqa: BLE001
                errors.append({"item": idx, "error": str(exc)[:200]})

    if concurrency > 1:
        await asyncio.gather(*(_one(it, i) for i, it in enumerate(items)))
    else:
        for i, it in enumerate(items):
            await _one(it, i)
            if errors and fail_policy == "fail":
                break

    if errors and fail_policy == "fail":
        return NodeOutcome(
            error=f"for_each falló en {len(errors)} ítems",
            output={"processed": len(outcomes), "errors": errors[:20]},
        )
    return NodeOutcome(
        output={
            "items_processed": len(items),
            "results": outcomes,
            "errors": errors[:50],
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    )


async def _exec_join(rctx: NodeContext) -> NodeOutcome:
    values = {k: v.get("output") for k, v in rctx.inputs.items() if isinstance(v, dict)}
    return NodeOutcome(output={"merged": True, "values": values})


async def _exec_merge(rctx: NodeContext) -> NodeOutcome:
    values = {k: v.get("output") for k, v in rctx.inputs.items() if isinstance(v, dict)}
    return NodeOutcome(output={"first": next(iter(values.values()), None), "values": values})


async def _exec_set_variable(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    name = str(cfg.get("name") or "")
    if not name:
        return NodeOutcome(error="set_variable requiere name")
    value = _resolve_ref(cfg.get("value", None), rctx)
    rctx.variables[name] = value
    return NodeOutcome(output={"variable": name, "value": value})


async def _exec_filter(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    items = _resolve_ref(cfg.get("items", []), rctx)
    field = str(cfg.get("field") or "")
    operator = str(cfg.get("operator", "=="))
    value = _resolve_ref(cfg.get("value", None), rctx)
    from src.platform.workflows.engine import _eval_condition as _eval

    if not isinstance(items, list):
        return NodeOutcome(output={"filtered": []})
    kept = [it for it in items if _eval(_field_of(it, field), operator, value)]
    return NodeOutcome(output={"filtered": kept, "count": len(kept), "total": len(items)})


def _field_of(item: Any, field: str) -> Any:
    if field.startswith("."):
        field = field[1:]
    cur = item
    for part in field.split(".") if field else []:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


async def _exec_stop(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    status = str(cfg.get("status") or "success")
    message = str(cfg.get("message") or "")
    control = "stop_success" if status == "success" else "stop_fail"
    return NodeOutcome(output={"stopped": True, "message": message}, control=control)


async def _exec_human_approval(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    action = str(cfg.get("action") or "acción sensible")
    summary = str(cfg.get("summary") or cfg.get("message") or "")
    expires_minutes = int(cfg.get("expires_minutes", 1440) or 1440)
    requested_by = rctx.execution.actor_id
    approval_id = await _create_approval(
        rctx.execution, rctx.node_id, action, summary, requested_by, expires_minutes
    )
    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={"kind": "approval", "action": action, "summary": summary},
            output={"approval_id": str(approval_id), "simulated": True, "status": "pending"},
        )
    return NodeOutcome(
        output={"approval_id": str(approval_id), "status": "pending", "action": action, "summary": summary},
        control="wait_approval",
    )


async def _create_approval(
    execution: "ExecutionContext",  # noqa: F821
    node_id: str,
    action: str,
    summary: str,
    requested_by: UUID | None,
    expires_minutes: int,
) -> UUID:
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    approval_id = uuid4()
    expires = datetime.now(timezone.utc) + timedelta(minutes=max(expires_minutes, 1))
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_approvals "
                "(id, run_id, workflow_id, organization_id, workspace_id, node_id, "
                "action, summary, requested_by, expires_at) "
                "VALUES (:id, :rid, :wid, :oid, :ws, :nid, :action, :summary, :by, :exp)"
            ),
            {
                "id": approval_id,
                "rid": execution.run_id,
                "wid": execution.workflow_id,
                "oid": execution.organization_id,
                "ws": execution.workspace_id,
                "nid": node_id,
                "action": action[:120],
                "summary": summary,
                "by": requested_by,
                "exp": expires,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return approval_id


async def _exec_end(rctx: NodeContext) -> NodeOutcome:
    return NodeOutcome(output={"end": True})


async def _exec_marketplace_action(rctx: NodeContext) -> NodeOutcome:
    """Acción del marketplace instalada: mismo runtime que agente/manual/API."""
    from src.platform.marketplace import runtime as mkt

    cfg = rctx.node.config
    install_id = str(cfg.get("install_id") or "")
    action_id = str(cfg.get("action_id") or "")
    if not install_id or not action_id:
        return NodeOutcome(error="marketplace_action requiere install_id y action_id")
    raw_inputs = cfg.get("inputs") or {}
    if not isinstance(raw_inputs, dict):
        return NodeOutcome(error="inputs debe ser un objeto")
    inputs: dict[str, object] = {
        str(k): _resolve_ref(v, rctx) for k, v in raw_inputs.items()
    }
    purpose = str(_resolve_ref(cfg.get("purpose") or "", rctx) or "") or None
    if rctx.simulate:
        from src.platform.marketplace.runtime import _estimate_cost

        return NodeOutcome(
            simulated=True,
            planned={
                "kind": "marketplace",
                "action_id": action_id,
                "inputs": {k: (str(v)[:40]) for k, v in inputs.items()},
                "estimated_cost": _estimate_cost({"cost_model": {"model": "PER_CALL"}}),
            },
            output={"simulated": True, "action_id": action_id},
        )
    outcome = await mkt.execute_action(
        rctx.organization_id,
        UUID(install_id) if _is_uuid(install_id) else None,
        action_id,
        inputs,
        workspace_id=rctx.workspace_id,
        purpose=purpose,
        workflow_id=rctx.execution.workflow_id,
        run_id=rctx.execution.run_id,
        actor_id=rctx.execution.actor_id,
        actor_type="workflow",
        source="workflow",
    )
    if not outcome.ok:
        return NodeOutcome(error=f"{outcome.error_code}: {outcome.error_message}")
    return NodeOutcome(
        output={
            **outcome.data,
            "evidence_id": str(outcome.evidence_id) if outcome.evidence_id else None,
            "cached": outcome.cached,
            "cost": outcome.customer_cost,
            "latency_ms": round(outcome.latency_ms, 1),
        },
        cost_ms=outcome.customer_cost,
    )


def _is_uuid(value: str) -> bool:
    import re

    return bool(re.match(r"^[0-9a-fA-F-]{36}$", value))


async def _exec_business_result(rctx: NodeContext) -> NodeOutcome:
    """Persiste un BusinessResult normalizado (dashboard/inbox/email/API)."""
    from src.platform.intelligence.results import (
        BusinessResult,
        BusinessResultError,
        save_result,
    )

    cfg = rctx.node.config
    title = str(_resolve_ref(cfg.get("title") or "Resultado", rctx) or "Resultado")
    summary = str(_resolve_ref(cfg.get("summary") or "", rctx) or "") or None
    section = str(cfg.get("section") or "reports")
    importance = str(cfg.get("importance") or "INFO")
    metrics = _resolve_ref(cfg.get("metrics") or {}, rctx)
    insights = _resolve_ref(cfg.get("insights") or [], rctx)
    entities = _resolve_ref(cfg.get("entities") or [], rctx)
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(insights, list):
        insights = [str(insights)] if insights else []
    if not isinstance(entities, list):
        entities = []
    result = BusinessResult(
        title=title,
        summary=summary,
        section=section,
        importance=importance,
        metrics=metrics,
        insights=[str(i) for i in insights],
        entities=entities,
        workflow_id=rctx.execution.workflow_id,
        workflow_run_id=rctx.execution.run_id,
        agent_run_id=rctx.execution.actor_id,
        correlation_id=rctx.execution.correlation_id,
        source="workflow",
    )
    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={"kind": "business_result", "title": title, "importance": importance},
            output={"simulated": True},
        )
    try:
        saved = await save_result(rctx.organization_id, result, workspace_id=rctx.workspace_id)
    except BusinessResultError as exc:
        return NodeOutcome(error=str(exc))
    return NodeOutcome(output={"result_id": str(saved["result_id"]), "importance": saved["importance"]})


def _register_defaults() -> None:
    already = registry.get("llm")
    if already is not None:
        return

    # TRIGGERS (config-only; el disparo lo hace el runtime).
    for ttype, label, risk in (
        ("trigger_schedule", "Schedule", "info"),
        ("trigger_webhook", "Webhook", "info"),
        ("trigger_event", "Zent Event", "info"),
    ):
        registry.register(
            ttype,
            version=1,
            label=label,
            category="trigger",
            risk_level=risk,
            capabilities=frozenset({IS_TRIGGER}),
            execute=_exec_end,
        )

    # DATA
    registry.register(
        "api_call",
        version=1,
        label="Llamar API",
        category="integration",
        risk_level="elevated",
        capabilities=frozenset({READ_DB, CALLS_EXTERNAL}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_api_call,
    )
    registry.register(
        "kb_query",
        version=1,
        label="Consultar knowledge base",
        category="data",
        risk_level="normal",
        capabilities=frozenset({READ_DB}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_kb_query,
    )
    registry.register(
        "query_business_data",
        version=1,
        label="Consultar datos de negocio",
        category="data",
        risk_level="normal",
        capabilities=frozenset({READ_DB}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "record_list"}},
        execute=_exec_query_business_data,
    )

    # AI
    registry.register(
        "llm",
        version=1,
        label="Preguntar a un agente",
        category="ai",
        risk_level="normal",
        capabilities=frozenset({CALLS_AGENT}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_llm,
    )

    # LOGIC
    registry.register(
        "condition",
        version=1,
        label="Si / si no",
        category="logic",
        risk_level="info",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "boolean"}, "then": {"type": "json"}, "else": {"type": "json"}},
        execute=_exec_condition,
    )
    registry.register(
        "for_each",
        version=1,
        label="Para cada",
        category="logic",
        risk_level="normal",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}, "done": {"type": "json"}},
        execute=_exec_for_each,
    )
    registry.register(
        "join",
        version=1,
        label="Unir resultados",
        category="logic",
        risk_level="info",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_join,
    )
    registry.register(
        "merge",
        version=1,
        label="Primer resultado",
        category="logic",
        risk_level="info",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_merge,
    )
    registry.register(
        "filter",
        version=1,
        label="Filtrar",
        category="logic",
        risk_level="info",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "record_list"}},
        execute=_exec_filter,
    )
    registry.register(
        "set_variable",
        version=1,
        label="Guardar variable",
        category="logic",
        risk_level="info",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_set_variable,
    )

    # OUTPUT
    registry.register(
        "notify",
        version=1,
        label="Avisar",
        category="output",
        risk_level="normal",
        capabilities=frozenset({SENDS_NOTIFICATION}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_notify,
    )

    # MARKETPLACE (Phase 32B)
    registry.register(
        "marketplace_action",
        version=1,
        label="Acción de integración",
        category="integration",
        risk_level="normal",
        capabilities=frozenset({CALLS_EXTERNAL}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_marketplace_action,
    )

    # INTELLIGENCE (Phase 32C)
    registry.register(
        "business_result",
        version=1,
        label="Resultado de negocio",
        category="output",
        risk_level="info",
        capabilities=frozenset({WRITE_DB}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_business_result,
    )

    # CONTROL
    registry.register(
        "stop",
        version=1,
        label="Detener",
        category="control",
        risk_level="info",
        capabilities=frozenset({IS_LOGIC}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_stop,
    )
    registry.register(
        "human_approval",
        version=1,
        label="Esperar aprobación",
        category="control",
        risk_level="critical",
        capabilities=frozenset({NEEDS_APPROVAL}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_human_approval,
    )
    registry.register(
        "end",
        version=1,
        label="Fin",
        category="control",
        risk_level="info",
        capabilities=frozenset({VIRTUAL}),
        execute=_exec_end,
    )


_register_defaults()


def capability_permission(capability: str) -> str | None:
    return _CAPABILITY_PERMISSION.get(capability)

