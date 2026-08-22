# =============================================================================
# Fusion — RRF / weighted / dedupe / prioridad de doc_type (funciones puras)
# =============================================================================
# IMPORTANTE: la fusión ordena pero NO reescribe chunk.score. El score
# original por pata (coseno en dense, dot-product en sparse) se conserva
# para que el gate anti-alucinación del orchestrator siga funcionando
# con umbrales comparables.
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import RetrievalChunk


def dedupe_chunks(chunks: list[RetrievalChunk]) -> list[RetrievalChunk]:
    """Elimina duplicados por document_id conservando la primera aparición
    (la de mejor posición en el orden fusionado)."""
    seen: set = set()
    result: list[RetrievalChunk] = []
    for chunk in chunks:
        if chunk.document_id in seen:
            continue
        seen.add(chunk.document_id)
        result.append(chunk)
    return result


def rrf_fusion(
    ranked_lists: list[list[RetrievalChunk]],
    k: int = 60,
) -> list[RetrievalChunk]:
    """Reciprocal Rank Fusion: ordena por suma de 1/(k + rank) por pata.

    Cada lista se trata como ranking (orden de llegada = rank). El score
    original de cada chunk se conserva intacto.
    """
    fusion_scores: dict = {}
    order: dict = {}
    first_seen: dict = {}
    for leg_index, ranked in enumerate(ranked_lists):
        for rank, chunk in enumerate(ranked, start=1):
            doc_id = chunk.document_id
            fusion_scores[doc_id] = fusion_scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            order.setdefault(doc_id, chunk)
            first_seen.setdefault(doc_id, leg_index)

    ranked_ids = sorted(
        fusion_scores,
        key=lambda doc_id: (fusion_scores[doc_id], -first_seen[doc_id]),
        reverse=True,
    )
    return [order[doc_id] for doc_id in ranked_ids]


def weighted_fusion(
    scored_lists: list[list[RetrievalChunk]],
    weights: list[float] | None = None,
) -> list[RetrievalChunk]:
    """Fusión por score normalizado (min-max por pata) y suma ponderada.

    Los scores de cada pata viven en rangos distintos (coseno vs
    dot-product); se normalizan por pata antes de combinar. El score
    original de cada chunk se conserva.
    """
    if not scored_lists:
        return []
    weights = weights or [1.0 / len(scored_lists)] * len(scored_lists)
    if len(weights) != len(scored_lists):
        raise ValueError("weights length must match number of scored lists")

    combined: dict = {}
    order: dict = {}
    for _leg_index, (scored, weight) in enumerate(zip(scored_lists, weights)):
        if not scored:
            continue
        scores = [c.score for c in scored]
        lo, hi = min(scores), max(scores)
        span = (hi - lo) or 1.0
        for chunk in scored:
            doc_id = chunk.document_id
            normalized = (chunk.score - lo) / span
            combined[doc_id] = combined.get(doc_id, 0.0) + weight * normalized
            order[doc_id] = chunk

    ranked_ids = sorted(combined, key=lambda doc_id: combined[doc_id], reverse=True)
    return [order[doc_id] for doc_id in ranked_ids]


def apply_doc_type_priority(
    chunks: list[RetrievalChunk],
    priority: list[str],
) -> list[RetrievalChunk]:
    """Partición estable: chunks con metadata.doc_type en `priority` primero,
    conservando su orden relativo fusionado dentro de cada grupo.

    Generaliza el comportamiento "aggregated first" del pipeline original.
    """
    if not priority:
        return chunks
    priority_set = set(priority)
    prioritized = [c for c in chunks if (c.metadata or {}).get("doc_type") in priority_set]
    rest = [c for c in chunks if (c.metadata or {}).get("doc_type") not in priority_set]
    return prioritized + rest


def filter_by_threshold(
    chunks: list[RetrievalChunk],
    score_threshold: float,
) -> list[RetrievalChunk]:
    """Filtro post-fusión por umbral de score original."""
    return [c for c in chunks if c.score >= score_threshold]
