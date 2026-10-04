# =============================================================================
# SemanticFabric — proyección global de significado (§21-22)
# =============================================================================
# Todo lo comprendido se proyecta a un grafo consultable:
#
#   nodos:  Entity, Concept, Definition, Claim, Rule, Condition, Exception,
#           Procedure, Metric, Attribute, Symbol, TableSemantic,
#           TemporalAssertion, Reference, Evidence
#   aristas: DEFINES, MENTIONS, USES, IS_A, PART_OF, HAS_ATTRIBUTE,
#            DEPENDS_ON, APPLIES_TO, CONSTRAINS, HAS_CONDITION,
#            HAS_EXCEPTION, REFERENCES, SUPPORTS, CONTRADICTS, SUPERSEDES,
#            DERIVED_FROM, ALIAS_OF, SAME_AS, RELATED_TO, VALID_FROM, VALID_TO
#
# Cross-source: el fabric NO fusiona por similitud. Propone candidatos con
# estado explícito (same_identity / likely_identity / alias_candidate /
# related_concept), evidencia, confianza y compatibilidad; la decisión es
# humana o de una fase posterior con autoridad declarada.
#
# Determinista. Toda arista conserva evidencia física (block_ids) y ventanas.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID, uuid5

from src.knowledge.compiler.model import normalize_term
from src.knowledge.representation.versions import FABRIC_REPRESENTATION_VERSION

from .global_model import GlobalSemanticModel
from .stitcher import StitchedUnit, StitchRelation

FABRIC_VERSION = "semantic-fabric-1"

FABRIC_NS = UUID("b8e2f5a7-4d1c-4a6e-9b3f-1e8c7d5a2f96")

#: Tipos de nodo del vocabulario de la misión (§21).
FABRIC_NODE_TYPES: tuple[str, ...] = (
    "Entity",
    "Concept",
    "Definition",
    "Claim",
    "Rule",
    "Condition",
    "Exception",
    "Procedure",
    "Event",
    "Metric",
    "Attribute",
    "Symbol",
    "TableSemantic",
    "TemporalAssertion",
    "Reference",
    "Evidence",
)

#: Tipos de arista del vocabulario de la misión (§21).
FABRIC_EDGE_TYPES: tuple[str, ...] = (
    "DEFINES",
    "MENTIONS",
    "USES",
    "IS_A",
    "PART_OF",
    "HAS_ATTRIBUTE",
    "DEPENDS_ON",
    "APPLIES_TO",
    "CONSTRAINS",
    "HAS_CONDITION",
    "HAS_EXCEPTION",
    "REFERENCES",
    "SUPPORTS",
    "CONTRADICTS",
    "SUPERSEDES",
    "DERIVED_FROM",
    "ALIAS_OF",
    "SAME_AS",
    "RELATED_TO",
    "VALID_FROM",
    "VALID_TO",
)

IDENTITY_STATUSES: tuple[str, ...] = (
    "same_identity",
    "likely_identity",
    "alias_candidate",
    "related_concept",
)

_NODE_TYPE_BY_UNIT: dict[str, str] = {
    "definition": "Definition",
    "symbol": "Symbol",
    "entity": "Entity",
    "concept": "Concept",
    "rule": "Rule",
    "condition": "Condition",
    "exception": "Exception",
    "procedure": "Procedure",
    "claim": "Claim",
    "temporal": "TemporalAssertion",
    "reference": "Reference",
    "unresolved_reference": "Reference",
    "table": "TableSemantic",
    "alias": "Concept",
    "conflict": "Claim",
    "note": "Evidence",
}

#: Relaciones del stitcher que se copian tal cual al vocabulario del fabric.
_DIRECT_EDGES = frozenset(
    {
        "DEFINES",
        "USES",
        "HAS_ATTRIBUTE",
        "HAS_CONDITION",
        "HAS_EXCEPTION",
        "REFERENCES",
        "ALIAS_OF",
        "SAME_AS",
        "CONTRADICTS",
        "SUPERSEDES",
        "PART_OF",
    }
)

_DEPENDENCY_SUBJECTS = frozenset({"Rule", "Condition", "Exception", "Procedure"})


@dataclass(frozen=True, kw_only=True)
class FabricNode:
    id: UUID
    node_key: str
    node_type: str
    label: str
    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    text: str = ""
    confidence: float = 0.6
    scope: str = "document"
    unit_key: str = ""
    block_ids: tuple[str, ...] = ()
    windows: tuple[int, ...] = ()
    attributes: dict = field(default_factory=dict)
    version: str = FABRIC_VERSION

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "node_key": self.node_key,
            "node_type": self.node_type,
            "label": self.label[:300],
            "text": self.text[:600],
            "confidence": round(float(self.confidence), 4),
            "scope": self.scope,
            "unit_key": self.unit_key,
            "block_ids": list(self.block_ids),
            "windows": list(self.windows),
            "attributes": dict(self.attributes),
            "derived": True,
            "canonical": False,
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class FabricEdge:
    id: UUID
    edge_key: str
    relation_type: str
    subject_id: UUID
    object_id: UUID
    subject_key: str
    object_key: str
    organization_id: UUID
    source_id: UUID | None = None
    workspace_id: UUID | None = None
    document_id: UUID | None = None
    confidence: float = 0.7
    method: str = "deterministic"
    evidence: tuple[str, ...] = ()
    windows: tuple[int, ...] = ()
    attributes: dict = field(default_factory=dict)
    version: str = FABRIC_VERSION

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "edge_key": self.edge_key,
            "relation_type": self.relation_type,
            "subject_id": str(self.subject_id),
            "object_id": str(self.object_id),
            "subject_key": self.subject_key,
            "object_key": self.object_key,
            "confidence": round(float(self.confidence), 4),
            "method": self.method,
            "evidence": list(self.evidence),
            "windows": list(self.windows),
            "attributes": dict(self.attributes),
            "derived": True,
            "canonical": False,
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class IdentityCandidate:
    id: UUID
    identity_status: str
    left_node_id: UUID
    right_node_id: UUID
    left_key: str
    right_key: str
    left_label: str
    right_label: str
    organization_id: UUID
    left_document_id: UUID | None = None
    right_document_id: UUID | None = None
    left_source_id: UUID | None = None
    right_source_id: UUID | None = None
    confidence: float = 0.5
    reason: str = ""
    evidence: dict = field(default_factory=dict)
    temporal_compatible: bool = True
    scope_compatible: bool = True
    version: str = FABRIC_VERSION

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "identity_status": self.identity_status,
            "left_node_id": str(self.left_node_id),
            "right_node_id": str(self.right_node_id),
            "left_key": self.left_key,
            "right_key": self.right_key,
            "left_label": self.left_label[:200],
            "right_label": self.right_label[:200],
            "left_document_id": str(self.left_document_id)
            if self.left_document_id
            else None,
            "right_document_id": str(self.right_document_id)
            if self.right_document_id
            else None,
            "left_source_id": str(self.left_source_id)
            if self.left_source_id
            else None,
            "right_source_id": str(self.right_source_id)
            if self.right_source_id
            else None,
            "confidence": round(float(self.confidence), 4),
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "temporal_compatible": bool(self.temporal_compatible),
            "scope_compatible": bool(self.scope_compatible),
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class FabricProjection:
    nodes: tuple[FabricNode, ...] = ()
    edges: tuple[FabricEdge, ...] = ()
    identity_candidates: tuple[IdentityCandidate, ...] = ()
    stats: dict = field(default_factory=dict)
    version: str = FABRIC_VERSION

    def to_dict(self) -> dict:
        counts: dict[str, int] = {}
        for node in self.nodes:
            counts[node.node_type] = counts.get(node.node_type, 0) + 1
        edge_counts: dict[str, int] = {}
        for edge in self.edges:
            edge_counts[edge.relation_type] = edge_counts.get(edge.relation_type, 0) + 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "identity_candidates": len(self.identity_candidates),
            "node_types": counts,
            "edge_types": edge_counts,
            "stats": dict(self.stats),
            "version": self.version,
        }


class SemanticFabricBuilder:
    """Proyecta el modelo global a nodos/aristas + identidad cross-source."""

    version = FABRIC_VERSION

    def __init__(
        self,
        *,
        max_nodes: int = 20000,
        max_edges: int = 50000,
        max_evidence_nodes: int = 5000,
        max_identity_candidates: int = 2000,
        max_candidates_per_node: int = 5,
    ) -> None:
        self._max_nodes = max(1, int(max_nodes))
        self._max_edges = max(1, int(max_edges))
        self._max_evidence = max(1, int(max_evidence_nodes))
        self._max_candidates = max(1, int(max_identity_candidates))
        self._per_node = max(1, int(max_candidates_per_node))

    def project(
        self,
        *,
        document,
        global_model: GlobalSemanticModel,
        units: list[StitchedUnit],
        relations: list[StitchRelation],
        existing_nodes: list[dict] | None = None,
    ) -> FabricProjection:
        document_id = getattr(document, "id", None)
        nodes: dict[str, FabricNode] = {}
        edges: dict[str, FabricEdge] = {}

        for unit in units:
            node = self._node_from_unit(document, unit, document_id)
            if node is None:
                continue
            nodes[node.node_key] = node

        evidence_nodes = self._evidence_nodes(document, units, document_id)
        for key, node in evidence_nodes.items():
            nodes.setdefault(key, node)

        self._edges_from_relations(nodes, relations, edges, document_id)
        self._derived_edges(nodes, edges, document_id)
        self._evidence_edges(nodes, edges, units, document_id)

        node_list = list(nodes.values())[: self._max_nodes]
        edge_list = list(edges.values())[: self._max_edges]
        candidates = self._identity_candidates(
            nodes=node_list,
            existing_nodes=list(existing_nodes or ()),
            document_id=document_id,
        )
        return FabricProjection(
            nodes=tuple(node_list),
            edges=tuple(edge_list),
            identity_candidates=tuple(candidates[: self._max_candidates]),
            stats={
                "units": len(units),
                "relations": len(relations),
                "global_fingerprint": global_model.fingerprint,
                "evidence_nodes": len(evidence_nodes),
            },
        )

    # ------------------------------------------------------------------
    def _node_from_unit(
        self, document, unit: StitchedUnit, document_id
    ) -> FabricNode | None:
        node_type = _NODE_TYPE_BY_UNIT.get(unit.unit_kind)
        if node_type is None:
            return None
        if unit.unit_kind == "entity" and unit.attributes.get("entity_type") == "field":
            node_type = "Attribute"
        node_key = f"{node_type}:{unit.unit_key}"
        return FabricNode(
            id=uuid5(FABRIC_NS, f"{document_id}|{node_key}"),
            node_key=node_key,
            node_type=node_type,
            label=unit.label,
            organization_id=document.organization_id,
            source_id=document.source_id,
            workspace_id=document.workspace_id,
            document_id=document.id,
            text=unit.text,
            confidence=float(unit.confidence),
            unit_key=unit.unit_key,
            block_ids=unit.block_ids,
            windows=unit.source_windows,
            attributes={
                **dict(unit.attributes),
                "regions": list(unit.attributes.get("regions") or ()),
            },
        )

    def _evidence_nodes(
        self, document, units: list[StitchedUnit], document_id
    ) -> dict[str, FabricNode]:
        seen: dict[str, FabricNode] = {}
        for unit in units:
            for block_id in unit.block_ids:
                if len(seen) >= self._max_evidence:
                    return seen
                node_key = f"Evidence:block:{block_id}"
                if node_key in seen:
                    continue
                seen[node_key] = FabricNode(
                    id=uuid5(FABRIC_NS, f"{document_id}|{node_key}"),
                    node_key=node_key,
                    node_type="Evidence",
                    label=str(block_id)[:36],
                    organization_id=document.organization_id,
                    source_id=document.source_id,
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    confidence=1.0,
                    unit_key=unit.unit_key,
                    block_ids=(str(block_id),),
                    windows=unit.source_windows,
                    attributes={"block_id": str(block_id)},
                )
        return seen

    def _edges_from_relations(
        self,
        nodes: dict[str, FabricNode],
        relations: list[StitchRelation],
        edges: dict[str, FabricEdge],
        document_id,
    ) -> None:
        node_by_unit: dict[str, FabricNode] = {}
        for node in nodes.values():
            if node.node_type != "Evidence" and node.unit_key:
                node_by_unit.setdefault(node.unit_key, node)
        for relation in relations:
            subject = node_by_unit.get(relation.subject_key)
            object_node = node_by_unit.get(relation.object_key)
            if subject is None or object_node is None:
                continue
            if relation.relation_type not in _DIRECT_EDGES:
                continue
            self._add_edge(
                edges,
                document_id=document_id,
                relation_type=relation.relation_type,
                subject=subject,
                object_node=object_node,
                confidence=float(relation.confidence),
                evidence=relation.evidence,
                windows=relation.windows,
                attributes=dict(relation.attributes),
            )

    def _derived_edges(
        self,
        nodes: dict[str, FabricNode],
        edges: dict[str, FabricEdge],
        document_id,
    ) -> None:
        by_id = {node.id: node for node in nodes.values()}
        for edge in list(edges.values()):
            subject = by_id.get(edge.subject_id)
            object_node = by_id.get(edge.object_id)
            if subject is None or object_node is None:
                continue
            if edge.relation_type == "USES" and subject.node_type in _DEPENDENCY_SUBJECTS:
                self._add_edge(
                    edges,
                    document_id=document_id,
                    relation_type="DEPENDS_ON",
                    subject=subject,
                    object_node=object_node,
                    confidence=round(edge.confidence * 0.9, 4),
                    evidence=edge.evidence,
                    windows=edge.windows,
                    attributes={"derived_from": "USES"},
                )
                if object_node.node_type in {"Symbol", "Entity", "Attribute"}:
                    self._add_edge(
                        edges,
                        document_id=document_id,
                        relation_type="CONSTRAINS",
                        subject=subject,
                        object_node=object_node,
                        confidence=round(edge.confidence * 0.8, 4),
                        evidence=edge.evidence,
                        windows=edge.windows,
                        attributes={"derived_from": "USES"},
                    )
            if edge.relation_type in {"HAS_CONDITION", "HAS_EXCEPTION"}:
                self._add_edge(
                    edges,
                    document_id=document_id,
                    relation_type="DEPENDS_ON",
                    subject=subject,
                    object_node=object_node,
                    confidence=round(edge.confidence * 0.9, 4),
                    evidence=edge.evidence,
                    windows=edge.windows,
                    attributes={"derived_from": edge.relation_type},
                )
            if (
                edge.relation_type == "HAS_ATTRIBUTE"
                and subject.node_type in {"Entity", "Attribute"}
                and object_node.node_type == "Symbol"
            ):
                self._add_edge(
                    edges,
                    document_id=document_id,
                    relation_type="APPLIES_TO",
                    subject=object_node,
                    object_node=subject,
                    confidence=round(edge.confidence * 0.8, 4),
                    evidence=edge.evidence,
                    windows=edge.windows,
                    attributes={"derived_from": "HAS_ATTRIBUTE"},
                )

        # MENTIONS: una definición menciona símbolos/entidades de su texto.
        definitions = [node for node in nodes.values() if node.node_type == "Definition"]
        targets = [
            node
            for node in nodes.values()
            if node.node_type in {"Symbol", "Entity", "Concept", "Attribute"}
        ]
        for definition in definitions:
            for target in targets:
                if target.label and target.label in (definition.text or ""):
                    self._add_edge(
                        edges,
                        document_id=document_id,
                        relation_type="MENTIONS",
                        subject=definition,
                        object_node=target,
                        confidence=0.7,
                        evidence=definition.block_ids,
                        windows=definition.windows,
                    )

        # SUPPORTS: un claim que menciona la regla en su ventana.
        claims = [node for node in nodes.values() if node.node_type == "Claim"]
        rules = [node for node in nodes.values() if node.node_type == "Rule"]
        for claim in claims:
            for rule in rules:
                if (
                    set(claim.windows).intersection(rule.windows)
                    and rule.label
                    and rule.label.split()[0].casefold() in claim.text.casefold()
                ):
                    self._add_edge(
                        edges,
                        document_id=document_id,
                        relation_type="SUPPORTS",
                        subject=claim,
                        object_node=rule,
                        confidence=0.6,
                        evidence=claim.block_ids,
                        windows=claim.windows,
                    )

        # VALID_FROM: temporal assertions vigen una regla/claim de su ventana.
        temporals = [
            node for node in nodes.values() if node.node_type == "TemporalAssertion"
        ]
        for temporal in temporals:
            for target in (*rules, *claims):
                if set(temporal.windows).intersection(target.windows):
                    self._add_edge(
                        edges,
                        document_id=document_id,
                        relation_type="VALID_FROM",
                        subject=target,
                        object_node=temporal,
                        confidence=0.5,
                        evidence=temporal.block_ids,
                        windows=temporal.windows,
                        attributes={"requires_review": True},
                    )

    def _evidence_edges(
        self,
        nodes: dict[str, FabricNode],
        edges: dict[str, FabricEdge],
        units: list[StitchedUnit],
        document_id,
    ) -> None:
        for unit in units:
            node_type = _NODE_TYPE_BY_UNIT.get(unit.unit_kind)
            if node_type is None:
                continue
            if unit.unit_kind == "entity" and unit.attributes.get("entity_type") == "field":
                node_type = "Attribute"
            subject = nodes.get(f"{node_type}:{unit.unit_key}")
            if subject is None:
                continue
            for block_id in unit.block_ids:
                evidence = nodes.get(f"Evidence:block:{block_id}")
                if evidence is None:
                    continue
                self._add_edge(
                    edges,
                    document_id=document_id,
                    relation_type="DERIVED_FROM",
                    subject=subject,
                    object_node=evidence,
                    confidence=1.0,
                    evidence=(str(block_id),),
                    windows=unit.source_windows,
                    attributes={"unit_key": unit.unit_key},
                )

    def _add_edge(
        self,
        edges: dict[str, FabricEdge],
        *,
        document_id,
        relation_type: str,
        subject: FabricNode,
        object_node: FabricNode,
        confidence: float,
        evidence: tuple[str, ...] = (),
        windows: tuple[int, ...] = (),
        attributes: dict | None = None,
    ) -> None:
        key = f"{relation_type}:{subject.node_key}->{object_node.node_key}"
        if key in edges:
            return
        edges[key] = FabricEdge(
            id=uuid5(FABRIC_NS, f"{document_id}|{key}"),
            edge_key=key,
            relation_type=relation_type,
            subject_id=subject.id,
            object_id=object_node.id,
            subject_key=subject.node_key,
            object_key=object_node.node_key,
            organization_id=subject.organization_id,
            source_id=subject.source_id,
            workspace_id=subject.workspace_id,
            document_id=subject.document_id,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            evidence=tuple(dict.fromkeys(evidence))[:32],
            windows=tuple(sorted({*windows, *subject.windows, *object_node.windows})),
            attributes=dict(attributes or {}),
        )

    # ------------------------------------------------------------------
    def _identity_candidates(
        self,
        *,
        nodes: list[FabricNode],
        existing_nodes: list[dict],
        document_id,
    ) -> list[IdentityCandidate]:
        """Cross-source: propone identidad, nunca fusiona."""
        candidates: list[IdentityCandidate] = []
        per_node: dict[str, int] = {}
        index = _existing_index(existing_nodes)
        for node in nodes:
            if node.node_type == "Evidence":
                continue
            label = normalize_term(node.label)
            if len(label) < 2:
                continue
            for other in index.get(label, ()):
                if str(other.get("document_id") or "") == str(document_id):
                    continue
                status, confidence, reason = _identity_status(node, other)
                if status is None:
                    continue
                left_id = node.id
                right_id = _as_uuid(other.get("id"))
                if right_id is None:
                    continue
                key = tuple(sorted((str(left_id), str(right_id))))
                if per_node.get(str(left_id), 0) >= self._per_node:
                    break
                per_node[str(left_id)] = per_node.get(str(left_id), 0) + 1
                candidates.append(
                    IdentityCandidate(
                        id=uuid5(FABRIC_NS, f"{key[0]}|{key[1]}|{status}"),
                        identity_status=status,
                        left_node_id=left_id,
                        right_node_id=right_id,
                        left_key=node.node_key,
                        right_key=str(other.get("node_key") or ""),
                        left_label=node.label,
                        right_label=str(other.get("label") or ""),
                        organization_id=node.organization_id,
                        left_document_id=node.document_id,
                        right_document_id=_as_uuid(other.get("document_id")),
                        left_source_id=node.source_id,
                        right_source_id=_as_uuid(other.get("source_id")),
                        confidence=confidence,
                        reason=reason,
                        evidence={
                            "left": {
                                "node_key": node.node_key,
                                "unit_key": node.unit_key,
                                "block_ids": list(node.block_ids)[:8],
                            },
                            "right": {
                                "node_key": other.get("node_key"),
                                "unit_key": other.get("unit_key"),
                                "block_ids": list(other.get("block_ids") or ())[:8],
                            },
                        },
                        temporal_compatible=_temporal_compatible(node, other),
                        scope_compatible=True,
                    )
                )
        return candidates


def _existing_index(existing_nodes: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for node in existing_nodes:
        label = normalize_term(str(node.get("label") or ""))
        if len(label) < 2:
            continue
        index.setdefault(label, []).append(node)
    return index


def _identity_status(node: FabricNode, other: dict) -> tuple[str | None, float, str]:
    other_type = str(other.get("node_type") or "")
    other_label = normalize_term(str(other.get("label") or ""))
    label = normalize_term(node.label)
    if not other_label:
        return None, 0.0, ""
    if node.node_type == other_type and label == other_label:
        return "same_identity", 0.9, "same_type_same_normalized_label"
    if node.node_type == other_type:
        left_tokens = set(label.split())
        right_tokens = set(other_label.split())
        if left_tokens and (
            left_tokens <= right_tokens or right_tokens <= left_tokens
        ):
            return "likely_identity", 0.7, "same_type_token_subset"
    if node.node_type != other_type and label == other_label:
        return "alias_candidate", 0.6, "different_type_same_label"
    left_tokens = set(label.split())
    right_tokens = set(other_label.split())
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / max(
            1, len(left_tokens | right_tokens)
        )
        if overlap >= 0.5:
            return "related_concept", 0.5, "token_overlap"
    return None, 0.0, ""


def _temporal_compatible(node: FabricNode, other: dict) -> bool:
    """Compatibilidad temporal conservadora: solo descarta rangos disjuntos."""
    left_from = node.attributes.get("valid_from")
    left_to = node.attributes.get("valid_to")
    right_from = other.get("valid_from")
    right_to = other.get("valid_to")
    if left_to and right_from and str(left_to) < str(right_from):
        return False
    if right_to and left_from and str(right_to) < str(left_from):
        return False
    return True


def _as_uuid(value) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class FabricRetrievalContext:
    """Vista compacta del fabric para enriquecer retrieval units (Fase 9).

    El chunk NO reemplaza su evidencia: agrega ids del fabric + vecindad
    semántica + labels. `shadow` solo anota payload; `active` además suma los
    labels al texto sparse (recall lexical), nunca al dense.
    """

    version: str = FABRIC_REPRESENTATION_VERSION
    document_id: str = ""
    mode: str = "shadow"
    nodes_by_block: dict = field(default_factory=dict)
    node_by_id: dict = field(default_factory=dict)
    edges_by_node: dict = field(default_factory=dict)

    @property
    def enabled(self) -> bool:
        return self.mode in ("shadow", "active") and bool(self.node_by_id)

    def chunk_fields(
        self,
        block_ids,
        *,
        unit_key: str | None = None,
        max_ids: int = 16,
        max_neighbors: int = 12,
        max_labels: int = 16,
    ) -> dict:
        nodes = self._nodes_for(block_ids, unit_key=unit_key)
        if not nodes:
            return {}
        node_ids = {str(node["id"]) for node in nodes}
        by_type: dict[str, list[str]] = {}
        labels: list[str] = []
        unit_keys: list[str] = []
        for node in nodes:
            node_type = str(node.get("node_type") or "")
            if node_type == "Evidence":
                continue
            by_type.setdefault(node_type, [])
            if node["id"] not in by_type[node_type]:
                by_type[node_type].append(str(node["id"]))
            unit_key = str(node.get("unit_key") or "")
            if unit_key and unit_key not in unit_keys:
                unit_keys.append(unit_key)
            label = str(node.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)

        def ids_for(*types: str) -> list[str]:
            values: list[str] = []
            for node_type in types:
                for value in by_type.get(node_type, ()):
                    if value not in values:
                        values.append(value)
            return values[:max_ids]

        dependency_ids: list[str] = []
        neighborhood: list[dict] = []
        seen_neighbors: set[tuple[str, str]] = set()
        for node in nodes:
            for edge in self.edges_by_node.get(str(node["id"]), ()):
                relation_type = str(edge.get("relation_type") or "")
                if relation_type in _DEPENDENCY_EDGE_TYPES and edge["id"] not in dependency_ids:
                    dependency_ids.append(str(edge["id"]))
                other_id = (
                    str(edge.get("object_id"))
                    if str(edge.get("subject_id")) == str(node["id"])
                    else str(edge.get("subject_id"))
                )
                if other_id in node_ids:
                    continue
                other = self.node_by_id.get(other_id)
                if other is None or other.get("node_type") == "Evidence":
                    continue
                key = (relation_type, other_id)
                if key in seen_neighbors or len(neighborhood) >= max_neighbors:
                    continue
                seen_neighbors.add(key)
                neighborhood.append(
                    {
                        "relation": relation_type,
                        "node_id": other_id,
                        "node_type": other.get("node_type"),
                        "label": str(other.get("label") or "")[:120],
                        "direction": (
                            "out" if str(edge.get("subject_id")) == str(node["id"]) else "in"
                        ),
                    }
                )

        payload: dict = {
            "fabric_version": self.version,
            "fabric_mode": self.mode,
            "fabric_node_ids": [str(node["id"]) for node in nodes][:max_ids],
            "semantic_unit_ids": unit_keys[:max_ids],
            "fabric_node_types": sorted(by_type),
            "fabric_labels": labels[:max_labels],
        }
        optional = {
            "concept_ids": ids_for("Concept"),
            "entity_ids": ids_for("Entity", "Attribute"),
            "rule_ids": ids_for("Rule"),
            "definition_ids": ids_for("Definition"),
            "exception_ids": ids_for("Exception"),
            "condition_ids": ids_for("Condition"),
            "symbol_ids": ids_for("Symbol"),
            "claim_ids": ids_for("Claim"),
            "procedure_ids": ids_for("Procedure"),
            "table_ids": ids_for("TableSemantic"),
            "temporal_ids": ids_for("TemporalAssertion"),
            "reference_ids": ids_for("Reference"),
            "fabric_dependency_ids": dependency_ids[:max_ids],
            "semantic_neighborhood": neighborhood,
        }
        payload.update({key: value for key, value in optional.items() if value})
        return payload

    def sparse_labels(self, block_ids, *, max_labels: int = 12) -> list[str]:
        """Labels del fabric que tocan el chunk (para la pata sparse en active)."""
        if self.mode != "active":
            return []
        labels: list[str] = []
        for node in self._nodes_for(block_ids, unit_key=None):
            if node.get("node_type") == "Evidence":
                continue
            label = str(node.get("label") or "").strip()
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= max_labels:
                break
        return labels

    def _nodes_for(self, block_ids, *, unit_key: str | None) -> list[dict]:
        found: dict[str, dict] = {}
        for raw in block_ids or ():
            for node in self.nodes_by_block.get(str(raw), ()):
                found.setdefault(str(node["id"]), node)
        if unit_key:
            for node in self.node_by_id.values():
                if str(node.get("unit_key") or "") == str(unit_key):
                    found.setdefault(str(node["id"]), node)
        return list(found.values())


_DEPENDENCY_EDGE_TYPES = frozenset(
    {"DEPENDS_ON", "USES", "HAS_EXCEPTION", "HAS_CONDITION", "HAS_ATTRIBUTE"}
)


def build_retrieval_context(
    nodes: list[dict],
    edges: list[dict],
    *,
    document_id=None,
    mode: str = "shadow",
    max_nodes: int = 20000,
    max_edges: int = 50000,
) -> FabricRetrievalContext:
    """Indexa el fabric por bloque/nodo para enriquecer chunks (Fase 9)."""
    if mode == "off":
        return FabricRetrievalContext(document_id=str(document_id or ""), mode="off")
    node_by_id: dict[str, dict] = {}
    nodes_by_block: dict[str, list[dict]] = {}
    for node in nodes[:max_nodes]:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        node_by_id[node_id] = node
        for block_id in node.get("block_ids") or ():
            nodes_by_block.setdefault(str(block_id), []).append(node)
    edges_by_node: dict[str, list[dict]] = {}
    for edge in edges[:max_edges]:
        subject = str(edge.get("subject_id") or "")
        object_id = str(edge.get("object_id") or "")
        if subject:
            edges_by_node.setdefault(subject, []).append(edge)
        if object_id and object_id != subject:
            edges_by_node.setdefault(object_id, []).append(edge)
    return FabricRetrievalContext(
        document_id=str(document_id or ""),
        mode=mode,
        nodes_by_block=nodes_by_block,
        node_by_id=node_by_id,
        edges_by_node=edges_by_node,
    )


def projection_fingerprint(projection: FabricProjection) -> str:
    material = {
        "version": projection.version,
        "nodes": [node.node_key for node in projection.nodes],
        "edges": [edge.edge_key for edge in projection.edges],
        "identities": [
            candidate.id for candidate in projection.identity_candidates
        ],
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "FABRIC_EDGE_TYPES",
    "FABRIC_NS",
    "FABRIC_NODE_TYPES",
    "FABRIC_VERSION",
    "IDENTITY_STATUSES",
    "FabricEdge",
    "FabricNode",
    "FabricProjection",
    "FabricRetrievalContext",
    "IdentityCandidate",
    "SemanticFabricBuilder",
    "build_retrieval_context",
    "projection_fingerprint",
]
