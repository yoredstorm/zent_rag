# =============================================================================
# SemanticQueryPlan — la pregunta se interpreta contra el fabric aprendido.
# El vector search localiza evidencia después. No hay diccionario de dominio.
# =============================================================================
from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from src.infrastructure.observability.logging_config import get_logger

from .rollout import ACTIVE

logger = get_logger(__name__)

LEGACY_RETRIEVAL = "LEGACY_RETRIEVAL"
SEMANTIC_GLOBAL = "SEMANTIC_GLOBAL"

_ENTITY_TYPES = frozenset({"Concept", "Entity", "Definition"})
_ASPECT_TYPES = frozenset({"Attribute", "TemporalAssertion", "Definition"})
_HOP_RELATIONS = frozenset(
    {
        "HAS_FIELD",
        "HAS_ATTRIBUTE",
        "REFERENCES",
        "DEFINES",
        "ALIAS_OF",
        "PART_OF",
        "RELATED_TO",
        "APPLIES_TO",
    }
)
_MAX_NODES = 80
_MAX_HOPS = 8


@dataclass(frozen=True)
class SemanticQueryPlan:
    knowledge_mode: str
    entities: tuple[str, ...] = ()
    concepts: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    activated: tuple[dict, ...] = ()
    search_query: str = ""
    aspect_labels: tuple[str, ...] = ()
    hops: int = 0

    def to_public_dict(self) -> dict:
        return {
            "knowledge_mode": self.knowledge_mode,
            "semantic_entities": list(self.entities),
            "semantic_concepts": list(self.concepts),
            "regions_activated": list(self.regions),
            "fabric_nodes_activated": len(self.activated),
            "graph_hops": self.hops,
            "search_query": self.search_query,
        }


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def _node_text(node: dict) -> str:
    label = " ".join(str(node.get("label") or "").split())
    body = " ".join(str(node.get("text") or "").split())
    if body and body.casefold() not in label.casefold():
        return f"{label}. {body[:240]}".strip()
    return label


def activate_nodes(
    question_vector: list[float],
    nodes: list[dict],
    vectors: list[list[float]],
    *,
    min_score: float = 0.42,
    limit: int = 6,
) -> list[dict]:
    """Rankea nodos aprendidos por similitud. El embedder es el puente de idioma."""
    ranked: list[dict] = []
    for node, vector in zip(nodes, vectors):
        label = " ".join(str(node.get("label") or "").split())
        if not label:
            continue
        score = _cosine(question_vector, vector)
        if score < min_score:
            continue
        ranked.append(
            {
                "id": str(node.get("id") or ""),
                "label": label,
                "node_type": str(node.get("node_type") or ""),
                "score": round(score, 4),
                "block_ids": list(node.get("block_ids") or ()),
                "document_id": str(node.get("document_id") or ""),
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["label"].lower()))
    return ranked[: max(1, int(limit))]


def expand_one_hop(
    activated: list[dict],
    nodes: list[dict],
    edges: list[dict],
    *,
    limit: int = _MAX_HOPS,
) -> list[dict]:
    """Un salto desde los nodos activados. No recorre el grafo entero."""
    by_id = {str(node.get("id") or ""): node for node in nodes}
    seen = {item["id"] for item in activated if item.get("id")}
    extra: list[dict] = []
    seeds = {item["id"] for item in activated if item.get("id")}
    for edge in edges:
        if str(edge.get("relation_type") or "") not in _HOP_RELATIONS:
            continue
        if float(edge.get("confidence") or 0) < 0.5:
            continue
        subject = str(edge.get("subject_id") or "")
        object_id = str(edge.get("object_id") or "")
        other = ""
        if subject in seeds and object_id not in seen:
            other = object_id
        elif object_id in seeds and subject not in seen:
            other = subject
        if not other:
            continue
        node = by_id.get(other)
        if node is None:
            continue
        kind = str(node.get("node_type") or "")
        if kind not in _ASPECT_TYPES and kind not in _ENTITY_TYPES:
            continue
        label = " ".join(str(node.get("label") or "").split())
        if not label:
            continue
        seen.add(other)
        extra.append(
            {
                "id": other,
                "label": label,
                "node_type": kind,
                "score": round(float(edge.get("confidence") or 0), 4),
                "block_ids": list(node.get("block_ids") or ()),
                "document_id": str(node.get("document_id") or ""),
                "hop": 1,
            }
        )
        if len(extra) >= limit:
            break
    return extra


def build_plan(question: str, activated: list[dict], *, hops: int = 0) -> SemanticQueryPlan:
    if not activated:
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    entities: list[str] = []
    aspects: list[str] = []
    regions: list[str] = []
    for item in activated:
        label = item["label"]
        kind = item["node_type"]
        if kind in _ENTITY_TYPES and label not in entities:
            entities.append(label)
        if kind in _ASPECT_TYPES and label not in aspects:
            aspects.append(label)
        for block in item.get("block_ids") or ():
            text = str(block)
            if text and text not in regions and len(regions) < 8:
                regions.append(text)
    labels: list[str] = []
    for label in (*entities, *aspects):
        if label not in labels:
            labels.append(label)
    if not labels:
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    return SemanticQueryPlan(
        knowledge_mode=SEMANTIC_GLOBAL,
        entities=tuple(entities),
        concepts=tuple(aspects),
        regions=tuple(regions),
        activated=tuple(activated),
        search_query=" ".join(labels),
        aspect_labels=tuple(aspects),
        hops=hops,
    )


def _as_vectors(raw) -> list[list[float]]:
    if not raw:
        return []
    if isinstance(raw[0], (int, float)):
        return [list(raw)]
    return [list(item) for item in raw]


async def resolve_semantic_query(
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    question: str,
    embedder,
    store=None,
) -> SemanticQueryPlan:
    """ACTIVE consulta el fabric. Sin modelo, o si el modo no es active: legacy."""
    from .rollout import resolve_semantic_mode
    from .service import _setting

    global_mode = str(_setting("KNOWLEDGE_SEMANTIC_INGESTION_MODE", "off") or "off")
    mode = resolve_semantic_mode(
        organization_id=organization_id,
        workspace_id=workspace_id,
        global_mode=global_mode,
    )
    if mode != ACTIVE or not str(question or "").strip():
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    if store is None:
        from .store import PostgresSemanticIngestionStore

        store = PostgresSemanticIngestionStore()
    try:
        document_ids = await store.list_modeled_document_ids(
            organization_id, workspace_id=workspace_id, limit=8
        )
    except Exception:
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    nodes: list[dict] = []
    edges: list[dict] = []
    for document_id in document_ids:
        try:
            found = await store.list_fabric_nodes(
                organization_id, document_id=document_id, limit=2000
            )
            found_edges = await store.list_fabric_edges(
                organization_id, document_id=document_id, limit=4000
            )
        except Exception as exc:  # noqa: BLE001 — un documento ilegible no corta el plan
            logger.warning(
                "Semantic query plan skipped a document",
                document_id=str(document_id),
                error=str(exc)[:150],
            )
            continue
        for node in found:
            node["document_id"] = str(document_id)
            kind = str(node.get("node_type") or "")
            if kind in _ENTITY_TYPES or kind in _ASPECT_TYPES:
                nodes.append(node)
        edges.extend(found_edges)
    nodes = nodes[:_MAX_NODES]
    if not nodes or embedder is None:
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    texts = [question, *(_node_text(node) for node in nodes)]
    try:
        embedded = _as_vectors(await embedder.embed(texts))
    except Exception:
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    if len(embedded) != len(texts):
        return SemanticQueryPlan(knowledge_mode=LEGACY_RETRIEVAL)
    activated = activate_nodes(embedded[0], nodes, embedded[1:])
    hopped = expand_one_hop(activated, nodes, edges)
    merged = list(activated)
    seen = {item["id"] for item in merged}
    for item in hopped:
        if item["id"] not in seen:
            merged.append(item)
            seen.add(item["id"])
    return build_plan(question, merged, hops=1 if hopped else 0)
