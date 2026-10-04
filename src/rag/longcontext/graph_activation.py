# =============================================================================
# Graph-aware retrieval — spreading activation controlado (§37-42)
# =============================================================================
# El Semantic Fabric participa del retrieval, no solo de la UI:
#
#   seeds (dense/sparse/exact) -> nodos del fabric -> vecinos por relación
#   -> chunks que contienen esos nodos -> contexto.
#
# Activación LIMITADA por: tipos de relación, confianza, hops, nodos, decay y
# presupuesto de chunks. Nada de recorrer el grafo completo.
# =============================================================================
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from src.core.domain.entities import RetrievalChunk

from .expansion import Expansion, ExpansionContext, ExpansionStrategy

GRAPH_ACTIVATION_VERSION = "graph-activation-1"

#: Relaciones que propagan activación (semánticas, no estructurales).
ACTIVATION_RELATIONS: tuple[str, ...] = (
    "DEFINES",
    "USES",
    "DEPENDS_ON",
    "HAS_ATTRIBUTE",
    "APPLIES_TO",
    "CONSTRAINS",
    "HAS_CONDITION",
    "HAS_EXCEPTION",
    "REFERENCES",
    "ALIAS_OF",
    "SAME_AS",
    "CONTRADICTS",
    "SUPERSEDES",
    "PART_OF",
    "SUPPORTS",
    "MENTIONS",
    "DERIVED_FROM",
)


@dataclass(frozen=True, kw_only=True)
class ActivationPolicy:
    """Límites duros de la activación: nunca se recorre todo el grafo."""

    max_hops: int = 2
    max_nodes: int = 48
    max_seed_nodes: int = 24
    max_edges: int = 4000
    min_confidence: float = 0.35
    decay: float = 0.75
    relation_whitelist: tuple[str, ...] = ACTIVATION_RELATIONS


@dataclass(frozen=True, kw_only=True)
class ActivatedNode:
    node_id: str
    label: str
    node_type: str
    hop: int
    activation: float
    via_relation: str

    def to_public_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "label": self.label[:120],
            "node_type": self.node_type,
            "hop": self.hop,
            "activation": round(float(self.activation), 4),
            "via_relation": self.via_relation,
        }


def spreading_activation(
    seed_node_ids: list[str] | tuple[str, ...],
    edges: list[dict],
    *,
    policy: ActivationPolicy | None = None,
) -> dict[str, ActivatedNode]:
    """Activa vecinos desde las semillas con decay y límites duros.

    `edges` son dicts del fabric (subject_id, object_id, relation_type,
    confidence). Devuelve nodo_id -> ActivatedNode (incluye semillas con
    hop 0 y activation 1.0).
    """
    limits = policy or ActivationPolicy()
    seeds = [str(value) for value in seed_node_ids if value][: limits.max_seed_nodes]
    activated: dict[str, ActivatedNode] = {
        seed: ActivatedNode(
            node_id=seed,
            label="",
            node_type="",
            hop=0,
            activation=1.0,
            via_relation="seed",
        )
        for seed in seeds
    }
    if not seeds or limits.max_hops <= 0:
        return activated
    edges = list(edges)[: limits.max_edges]
    frontier = set(seeds)
    for hop in range(1, limits.max_hops + 1):
        next_frontier: set[str] = set()
        for edge in edges:
            if len(activated) >= limits.max_nodes:
                break
            relation = str(edge.get("relation_type") or "")
            if relation not in limits.relation_whitelist:
                continue
            confidence = _confidence(edge)
            if confidence < limits.min_confidence:
                continue
            subject = str(edge.get("subject_id") or "")
            object_id = str(edge.get("object_id") or "")
            for source, target in ((subject, object_id), (object_id, subject)):
                if source not in frontier or not target or target in activated:
                    continue
                parent = activated[source]
                activation = parent.activation * confidence * limits.decay
                if activation < limits.min_confidence:
                    continue
                activated[target] = ActivatedNode(
                    node_id=target,
                    label=str(edge.get("object_label") or edge.get("subject_label") or ""),
                    node_type=str(edge.get("object_kind") or edge.get("subject_kind") or ""),
                    hop=hop,
                    activation=round(activation, 6),
                    via_relation=relation,
                )
                next_frontier.add(target)
        frontier = next_frontier
        if not frontier:
            break
    return activated


def _confidence(edge: dict) -> float:
    try:
        value = float(edge.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, value))


def seed_node_ids_from_chunks(chunks: list[RetrievalChunk]) -> list[str]:
    """Ids de nodos del fabric presentes en los chunks semilla."""
    seeds: list[str] = []
    for chunk in chunks:
        values = (chunk.metadata or {}).get("fabric_node_ids") or ()
        if isinstance(values, str):
            values = [values]
        for value in values:
            text = str(value or "")
            if text and text not in seeds:
                seeds.append(text)
    return seeds


def _chunk_key(chunk: RetrievalChunk) -> tuple[str, str]:
    metadata = chunk.metadata or {}
    identity = str(metadata.get("chunk_id") or metadata.get("unit_id") or "")
    if not identity:
        identity = (chunk.content or "")[:80]
    return str(chunk.document_id), identity


def _rank_by_activation(
    chunks: list[RetrievalChunk], activated: dict[str, ActivatedNode]
) -> list[RetrievalChunk]:
    def best(chunk: RetrievalChunk) -> float:
        values = (chunk.metadata or {}).get("fabric_node_ids") or ()
        if isinstance(values, str):
            values = [values]
        score = 0.0
        for value in values:
            node = activated.get(str(value or ""))
            if node is not None and node.activation > score:
                score = node.activation
        return score

    ranked: list[RetrievalChunk] = []
    for chunk in sorted(chunks, key=lambda item: (-best(item), str(item.document_id))):
        metadata = {
            **(chunk.metadata or {}),
            "retrieval": "fabric_activation",
            "fabric_activation": round(best(chunk), 4),
        }
        ranked.append(dataclasses.replace(chunk, metadata=metadata))
    return ranked


def chunks_for_activated_nodes(
    chunks: list[RetrievalChunk],
    activated: dict[str, ActivatedNode],
    *,
    limit: int = 6,
) -> list[RetrievalChunk]:
    """Chunks que contienen nodos activados, ordenados por activación."""
    best_by_chunk: dict[int, tuple[float, RetrievalChunk]] = {}
    for index, chunk in enumerate(chunks):
        values = (chunk.metadata or {}).get("fabric_node_ids") or ()
        if isinstance(values, str):
            values = [values]
        best = 0.0
        for value in values:
            node = activated.get(str(value or ""))
            if node is not None and node.activation > best:
                best = node.activation
        if best > 0:
            best_by_chunk[index] = (best, chunk)
    ordered = sorted(
        best_by_chunk.values(), key=lambda item: (-item[0], item[1].document_id)
    )
    selected: list[RetrievalChunk] = []
    for activation, chunk in ordered[: max(1, int(limit))]:
        metadata = {
            **(chunk.metadata or {}),
            "retrieval": "fabric_activation",
            "fabric_activation": round(float(activation), 4),
        }
        selected.append(dataclasses.replace(chunk, metadata=metadata))
    return selected


class FabricActivationExpansion(ExpansionStrategy):
    """Expansión por vecindad semántica del Fabric (1..N hops controlados)."""

    name = "fabric_activation"
    reason = "activar vecinos semánticos del Semantic Fabric"

    def __init__(self, store: object, *, policy: ActivationPolicy | None = None) -> None:
        self._store = store
        self._policy = policy or ActivationPolicy()

    async def expand(self, context: ExpansionContext) -> Expansion:
        empty = Expansion(name=self.name, reason=self.reason, strategy=self.name)
        fetch = getattr(self._store, "list_fabric_edges_for_nodes", None)
        if not callable(fetch):
            return empty
        seeds = seed_node_ids_from_chunks(context.chunks)
        if not seeds:
            return empty
        edges: list[dict] = []
        seen_edges: set[str] = set()
        frontier = list(seeds)
        visited: set[str] = set(seeds)
        for _hop in range(max(1, self._policy.max_hops)):
            if not frontier:
                break
            cache_key = ("fabric_edges", tuple(sorted(frontier)))
            cached = context.cache.get_chunks(cache_key) if context.cache else None
            if cached is not None:
                batch = list(cached)
            else:
                try:
                    batch = await fetch(
                        context.query.organization_id,
                        frontier,
                        limit=self._policy.max_edges,
                    )
                except Exception:  # noqa: BLE001 — el grafo nunca frena el retrieval
                    batch = []
                if context.cache is not None:
                    context.cache.put_chunks(cache_key, batch)
            for edge in batch:
                edge_id = str(edge.get("id") or edge.get("edge_key") or "")
                if edge_id and edge_id in seen_edges:
                    continue
                if edge_id:
                    seen_edges.add(edge_id)
                edges.append(edge)
            discovered: list[str] = []
            for edge in batch:
                for value in (edge.get("subject_id"), edge.get("object_id")):
                    text = str(value or "")
                    if text and text not in visited:
                        visited.add(text)
                        discovered.append(text)
            frontier = discovered[: self._policy.max_nodes]
        activated = spreading_activation(seeds, edges, policy=self._policy)
        neighbor_ids = [
            node_id for node_id, node in activated.items() if node.hop > 0
        ]
        fetched: list[RetrievalChunk] = []
        fetch_chunks = getattr(self._store, "get_chunks_by_fabric_nodes", None)
        if neighbor_ids and callable(fetch_chunks):
            try:
                context_result = await fetch_chunks(
                    context.query.organization_id,
                    node_ids=neighbor_ids,
                    role=getattr(context.query, "role", "admin"),
                    user_id=getattr(context.query, "user_id", None),
                    groups=list(getattr(context.query, "groups", []) or []),
                    limit=max(1, int(context.limit) * 4),
                )
                fetched = list(getattr(context_result, "chunks", []) or [])
            except Exception:  # noqa: BLE001 — el grafo nunca frena el retrieval
                fetched = []
        if not fetched:
            # Fallback sin fetch: activa chunks YA presentes en el set.
            fetched = chunks_for_activated_nodes(
                context.chunks, activated, limit=context.limit
            )
        known = {_chunk_key(chunk) for chunk in context.chunks}
        new_chunks = [chunk for chunk in fetched if _chunk_key(chunk) not in known]
        new_chunks = _rank_by_activation(new_chunks, activated)[: context.limit]
        return Expansion(
            name=self.name,
            reason=self.reason,
            chunks=new_chunks,
            strategy=self.name,
        )


__all__ = [
    "ACTIVATION_RELATIONS",
    "GRAPH_ACTIVATION_VERSION",
    "ActivatedNode",
    "ActivationPolicy",
    "FabricActivationExpansion",
    "chunks_for_activated_nodes",
    "seed_node_ids_from_chunks",
    "spreading_activation",
]
