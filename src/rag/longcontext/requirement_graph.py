# =============================================================================
# QueryRequirementGraph — qué conocimiento exige la pregunta (§38-39)
# =============================================================================
# La pregunta se transforma en un grafo de requisitos:
#
#   pregunta -> regla R -> definición D -> símbolo S -> excepción E -> evidencia
#
# El grafo dice QUÉ FALTA (nodos MISSING), no solo qué chunks se recuperaron.
# Se construye desde:
#   - requirements de evidencia (anchors/entidades/cláusulas);
#   - payload de los chunks (fabric ids por tipo + semantic_neighborhood).
#
# Determinista, con límites duros y salida auditable para «Ver flujo».
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256

REQUIREMENT_GRAPH_VERSION = "requirement-graph-1"

#: Relaciones que expresan dependencia de conocimiento.
DEPENDENCY_RELATIONS: tuple[str, ...] = (
    "DEPENDS_ON",
    "HAS_EXCEPTION",
    "HAS_CONDITION",
    "USES",
    "CONSTRAINS",
    "APPLIES_TO",
)

#: Campos del payload que mapean tipo de nodo -> ids.
_PAYLOAD_TYPE_FIELDS: tuple[tuple[str, str], ...] = (
    ("Rule", "rule_ids"),
    ("Definition", "definition_ids"),
    ("Symbol", "symbol_ids"),
    ("Entity", "entity_ids"),
    ("Exception", "exception_ids"),
    ("Condition", "condition_ids"),
    ("Claim", "claim_ids"),
    ("TemporalAssertion", "temporal_ids"),
    ("Reference", "reference_ids"),
)


class RequirementNodeType(StrEnum):
    RULE = "Rule"
    DEFINITION = "Definition"
    SYMBOL = "Symbol"
    ENTITY = "Entity"
    EXCEPTION = "Exception"
    CONDITION = "Condition"
    EVIDENCE = "Evidence"
    #: Fase 16: clasificación de la pregunta.
    RUNTIME_INPUT = "RuntimeInput"
    OPTIONAL_CONTEXT = "OptionalContext"


class RequirementStatus(StrEnum):
    FOUND = "FOUND"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    CONFLICTING = "CONFLICTING"


@dataclass(frozen=True, kw_only=True)
class RequirementNode:
    id: str
    node_type: str
    label: str
    status: str
    key: str = ""
    hop: int = 0
    via_relation: str = ""
    evidence_chunk_keys: tuple[str, ...] = ()
    activation: float = 0.0

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "node_type": self.node_type,
            "label": self.label[:160],
            "status": self.status,
            "key": self.key[:200],
            "hop": int(self.hop),
            "via_relation": self.via_relation,
            "evidence_chunks": list(self.evidence_chunk_keys[:6]),
            "activation": round(float(self.activation), 4),
        }


@dataclass(frozen=True, kw_only=True)
class QueryRequirementGraph:
    question: str = ""
    nodes: tuple[RequirementNode, ...] = ()
    edges: tuple[tuple[str, str, str], ...] = ()
    missing: tuple[str, ...] = ()
    stats: dict = field(default_factory=dict)
    version: str = REQUIREMENT_GRAPH_VERSION

    @property
    def fingerprint(self) -> str:
        import json

        material = {
            "version": self.version,
            "question": self.question,
            "nodes": [
                [node.id, node.node_type, node.status] for node in self.nodes
            ],
            "edges": [list(edge) for edge in self.edges],
        }
        raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(raw.encode("utf-8")).hexdigest()

    def missing_by_type(self, node_type: str) -> tuple[str, ...]:
        return tuple(
            node.label
            for node in self.nodes
            if node.status == RequirementStatus.MISSING.value
            and node.node_type == node_type
        )

    def to_public_dict(self) -> dict:
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "missing": list(self.missing[:24]),
            "missing_count": len(self.missing),
            "dependency_coverage": self.stats.get("dependency_coverage"),
            "coverage": dict(self.stats.get("coverage") or {}),
            "by_status": self.stats.get("by_status", {}),
            "by_type": self.stats.get("by_type", {}),
            "top_missing": [
                node.to_public_dict()
                for node in self.nodes
                if node.status == RequirementStatus.MISSING.value
            ][:12],
        }


def _chunk_key(chunk) -> str:
    metadata = getattr(chunk, "metadata", None) or {}
    value = str(metadata.get("chunk_id") or metadata.get("unit_id") or "")
    if value:
        return value
    return str(getattr(chunk, "document_id", ""))[:36]


def build_requirement_graph(
    *,
    question: str,
    requirements: list | tuple = (),
    chunks: list | tuple = (),
    evidence_state: object | None = None,
    runtime_inputs: list | tuple = (),
    optional_context: list | tuple = (),
    max_nodes: int = 96,
    max_edges: int = 256,
) -> QueryRequirementGraph:
    """Construye el grafo de requisitos desde requirements + payload fabric.

    `runtime_inputs` son valores del usuario que NO deben buscarse en fuentes
    (§65): se clasifican como RuntimeInput y jamás cuentan como missing.
    `optional_context` es contexto auxiliar, tampoco exigible.
    """
    nodes: dict[str, RequirementNode] = {}
    edges: list[tuple[str, str, str]] = []
    edge_seen: set[tuple[str, str, str]] = set()
    missing_external: list[str] = []

    # Fase 16: clasificación de la pregunta (input vs contexto vs conocimiento).
    for value in runtime_inputs or ():
        label = str(value or "").strip()
        if not label:
            continue
        node_id = f"runtime:{label[:80]}"
        add_node = RequirementNode(
            id=node_id,
            node_type=RequirementNodeType.RUNTIME_INPUT.value,
            label=label,
            status=RequirementStatus.FOUND.value,
            key=node_id,
        )
        nodes.setdefault(node_id, add_node)
    for value in optional_context or ():
        label = str(value or "").strip()
        if not label:
            continue
        node_id = f"optional:{label[:80]}"
        nodes.setdefault(
            node_id,
            RequirementNode(
                id=node_id,
                node_type=RequirementNodeType.OPTIONAL_CONTEXT.value,
                label=label,
                status=RequirementStatus.FOUND.value,
                key=node_id,
            ),
        )

    def add_node(node: RequirementNode) -> None:
        existing = nodes.get(node.id)
        if existing is None:
            nodes[node.id] = node
            return
        # FOUND gana a PARTIAL gana a MISSING; conserva evidencia.
        priority = {
            RequirementStatus.MISSING.value: 0,
            RequirementStatus.PARTIAL.value: 1,
            RequirementStatus.CONFLICTING.value: 2,
            RequirementStatus.FOUND.value: 3,
        }
        if priority.get(node.status, 0) > priority.get(existing.status, 0):
            nodes[node.id] = node

    def add_edge(subject: str, relation: str, object_id: str) -> None:
        key = (subject, relation, object_id)
        if key in edge_seen or len(edges) >= max_edges:
            return
        edge_seen.add(key)
        edges.append(key)

    # 1. Requirements de evidencia: nodos EVIDENCE con su estado real.
    for requirement in requirements or ():
        state = str(getattr(requirement, "state", "") or "").upper()
        status = {
            "FOUND": RequirementStatus.FOUND.value,
            "PARTIAL": RequirementStatus.PARTIAL.value,
            "MISSING": RequirementStatus.MISSING.value,
            "CONFLICTING": RequirementStatus.CONFLICTING.value,
        }.get(state, RequirementStatus.MISSING.value)
        description = str(getattr(requirement, "description", "") or "")
        if not description:
            continue
        node_id = f"evidence:{description[:80]}"
        add_node(
            RequirementNode(
                id=node_id,
                node_type=RequirementNodeType.EVIDENCE.value,
                label=description,
                status=status,
                key=node_id,
            )
        )

    # 2. Nodos del fabric presentes en los chunks recuperados (FOUND).
    chunk_node_ids: dict[str, set[str]] = {}
    for chunk in chunks or ():
        metadata = getattr(chunk, "metadata", None) or {}
        chunk_key = _chunk_key(chunk)
        present: set[str] = set()
        for node_type, field_name in _PAYLOAD_TYPE_FIELDS:
            values = metadata.get(field_name) or ()
            if isinstance(values, str):
                values = [values]
            for value in values:
                node_id = str(value or "")
                if not node_id:
                    continue
                present.add(node_id)
                add_node(
                    RequirementNode(
                        id=node_id,
                        node_type=node_type,
                        label=node_id,
                        status=RequirementStatus.FOUND.value,
                        evidence_chunk_keys=(chunk_key,),
                    )
                )
        # Labels legibles si el payload los trae (fabric_labels).
        for node_id in present:
            chunk_node_ids.setdefault(node_id, set()).add(chunk_key)
        # 3. Vecindad semántica: dependencias del chunk hacia otros nodos.
        neighborhood = metadata.get("semantic_neighborhood") or ()
        for entry in neighborhood:
            if not isinstance(entry, dict):
                continue
            neighbor_id = str(entry.get("node_id") or "")
            if not neighbor_id:
                continue
            relation = str(entry.get("relation") or "")
            neighbor_type = str(entry.get("node_type") or "Entity")
            label = str(entry.get("label") or neighbor_id)
            neighbor_present = neighbor_id in chunk_node_ids
            add_node(
                RequirementNode(
                    id=neighbor_id,
                    node_type=neighbor_type,
                    label=label,
                    status=(
                        RequirementStatus.FOUND.value
                        if neighbor_present
                        else RequirementStatus.MISSING.value
                    ),
                    hop=1,
                    via_relation=relation,
                    evidence_chunk_keys=(
                        tuple(sorted(chunk_node_ids.get(neighbor_id, ())))
                    ),
                    activation=float(entry.get("activation") or 0.0),
                )
            )
            for source_id in present:
                if relation in DEPENDENCY_RELATIONS:
                    add_edge(source_id, relation, neighbor_id)

    # 4. Evidence state: faltantes documentables reales (autoridad única).
    if evidence_state is not None and hasattr(
        evidence_state, "missing_documentable_evidence"
    ):
        try:
            for label in evidence_state.missing_documentable_evidence():
                text = str(label or "")
                if text:
                    missing_external.append(text)
        except Exception:  # noqa: BLE001 — el grafo nunca frena el retrieval
            pass

    node_list = list(nodes.values())[:max_nodes]
    # Missing se calcula al FINAL desde el estado real de los nodos: una
    # dependencia vista como MISSING y resuelta por un chunk posterior no se
    # reporta como faltante.
    missing = [
        node.label
        for node in node_list
        if node.status == RequirementStatus.MISSING.value
    ] + missing_external
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for node in node_list:
        by_status[node.status] = by_status.get(node.status, 0) + 1
        by_type[node.node_type] = by_type.get(node.node_type, 0) + 1
    dependency_edges = [
        edge for edge in edges if edge[1] in DEPENDENCY_RELATIONS
    ]
    dependency_targets = {edge[2] for edge in dependency_edges}
    found_targets = {
        node.id
        for node in node_list
        if node.status == RequirementStatus.FOUND.value
    }
    dependency_coverage = (
        round(len(dependency_targets & found_targets) / len(dependency_targets), 4)
        if dependency_targets
        else None
    )
    unique_missing = list(dict.fromkeys(missing))

    def type_counts(node_type: str) -> tuple[int, int]:
        items = [node for node in node_list if node.node_type == node_type]
        total = len(items)
        satisfied = sum(
            1 for node in items if node.status == RequirementStatus.FOUND.value
        )
        return total, satisfied

    definitions_total, definitions_satisfied = type_counts("Definition")
    rules_total, rules_satisfied = type_counts("Rule")
    exceptions_total, exceptions_satisfied = type_counts("Exception")
    coverage = {
        "requirements_total": len(node_list),
        "requirements_satisfied": sum(
            1
            for node in node_list
            if node.status == RequirementStatus.FOUND.value
        ),
        "definitions_total": definitions_total,
        "definitions_satisfied": definitions_satisfied,
        "rules_total": rules_total,
        "rules_satisfied": rules_satisfied,
        "exceptions_total": exceptions_total,
        "exceptions_satisfied": exceptions_satisfied,
        "conflicts": sum(
            1
            for node in node_list
            if node.status == RequirementStatus.CONFLICTING.value
        ),
    }
    return QueryRequirementGraph(
        question=question[:400],
        nodes=tuple(node_list),
        edges=tuple(edges[:max_edges]),
        missing=tuple(unique_missing[:48]),
        stats={
            "by_status": by_status,
            "by_type": by_type,
            "dependency_edges": len(dependency_edges),
            "dependency_coverage": dependency_coverage,
            "coverage": coverage,
        },
    )


__all__ = [
    "DEPENDENCY_RELATIONS",
    "REQUIREMENT_GRAPH_VERSION",
    "QueryRequirementGraph",
    "RequirementNode",
    "RequirementNodeType",
    "RequirementStatus",
    "build_requirement_graph",
]
