# =============================================================================
# Citation Engine — Knowledge V2 (brief §17)
# =============================================================================
# Construye Citations de primera clase desde los chunks del contexto
# (document_id / section_id / page / external_id en metadata) y numera el texto
# de la respuesta con [N] para el Source Viewer (Phase G UI).
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.rag.grounding.models import Citation
from src.rag.retrieval.structured import AssembledContext

_CITE_RE = re.compile(r"\[(\d+)\]")


def citation_from_chunk(
    chunk,
    *,
    index: int = 0,
    relevance: float = 0.0,
) -> Citation:
    """Mapea un RetrievalChunk (metadata estructural V2) a una Citation."""
    metadata = chunk.metadata or {}
    section_path_raw = metadata.get("section_path")
    section_path: tuple[str, ...] = ()
    if isinstance(section_path_raw, list):
        section_path = tuple(str(p) for p in section_path_raw)
    elif isinstance(section_path_raw, str) and section_path_raw:
        section_path = (section_path_raw,)

    document_id_raw = metadata.get("document_id") or metadata.get("source_id")
    return Citation(
        source_id=_uuid_of(metadata.get("source_id")),
        document_id=_uuid_of(document_id_raw),
        document_name=str(metadata.get("external_id") or metadata.get("filename") or ""),
        page=_int_of(metadata.get("page_start")),
        section_path=section_path,
        chunk_id=_uuid_of(metadata.get("chunk_id")),
        excerpt=str(chunk.content)[:1200],
        relevance=float(relevance) if relevance is not None else 0.0,
    )


def build_citations(
    assembled: AssembledContext,
    *,
    limit: int = 8,
) -> list[Citation]:
    """Citas desde children (relevancia) + parents (contexto de sección)."""
    citations: list[Citation] = []
    for order, chunk in enumerate(assembled.children):
        if len(citations) >= limit:
            break
        citations.append(
            citation_from_chunk(chunk, index=order, relevance=chunk.score)
        )
    for chunk in assembled.parents:
        if len(citations) >= limit:
            break
        citations.append(
            citation_from_chunk(chunk, relevance=0.5)
        )
    # dedupe por (document_id, page, section_path)
    unique: dict[tuple, Citation] = {}
    for citation in citations:
        key = (
            citation.document_id,
            citation.page,
            citation.section_path,
            citation.excerpt[:80],
        )
        if key not in unique:
            unique[key] = citation
    return sorted(
        unique.values(), key=lambda c: c.relevance, reverse=True
    )[:limit]


def instrument_answer(
    answer: str,
    citations: list[Citation],
    *,
    max_cites: int = 8,
) -> tuple[str, list[Citation]]:
    """Numera la respuesta con [1]..[N] alineando las citas usadas.

    No toca el contenido: añade el bloque de referencias numeradas al final y
    reemplaza las marcas [N] existentes por el subíndice de la citación dada.
    """
    used = citations[:max_cites]
    text = answer
    found: list[int] = []
    for match in _CITE_RE.finditer(answer):
        idx = int(match.group(1)) - 1
        if 0 <= idx < len(used) and idx not in found:
            found.append(idx)
    referenced = sorted(found) if found else list(range(len(used)))
    markers = " ".join(f"[{i + 1}]" for i in referenced)
    if markers:
        references = "\n\n**Referencias** " + markers
        text = text + references
    return text, [used[i] for i in referenced]


def _uuid_of(value) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _int_of(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
