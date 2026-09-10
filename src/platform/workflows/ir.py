# =============================================================================
# Phase 32A — Workflow Graph IR
#
# Evolución del modelo steps[] (legacy) hacia un grafo dirigido con nodos,
# edges, variables, entrypoints y metadata. Incluye LegacyWorkflowAdapter
# (backward compatibility) y validación estructural.
# =============================================================================
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

# Tipos de datos de los puertos (typed data).
PORT_TYPES = (
    "string",
    "number",
    "boolean",
    "date",
    "datetime",
    "money",
    "entity",
    "record",
    "record_list",
    "document",
    "evidence",
    "json",
    "binary",
)

LEGACY_STEP_TYPES = ("llm", "kb_query", "api_call", "condition", "notify")
LEGACY_TRIGGER_TYPES = ("webhook", "schedule", "event")
TRIGGER_NODE_TO_TYPE = {
    "trigger_schedule": "schedule",
    "trigger_event": "event",
    "trigger_webhook": "webhook",
}


def trigger_type_from_graph(graph: WorkflowGraph) -> str:
    """Deriva trigger_type persistido desde el nodo trigger del canvas."""
    for node in graph.nodes:
        mapped = TRIGGER_NODE_TO_TYPE.get(node.type)
        if mapped is not None:
            return mapped
    return "webhook"

# Coerciones permitidas entre tipos de puerto al conectar un edge.
_COERCIONES: dict[str, set[str]] = {
    "number": {"string", "money", "json"},
    "money": {"string", "number", "json"},
    "boolean": {"string"},
    "date": {"string", "datetime"},
    "datetime": {"string", "date"},
    "record": {"json", "string"},
    "record_list": {"json", "string"},
    "document": {"json"},
    "evidence": {"json"},
    "entity": {"json", "record"},
    "json": {"string"},
}

# Referencias estables por node id: {{nodes.<id>.output.<path>}} / ${nodes...}
_NODE_REF_RE = re.compile(r"\{\{(?:nodes\.([A-Za-z0-9_-]+))(?:\.([a-zA-Z0-9_.\[\]-]+))?\}\}")
_TRIGGER_REF_RE = re.compile(r"\{\{trigger\.([a-zA-Z0-9_.\[\]-]+)\}\}")
_VARIABLE_REF_RE = re.compile(r"\{\{variables\.([a-zA-Z0-9_-]+)\}\}")
_LEGACY_STEP_REF_RE = re.compile(r"\{\{steps\.(\d+)\.output\.([^}]+)\}\}")


@dataclass
class PortRef:
    port: str = "out"
    type: str = "json"


@dataclass
class InPort:
    name: str = "in"
    type: str = "json"
    required: bool = True


@dataclass
class OutPort:
    name: str = "out"
    type: str = "json"


@dataclass
class WorkflowNode:
    """Nodo del grafo. `config` es específico del handler registrado en el
    node registry (registry: node_type → handler)."""

    id: str
    type: str
    version: int = 1
    label: str = ""
    position: dict[str, float] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    input_ports: list[InPort] = field(default_factory=lambda: [InPort()])
    output_ports: list[OutPort] = field(default_factory=lambda: [OutPort()])
    retry_policy: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 60_000
    error_policy: str = "fail"  # fail | continue | stop
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowEdge:
    id: str
    from_node: str
    from_port: str = "out"
    to_node: str = "in"
    to_port: str = "in"
    condition: dict[str, Any] | None = None


@dataclass
class WorkflowGraph:
    """IR canónico del workflow. workflow_version es la versión del IR;
    graph_source indica el origen (legacy | graph)."""

    workflow_version: int = 2
    nodes: list[WorkflowNode] = field(default_factory=list)
    edges: list[WorkflowEdge] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    entrypoints: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def node_map(self) -> dict[str, WorkflowNode]:
        return {n.id: n for n in self.nodes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_version": self.workflow_version,
            "nodes": [
                {
                    "id": n.id,
                    "type": n.type,
                    "version": n.version,
                    "label": n.label,
                    "position": n.position,
                    "config": n.config,
                    "input_ports": [p.__dict__ for p in n.input_ports],
                    "output_ports": [p.__dict__ for p in n.output_ports],
                    "retry_policy": n.retry_policy,
                    "timeout_ms": n.timeout_ms,
                    "error_policy": n.error_policy,
                    "metadata": n.metadata,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "id": e.id,
                    "from_node": e.from_node,
                    "from_port": e.from_port,
                    "to_node": e.to_node,
                    "to_port": e.to_port,
                    "condition": e.condition,
                }
                for e in self.edges
            ],
            "variables": self.variables,
            "entrypoints": self.entrypoints,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WorkflowGraph":
        nodes = [
            WorkflowNode(
                id=n["id"],
                type=n["type"],
                version=int(n.get("version", 1)),
                label=str(n.get("label", "")),
                position=dict(n.get("position") or {}),
                config=dict(n.get("config") or {}),
                input_ports=[
                    InPort(name=p.get("name", "in"), type=p.get("type", "json"), required=bool(p.get("required", True)))
                    for p in n.get("input_ports") or []
                ]
                or [InPort()],
                output_ports=[
                    OutPort(name=p.get("name", "out"), type=p.get("type", "json"))
                    for p in n.get("output_ports") or []
                ]
                or [OutPort()],
                retry_policy=dict(n.get("retry_policy") or {}),
                timeout_ms=int(n.get("timeout_ms", 60_000) or 60_000),
                error_policy=str(n.get("error_policy", "fail")),
                metadata=dict(n.get("metadata") or {}),
            )
            for n in raw.get("nodes") or []
        ]
        edges = [
            WorkflowEdge(
                id=e.get("id") or str(uuid4()),
                from_node=e["from_node"],
                from_port=e.get("from_port", "out"),
                to_node=e["to_node"],
                to_port=e.get("to_port", "in"),
                condition=dict(e["condition"]) if e.get("condition") else None,
            )
            for e in raw.get("edges") or []
        ]
        return cls(
            workflow_version=int(raw.get("workflow_version", 2) or 2),
            nodes=nodes,
            edges=edges,
            variables=dict(raw.get("variables") or {}),
            entrypoints=[str(x) for x in raw.get("entrypoints") or []],
            metadata=dict(raw.get("metadata") or {}),
        )


class WorkflowGraphError(ValueError):
    """Error de validación estructural del grafo."""


def port_type_assignable(src: str, dst: str) -> bool:
    if src == dst:
        return True
    return src in _COERCIONES and dst in _COERCIONES[src]


def validate_graph(graph: WorkflowGraph) -> None:
    """Validación estructural: ids únicos, referencias de edges, ciclos y
    compatibilidad de tipos de puerto."""
    if not graph.nodes:
        raise WorkflowGraphError("el grafo no tiene nodos")
    ids = [n.id for n in graph.nodes]
    if len(set(ids)) != len(ids):
        raise WorkflowGraphError("los ids de nodos deben ser únicos")
    if not graph.entrypoints:
        raise WorkflowGraphError("el grafo requiere al menos un entrypoint")
    for ep in graph.entrypoints:
        if ep not in graph.node_map:
            raise WorkflowGraphError(f"entrypoint {ep} no existe")

    node_map = graph.node_map
    for e in graph.edges:
        if e.from_node not in node_map:
            raise WorkflowGraphError(f"edge {e.id}: from_node {e.from_node} no existe")
        if e.to_node not in node_map:
            raise WorkflowGraphError(f"edge {e.id}: to_node {e.to_node} no existe")
        src = node_map[e.from_node]
        dst = node_map[e.to_node]
        src_out = {p.name: p.type for p in src.output_ports}
        dst_in = {p.name: p.type for p in dst.input_ports}
        if src_out and e.from_port not in src_out:
            raise WorkflowGraphError(
                f"edge {e.id}: {e.from_node} no tiene puerto de salida {e.from_port}"
            )
        if dst_in and e.to_port not in dst_in:
            raise WorkflowGraphError(
                f"edge {e.id}: {e.to_node} no tiene puerto de entrada {e.to_port}"
            )
        if src_out and dst_in:
            src_type = src_out[e.from_port]
            dst_type = dst_in[e.to_port]
            if not port_type_assignable(src_type, dst_type):
                raise WorkflowGraphError(
                    f"edge {e.id}: tipo {src_type} no compatible con {dst_type} "
                    f"({e.from_node}.{e.from_port} → {e.to_node}.{e.to_port})"
                )
        if e.from_node == e.to_node:
            raise WorkflowGraphError(f"edge {e.id}: self-loop prohibido")

    # Ciclos: DFS desde entrypoints (restringidos a edges sin condición de
    # iteración; los loops reales se modelan con for_each, no con edges).
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        adj[e.from_node].append(e.to_node)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n.id: WHITE for n in graph.nodes}

    def _visit(node_id: str, path: list[str]) -> None:
        nonlocal_color = color
        if node_id in path:
            cycle = " → ".join(path[path.index(node_id):] + [node_id])
            raise WorkflowGraphError(f"ciclo detectado en el grafo: {cycle}")
        if nonlocal_color[node_id] == BLACK:
            return
        nonlocal_color[node_id] = GRAY
        for nxt in adj[node_id]:
            _visit(nxt, path + [node_id])
        nonlocal_color[node_id] = BLACK

    for seed in graph.entrypoints:
        _visit(seed, [])


# ---------------------------------------------------------------------------
# LegacyWorkflowAdapter — steps[] ⇄ WorkflowGraph
# ---------------------------------------------------------------------------
class LegacyWorkflowAdapter:
    """Convierte el IR legacy (steps + then/else) hacia graph IR y viceversa.

    Reglas:
    - Cada step → nodo con id estable `n{index}` (mismo índice del array).
    - Se preserva un mapa legacy_index → node_id en metadata.legacy_index_map.
    - condition genera dos edges: puerto 'then' → rama verdadera y 'else' →
      rama falsa (los puertos then/else se añaden a su output_ports).
    - La resolución de referencias legacy ({{steps.N.output.X}}) se mantiene
      en ejecución mapeando index → node_id.
    """

    @staticmethod
    def steps_to_graph(
        steps: list[dict] | None,
        trigger_type: str = "webhook",
        trigger_config: dict | None = None,
    ) -> WorkflowGraph:
        index_map: dict[int, str] = {}

        def convert_chain(
            chain: list[dict], *, index_base: int, legacy_mode: bool, legacy_index: int = 0
        ) -> tuple[list[WorkflowNode], list[WorkflowEdge], list[str], int]:
            """Convierte una cadena lineal (o rama) a nodos/edges.

            Devuelve (nodos, edges, últimas_ids, siguiente_índice). Las ramas
            then/else se convierten recursivamente; sus últimos nodos quedan
            como "extremos" para reconectar al siguiente paso del nivel padre.
            `legacy_mode` marca la cadena top-level: solo ahí se registra el
            mapa legacy_index → node_id (referencias {{steps.N.output.X}}).
            """
            nodes: list[WorkflowNode] = []
            edges: list[WorkflowEdge] = []
            cursor = index_base
            last_ids: list[str] = []
            for step in chain or []:
                node_id = f"n{cursor}"
                node_type = str(step.get("type") or "llm")
                ports: list[OutPort] = [OutPort(name="out", type="json")]
                if node_type == "condition":
                    ports.append(OutPort(name="then", type="json"))
                    ports.append(OutPort(name="else", type="json"))
                config = dict(step.get("config") or {})
                if legacy_mode:
                    index_map[str(legacy_index)] = node_id
                    config = rewrite_legacy_references(config, index_map)
                node = WorkflowNode(
                    id=node_id,
                    type=node_type,
                    label=node_type,
                    config=config,
                    retry_policy={"max_attempts": int(step.get("retries", 0) or 0) + 1},
                    error_policy=str(step.get("on_error") or "fail"),
                    input_ports=[InPort(name="in", type="json")],
                    output_ports=ports,
                    metadata={"legacy": True, "legacy_index": legacy_index if legacy_mode else None},
                )
                nodes.append(node)
                # Conecta todos los extremos previos (último de cada rama).
                for prev_id in last_ids:
                    edges.append(
                        WorkflowEdge(
                            id=f"e{cursor}-{prev_id}",
                            from_node=prev_id,
                            from_port="out",
                            to_node=node_id,
                            to_port="in",
                        )
                    )
                cursor += 1
                if node_type != "condition":
                    last_ids = [node_id]
                    if legacy_mode:
                        legacy_index += 1
                    continue
                # Ramas then/else → subgrafo recursivo (sin índices legacy).
                branch_ends: list[str] = []
                for port_name, branch in (("then", step.get("then")), ("else", step.get("else"))):
                    bn, be, branch_last, cursor2 = convert_chain(
                        branch or [], index_base=cursor, legacy_mode=False
                    )
                    cursor = cursor2
                    if bn:
                        edges.append(
                            WorkflowEdge(
                                id=f"e{node_id}-{port_name}",
                                from_node=node_id,
                                from_port=port_name,
                                to_node=bn[0].id,
                                to_port="in",
                            )
                        )
                        nodes.extend(bn)
                        edges.extend(be)
                        branch_ends.extend(branch_last)
                    else:
                        # Rama vacía → nodo terminal virtual (se satisface al
                        # instante; no se persiste).
                        end_id = f"_end{cursor}"
                        nodes.append(
                            WorkflowNode(
                                id=end_id,
                                type="end",
                                label="fin",
                                config={},
                                metadata={"virtual": True},
                            )
                        )
                        edges.append(
                            WorkflowEdge(
                                id=f"e{node_id}-{port_name}",
                                from_node=node_id,
                                from_port=port_name,
                                to_node=end_id,
                                to_port="in",
                            )
                        )
                        cursor += 1
                        branch_ends.append(end_id)
                last_ids = branch_ends
                if legacy_mode:
                    legacy_index += 1
            return nodes, edges, last_ids, cursor

        nodes, edges, _last_ids, _end = convert_chain(
            steps or [], index_base=0, legacy_mode=True
        )
        if not nodes:
            nodes.append(
                WorkflowNode(id="_empty", type="end", label="sin pasos", metadata={"virtual": True})
            )
        graph = WorkflowGraph(
            workflow_version=1,
            nodes=nodes,
            edges=edges,
            entrypoints=[nodes[0].id],
            metadata={
                "legacy": True,
                "legacy_index_map": {str(k): v for k, v in index_map.items()},
                "trigger_type": trigger_type,
                "trigger_config": dict(trigger_config or {}),
            },
        )
        return graph


# Compatibilidad de referencias legacy → node ids.
def rewrite_legacy_references(value: Any, index_map: dict[int, str]) -> Any:
    """Reescribe referencias {{steps.N.output.X}} → {{nodes.<id>.output.X}}.

    Los ids de nodo legacy son `n{index}`, por lo que el mapeo es directo.
    """

    def repl(match: re.Match) -> str:
        idx = int(match.group(1))
        nid = index_map.get(idx, f"n{idx}")
        return f"{{{{nodes.{nid}.output.{match.group(2)}}}}}"

    if isinstance(value, str):
        return _LEGACY_STEP_REF_RE.sub(repl, value)
    if isinstance(value, list):
        return [rewrite_legacy_references(v, index_map) for v in value]
    if isinstance(value, dict):
        return {k: rewrite_legacy_references(v, index_map) for k, v in value.items()}
    return value


def get_node_id_for_legacy_index(graph: WorkflowGraph, index: int) -> str:
    return graph.metadata.get("legacy_index_map", {}).get(str(index), f"n{index}")


def resolve_stable_references(
    value: Any, node_outputs: dict[str, Any], trigger: dict[str, Any] | None = None
) -> Any:
    """Resuelve referencias estables por node id ({{nodes.<id>.output.<path>}}),
    {{trigger.<path>}} y {{variables.<name>}} contra datos ya disponibles."""

    def _walk(cur: Any, path: str) -> Any:
        for part in path.split("."):
            if not part:
                continue
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit() and 0 <= int(part) < len(cur):
                cur = cur[int(part)]
            else:
                return None
        return cur

    def _render(cur: Any) -> str:
        if cur is None:
            return ""
        return json.dumps(cur, ensure_ascii=False) if isinstance(cur, (dict, list)) else str(cur)

    def repl(match: re.Match) -> str:
        nid, path = match.group(1), match.group(2) or ""
        out = node_outputs.get(nid, {})
        cur = out.get("output", out) if isinstance(out, dict) else out
        if path.startswith("output."):
            path = path[len("output."):]
        return _render(_walk(cur, path))

    def repl_trigger(match: re.Match) -> str:
        if trigger is None:
            return match.group(0)
        return _render(_walk(trigger, match.group(1)))

    def repl_variable(match: re.Match) -> str:
        return match.group(0)

    if isinstance(value, str):
        out = value
        out = _TRIGGER_REF_RE.sub(repl_trigger, out)
        out = _NODE_REF_RE.sub(repl, out)
        return out
    if isinstance(value, dict):
        return {k: resolve_stable_references(v, node_outputs, trigger) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_stable_references(v, node_outputs, trigger) for v in value]
    return value
