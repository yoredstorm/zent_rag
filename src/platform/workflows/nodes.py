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
from src.platform.workflows.context import WorkflowContext
from src.platform.workflows.contributions import ContextWrite, NodeContribution
from src.platform.workflows.values import node_provenance

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
    partial: dict[str, Any] = field(default_factory=dict)
    contribution: NodeContribution | None = None  # escrituras al WorkflowContext


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
    context: WorkflowContext | None = None  # contexto compartido del run (Fase 1)

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
# Contribuciones de contexto (Fase 2) — builders puros y testables.
# ---------------------------------------------------------------------------
def _kb_query_contribution(
    rctx: NodeContext, *, query: str, chunks: list[dict], count: int
) -> NodeContribution:
    write = ContextWrite(
        section="knowledge",
        key=rctx.node_id,
        value={"query": query, "chunks": chunks[:5], "count": count},
        value_type="knowledge_answer",
        label=str(rctx.node.label or "Knowledge"),
        provenance=node_provenance(
            rctx.node_id,
            "kb_query",
            origin_kind="knowledge",
            workspace_id=rctx.workspace_id,
        ),
    )
    return NodeContribution(writes=(write,))


def _query_business_data_contribution(rctx: NodeContext, outcome: dict[str, Any]) -> NodeContribution:
    payload = {
        key: outcome[key]
        for key in ("answer", "rows", "columns", "query_id", "method", "metrics")
        if outcome.get(key) is not None
    }
    metrics = outcome.get("metrics")
    confidence = None
    if isinstance(metrics, dict) and isinstance(metrics.get("answerable"), bool):
        confidence = 1.0 if metrics["answerable"] else 0.0
    write = ContextWrite(
        section="data",
        key=rctx.node_id,
        value=payload,
        value_type="record_list" if outcome.get("rows") else "knowledge_answer",
        label=str(rctx.node.config.get("ask") or rctx.node.label or "Datos")[:80],
        provenance=node_provenance(
            rctx.node_id,
            "query_business_data",
            origin_kind="datasource",
            source_id=str(outcome.get("query_id") or "") or None,
            workspace_id=rctx.workspace_id,
            confidence=confidence,
        ),
    )
    return NodeContribution(writes=(write,))


def _api_call_contribution(
    rctx: NodeContext, *, url: str, status_code: int, ok: bool, extracted: Any
) -> NodeContribution:
    write = ContextWrite(
        section="data",
        key=rctx.node_id,
        value={"url": url, "status_code": status_code, "ok": ok, "extracted": extracted},
        value_type="record",
        label=str(rctx.node.label or "API"),
        provenance=node_provenance(
            rctx.node_id,
            "api_call",
            origin_kind="datasource",
            source_id=url[:200],
            workspace_id=rctx.workspace_id,
        ),
    )
    return NodeContribution(writes=(write,))


def _marketplace_contribution(
    rctx: NodeContext, *, action_id: str, data: dict[str, Any], evidence_id: Any
) -> NodeContribution:
    writes: list[ContextWrite] = [
        ContextWrite(
            section="data",
            key=rctx.node_id,
            value=data,
            value_type="record",
            label=action_id,
            provenance=node_provenance(
                rctx.node_id,
                "marketplace_action",
                origin_kind="datasource",
                source_id=action_id,
                workspace_id=rctx.workspace_id,
            ),
        )
    ]
    if evidence_id:
        evidence = str(evidence_id)
        writes.append(
            ContextWrite(
                section="evidence",
                value={"evidence_id": evidence, "label": action_id},
                value_type="evidence",
                provenance=node_provenance(
                    rctx.node_id,
                    "marketplace_action",
                    origin_kind="datasource",
                    source_id=action_id,
                    evidence_id=UUID(evidence) if _is_uuid(evidence) else None,
                    workspace_id=rctx.workspace_id,
                ),
            )
        )
    return NodeContribution(writes=tuple(writes))


def _business_node_contribution(
    rctx: NodeContext, *, title: str, outputs: dict[str, Any], evidence_ids: list[str]
) -> NodeContribution:
    action_outputs = {
        key: value for key, value in outputs.items() if str(key).startswith("action_")
    }
    writes: list[ContextWrite] = [
        ContextWrite(
            section="data",
            key=rctx.node_id,
            value={"title": title, "outputs": action_outputs},
            value_type="record",
            label=title[:80],
            provenance=node_provenance(
                rctx.node_id,
                "business_node",
                origin_kind="node",
                source_id=str(rctx.execution.correlation_id or "") or None,
                workspace_id=rctx.workspace_id,
            ),
        )
    ]
    for evidence in evidence_ids[:20]:
        writes.append(
            ContextWrite(
                section="evidence",
                value={"evidence_id": str(evidence), "label": title[:80]},
                value_type="evidence",
                provenance=node_provenance(
                    rctx.node_id,
                    "business_node",
                    origin_kind="datasource",
                    evidence_id=UUID(str(evidence)) if _is_uuid(str(evidence)) else None,
                    workspace_id=rctx.workspace_id,
                ),
            )
        )
    return NodeContribution(writes=tuple(writes))


def _business_result_contribution(rctx: NodeContext, *, result_id: str, title: str) -> NodeContribution:
    write = ContextWrite(
        section="artifacts",
        value={"id": result_id, "title": title, "kind": "business_result"},
        value_type="artifact",
        label=title[:80],
        provenance=node_provenance(
            rctx.node_id,
            "business_result",
            origin_kind="node",
            source_id=result_id,
            workspace_id=rctx.workspace_id,
        ),
    )
    return NodeContribution(writes=(write,))


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
    output = {
        "url": url,
        "status_code": resp.status_code,
        "ok": 200 <= resp.status_code < 300,
        "body": resp.text[:4000],
        "json": parsed_json,
        "extracted": extracted,
        "idempotency_key": rctx.idempotency_key,
    }
    return NodeOutcome(
        output=output,
        contribution=_api_call_contribution(
            rctx,
            url=url,
            status_code=int(output["status_code"]),
            ok=bool(output["ok"]),
            extracted=extracted,
        ),
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
            return NodeOutcome(
                output={"chunks": chunks, "count": len(chunks), "documents": chunks},
                contribution=_kb_query_contribution(
                    rctx, query=query, chunks=chunks, count=len(chunks)
                ),
            )
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
    return NodeOutcome(
        output={"documents": docs, "count": len(docs)},
        contribution=_kb_query_contribution(rctx, query=query, chunks=docs, count=len(docs)),
    )


def _resolve_dep(getter: Callable[[], Any]) -> Any:
    """Respeta `app.dependency_overrides`: el nodo se ejecuta fuera de FastAPI."""
    try:
        from src.api.main import app

        override = app.dependency_overrides.get(getter)
        if override is not None:
            return override()
    except Exception:  # noqa: BLE001
        pass
    return getter()


async def _exec_llm(rctx: NodeContext) -> NodeOutcome:
    cfg = rctx.node.config
    raw_prompt = str(cfg.get("prompt") or cfg.get("message") or "")
    prompt = str(_resolve_ref(raw_prompt, rctx) or "")
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
                        "AND (status IN ('configured', 'ready', 'deployed') OR is_active = true)"
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

        agent = await get_agent_repo().get_agent(rctx.organization_id, agent_id)
        if agent is None:
            raise LookupError()
        org_config = await _org_config_json(rctx.organization_id)
        context_payload = None
        context_truncated: list[str] = []
        reads = cfg.get("context_reads")
        if rctx.context is not None and isinstance(reads, list) and reads:
            from src.platform.workflows.context_assembler import WorkflowContextAssembler

            assembled = WorkflowContextAssembler().for_agent(
                rctx.context,
                reads=tuple(str(item) for item in reads if str(item).strip()),
            )
            context_payload = assembled.payload or None
            context_truncated = list(assembled.truncated)
        result = await _resolve_dep(get_agent_runtime).run(
            AgentRunRequest(
                agent=agent,
                message=prompt,
                user_id=rctx.execution.actor_id,
                role="admin",
                permissions=rctx.permissions,
                org_config=org_config,
                trace_id=rctx.execution.correlation_id,
                context=context_payload,
            )
        )
        output: dict[str, Any] = {
            "text": result.answer or result.message or "",
            "agent_id": str(agent_id),
            "model": result.model,
            "cost": result.cost,
        }
        if context_truncated:
            output["context_truncated"] = context_truncated
        return NodeOutcome(output=output, cost_ms=float(result.cost or 0.0))

    async def _echo() -> NodeOutcome:
        model = cfg.get("model", "gpt-4o-mini")
        return NodeOutcome(
            output={
                "text": f"[{model}] {prompt[:300]}",
                "model": model,
                "echo": True,
                "warning": "El nodo no tiene agente asignado: esto es un eco, no la respuesta de un agente.",
            }
        )

    # Nodo de lectura: se ejecuta de verdad incluso en dry-run (`simulate`).
    if "agents:execute" not in rctx.permissions:
        return _deny(NodeOutcome(), "agents:execute", "llm")
    if agent_id is None:
        return await _echo()
    if not prompt.strip():
        if not raw_prompt.strip():
            return NodeOutcome(
                error="El nodo no tiene prompt: usa {{trigger.message}} para pasar la pregunta del trigger."
            )
        return NodeOutcome(
            error=(
                f'El prompt "{raw_prompt[:80]}" quedó vacío: el trigger no trae esos datos. '
                'Escribe la pregunta en el dock de Probar o manda {"message": "..."} en el payload.'
            )
        )
    try:
        outcome = await _agent_run()
    except LookupError:
        return NodeOutcome(
            error=(
                f"El agente {agent_id} no está disponible para este workflow: "
                "no existe en la organización o está inactivo."
            )
        )
    except Exception as exc:  # noqa: BLE001
        return NodeOutcome(error=f"el agente falló: {str(exc)[:280]}")
    return _apply_output_schema(cfg, outcome, rctx)


_AGENT_DECISION_KEYS = ("decision", "risk", "recommendation", "confidence", "reason", "summary")


def _agent_output_contribution(data: dict[str, Any], rctx: NodeContext) -> NodeContribution | None:
    """Traduce un output estructurado del agente a contribuciones de contexto.

    El texto del agente nunca se convierte en claim aprobado: esto solo
    transporta decisiones/hallazgos estructurados del output schema (brief §16).
    """
    label = str(rctx.node.config.get("agent_name") or rctx.node.label or "") or None
    agent_source = str(rctx.node.config.get("agent_id") or "") or None
    raw_confidence = data.get("confidence")
    confidence = (
        float(raw_confidence)
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool)
        else None
    )
    provenance = node_provenance(
        rctx.node_id,
        "llm",
        origin_kind="agent",
        source_id=agent_source,
        workspace_id=rctx.workspace_id,
        confidence=confidence,
    )
    writes: list[ContextWrite] = []
    decision = {
        key: data[key]
        for key in _AGENT_DECISION_KEYS
        if key in data and data[key] is not None
    }
    if decision:
        writes.append(
            ContextWrite(
                section="decisions",
                key=rctx.node_id,
                value=decision,
                value_type="decision",
                label=label,
                provenance=provenance,
            )
        )
    findings = data.get("findings")
    if isinstance(findings, list):
        for item in findings[:20]:
            payload = item if isinstance(item, dict) else {"text": str(item)[:500]}
            writes.append(
                ContextWrite(
                    section="findings",
                    value=payload,
                    value_type="agent_finding",
                    label=label,
                    provenance=provenance,
                )
            )
    if not writes:
        return None
    return NodeContribution(writes=tuple(writes))


def _apply_output_schema(
    cfg: dict[str, Any],
    outcome: NodeOutcome,
    rctx: NodeContext | None = None,
) -> NodeOutcome:
    """Outputs estructurados opcionales (misión §16): si el nodo declara
    `output_schema` y el agente devolvió JSON válido, sus campos quedan
    disponibles al Data Picker en la raíz del output."""
    schema = cfg.get("output_schema")
    if not isinstance(schema, dict) or not schema or outcome.error:
        return outcome
    text = str((outcome.output or {}).get("text") or "")
    if not text.strip():
        return outcome
    from src.platform.deployments.output_schema import validate_json_answer

    data, errors = validate_json_answer(text, schema)
    if isinstance(data, dict) and not errors:
        outcome.output.update(data)
        outcome.output["structured"] = True
        outcome.output.pop("schema_errors", None)
        if rctx is not None:
            contribution = _agent_output_contribution(data, rctx)
            if contribution is not None:
                outcome.contribution = contribution
    else:
        outcome.output["structured"] = False
        outcome.output["schema_errors"] = errors[:5] or ["La respuesta no es JSON válido"]
    return outcome


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
    from src.platform.workflows.conditions import (
        describe_condition_tree,
        evaluate_condition_tree,
        normalize_rules,
    )
    from src.platform.workflows.engine import _eval_condition as _eval

    rules = normalize_rules(cfg)
    if rules is not None and rules.get("kind") == "group":
        result = evaluate_condition_tree(
            rules, lambda field: _resolve_condition_field(field, rctx), _eval
        )
        return NodeOutcome(output={"condition": describe_condition_tree(rules), "result": result})

    # Formato legacy / condición única: mismo shape de salida que siempre.
    field = str(cfg.get("field", ""))
    operator = str(cfg.get("operator", "=="))
    value = _resolve_ref(cfg.get("value", ""), rctx)
    actual = _resolve_condition_field(field, rctx)
    result = _eval(actual, operator, value)
    return NodeOutcome(output={"condition": f"{field} {operator} {value}", "result": result})


def _resolve_condition_field(field: str, rctx: NodeContext) -> Any:
    """Resuelve el campo de una condición: referencias estables, trigger, legacy
    steps.N y literales. Antes, `{{nodes...}}` no se resolvía y comparaba el
    literal: el Condition Builder depende de esta resolución."""
    field = str(field or "")
    if field.startswith("{{") and field.endswith("}}"):
        resolved = _resolve_ref(field, rctx)
        return None if isinstance(resolved, str) and "{{" in resolved else resolved
    if field.startswith("trigger."):
        actual = _trigger_field(field, rctx.trigger)
        return "" if actual is None else actual
    if field.startswith("nodes."):
        resolved = _resolve_ref("{{" + field + "}}", rctx)
        return None if "{{" in str(resolved) else resolved
    if field.startswith("steps."):
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
        return actual
    return str(field)


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
    recipients_raw = cfg.get("recipients")
    recipients = (
        [r for r in recipients_raw if isinstance(r, dict)] if isinstance(recipients_raw, list) else []
    )
    if channel not in ("in_app", "email", "webhook", "all"):
        label = {"slack": "Slack", "teams": "Microsoft Teams", "whatsapp": "WhatsApp"}.get(channel, channel)
        return NodeOutcome(error=f"Necesitas conectar {label} para usar esta acción.")

    wanted = None if channel == "all" else {str(channel)}
    data = dict(cfg.get("data") or {}) if isinstance(cfg.get("data"), dict) else {}
    data = _resolve_ref(data, rctx)
    if isinstance(data, dict):
        data.setdefault("workflow_id", str(rctx.execution.workflow_id))
        data.setdefault("run_id", str(rctx.execution.run_id))
        if recipients:
            data.setdefault(
                "recipients",
                [str(r.get("label") or r.get("value") or "") for r in recipients if r.get("label") or r.get("value")],
            )
    title = str(_resolve_ref(cfg.get("title") or "Workflow", rctx) or "Workflow")
    message = str(_resolve_ref(cfg.get("message") or "Notificación de workflow", rctx) or "")

    # Correo con destinatarios explícitos (Persona/Equipo/Correo).
    if channel == "email" and recipients:
        from src.platform.workflows.notifications import resolve_notify_recipient_emails

        emails = await resolve_notify_recipient_emails(rctx.organization_id, recipients)
        if rctx.simulate:
            return NodeOutcome(
                simulated=True,
                planned={"kind": "notification", "channel": "email", "title": title, "recipients": emails},
                output={"simulated": True, "channel": "email", "recipients": emails},
            )
        if not emails:
            return NodeOutcome(error="No encontramos correos para los destinatarios elegidos.")
        from src.platform.customer_success.customer_success import send_email

        delivered = 0
        for to in emails:
            try:
                if await send_email(to, title, f"<p>{message}</p>"):
                    delivered += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("notify recipient failed", to=to, error=str(exc)[:150])
        return NodeOutcome(
            output={
                "sent": delivered > 0,
                "channel": "email",
                "recipients": emails,
                "delivered": delivered,
                "count": len(emails),
            }
        )

    # Webhook con URLs explícitas.
    if channel == "webhook" and recipients:
        urls = [str(r.get("value")) for r in recipients if r.get("kind") == "webhook" and r.get("value")]
        if urls:
            if rctx.simulate:
                return NodeOutcome(
                    simulated=True,
                    planned={"kind": "notification", "channel": "webhook", "title": title, "recipients": urls},
                    output={"simulated": True, "channel": "webhook", "recipients": urls},
                )
            from src.platform.workflows import engine as wf_engine

            delivered = 0
            for url in urls:
                try:
                    async with wf_engine.httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(url, json={"title": title, "message": message, "data": data})
                    if 200 <= resp.status_code < 300:
                        delivered += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning("notify webhook failed", url=url, error=str(exc)[:150])
            return NodeOutcome(
                output={"sent": delivered > 0, "channel": "webhook", "deliveries": delivered, "count": len(urls)}
            )

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
    return NodeOutcome(
        output=outcome,
        contribution=_query_business_data_contribution(rctx, outcome),
    )


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
    output = {
        **outcome.data,
        "evidence_id": str(outcome.evidence_id) if outcome.evidence_id else None,
        "cached": outcome.cached,
        "cost": outcome.customer_cost,
        "latency_ms": round(outcome.latency_ms, 1),
        "renderer": str(cfg.get("renderer") or "") or None,
    }
    return NodeOutcome(
        output=output,
        cost_ms=outcome.customer_cost,
        contribution=_marketplace_contribution(
            rctx,
            action_id=action_id,
            data=dict(outcome.data or {}),
            evidence_id=outcome.evidence_id,
        ),
    )


def _is_uuid(value: str) -> bool:
    import re

    return bool(re.match(r"^[0-9a-fA-F-]{36}$", value))


async def _exec_business_node(rctx: NodeContext) -> NodeOutcome:
    """Nodo de alto nivel de un Business Pack: valida, llama capacidades,
    normaliza, crea evidencia y produce un BusinessResult. Oculta el grafo
    interno; la UI puede "expandir" para revelarlo."""
    from src.platform.marketplace import runtime as mkt

    cfg = rctx.node.config
    title = str(cfg.get("title") or "Operación de negocio")
    actions = cfg.get("actions") or []
    if not isinstance(actions, list):
        return NodeOutcome(error="business_node requiere actions[]")

    outputs: dict[str, object] = {"title": title}
    evidence_ids: list[str] = []
    total_cost = 0.0
    planned: list[dict] = []

    for idx, act in enumerate(actions):
        if not isinstance(act, dict):
            continue
        action_id = str(act.get("action_id") or "")
        install_id = str(act.get("install_id") or "")
        if not action_id:
            return NodeOutcome(error=f"action {idx} sin action_id")
        raw_inputs = act.get("inputs") or {}
        inputs = {
            str(k): _resolve_ref(v, rctx) for k, v in raw_inputs.items()
        }
        if rctx.simulate:
            from src.platform.marketplace.runtime import _estimate_cost

            price = _estimate_cost((act.get("cost_model") or {"cost_model": {"model": "PER_CALL"}}))
            planned.append({"action_id": action_id, "estimated_cost": price})
            outputs[f"action_{idx}"] = {"simulated": True, "action_id": action_id}
            continue
        outcome = await mkt.execute_action(
            rctx.organization_id,
            UUID(install_id) if _is_uuid(install_id) else None,
            action_id,
            inputs,
            workspace_id=rctx.workspace_id,
            purpose=str(act.get("purpose") or "") or None,
            workflow_id=rctx.execution.workflow_id,
            run_id=rctx.execution.run_id,
            actor_id=rctx.execution.actor_id,
            actor_type="workflow",
            source="workflow",
        )
        if not outcome.ok:
            return NodeOutcome(
                error=f"{outcome.error_code}: {outcome.error_message}",
                partial=dict(outputs),
            )
        normalized: dict[str, object] = dict(outcome.data or {})
        output_map = act.get("output_map") or {}
        if isinstance(output_map, dict):
            mapped: dict[str, object] = {}
            for field, path in output_map.items():
                cur: Any = outcome.data
                for part in str(path).split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        cur = None
                        break
                if cur is not None:
                    mapped[str(field)] = cur
            normalized = mapped or normalized
        outputs[f"action_{idx}"] = {
            **normalized,
            "evidence_id": str(outcome.evidence_id) if outcome.evidence_id else None,
            "cost": outcome.customer_cost,
        }
        if outcome.evidence_id:
            evidence_ids.append(str(outcome.evidence_id))
        total_cost += outcome.customer_cost or 0.0

    if rctx.simulate:
        return NodeOutcome(
            simulated=True,
            planned={
                "kind": "business",
                "title": title,
                "actions": planned,
                "has_business_result": bool(cfg.get("business_result")),
            },
            output=outputs,
        )

    br = cfg.get("business_result") or {}
    if br:
        from src.platform.intelligence.results import BusinessResult, BusinessResultError, save_result

        result = BusinessResult(
            title=str(_resolve_ref(br.get("title") or title, rctx) or title),
            summary=str(_resolve_ref(br.get("summary") or "", rctx) or "") or None,
            section=str(br.get("section") or "reports"),
            importance=str(br.get("importance") or "INFO"),
            metrics=_resolve_ref(br.get("metrics") or {}, rctx),
            insights=_resolve_ref(br.get("insights") or [], rctx),
            entities=_resolve_ref(br.get("entities") or [], rctx),
            workflow_id=rctx.execution.workflow_id,
            workflow_run_id=rctx.execution.run_id,
            agent_run_id=rctx.execution.actor_id,
            correlation_id=rctx.execution.correlation_id,
            source="workflow",
        )
        try:
            saved = await save_result(rctx.organization_id, result, workspace_id=rctx.workspace_id)
            outputs["result_id"] = saved["result_id"]
        except BusinessResultError as exc:
            return NodeOutcome(error=str(exc), partial=dict(outputs))

    outputs["evidence_ids"] = evidence_ids
    outputs["total_cost"] = total_cost
    return NodeOutcome(
        output=outputs,
        cost_ms=total_cost,
        contribution=_business_node_contribution(
            rctx, title=title, outputs=outputs, evidence_ids=evidence_ids
        ),
    )


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
    result_id = str(saved["result_id"])
    return NodeOutcome(
        output={"result_id": result_id, "importance": saved["importance"]},
        contribution=_business_result_contribution(rctx, result_id=result_id, title=title),
    )


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

    # BUSINESS / PACKS (Phase 33B) — nodo compuesto de alto nivel.
    registry.register(
        "business_node",
        version=1,
        label="Operación de negocio",
        category="business",
        risk_level="normal",
        capabilities=frozenset({CALLS_EXTERNAL, WRITE_DB}),
        inputs={"in": {"type": "json"}},
        outputs={"out": {"type": "json"}},
        execute=_exec_business_node,
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

