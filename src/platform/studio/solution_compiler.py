# =============================================================================
# Solution Compiler — misión → rol/agente/workflow(s) → recursos reales.
#
# Capa de composición sobre las autoridades existentes: RoleProfile, agentes,
# WorkflowGraph v2, capability bindings, knowledge bases y release policy.
# No crea un segundo runtime, planner, registro de agentes ni tienda.
# =============================================================================
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.studio.contracts import RoleProfileV1, SolutionV1
from src.platform.studio.roles import create_role, link_agent_role, list_roles
from src.platform.studio.solutions import (
    SolutionConflict,
    create_solution,
    list_solutions,
)
from src.platform.studio.templates import (
    match_role_template,
    role_template,
    workflow_proposal,
)
from src.platform.workflows.bindings import list_bindings
from src.platform.workflows.plan_compiler import load_capabilities

logger = get_logger(__name__)

COMPILATION_SCHEMA = "zent.solution.compilation/v1"
MATERIALIZATION_SCHEMA = "zent.solution.materialization/v1"
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_HARD_CAPABILITIES = {
    "sales_advisor": ["catalog.products.search"],
    "auditor": [],
}
_SOURCE_ROLES = {"auditor", "support_agent", "tutor"}
_DURABLE_ROLES = {"mentor", "tutor", "sales_advisor"}

_MATERIALIZATION_DDL = """
CREATE TABLE IF NOT EXISTS studio_solution_materializations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID,
    solution_id UUID REFERENCES studio_solutions(id) ON DELETE SET NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    compilation_hash VARCHAR(64) NOT NULL,
    template_id VARCHAR(80) NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL DEFAULT 'IN_PROGRESS',
    compilation JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifacts JSONB NOT NULL DEFAULT '{}'::jsonb,
    requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    error VARCHAR(400),
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, idempotency_key)
)
"""

_ENSURED = False


class CompilationError(ValueError):
    pass


class MaterializationConflict(CompilationError):
    pass


async def ensure_materialization_tables() -> None:
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        await session.execute(text(_MATERIALIZATION_DDL))
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_solution_materializations_solution "
                "ON studio_solution_materializations(organization_id, solution_id, updated_at DESC)"
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_solution_materializations_hash "
                "ON studio_solution_materializations(organization_id, compilation_hash)"
            )
        )
        await session.commit()
        _ENSURED = True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _slug(value: str, limit: int = 60) -> str:
    cleaned = _SLUG_RE.sub("_", str(value or "").lower()).strip("_")
    return cleaned[:limit] or "solucion"


def _brief_text(brief: str | dict[str, Any]) -> str:
    if isinstance(brief, dict):
        return str(brief.get("text") or brief.get("mission") or brief.get("prompt") or "")
    return str(brief or "")


def _fingerprint(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _node(
    node_id: str,
    node_type: str,
    config: dict[str, Any],
    *,
    label: str | None = None,
    output_ports: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    node = {
        "id": node_id,
        "type": node_type,
        "label": label or node_type,
        "config": config,
        "version": 1,
        "metadata": {},
        "position": {},
        "timeout_ms": 60_000,
        "input_ports": [{"name": "in", "type": "json", "required": True}],
        "output_ports": output_ports or [{"name": "out", "type": "json"}],
        "retry_policy": {"max_attempts": 1},
        "error_policy": "fail",
    }
    return node


def _edge(edge_id: str, from_node: str, to_node: str, *, from_port: str = "out") -> dict[str, Any]:
    return {
        "id": edge_id,
        "from_node": from_node,
        "from_port": from_port,
        "to_node": to_node,
        "to_port": "in",
        "condition": None,
    }


def _graph(nodes: list[dict], edges: list[dict], *, entrypoints: list[str], solution_ref: str) -> dict:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {"solution_ref": solution_ref},
    }


def _llm_prompt(role_name: str, mission: str) -> str:
    return (
        f"Eres {role_name}. {mission} "
        "Responde en español, con pasos concretos y sin inventar datos. "
        "Mensaje del usuario: {{trigger.message}}"
    )


def _build_graph(
    template_id: str,
    *,
    agent_id: str | None,
    agent_ref: str,
    sources: list[str],
    solution_ref: str,
) -> dict[str, Any]:
    role = role_template(template_id)
    role_name = role.name if role else template_id
    mission = role.mission if role else "Ayuda al usuario."
    llm_config = {"prompt": _llm_prompt(role_name, mission)}
    if agent_id:
        llm_config["agent_id"] = agent_id
    else:
        llm_config["agent_ref"] = agent_ref

    if template_id == "sales_advisor":
        search_cfg = {"capability": "catalog.products.search", "inputs": {"query": "{{trigger.message}}"}}
        return _graph(
            [
                _node("t", "trigger_webhook", {}),
                _node("search", "capability_call", search_cfg, label="Buscar catálogo"),
                _node("ask", "llm", llm_config, label="Asesor"),
                _node(
                    "approval",
                    "human_approval",
                    {
                        "action": "Confirmar la compra",
                        "summary": "El cliente eligió productos",
                    },
                ),
                _node(
                    "notify",
                    "notify",
                    {
                        "channel": "in_app",
                        "title": "Venta preparada",
                        "message": "Revisa el pedido antes de cobrar.",
                    },
                ),
                _node("end", "end", {}),
            ],
            [
                _edge("e1", "t", "search"),
                _edge("e2", "search", "ask"),
                _edge("e3", "ask", "approval"),
                _edge("e4", "approval", "notify"),
                _edge("e5", "notify", "end"),
            ],
            entrypoints=["t"],
            solution_ref=solution_ref,
        )
    if template_id == "auditor":
        source_a = sources[0] if sources else ""
        source_b = sources[1] if len(sources) > 1 else ""
        return _graph(
            [
                _node("t", "trigger_webhook", {}),
                _node(
                    "src_a",
                    "kb_query",
                    {
                        "knowledge_base_id": source_a,
                        "query": "{{trigger.message}}",
                        "limit": 8,
                    },
                    label="Fuente A",
                ),
                _node(
                    "src_b",
                    "kb_query",
                    {
                        "knowledge_base_id": source_b,
                        "query": "{{trigger.message}}",
                        "limit": 8,
                    },
                    label="Fuente B",
                ),
                _node("ask", "llm", llm_config, label="Auditor"),
                _node(
                    "approval",
                    "human_approval",
                    {
                        "action": "Aprobar el reporte de auditoría",
                        "summary": "Revisión de diferencias",
                    },
                ),
                _node("end", "end", {}),
            ],
            [
                _edge("e1", "t", "src_a"),
                _edge("e2", "src_a", "src_b"),
                _edge("e3", "src_b", "ask"),
                _edge("e4", "ask", "approval"),
                _edge("e5", "approval", "end"),
            ],
            entrypoints=["t"],
            solution_ref=solution_ref,
        )
    if template_id in ("mentor", "tutor"):
        wait_cfg = {"preset": "message"}
        return _graph(
            [
                _node("t", "trigger_webhook", {}),
                _node("ask", "llm", llm_config, label=role_name),
                _node(
                    "progress",
                    "state_append",
                    {
                        "path": "progress",
                        "value": {"message": "{{trigger.message}}"},
                    },
                    label="Guardar progreso",
                ),
                _node("wait", "wait_event", wait_cfg, label="Esperar al estudiante"),
                _node("follow", "llm", llm_config, label="Continuar"),
                _node("end", "end", {}),
            ],
            [
                _edge("e1", "t", "ask"),
                _edge("e2", "ask", "progress"),
                _edge("e3", "progress", "wait"),
                _edge("e4", "wait", "follow"),
                _edge("e5", "follow", "end"),
            ],
            entrypoints=["t"],
            solution_ref=solution_ref,
        )
    if template_id == "support_agent":
        return _graph(
            [
                _node("t", "trigger_webhook", {}),
                _node("ask", "llm", llm_config, label=role_name),
                _node(
                    "notify",
                    "notify",
                    {
                        "channel": "in_app",
                        "title": "Soporte",
                        "message": "Caso atendido o escalado.",
                    },
                ),
                _node("end", "end", {}),
            ],
            [_edge("e1", "t", "ask"), _edge("e2", "ask", "notify"), _edge("e3", "notify", "end")],
            entrypoints=["t"],
            solution_ref=solution_ref,
        )
    return _graph(
        [
            _node("t", "trigger_webhook", {}),
            _node("ask", "llm", llm_config, label=role_name),
            _node("end", "end", {}),
        ],
        [_edge("e1", "t", "ask"), _edge("e2", "ask", "end")],
        entrypoints=["t"],
        solution_ref=solution_ref,
    )


def _scenarios(template_id: str) -> list[dict[str, Any]]:
    common = {"max_segments": 10, "budget_ms": 60_000}
    return {
        "mentor": [
            {"scenario_id": "primer_dia", "messages": ["Quiero aprender Python"], "expect_waiting": True, **common},
            {"scenario_id": "dia_siguiente", "messages": ["Sigo con ejercicios"], "expect_waiting": True, **common},
        ],
        "tutor": [
            {"scenario_id": "respuesta_incorrecta", "messages": ["Creo que 2+2 es 5"], **common},
        ],
        "sales_advisor": [
            {
                "scenario_id": "arroz_1kg",
                "messages": ["Quiero 1 kg de arroz"],
                "allowed_effects": ["catalog.products.search"],
                **common,
            },
            {
                "scenario_id": "cambio_2kg",
                "messages": ["Ahora quiero 2 kg"],
                "allowed_effects": ["catalog.products.search"],
                **common,
            },
        ],
        "auditor": [
            {"scenario_id": "dos_fuentes", "messages": ["Compara las dos fuentes"], "expect_approval": True, **common},
        ],
        "support_agent": [
            {"scenario_id": "sin_respuesta", "messages": ["No encuentro mi pedido"], **common},
        ],
        "wellness_companion": [
            {
                "scenario_id": "apoyo",
                "messages": ["Necesito apoyo"],
                "forbidden_effects": ["clinical.diagnose"],
                **common,
            },
        ],
    }.get(template_id, [{"scenario_id": "default", "messages": ["Hola"], **common}])


async def _resolve_sources(
    capabilities: dict[str, Any], requested: list[str], *, minimum: int
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    index = capabilities.get("knowledge_bases") or {}
    candidates: list[str] = []
    blockers: list[dict[str, str]] = []
    for ref in requested:
        found = index.get(ref) or index.get(str(ref).lower())
        if not found:
            blockers.append(
                {
                    "code": "source_missing",
                    "message": f"La fuente {ref} no existe o no está autorizada.",
                    "action": "Selecciona una fuente real del tenant.",
                }
            )
        elif found not in candidates:
            candidates.append(str(found))
    available = sorted({str(value) for value in index.values()})
    if not requested:
        candidates = available[:max(minimum, 1)]
    if len(candidates) < minimum:
        blockers.append(
            {
                "code": "sources_required",
                "message": f"Esta solución necesita al menos {minimum} fuentes autorizadas.",
                "action": "Conecta o selecciona las fuentes en Knowledge.",
            }
        )
    return candidates, available, blockers


def _scope_refs_from_graph(graph: dict[str, Any] | None) -> list[str]:
    refs: set[str] = set()
    for node in (graph or {}).get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "")
        if node_type not in {
            "capability_call",
            "marketplace_action",
            "api_call",
            "business_node",
        }:
            continue
        config = node.get("config") or {}
        ref = (
            config.get("capability")
            or config.get("capability_ref")
            or config.get("action_id")
            or node_type
        )
        if ref:
            refs.add(str(ref))
    return sorted(refs)


def _bind_agent_to_graph(
    graph: dict[str, Any], *, agent_id: str, agent_ref: str
) -> dict[str, Any]:
    data = copy.deepcopy(graph)
    for node in data.get("nodes") or []:
        if not isinstance(node, dict) or str(node.get("type")) != "llm":
            continue
        config = node.setdefault("config", {})
        if not str(config.get("agent_id") or "").strip():
            config["agent_id"] = agent_id
        config.pop("agent_ref", None)
    return data


class _UnavailablePlannerProvider:
    """Fuerza el fallback determinista del Architect cuando no hay proveedor."""

    async def generate(self, **_kwargs):
        raise RuntimeError("planner provider unavailable in this environment")


_EXTERNAL_TASK_MARKERS = (
    "erp",
    "pago",
    "payment",
    "factura",
    "inventario",
    "stock",
    "sql",
    "base de datos",
    "crm",
    "correo",
    "email",
    "stripe",
    "checkout",
)


def _conservative_graph(
    text_brief: str, *, agent_ref: str, agent_id: str | None, solution_ref: str
) -> dict[str, Any]:
    """Grafo mínimo sin conectores inventados, para misiones sin integración."""
    llm_config: dict[str, Any] = {
        "prompt": (
            f"Analiza la solicitud y prepara una respuesta para: {text_brief[:500]}. "
            "No inventes datos. Mensaje: {{trigger.message}}"
        )
    }
    if agent_id:
        llm_config["agent_id"] = agent_id
    else:
        llm_config["agent_ref"] = agent_ref
    nodes = [
        _node("t", "trigger_webhook", {}),
        _node("analyze", "llm", llm_config, label="Analizar"),
        _node(
            "approval",
            "human_approval",
            {
                "action": "Revisar la respuesta propuesta",
                "summary": text_brief[:240],
            },
        ),
        _node(
            "notify",
            "notify",
            {
                "channel": "in_app",
                "title": "Misión compuesta",
                "message": "Respuesta revisada y lista.",
            },
        ),
        _node("end", "end", {}),
    ]
    edges = [
        _edge("e1", "t", "analyze"),
        _edge("e2", "analyze", "approval"),
        _edge("e3", "approval", "notify"),
        _edge("e4", "notify", "end"),
    ]
    return _graph(
        nodes,
        edges,
        entrypoints=["t"],
        solution_ref=solution_ref,
    )


async def _compile_composed(
    organization_id: UUID,
    *,
    text_brief: str,
    workspace_id: UUID | None,
    source_refs: list[str] | None,
    existing_agent_id: str | None,
    options: dict[str, Any] | None,
    mode: str,
    forced_agent_id: str | None = None,
) -> dict[str, Any]:
    """Composición real reutilizando plan_workflow + Architect validator."""
    from src.platform.studio.mission_contracts import (
        MissionSpec,
        validate_materialization_graph,
    )
    from src.platform.workflows.architect import plan_workflow
    from src.platform.workflows.ir import WorkflowGraph, validate_graph

    mission = MissionSpec(
        brief=text_brief,
        mode=mode if mode in ("auto", "template", "compose", "hybrid") else "auto",
        language=str((options or {}).get("language") or "es"),
        capabilities=list(source_refs or []),
    )
    architect = await plan_workflow(
        organization_id,
        text_brief,
        workspace_id=workspace_id,
        provider=_UnavailablePlannerProvider(),
        preferred_agent_id=existing_agent_id,
    )
    graph = architect.get("graph")
    validated = validate_materialization_graph(graph)
    if graph is not None:
        try:
            validate_graph(WorkflowGraph.from_dict(graph))
        except Exception as exc:  # noqa: BLE001
            graph = None
            validated = validate_materialization_graph(None)
            validated.errors.append(str(exc)[:200])

    capabilities = await load_capabilities(organization_id, workspace_id)
    bindings = (await list_bindings(organization_id, workspace_id)).get("bindings") or []
    bound_refs = {str(item.get("capability_ref")) for item in bindings}
    action_refs = set((capabilities.get("actions") or {}).keys())
    refs = _scope_refs_from_graph(graph)
    requirements: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for ref in refs:
        available = ref in bound_refs or ref in action_refs
        requirements.append(
            {
                "capability_ref": ref,
                "status": "available" if available else "missing",
                "required": True,
            }
        )
        if not available:
            blockers.append(
                {
                    "code": "capability_missing",
                    "message": f"La capacidad {ref} no está instalada ni tiene binding.",
                    "action": "Instala o configura el binding real en Marketplace/Integraciones.",
                }
            )
    for item in architect.get("requirements") or []:
        if isinstance(item, dict):
            blockers.append(
                {
                    "code": str(item.get("code") or "architect_requirement"),
                    "message": str(item.get("message") or item.get("requirement") or "Requisito pendiente."),
                    "action": str(item.get("action") or "Resuelve el requisito y recompila."),
                }
            )
    for item in architect.get("blockers") or []:
        if isinstance(item, dict):
            code = str(item.get("code") or "")
            if code and not any(existing.get("code") == code for existing in blockers):
                blockers.append(
                    {
                        "code": code,
                        "message": str(item.get("message") or code),
                        "action": str(item.get("action") or "Revisa el bloqueo."),
                    }
                )
    if graph is None and not blockers:
        blockers.append(
            {
                "code": "composition_incomplete",
                "message": "El Architect no pudo producir un grafo ejecutable para esta misión.",
                "action": "Añade datos, capacidades o agentes; revisa las clarificaciones.",
            }
        )

    agent_selection = "create"
    existing_agent: dict[str, Any] | None = None
    if existing_agent_id:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, name, is_active, workspace_id FROM agents "
                        "WHERE id = :aid AND organization_id = :oid"
                    ),
                    {"aid": existing_agent_id, "oid": organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None or not bool(row.is_active):
            blockers.append(
                {
                    "code": "agent_unavailable",
                    "message": "El agente seleccionado no existe o está inactivo.",
                    "action": "Elige un agente activo o deja que ZENT cree uno.",
                }
            )
        elif workspace_id and row.workspace_id and UUID(str(row.workspace_id)) != workspace_id:
            blockers.append(
                {
                    "code": "workspace_mismatch",
                    "message": "El agente pertenece a otro workspace.",
                    "action": "Elige un agente de este workspace.",
                }
            )
        else:
            agent_selection = "reuse"
            existing_agent = {"id": str(row.id), "name": row.name}

    digest = _fingerprint({"brief": text_brief, "mode": mode, "workspace": str(workspace_id or "")})
    composed_slug = f"composed_{_slug(text_brief, 40)}_{digest[:8]}"[:80]
    role_id = f"composed_{_slug(text_brief, 30)}_{digest[:8]}"[:80]
    role = RoleProfileV1(
        role_id=role_id,
        name=text_brief[:150],
        description=text_brief[:1200],
        mission=text_brief[:1200],
        allowed_capabilities=refs,
        allowed_tools=[],
        autonomy_level="propose_actions",
        risk_class="medium",
        expected_outcomes=[
            {"name": "resultado de la misión", "metric": "completion", "target": "> 0"}
        ],
        safety={"no_automatic_irreversible_action": True},
    )
    agent_ref = f"composed_agent_{digest[:8]}"
    workflow_ref = f"composed_flow_{digest[:8]}"
    solution_slug = composed_slug
    fallback_composition = False
    if graph is None and not any(
        marker in text_brief.lower() for marker in _EXTERNAL_TASK_MARKERS
    ):
        graph = _conservative_graph(
            text_brief,
            agent_ref=agent_ref,
            agent_id=(existing_agent or {}).get("id") or forced_agent_id,
            solution_ref=solution_slug,
        )
        validated = validate_materialization_graph(graph)
        blockers = [
            item
            for item in blockers
            if item.get("code")
            not in ("missing.managed_db", "missing.agents", "composition_incomplete")
        ]
        fallback_composition = True
    blueprint = {
        "schema": "zent.solution/v1",
        "solution_id": solution_slug,
        "version": "1.0.0",
        "status": "draft",
        "name": text_brief[:150],
        "description": text_brief[:1200],
        "roles": [{"role_ref": role.role_id, "version": role.version, "required": True}],
        "agents": [
            {
                "agent_ref": agent_ref,
                "role_ref": role.role_id,
                "name": (existing_agent or {}).get("name") or f"Agente compuesto {digest[:6]}",
                "workflow_refs": [workflow_ref],
                "capability_refs": refs,
            }
        ],
        "workflows": [
            {
                "workflow_ref": workflow_ref,
                "name": f"Proceso compuesto: {text_brief[:80]}",
                "role_refs": [role.role_id],
                "agent_refs": [agent_ref],
                "capability_refs": refs,
                "trigger": {"type": "webhook"},
                "requirements": refs,
            }
        ],
        "capabilities": [
            {
                "capability_ref": ref,
                "required": True,
                "purpose": "Operación compuesta por el Architect",
            }
            for ref in refs
        ],
        "knowledge": [],
        "channels": ["webhook"],
        "requirements": [
            "Revisar el plan semántico y las clarificaciones",
            "Configurar capacidades y bindings reales",
            "Certificar antes de publicar",
        ],
        "installation": [
            {
                "order": 1,
                "action": "create_or_reuse_role",
                "module": "roles",
                "description": "Crear o reutilizar el rol compuesto.",
                "required": True,
            },
            {
                "order": 2,
                "action": "create_or_link_agent",
                "module": "agents",
                "description": "Crear o vincular un agente activo.",
                "required": True,
            },
            {
                "order": 3,
                "action": "create_draft_workflow",
                "module": "workflows",
                "description": "Persistir el grafo compilado como borrador.",
                "required": True,
            },
        ],
        "expected_outcomes": [
            item.model_dump(mode="json") for item in role.expected_outcomes
        ],
        "risk_class": role.risk_class,
        "compliance_tags": role.compliance_tags,
        "locales": role.locales,
    }
    try:
        SolutionV1.model_validate(blueprint)
    except Exception as exc:  # noqa: BLE001
        raise CompilationError(f"blueprint compuesto inválido: {str(exc)[:300]}") from exc

    status = "READY_TO_MATERIALIZE" if graph is not None and not blockers else "NEEDS_CONFIGURATION"
    return {
        "schema": COMPILATION_SCHEMA,
        "compilation_hash": digest,
        "status": status,
        "can_materialize": status == "READY_TO_MATERIALIZE",
        "mode": "compose",
        "template_id": "composed",
        "mission": mission.model_dump(mode="json", by_alias=True),
        "brief": {
            "text": text_brief,
            "language": mission.language,
            "audience": role.audience,
            "outcomes": [item.name for item in role.expected_outcomes],
            "risk_class": role.risk_class,
            "memory": role.memory_policy.model_dump(mode="json"),
            "autonomy": role.autonomy_level,
        },
        "role": role.model_dump(by_alias=True),
        "blueprint": blueprint,
        "plan": {
            "role": {"logical_ref": role.role_id, "name": role.name, "action": "create"},
            "agent": {
                "logical_ref": agent_ref,
                "name": (existing_agent or {}).get("name") or f"Agente compuesto {digest[:6]}",
                "action": agent_selection,
                "existing_agent_id": (existing_agent or {}).get("id"),
            },
            "workflow": {
                "logical_ref": workflow_ref,
                "name": f"Proceso compuesto: {text_brief[:80]}",
                "action": "create_draft",
                "will_create": status == "READY_TO_MATERIALIZE",
            },
            "sources": [],
            "bindings": sorted(bound_refs),
        },
        "requirements": requirements,
        "blockers": blockers,
        "available_sources": sorted((capabilities.get("knowledge_bases") or {}).values()),
        "scenarios": [
            {
                "scenario_id": "composed_default",
                "messages": [text_brief[:200]],
                "max_segments": 10,
                "budget_ms": 60_000,
            }
        ],
        "graph": graph,
        "graph_preview": graph,
        "architect": {
            "state": architect.get("state"),
            "source": architect.get("source"),
            "plan_hash": architect.get("plan_hash"),
            "clarifications": architect.get("clarifications") or [],
            "readiness": architect.get("readiness"),
            "fallback_composition": fallback_composition,
            "validated": validated.model_dump(mode="json", by_alias=True),
        },
        "next_actions": [
            "Revisar el plan y las clarificaciones",
            "Resolver capacidades/bindings pendientes",
            "Materializar el borrador",
            "Probar y certificar antes de publicar",
        ],
    }


async def compile_solution(
    organization_id: UUID,
    *,
    brief: str | dict[str, Any],
    workspace_id: UUID | None = None,
    template_id: str | None = None,
    source_refs: list[str] | None = None,
    existing_agent_id: str | None = None,
    options: dict[str, Any] | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """Compila sin escribir. Devuelve blueprint portable + plan + bloqueos."""
    text_brief = _brief_text(brief).strip()
    if not text_brief:
        raise CompilationError("La misión no puede estar vacía.")
    normalized_mode = str(mode or "auto").strip().lower()
    if normalized_mode not in ("auto", "template", "compose", "hybrid"):
        raise CompilationError(f"mode inválido: {mode}")
    matched_template, match_score = match_role_template(text_brief)
    if normalized_mode == "compose" or (
        normalized_mode in ("auto", "hybrid") and match_score <= 0
    ):
        return await _compile_composed(
            organization_id,
            text_brief=text_brief,
            workspace_id=workspace_id,
            source_refs=source_refs,
            existing_agent_id=existing_agent_id,
            options=options,
            mode=normalized_mode,
        )
    chosen_template = str(template_id or "").strip()
    if not chosen_template:
        chosen_template = matched_template
    role = role_template(chosen_template)
    if role is None:
        raise CompilationError(f"Plantilla de rol desconocida: {chosen_template}")
    proposal = workflow_proposal(chosen_template) or {}
    capabilities = await load_capabilities(organization_id, workspace_id)
    bindings = (await list_bindings(organization_id, workspace_id)).get("bindings") or []
    bound_refs = {str(item.get("capability_ref")) for item in bindings}
    action_refs = set((capabilities.get("actions") or {}).keys())

    minimum_sources = 2 if chosen_template == "auditor" else 0
    sources, available_sources, blockers = await _resolve_sources(
        capabilities, list(source_refs or []), minimum=minimum_sources
    )
    requirements: list[dict[str, Any]] = []
    for ref in role.allowed_capabilities:
        if ref in ("knowledge_query", "conversation.send"):
            status = "available" if (sources or chosen_template not in _SOURCE_ROLES) else "needs_source"
        elif ref in bound_refs or ref in action_refs:
            status = "available"
        elif ref in _HARD_CAPABILITIES.get(chosen_template, []):
            status = "missing"
            blockers.append(
                {
                    "code": "capability_missing",
                    "message": f"La capacidad {ref} no está instalada ni tiene binding.",
                    "action": "Instala o configura el binding real en Marketplace/Integraciones.",
                }
            )
        else:
            status = "optional_missing"
        requirements.append(
            {
                "capability_ref": ref,
                "status": status,
                "required": ref in _HARD_CAPABILITIES.get(chosen_template, []),
            }
        )

    agent_selection = "create"
    existing_agent: dict[str, Any] | None = None
    if existing_agent_id:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT id, name, is_active, workspace_id FROM agents "
                        "WHERE id = :aid AND organization_id = :oid"
                    ),
                    {"aid": existing_agent_id, "oid": organization_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None or not bool(row.is_active):
            blockers.append(
                {
                    "code": "agent_unavailable",
                    "message": "El agente seleccionado no existe o está inactivo.",
                    "action": "Elige un agente activo o deja que ZENT cree uno.",
                }
            )
        elif workspace_id and row.workspace_id and UUID(str(row.workspace_id)) != workspace_id:
            blockers.append(
                {
                    "code": "workspace_mismatch",
                    "message": "El agente pertenece a otro workspace.",
                    "action": "Elige un agente de este workspace.",
                }
            )
        else:
            agent_selection = "reuse"
            existing_agent = {"id": str(row.id), "name": row.name}

    solution_slug = f"{chosen_template}_{_slug(text_brief, 40)}"[:80]
    compilation_basis = {
        "brief": text_brief,
        "template_id": chosen_template,
        "workspace_id": str(workspace_id) if workspace_id else None,
        "source_refs": sorted(sources),
        "existing_agent_id": existing_agent_id,
        "options": options or {},
    }
    compilation_hash = _fingerprint(compilation_basis)
    solution_slug = f"{solution_slug[:68]}_{compilation_hash[:8]}"
    agent_ref = f"{chosen_template}_agent"
    workflow_ref = f"{chosen_template}_flow"
    capability_refs = [item["capability_ref"] for item in requirements]

    logical_knowledge = [
        {
            "kind": "knowledge_base",
            "logical_ref": f"source_{index + 1}",
            "required": True,
            "purpose": "Evidencia autorizada",
        }
        for index in range(len(sources))
    ]
    blueprint = {
        "schema": "zent.solution/v1",
        "solution_id": solution_slug,
        "version": "1.0.0",
        "status": "draft",
        "name": f"{role.name}: {text_brief[:100]}",
        "description": text_brief[:1200],
        "roles": [{"role_ref": role.role_id, "version": role.version, "required": True}],
        "agents": [
            {
                "agent_ref": agent_ref,
                "role_ref": role.role_id,
                "name": role.name,
                "workflow_refs": [workflow_ref],
                "capability_refs": capability_refs,
            }
        ],
        "workflows": [
            {
                "workflow_ref": workflow_ref,
                "name": proposal.get("name") or f"Proceso de {role.name}",
                "role_refs": [role.role_id],
                "agent_refs": [agent_ref],
                "capability_refs": capability_refs,
                "trigger": {"type": "webhook"},
                "requirements": [item["capability_ref"] for item in requirements if item["required"]],
            }
        ],
        "capabilities": [
            {
                "capability_ref": item["capability_ref"],
                "required": bool(item["required"]),
                "purpose": "Operación del rol",
            }
            for item in requirements
        ],
        "knowledge": logical_knowledge,
        "channels": ["webhook"],
        "requirements": [
            "Revisar el plan de recursos antes de escribir",
            "Probar la conversación con un agente activo",
            "Certificar antes de publicar",
        ],
        "installation": [
            {
                "order": 1,
                "action": "create_or_reuse_role",
                "module": "roles",
                "description": "Crear o reutilizar el rol del template.",
                "required": True,
            },
            {
                "order": 2,
                "action": "create_or_link_agent",
                "module": "agents",
                "description": "Crear o vincular un agente activo con el rol.",
                "required": True,
            },
            {
                "order": 3,
                "action": "create_draft_workflow",
                "module": "workflows",
                "description": "Persistir el grafo compilado como borrador.",
                "required": True,
            },
        ],
        "expected_outcomes": [item.model_dump(mode="json") for item in role.expected_outcomes],
        "risk_class": role.risk_class,
        "compliance_tags": role.compliance_tags,
        "locales": role.locales,
    }
    try:
        SolutionV1.model_validate(blueprint)
    except Exception as exc:  # noqa: BLE001
        raise CompilationError(f"blueprint inválido: {str(exc)[:300]}") from exc

    graph_preview = _build_graph(
        chosen_template,
        agent_id=(existing_agent or {}).get("id"),
        agent_ref=agent_ref,
        sources=sources,
        solution_ref=solution_slug,
    )
    plan = {
        "role": {
            "logical_ref": role.role_id,
            "name": role.name,
            "action": "reuse_or_create",
        },
        "agent": {
            "logical_ref": agent_ref,
            "name": (existing_agent or {}).get("name") or f"{role.name} · {solution_slug[:30]}",
            "action": agent_selection,
            "existing_agent_id": (existing_agent or {}).get("id"),
        },
        "workflow": {
            "logical_ref": workflow_ref,
            "name": proposal.get("name") or f"Proceso de {role.name}",
            "action": "create_draft",
            "will_create": not blockers,
        },
        "sources": [{"logical_ref": f"source_{i + 1}", "physical_id": ref} for i, ref in enumerate(sources)],
        "bindings": sorted(bound_refs),
    }
    status = "READY_TO_MATERIALIZE" if not blockers else "NEEDS_CONFIGURATION"
    return {
        "schema": COMPILATION_SCHEMA,
        "compilation_hash": compilation_hash,
        "status": status,
        "can_materialize": not blockers,
        "mode": normalized_mode,
        "template_id": chosen_template,
        "brief": {
            "text": text_brief,
            "language": str((options or {}).get("language") or "es"),
            "audience": role.audience,
            "outcomes": [item.name for item in role.expected_outcomes],
            "risk_class": role.risk_class,
            "memory": role.memory_policy.model_dump(mode="json"),
            "autonomy": role.autonomy_level,
        },
        "role": role.model_dump(by_alias=True),
        "blueprint": blueprint,
        "plan": plan,
        "requirements": requirements,
        "blockers": blockers,
        "available_sources": available_sources,
        "scenarios": _scenarios(chosen_template),
        "graph_preview": graph_preview,
        "next_actions": [
            "Revisar recursos y bloqueos",
            "Confirmar y materializar",
            "Probar la conversación",
            "Certificar y publicar",
        ],
    }


async def _find_solution_by_slug(
    organization_id: UUID, slug: str, workspace_id: UUID | None
) -> dict[str, Any] | None:
    for item in await list_solutions(organization_id, workspace_id=workspace_id):
        if item.get("solution_id") == slug:
            return item
    return None


async def _find_role_by_slug(organization_id: UUID, slug: str, workspace_id: UUID | None) -> dict | None:
    for item in await list_roles(organization_id, workspace_id=workspace_id):
        if item.get("role_id") == slug:
            return item
    return None


async def _find_agent(
    organization_id: UUID, *, name: str, workspace_id: UUID | None
) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, is_active, workspace_id FROM agents "
                    "WHERE organization_id = :oid AND name = :name "
                    "AND workspace_id IS NOT DISTINCT FROM :ws "
                    "ORDER BY created_at LIMIT 1"
                ),
                {
                    "oid": organization_id,
                    "name": name[:255],
                    "ws": workspace_id,
                },
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "name": row.name,
        "is_active": bool(row.is_active),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
    }


async def _find_workflow_by_ref(organization_id: UUID, solution_ref: str) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, name, status FROM workflows "
                    "WHERE organization_id = :oid AND graph->'metadata'->>'solution_ref' = :ref "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"oid": organization_id, "ref": solution_ref},
            )
        ).fetchone()
    finally:
        await session.close()
    return {"id": str(row.id), "name": row.name, "status": row.status} if row else None


async def _materialization_row(row: Any) -> dict[str, Any]:
    return {
        "schema": MATERIALIZATION_SCHEMA,
        "id": str(row.id),
        "solution_id": str(row.solution_id) if row.solution_id else None,
        "idempotency_key": row.idempotency_key,
        "compilation_hash": row.compilation_hash,
        "template_id": row.template_id,
        "status": row.status,
        "artifacts": row.artifacts or {},
        "requirements": row.requirements or [],
        "blockers": (row.compilation or {}).get("blockers") or [],
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _begin_materialization(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    solution_id: UUID | None,
    idempotency_key: str,
    compilation_hash: str,
    template_id: str,
    compilation: dict[str, Any],
    user_id: UUID | None,
) -> tuple[Any, bool]:
    await ensure_materialization_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO studio_solution_materializations "
                    "(organization_id, workspace_id, solution_id, idempotency_key, "
                    "compilation_hash, template_id, status, compilation, requirements, created_by) "
                    "VALUES (:oid, :ws, :sid, :key, :hash, :template, 'IN_PROGRESS', "
                    "CAST(:comp AS jsonb), CAST(:req AS jsonb), :uid) "
                    "ON CONFLICT (organization_id, idempotency_key) DO NOTHING RETURNING *"
                ),
                {
                    "oid": organization_id,
                    "ws": workspace_id,
                    "sid": solution_id,
                    "key": idempotency_key[:200],
                    "hash": compilation_hash,
                    "template": template_id,
                    "comp": _json(compilation),
                    "req": _json(compilation.get("requirements") or []),
                    "uid": user_id,
                },
            )
        ).fetchone()
        if row is not None:
            await session.commit()
            return row, True
        await session.rollback()
        existing = (
            await session.execute(
                text(
                    "SELECT * FROM studio_solution_materializations "
                    "WHERE organization_id = :oid AND idempotency_key = :key"
                ),
                {"oid": organization_id, "key": idempotency_key[:200]},
            )
        ).fetchone()
        if existing is None:
            raise MaterializationConflict("no se pudo registrar la materialización")
        if str(existing.compilation_hash) != compilation_hash:
            raise MaterializationConflict(
                "La misma clave de idempotencia se usó con otra misión."
            )
        return existing, False
    finally:
        await session.close()


async def _update_materialization(
    row_id: UUID,
    *,
    status: str,
    artifacts: dict | None = None,
    error: str | None = None,
    solution_id: UUID | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE studio_solution_materializations SET status = :status, "
                "artifacts = COALESCE(CAST(:artifacts AS jsonb), artifacts), "
                "error = :error, solution_id = COALESCE(:sid, solution_id), "
                "updated_at = NOW() WHERE id = :id"
            ),
            {
                "status": status,
                "artifacts": _json(artifacts) if artifacts is not None else None,
                "error": (error or "")[:400] or None,
                "sid": solution_id,
                "id": row_id,
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _ensure_solution(
    organization_id: UUID,
    *,
    workspace_id: UUID | None,
    user_id: UUID | None,
    blueprint: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = await _find_solution_by_slug(
        organization_id, str(blueprint["solution_id"]), workspace_id
    )
    if existing is not None:
        return existing, False
    try:
        created = await create_solution(
            organization_id,
            workspace_id=workspace_id,
            user_id=user_id,
            payload=blueprint,
        )
        return created, True
    except SolutionConflict as exc:
        existing = await _find_solution_by_slug(
            organization_id, str(blueprint["solution_id"]), workspace_id
        )
        if existing is not None:
            return existing, False
        raise exc


async def _ensure_role(
    organization_id: UUID,
    *,
    workspace_id: UUID | None,
    user_id: UUID | None,
    role_payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = await _find_role_by_slug(
        organization_id, str(role_payload["role_id"]), workspace_id
    )
    if existing is not None:
        return existing, False
    payload = dict(role_payload)
    payload["status"] = "active"
    created = await create_role(
        organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        payload=payload,
    )
    return created, True


async def _ensure_agent(
    organization_id: UUID,
    *,
    workspace_id: UUID | None,
    user_id: UUID | None,
    name: str,
    role: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = await _find_agent(organization_id, name=name, workspace_id=workspace_id)
    if existing is not None:
        await link_agent_role(
            organization_id, UUID(existing["id"]), UUID(role["record_id"])
        )
        return existing, False
    from src.api.deps import get_agent_repo

    tools = [str(item) for item in role.get("allowed_tools") or []]
    repo = get_agent_repo()
    agent = await repo.create_agent(
        organization_id,
        name,
        description=str(role.get("mission") or "")[:500],
        workspace_id=workspace_id,
        system_prompt=f"{role.get('mission') or ''}\n\nRestricciones: "
        + "; ".join(str(item) for item in role.get("constraints") or []),
        tools=tools,
        created_by=user_id,
    )
    await repo.update_agent(organization_id, agent.id, status="ready", is_active=True)
    await link_agent_role(organization_id, agent.id, UUID(role["record_id"]))
    return {"id": str(agent.id), "name": agent.name}, True


async def _validate_workflow_agents(organization_id: UUID, graph: dict[str, Any]) -> None:
    agent_ids = {
        str((node.get("config") or {}).get("agent_id"))
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and node.get("type") == "llm"
    }
    if not agent_ids or "" in agent_ids:
        raise CompilationError("el workflow compilado tiene un llm sin agente activo")
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM agents WHERE organization_id = :oid AND id = ANY(:ids) "
                    "AND (status IN ('configured', 'ready', 'deployed') OR is_active = true)"
                ),
                {"oid": organization_id, "ids": [UUID(item) for item in agent_ids]},
            )
        ).fetchall()
    finally:
        await session.close()
    if len(rows) != len(agent_ids):
        raise CompilationError("el workflow compilado referencia un agente inactivo")


async def materialize_solution(
    organization_id: UUID,
    *,
    brief: str | dict[str, Any],
    workspace_id: UUID | None = None,
    template_id: str | None = None,
    source_refs: list[str] | None = None,
    existing_agent_id: str | None = None,
    options: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    confirm: bool = False,
    user_id: UUID | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    if not confirm:
        raise CompilationError("La materialización requiere confirmación explícita.")
    compilation = await compile_solution(
        organization_id,
        brief=brief,
        workspace_id=workspace_id,
        template_id=template_id,
        source_refs=source_refs,
        existing_agent_id=existing_agent_id,
        options=options,
        mode=mode,
    )
    key = (idempotency_key or compilation["compilation_hash"])[:200]
    blueprint = compilation["blueprint"]
    solution, solution_created = await _ensure_solution(
        organization_id,
        workspace_id=workspace_id,
        user_id=user_id,
        blueprint=blueprint,
    )
    row, created = await _begin_materialization(
        organization_id=organization_id,
        workspace_id=workspace_id,
        solution_id=UUID(str(solution["record_id"])) if solution.get("record_id") else None,
        idempotency_key=key,
        compilation_hash=compilation["compilation_hash"],
        template_id=compilation["template_id"],
        compilation=compilation,
        user_id=user_id,
    )
    if not created and str(row.status) == "READY":
        return await _materialization_row(row)

    artifacts: dict[str, Any] = dict(row.artifacts or {})
    artifacts.setdefault("solution", {"id": solution.get("record_id"), "created": solution_created})
    try:
        role, role_created = await _ensure_role(
            organization_id,
            workspace_id=workspace_id,
            user_id=user_id,
            role_payload=compilation["role"],
        )
        artifacts["role"] = {"id": role.get("record_id"), "created": role_created}
        plan_agent = compilation["plan"]["agent"]
        if plan_agent.get("existing_agent_id"):
            agent = {
                "id": plan_agent["existing_agent_id"],
                "name": plan_agent["name"],
            }
            await link_agent_role(
                organization_id, UUID(agent["id"]), UUID(role["record_id"])
            )
            agent_created = False
        else:
            agent, agent_created = await _ensure_agent(
                organization_id,
                workspace_id=workspace_id,
                user_id=user_id,
                name=plan_agent["name"],
                role=role,
            )
        artifacts["agent"] = {
            "id": agent["id"],
            "created": agent_created,
            "role_id": role.get("record_id"),
        }
        if compilation["blockers"]:
            await _update_materialization(
                row.id,
                status="NEEDS_CONFIGURATION",
                artifacts=artifacts,
                error="; ".join(item["code"] for item in compilation["blockers"]),
                solution_id=UUID(str(solution["record_id"])) if solution.get("record_id") else None,
            )
            fresh = await _get_materialization_by_id(organization_id, row.id)
            return fresh

        solution_ref = str(blueprint["solution_id"])
        existing_workflow = await _find_workflow_by_ref(organization_id, solution_ref)
        if existing_workflow is not None:
            artifacts["workflow"] = {"id": existing_workflow["id"], "created": False}
        else:
            from src.platform.workflows.engine import create_workflow
            from src.platform.workflows.ir import WorkflowGraph, validate_graph

            compiled_graph = compilation.get("graph")
            if isinstance(compiled_graph, dict) and compiled_graph:
                graph = _bind_agent_to_graph(
                    compiled_graph,
                    agent_id=agent["id"],
                    agent_ref=compilation["plan"]["agent"]["logical_ref"],
                )
            else:
                graph = _build_graph(
                    compilation["template_id"],
                    agent_id=agent["id"],
                    agent_ref=compilation["plan"]["agent"]["logical_ref"],
                    sources=[item["physical_id"] for item in compilation["plan"]["sources"]],
                    solution_ref=solution_ref,
                )
            validate_graph(WorkflowGraph.from_dict(graph))
            await _validate_workflow_agents(organization_id, graph)
            workflow = await create_workflow(
                organization_id,
                str(blueprint["workflows"][0]["name"])[:150],
                "webhook",
                {},
                [],
                str(blueprint["description"])[:1000],
                user_id,
                {"solution": {"solution_id": solution_ref, "compilation_hash": compilation["compilation_hash"]}},
                workspace_id=workspace_id,
                graph=graph,
                workflow_version=2,
            )
            artifacts["workflow"] = {"id": workflow["workflow_id"], "created": True}
        scope = sorted(
            {
                str(item.get("capability_ref"))
                for item in blueprint.get("capabilities") or []
                if isinstance(item, dict) and item.get("capability_ref")
            }
        )
        safety_profile = (
            "wellness"
            if str((role or {}).get("role_id") or "").startswith("wellness")
            else "standard"
        )
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE workflows SET solution_id = :sid, "
                    "capability_scope = CAST(:scope AS jsonb), "
                    "capability_scope_source = 'solution', safety_profile = :safety "
                    "WHERE id = :wid AND organization_id = :oid"
                ),
                {
                    "sid": UUID(str(solution["record_id"])) if solution.get("record_id") else None,
                    "scope": json.dumps(scope),
                    "safety": safety_profile,
                    "wid": UUID(str(artifacts["workflow"]["id"])),
                    "oid": organization_id,
                },
            )
            await session.commit()
        finally:
            await session.close()
        artifacts["sources"] = compilation["plan"]["sources"]
        artifacts["bindings"] = compilation["plan"]["bindings"]
        await _update_materialization(
            row.id,
            status="READY",
            artifacts=artifacts,
            solution_id=UUID(str(solution["record_id"])) if solution.get("record_id") else None,
        )
        fresh = await _get_materialization_by_id(organization_id, row.id)
        return fresh
    except Exception as exc:
        await _update_materialization(
            row.id,
            status="FAILED",
            artifacts=artifacts,
            error=str(exc),
            solution_id=UUID(str(solution["record_id"])) if solution.get("record_id") else None,
        )
        logger.warning("solution materialization failed", error=str(exc)[:300])
        raise CompilationError(
            "La materialización quedó incompleta; los recursos creados son reutilizables."
        ) from exc


async def _get_materialization_by_id(organization_id: UUID, row_id: UUID) -> dict[str, Any]:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT * FROM studio_solution_materializations "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": row_id, "oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise CompilationError("materialización no encontrada")
    return await _materialization_row(row)


async def get_solution_materialization(
    organization_id: UUID, solution_id: UUID
) -> dict[str, Any] | None:
    await ensure_materialization_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT * FROM studio_solution_materializations "
                    "WHERE organization_id = :oid AND solution_id = :sid "
                    "ORDER BY updated_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "sid": solution_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return await _materialization_row(row) if row else None


async def rollback_materialization(
    organization_id: UUID, solution_id: UUID
) -> dict[str, Any]:
    materialization = await get_solution_materialization(organization_id, solution_id)
    if materialization is None:
        raise CompilationError("la solución no tiene materialización")
    artifacts = materialization.get("artifacts") or {}
    deleted: list[str] = []
    kept: list[str] = []
    workflow = artifacts.get("workflow") or {}
    if workflow.get("created") and workflow.get("id"):
        from src.platform.workflows.engine import delete_workflow

        session = await get_async_session()
        try:
            used = (
                await session.execute(
                    text(
                        "SELECT 1 FROM workflow_runs WHERE workflow_id = :wid LIMIT 1"
                    ),
                    {"wid": UUID(workflow["id"])},
                )
            ).fetchone()
        finally:
            await session.close()
        if used is None:
            if await delete_workflow(organization_id, UUID(workflow["id"])):
                deleted.append("workflow")
        else:
            kept.append("workflow")
    agent = artifacts.get("agent") or {}
    if agent.get("created") and agent.get("id"):
        session = await get_async_session()
        try:
            used = (
                await session.execute(
                    text(
                        "SELECT 1 FROM workflows WHERE organization_id = :oid "
                        "AND graph::text LIKE :agent LIMIT 1"
                    ),
                    {"oid": organization_id, "agent": f"%{agent['id']}%"},
                )
            ).fetchone()
        finally:
            await session.close()
        if used is None:
            session = await get_async_session()
            try:
                await session.execute(
                    text("DELETE FROM agents WHERE id = :aid AND organization_id = :oid"),
                    {"aid": UUID(agent["id"]), "oid": organization_id},
                )
                await session.commit()
                deleted.append("agent")
            finally:
                await session.close()
        else:
            kept.append("agent")
    role = artifacts.get("role") or {}
    if role.get("created") and role.get("id"):
        session = await get_async_session()
        try:
            used = (
                await session.execute(
                    text("SELECT 1 FROM agents WHERE role_profile_id = :rid LIMIT 1"),
                    {"rid": UUID(role["id"])},
                )
            ).fetchone()
        finally:
            await session.close()
        if used is None:
            session = await get_async_session()
            try:
                await session.execute(
                    text("DELETE FROM role_profiles WHERE id = :rid AND organization_id = :oid"),
                    {"rid": UUID(role["id"]), "oid": organization_id},
                )
                await session.commit()
                deleted.append("role")
            finally:
                await session.close()
        else:
            kept.append("role")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE studio_solution_materializations SET status = 'ROLLED_BACK', "
                "updated_at = NOW() WHERE organization_id = :oid AND solution_id = :sid"
            ),
            {"oid": organization_id, "sid": solution_id},
        )
        await session.commit()
    finally:
        await session.close()
    return {
        "schema": MATERIALIZATION_SCHEMA,
        "solution_id": str(solution_id),
        "status": "ROLLED_BACK",
        "deleted": deleted,
        "kept": kept,
    }


__all__ = [
    "COMPILATION_SCHEMA",
    "CompilationError",
    "MATERIALIZATION_SCHEMA",
    "MaterializationConflict",
    "compile_solution",
    "ensure_materialization_tables",
    "get_solution_materialization",
    "materialize_solution",
    "rollback_materialization",
]
