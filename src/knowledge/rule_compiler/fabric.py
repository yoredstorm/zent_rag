# =============================================================================
# Semantic Rule Compiler — proyección al Semantic Fabric / Knowledge OS
# =============================================================================
# Una regla canónica entra al grafo conectando:
#
#   Rule — DEFINES -> Definition/Term
#   Rule — APPLIES_TO -> Entity/Concept (sujeto)
#   Rule — CONSTRAINS -> Entity/Concept (sujeto)
#   Rule — DEPENDS_ON -> Definition/Symbol
#   Rule — HAS_CONDITION -> Condition
#   Rule — HAS_EXCEPTION -> Exception
#   Rule — HAS_CONSEQUENCE -> Claim/Consequence
#   Rule — USES_SYMBOL -> Symbol
#   Rule — USES_UNIT -> Unit
#   Rule — SUPPORTED_BY -> Evidence
#   Rule — CONFLICTS_WITH -> Rule
#   Rule — SUPERSEDES -> Rule
#
# Nada se crea sin evidencia: cada nodo/arista arrastra evidence y locator.
# =============================================================================
from __future__ import annotations

from typing import Sequence
from uuid import UUID, uuid5

from src.core.domain.rule_semantics import RuleKind

from .model import CanonicalRule, RuleEvidence

FABRIC_NS = UUID("b8e2f5a7-4d1c-4a6e-9b3f-1e8c7d5a2f96")
FABRIC_RULE_PROJECTION_VERSION = "rule-fabric-1"

_MAX_NODES = 4000
_MAX_EDGES = 12000


def _node_id(node_key: str) -> str:
    return str(uuid5(FABRIC_NS, node_key))


def _edge_id(edge_key: str) -> str:
    return str(uuid5(FABRIC_NS, "edge:" + edge_key))


def _blocks(evidence: Sequence[RuleEvidence]) -> list[str]:
    blocks: list[str] = []
    for item in evidence:
        block_id = str(item.locator.get("block_id") or "")
        if block_id and block_id not in blocks:
            blocks.append(block_id)
    return blocks[:16]


def _base_node(
    *,
    node_key: str,
    node_type: str,
    label: str,
    text: str = "",
    confidence: float = 0.7,
    block_ids: Sequence[str] = (),
    attributes: dict | None = None,
    document_id: str = "",
    source_id: str = "",
) -> dict:
    return {
        "id": _node_id(node_key),
        "node_key": node_key,
        "node_type": node_type,
        "label": label[:300],
        "text": text[:600],
        "confidence": round(float(confidence), 4),
        "scope": "document",
        "unit_key": node_key,
        "block_ids": list(block_ids)[:16],
        "windows": [],
        "attributes": dict(attributes or {}),
        "document_id": document_id,
        "source_id": source_id,
        "derived": True,
        "canonical": True,
        "version": FABRIC_RULE_PROJECTION_VERSION,
    }


def _base_edge(
    *,
    relation_type: str,
    subject: dict,
    object_node: dict,
    confidence: float = 0.7,
    evidence: Sequence[str] = (),
    attributes: dict | None = None,
) -> dict:
    edge_key = f"{relation_type}:{subject['node_key']}->{object_node['node_key']}"
    return {
        "id": _edge_id(edge_key),
        "edge_key": edge_key,
        "relation_type": relation_type,
        "subject_id": subject["id"],
        "object_id": object_node["id"],
        "subject_key": subject["node_key"],
        "object_key": object_node["node_key"],
        "confidence": round(float(confidence), 4),
        "method": "deterministic",
        "evidence": list(evidence)[:12],
        "windows": [],
        "attributes": dict(attributes or {}),
        "derived": True,
        "canonical": True,
        "version": FABRIC_RULE_PROJECTION_VERSION,
    }


def project_rules_to_fabric(
    rules: Sequence[CanonicalRule],
    *,
    document_id: str = "",
    source_id: str = "",
) -> dict:
    """CanonicalRule[] -> nodos/aristas listos para persistir en el fabric."""
    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def add_node(node: dict) -> dict:
        if len(nodes) < _MAX_NODES:
            nodes.setdefault(node["node_key"], node)
        return nodes.get(node["node_key"], node)

    def add_edge(edge: dict) -> None:
        if len(edges) < _MAX_EDGES:
            edges.setdefault(edge["edge_key"], edge)

    rule_nodes: dict[str, dict] = {}
    for rule in rules:
        block_ids = _blocks(rule.provenance)
        node = add_node(
            _base_node(
                node_key=f"rule:{rule.rule_id}",
                node_type="Rule",
                label=rule.subject or rule.statement[:120],
                text=rule.statement,
                confidence=rule.confidence,
                block_ids=block_ids,
                attributes={
                    "verification_state": rule.verification_state,
                    "executable": bool(rule.executable),
                    "kind": rule.kind,
                    "modality": rule.modality,
                    "operator": rule.operator,
                    "rule_id": rule.rule_id,
                    "missing_premises": list(rule.missing_premises[:12]),
                },
                document_id=document_id,
                source_id=source_id,
            )
        )
        rule_nodes[rule.rule_id] = node

    for rule in rules:
        node = rule_nodes[rule.rule_id]
        evidence_ids = list(rule.evidence_ids())

        # Sujeto: la regla aplica y restringe algo.
        if rule.subject:
            subject_node = add_node(
                _base_node(
                    node_key=f"concept:{rule.subject.lower()[:160]}",
                    node_type="Concept",
                    label=rule.subject,
                    confidence=0.7,
                    block_ids=_blocks(rule.provenance),
                    document_id=document_id,
                    source_id=source_id,
                )
            )
            add_edge(
                _base_edge(
                    relation_type="APPLIES_TO",
                    subject=node,
                    object_node=subject_node,
                    confidence=rule.confidence,
                    evidence=evidence_ids,
                )
            )
            if rule.kind in (RuleKind.NORMATIVE_RULE.value, RuleKind.CONSTRAINT.value):
                add_edge(
                    _base_edge(
                        relation_type="CONSTRAINS",
                        subject=node,
                        object_node=subject_node,
                        confidence=rule.confidence,
                        evidence=evidence_ids,
                    )
                )

        # Símbolos declarados o usados.
        for name, prop in rule.properties.items():
            if name.startswith("matching.symbol.") and not name.endswith(".alphabet") and prop.known:
                symbol = name[len("matching.symbol.") :]
                symbol_node = add_node(
                    _base_node(
                        node_key=f"symbol:{symbol}",
                        node_type="Symbol",
                        label=symbol,
                        text=str(prop.value),
                        confidence=prop.confidence,
                        attributes={"meaning": str(prop.value)[:200]},
                        document_id=document_id,
                        source_id=source_id,
                    )
                )
                add_edge(
                    _base_edge(
                        relation_type="USES_SYMBOL",
                        subject=node,
                        object_node=symbol_node,
                        confidence=prop.confidence,
                        evidence=prop.evidence,
                    )
                )

        # Unidades declaradas por la regla.
        for name, prop in rule.properties.items():
            if name.endswith(".unit") and prop.known:
                unit = str(prop.value)
                if not unit:
                    continue
                unit_node = add_node(
                    _base_node(
                        node_key=f"unit:{unit.lower()}",
                        node_type="Attribute",
                        label=unit,
                        confidence=prop.confidence,
                        document_id=document_id,
                        source_id=source_id,
                    )
                )
                add_edge(
                    _base_edge(
                        relation_type="USES_UNIT",
                        subject=node,
                        object_node=unit_node,
                        confidence=prop.confidence,
                        evidence=prop.evidence,
                    )
                )

        # Condiciones / consecuencias / excepciones.
        for index, condition in enumerate(rule.conditions):
            condition_node = add_node(
                _base_node(
                    node_key=f"condition:{rule.rule_id}:{index}",
                    node_type="Condition",
                    label=condition[:160],
                    text=condition,
                    document_id=document_id,
                    source_id=source_id,
                )
            )
            add_edge(
                _base_edge(
                    relation_type="HAS_CONDITION",
                    subject=node,
                    object_node=condition_node,
                    confidence=rule.confidence,
                    evidence=evidence_ids,
                )
            )
        for index, exception in enumerate(rule.exceptions):
            exception_node = add_node(
                _base_node(
                    node_key=f"exception:{rule.rule_id}:{index}",
                    node_type="Exception",
                    label=exception[:160],
                    text=exception,
                    document_id=document_id,
                    source_id=source_id,
                )
            )
            add_edge(
                _base_edge(
                    relation_type="HAS_EXCEPTION",
                    subject=node,
                    object_node=exception_node,
                    confidence=rule.confidence,
                    evidence=evidence_ids,
                )
            )
        for index, consequence in enumerate(rule.consequences):
            consequence_node = add_node(
                _base_node(
                    node_key=f"consequence:{rule.rule_id}:{index}",
                    node_type="Claim",
                    label=consequence[:160],
                    text=consequence,
                    document_id=document_id,
                    source_id=source_id,
                )
            )
            add_edge(
                _base_edge(
                    relation_type="HAS_CONSEQUENCE",
                    subject=node,
                    object_node=consequence_node,
                    confidence=rule.confidence,
                    evidence=evidence_ids,
                )
            )

        # Evidencia física: toda regla está respaldada.
        for evidence in rule.provenance:
            evidence_node = add_node(
                _base_node(
                    node_key=f"evidence:{evidence.evidence_id}",
                    node_type="Evidence",
                    label=(evidence.locator.get("locator") or "source/unknown")[:200],
                    text=evidence.excerpt,
                    confidence=evidence.strength,
                    block_ids=_blocks([evidence]),
                    document_id=document_id,
                    source_id=source_id,
                )
            )
            add_edge(
                _base_edge(
                    relation_type="SUPPORTED_BY",
                    subject=node,
                    object_node=evidence_node,
                    confidence=evidence.strength,
                    evidence=[evidence.evidence_id],
                )
            )

        # Relaciones declaradas por enlaces distribuidos.
        for relation, targets in rule.relations.items():
            for target in targets[:12]:
                target_node = add_node(
                    _base_node(
                        node_key=f"link:{relation.lower()}:{target}",
                        node_type=(
                            "Symbol"
                            if relation == "USES_SYMBOL"
                            else "Exception"
                            if relation == "HAS_EXCEPTION"
                            else "Evidence"
                            if relation == "SUPPORTED_BY"
                            else "Definition"
                        ),
                        label=str(target)[:200],
                        document_id=document_id,
                        source_id=source_id,
                    )
                )
                relation_type = relation if relation in _ALLOWED_LINK_RELATIONS else "DEPENDS_ON"
                add_edge(
                    _base_edge(
                        relation_type=relation_type,
                        subject=node,
                        object_node=target_node,
                        confidence=rule.confidence,
                        evidence=evidence_ids,
                    )
                )

        # Conflictos y supersesión (siempre mutuos para conflicto).
        for other in rule.conflicts_with:
            other_node = rule_nodes.get(other)
            if other_node is None:
                continue
            add_edge(
                _base_edge(
                    relation_type="CONFLICTS_WITH",
                    subject=node,
                    object_node=other_node,
                    confidence=0.8,
                    evidence=evidence_ids,
                )
            )
        for superseded in rule.supersedes:
            other_node = rule_nodes.get(superseded)
            if other_node is None:
                continue
            add_edge(
                _base_edge(
                    relation_type="SUPERSEDES",
                    subject=node,
                    object_node=other_node,
                    confidence=rule.confidence,
                    evidence=evidence_ids,
                )
            )
        if rule.kind == RuleKind.DEFINITION.value and rule.subject:
            add_edge(
                _base_edge(
                    relation_type="DEFINES",
                    subject=node,
                    object_node=add_node(
                        _base_node(
                            node_key=f"definition:{rule.subject.lower()[:160]}",
                            node_type="Definition",
                            label=rule.subject,
                            text=rule.statement,
                            document_id=document_id,
                            source_id=source_id,
                        )
                    ),
                    confidence=rule.confidence,
                    evidence=evidence_ids,
                )
            )

    return {
        "version": FABRIC_RULE_PROJECTION_VERSION,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "counts": {"nodes": len(nodes), "edges": len(edges)},
    }


_ALLOWED_LINK_RELATIONS = frozenset(
    {
        "DEFINES",
        "APPLIES_TO",
        "CONSTRAINS",
        "DEPENDS_ON",
        "HAS_CONDITION",
        "HAS_EXCEPTION",
        "HAS_CONSEQUENCE",
        "OVERRIDES",
        "SUPERSEDES",
        "USES_SYMBOL",
        "USES_UNIT",
        "SUPPORTED_BY",
        "CONFLICTS_WITH",
        "REFERENCES",
        "HAS_EXAMPLE",
    }
)


__all__ = [
    "FABRIC_RULE_PROJECTION_VERSION",
    "project_rules_to_fabric",
]
