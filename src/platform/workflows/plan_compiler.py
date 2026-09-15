# =============================================================================
# Workflow Plan Compiler — WorkflowPlan (business-level) → WorkflowGraph (IR v2).
#
# El compilador es determinístico y validado: el LLM propone el Plan, el backend
# lo compila al MISMO grafo que ejecuta engine.py/runtime.py. Nunca publica ni
# activa nada y nunca escribe referencias a capabilities inexistentes.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.conditions import plan_node_to_rules
from src.platform.workflows.intent import (
    PlanAction,
    PlanAnalysis,
    PlanDataSource,
    PlanValidationIssue,
    WorkflowPlan,
    validate_plan,
)
from src.platform.workflows.ir import (
    InPort,
    OutPort,
    WorkflowEdge,
    WorkflowGraph,
    WorkflowGraphError,
    WorkflowNode,
    validate_graph,
)

CHANNEL_LABELS: dict[str, str] = {
    "zent": "Zent",
    "in_app": "Zent",
    "email": "correo",
    "webhook": "webhook",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "whatsapp": "WhatsApp",
}

_ACTION_LABELS: dict[str, str] = {
    "notify": "avisar",
    "marketplace_action": "usar una integración",
    "api_call": "consultar un servicio",
    "business_result": "publicar un resultado",
    "human_approval": "pedir aprobación",
    "stop": "detenerse",
}


@dataclass
class PlanSummary:
    when: str = ""
    conditions: str = ""
    analysis: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "when": self.when,
            "conditions": self.conditions,
            "analysis": self.analysis,
            "actions": self.actions,
            "text": self.text,
        }


@dataclass
class CompiledPlan:
    graph: WorkflowGraph
    issues: list[PlanValidationIssue] = field(default_factory=list)
    summary: PlanSummary = field(default_factory=PlanSummary)
    order: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[PlanValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def valid(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Capabilities index (validación contra el tenant, sin ejecutar nada)
# ---------------------------------------------------------------------------
async def load_capabilities(organization_id: UUID, workspace_id: UUID | None = None) -> dict[str, Any]:
    """Agentes, knowledge bases y acciones instaladas del tenant para validar
    el plan antes de compilarlo."""
    from src.platform.workflows.events import STANDARD_EVENTS

    agents: dict[str, dict] = {}
    knowledge_bases: dict[str, str] = {}
    actions: dict[str, dict] = {}
    managed_db = False
    session = await get_async_session()
    try:
        agent_rows = (
            await session.execute(
                text(
                    "SELECT id, name FROM agents WHERE organization_id = :oid "
                    "AND (status IN ('configured', 'ready', 'deployed') OR is_active = true) "
                    "ORDER BY name LIMIT 200"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        kb_rows = (
            await session.execute(
                text(
                    "SELECT id, name FROM knowledge_bases "
                    "WHERE organization_id = :oid ORDER BY name LIMIT 200"
                ),
                {"oid": organization_id},
            )
        ).fetchall()
        try:
            action_rows = (
                await session.execute(
                    text(
                        "SELECT a.action_id, a.display_name, i.id AS install_id "
                        "FROM integration_actions a "
                        "JOIN integration_manifests m ON m.id = a.integration_id "
                        "JOIN installed_integrations i ON i.integration_id = m.id "
                        "WHERE i.organization_id = :oid AND i.status IN ('active', 'installed') "
                        "AND (i.workspace_id IS NOT DISTINCT FROM :ws) "
                        "ORDER BY a.action_id LIMIT 500"
                    ),
                    {"oid": organization_id, "ws": workspace_id},
                )
            ).fetchall()
        except Exception:  # noqa: BLE001 — base sin marketplace
            action_rows = []
        try:
            managed_row = (
                await session.execute(
                    text(
                        "SELECT 1 FROM managed_databases "
                        "WHERE organization_id = :oid LIMIT 1"
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
            managed_db = managed_row is not None
        except Exception:  # noqa: BLE001 — base sin managed DB
            managed_db = False
    finally:
        await session.close()

    for row in agent_rows:
        entry = {"id": str(row.id), "name": row.name}
        agents[str(row.id)] = entry
        agents[str(row.name).lower()] = entry
    for row in kb_rows:
        knowledge_bases[str(row.id)] = str(row.id)
        knowledge_bases[str(row.name).lower()] = str(row.id)
    for row in action_rows:
        actions[str(row.action_id)] = {
            "action_id": str(row.action_id),
            "display_name": row.display_name,
            "install_id": str(row.install_id),
        }
    return {
        "agents": agents,
        "knowledge_bases": knowledge_bases,
        "actions": actions,
        "managed_db": managed_db,
        "event_types": list(STANDARD_EVENTS),
    }


# ---------------------------------------------------------------------------
# Compilación
# ---------------------------------------------------------------------------
class _Builder:
    def __init__(self) -> None:
        self.nodes: list[WorkflowNode] = []
        self.edges: list[WorkflowEdge] = []
        self._edge_seq = 0

    def add(
        self,
        node_id: str,
        node_type: str,
        label: str,
        config: dict[str, Any],
        x: int,
        y: int,
        *,
        input_ports: list[InPort] | None = None,
        output_ports: list[OutPort] | None = None,
    ) -> str:
        self.nodes.append(
            WorkflowNode(
                id=node_id,
                type=node_type,
                label=label,
                config=config,
                position={"x": x, "y": y},
                input_ports=input_ports if input_ports is not None else [InPort()],
                output_ports=output_ports if output_ports is not None else [OutPort()],
                metadata={"plan": True},
            )
        )
        return node_id

    def connect(self, from_node: str, to_node: str, *, from_port: str = "out") -> None:
        self._edge_seq += 1
        self.edges.append(
            WorkflowEdge(
                id=f"e{self._edge_seq}",
                from_node=from_node,
                from_port=from_port,
                to_node=to_node,
                to_port="in",
            )
        )


def compile_plan(plan: WorkflowPlan, capabilities: dict[str, Any] | None = None) -> CompiledPlan:
    """Compila el Plan a WorkflowGraph v2. Pura y determinística."""
    caps = capabilities or {}
    issues = list(validate_plan(plan))
    builder = _Builder()

    trigger_id = "trigger"
    trigger_config: dict[str, Any] = {}
    trigger_type = plan.trigger.kind.value
    if trigger_type == "event":
        trigger_config = {"event_type": plan.trigger.event_type, "filters": {}}
        builder.add("trigger", "trigger_event", "Cuando ocurra algo", trigger_config, 40, 140,
                    input_ports=[], output_ports=[OutPort()])
    elif trigger_type == "schedule":
        schedule = plan.schedule or plan.trigger.schedule
        if schedule is not None:
            trigger_config = {"schedule": schedule.model_dump(mode="json")}
        builder.add("trigger", "trigger_schedule", "Programar", trigger_config, 40, 140,
                    input_ports=[], output_ports=[OutPort()])
    else:
        # manual/webhook: el hook público y el botón Probar siguen disponibles.
        builder.add("trigger", "trigger_webhook", "Webhook", {}, 40, 140,
                    input_ports=[], output_ports=[OutPort()])

    source_to_node: dict[str, str] = {}
    prev = trigger_id
    x = 340
    for index, source in enumerate(plan.data_sources):
        node_id = f"data_{index + 1}"
        node_type, config = _data_node(source, caps, issues)
        builder.add(node_id, node_type, source.label or source.key, config, x, 140)
        builder.connect(prev, node_id)
        prev = node_id
        source_to_node[source.key.lower()] = node_id
        x += 280

    def ref_for(field_ref: Any) -> str:
        if field_ref.ref:
            return str(field_ref.ref)
        source_key = str(field_ref.source or "").lower()
        if source_key in ("trigger", "evento", "cuando", "cuando ocurra algo"):
            return f"trigger.{field_ref.field}"
        node_id = source_to_node.get(source_key)
        if node_id:
            return f"{{{{nodes.{node_id}.output.{field_ref.field}}}}}"
        return str(field_ref.field)

    condition_id: str | None = None
    if plan.conditions is not None and plan.conditions.children:
        condition_id = "condition"
        rules = plan_node_to_rules(plan.conditions, ref_for)
        builder.add(
            condition_id,
            "condition",
            "Si / si no",
            {"rules": rules},
            x,
            140,
            output_ports=[OutPort(name="out", type="boolean"), OutPort(name="then"), OutPort(name="else")],
        )
        builder.connect(prev, condition_id)
        x += 280

    # Cadena de análisis + acciones.
    chain_start = condition_id or prev
    chain_port = "then" if condition_id else "out"
    chain_prev = chain_start
    chain_port_current = chain_port
    y = 140
    for index, analysis in enumerate(plan.analysis):
        node_id = f"analysis_{index + 1}"
        config, analysis_label = _analysis_node(analysis, caps, issues)
        builder.add(node_id, "llm", analysis_label, config, x, y)
        builder.connect(chain_prev, node_id, from_port=chain_port_current)
        chain_prev, chain_port_current, y = node_id, "out", y + 80
        x += 280
    for index, action in enumerate(plan.actions):
        node_id = f"action_{index + 1}"
        node_type, config = _action_node(action, caps, issues)
        builder.add(
            node_id,
            node_type,
            action.description or _ACTION_LABELS.get(action.kind, action.kind),
            config,
            x,
            y,
        )
        builder.connect(chain_prev, node_id, from_port=chain_port_current)
        chain_prev, chain_port_current, y = node_id, "out", y + 80
        x += 280

    end_id = "end"
    builder.add(end_id, "end", "Fin", {}, max(x, 340), 140)
    builder.connect(chain_prev, end_id, from_port=chain_port_current)
    if condition_id is not None:
        builder.connect(condition_id, end_id, from_port="else")

    graph = WorkflowGraph(
        workflow_version=2,
        nodes=builder.nodes,
        edges=builder.edges,
        entrypoints=[trigger_id],
        metadata={
            "canvas": True,
            "plan_compiled": True,
            "plan_name": plan.name,
            "plan_version": plan.plan_version,
        },
    )
    try:
        validate_graph(graph)
    except WorkflowGraphError as exc:
        issues.append(
            PlanValidationIssue(
                code="graph.invalid",
                severity="error",
                message=f"No pude armar el flujo: {exc}",
            )
        )
    return CompiledPlan(
        graph=graph,
        issues=issues,
        summary=plan_summary(plan),
        order=[n.id for n in graph.nodes],
    )


def _data_node(
    source: PlanDataSource, caps: dict[str, Any], issues: list[PlanValidationIssue]
) -> tuple[str, dict[str, Any]]:
    if source.kind == "knowledge_base":
        kb_id = caps.get("knowledge_bases", {}).get(
            str(source.ref or source.label or source.key).lower()
        ) or source.ref
        if not kb_id:
            issues.append(
                PlanValidationIssue(
                    code="data.unknown_kb",
                    severity="warning",
                    message=f"No encontramos la base de conocimiento «{source.label or source.key}».",
                    hint="Elige una base existente antes de publicar.",
                )
            )
        return "kb_query", {"knowledge_base_id": kb_id or "", "query": source.label or source.key}
    if source.kind == "integration":
        # La fuente la aporta una acción del marketplace; se valida al compilar
        # la acción concreta.
        return "query_business_data", {"ask": source.label or source.key}
    return "query_business_data", {"ask": source.label or source.key}


def _analysis_node(
    analysis: PlanAnalysis, caps: dict[str, Any], issues: list[PlanValidationIssue]
) -> tuple[dict[str, Any], str]:
    agent_id = analysis.agent_id or ""
    agent_name = analysis.agent_name or ""
    if caps.get("agents"):
        resolved = caps["agents"].get(agent_id) or caps["agents"].get(agent_name.lower())
        if resolved:
            agent_id, agent_name = resolved["id"], resolved["name"]
        elif agent_name:
            issues.append(
                PlanValidationIssue(
                    code="analysis.unknown_agent",
                    severity="warning",
                    message=f"No encontramos el agente «{agent_name}».",
                    hint="Elige un agente existente antes de publicar.",
                )
            )
    elif agent_name and not agent_id:
        issues.append(
            PlanValidationIssue(
                code="analysis.unknown_agent",
                severity="warning",
                message=f"No encontramos el agente «{agent_name}».",
                hint="Elige un agente existente antes de publicar.",
            )
        )
    config: dict[str, Any] = {
        "prompt": analysis.prompt or "",
        "agent_id": agent_id,
        "agent_name": agent_name,
    }
    if analysis.output_schema:
        config["output_schema"] = analysis.output_schema
    label = agent_name or "Analizar con un agente"
    return config, label


def _action_node(
    action: PlanAction, caps: dict[str, Any], issues: list[PlanValidationIssue]
) -> tuple[str, dict[str, Any]]:
    if action.kind == "notify":
        channel = action.channel or "zent"
        engine_channel = "in_app" if channel == "zent" else channel
        if channel in ("slack", "teams", "whatsapp"):
            issues.append(
                PlanValidationIssue(
                    code="action.channel_not_connected",
                    severity="error",
                    message=f"Necesitas conectar {CHANNEL_LABELS.get(channel, channel)} para usar esta acción.",
                    hint="Conéctala en Integraciones o elige otro canal.",
                )
            )
        return "notify", {
            "channel": engine_channel,
            "title": action.subject or action.description or "Aviso",
            "message": action.message or action.description or "",
            "recipients": [r.model_dump(mode="json") for r in action.recipients],
        }
    if action.kind == "marketplace_action":
        entry = caps.get("actions", {}).get(str(action.action_id or ""))
        if entry is None and action.action_id:
            issues.append(
                PlanValidationIssue(
                    code="action.not_installed",
                    severity="error",
                    message=f"La acción «{action.action_id}» no está instalada.",
                    hint="Instálala desde el canvas o elige otra.",
                )
            )
        return "marketplace_action", {
            "install_id": (entry or {}).get("install_id", action.install_id or ""),
            "action_id": action.action_id or "",
            "inputs": action.params or {},
        }
    if action.kind == "api_call":
        return "api_call", {
            "url": action.params.get("url", ""),
            "method": str(action.params.get("method") or "GET").upper(),
            "json_body": action.params.get("json_body") or {},
            "json_path": action.params.get("json_path") or "",
        }
    if action.kind == "human_approval":
        return "human_approval", {
            "action": action.description or "Acción sensible",
            "summary": action.message or action.subject or "",
            "expires_minutes": int(action.params.get("expires_minutes") or 1440),
        }
    if action.kind == "stop":
        return "stop", {
            "status": str(action.params.get("status") or "success"),
            "message": action.message or action.description or "",
        }
    # business_result (default razonable)
    return "business_result", {
        "title": action.subject or action.description or "Resultado",
        "summary": action.message or "",
        "section": str(action.params.get("section") or "reports"),
        "importance": str(action.params.get("importance") or "INFO"),
    }


# ---------------------------------------------------------------------------
# Resumen humano (misión §20)
# ---------------------------------------------------------------------------
def plan_summary(plan: WorkflowPlan) -> PlanSummary:
    if plan.trigger.kind.value == "schedule":
        schedule = plan.schedule or plan.trigger.schedule
        when = schedule.describe() if schedule is not None else "según la programación"
    elif plan.trigger.kind.value == "event":
        when = f"ocurra {plan.trigger.event_type}"
    else:
        when = plan.trigger.description or "se reciba la señal"

    conditions = plan.conditions.describe() if plan.conditions is not None else ""

    analysis_lines: list[str] = []
    for item in plan.analysis:
        who = item.agent_name or "un agente"
        what = item.description or item.prompt or "analice la situación"
        analysis_lines.append(f"{who}: {what}")

    action_lines: list[str] = []
    for action in plan.actions:
        if action.kind == "notify":
            targets = ", ".join(r.describe() for r in action.recipients) or "los destinatarios"
            channel = CHANNEL_LABELS.get(action.channel or "zent", action.channel or "Zent")
            action_lines.append(f"avisar por {channel} a {targets}")
        elif action.kind == "marketplace_action":
            action_lines.append(f"usar la acción {action.action_id}")
        elif action.kind == "human_approval":
            action_lines.append("pedir aprobación humana")
        elif action.kind == "api_call":
            action_lines.append("consultar un servicio externo")
        elif action.kind == "stop":
            action_lines.append("detener el flujo")
        else:
            action_lines.append(action.description or action.kind)

    text_parts = [f"Cuando {when}"]
    if conditions:
        text_parts.append(f"si {conditions}")
    if analysis_lines:
        if len(analysis_lines) == 1:
            text_parts.append(f"Zent pedirá a {analysis_lines[0]}")
        else:
            text_parts.append("Zent analizará con sus agentes")
    if action_lines:
        text_parts.append("y " + " y ".join(action_lines))
    text = ", ".join(text_parts) + "."

    return PlanSummary(
        when=when,
        conditions=conditions,
        analysis=analysis_lines,
        actions=action_lines,
        text=text,
    )


def compiled_plan_payload(compiled: CompiledPlan) -> dict[str, Any]:
    return {
        "graph": compiled.graph.to_dict(),
        "issues": [i.model_dump(mode="json") for i in compiled.issues],
        "valid": compiled.valid,
        "summary": compiled.summary.to_dict(),
        "order": compiled.order,
    }


async def compile_plan_for_org(
    organization_id: UUID,
    plan: WorkflowPlan,
    workspace_id: UUID | None = None,
) -> CompiledPlan:
    capabilities = await load_capabilities(organization_id, workspace_id)
    return compile_plan(plan, capabilities)


__all__ = [
    "CHANNEL_LABELS",
    "CompiledPlan",
    "PlanSummary",
    "compile_plan",
    "compile_plan_for_org",
    "compiled_plan_payload",
    "load_capabilities",
    "plan_summary",
]
