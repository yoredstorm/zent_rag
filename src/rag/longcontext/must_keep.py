# =============================================================================
# MUST_KEEP — evidencia exacta que ninguna etapa puede expulsar
# =============================================================================
# Un fragmento marcado `must_keep` sólo puede excluirse si: es duplicado exacto,
# viola permisos (eso lo decide el store, nunca este módulo), pertenece a otra
# entidad/documento por metadata estructural, o es irrelevante de forma
# determinista. Nunca porque otro chunk tenga mayor cosine similarity.
# =============================================================================
from __future__ import annotations

import dataclasses
from typing import Any

MUST_KEEP_KEY = "must_keep"
REQUIREMENT_EVIDENCE_KEY = "requirement_evidence"
_EXACT_ANCHOR_KEY = "exact_anchor"
_TRUE = {"true", "1", "yes", "on", "si", "sí"}


def is_must_keep(chunk: Any) -> bool:
    metadata = getattr(chunk, "metadata", None) or {}
    return str(metadata.get(MUST_KEEP_KEY, "")).strip().lower() in _TRUE


def is_requirement_evidence(chunk: Any) -> bool:
    """Fragmento que prueba un requirement documentable (regla/campo).

    También protegido: el reranker y el presupuesto no lo expulsan. Sólo
    MUST_KEEP tiene prioridad mayor para ordenar.
    """
    metadata = getattr(chunk, "metadata", None) or {}
    return str(metadata.get(REQUIREMENT_EVIDENCE_KEY, "")).strip().lower() in _TRUE


def is_exact_anchor(chunk: Any) -> bool:
    metadata = getattr(chunk, "metadata", None) or {}
    if str(metadata.get(_EXACT_ANCHOR_KEY, "")).strip().lower() in _TRUE:
        return True
    return str(metadata.get(MUST_KEEP_KEY, "")).strip().lower() in _TRUE


def mark_must_keep(
    chunk: Any,
    *,
    needle: str = "",
    kind: str = "",
    retrieval: str = "exact",
) -> Any:
    """Devuelve el chunk con la marca MUST_KEEP y su procedencia."""
    metadata = {
        **(getattr(chunk, "metadata", None) or {}),
        MUST_KEEP_KEY: "true",
        _EXACT_ANCHOR_KEY: "true",
        "retrieval": retrieval,
    }
    if needle:
        metadata["exact_needle"] = needle
    if kind:
        metadata["exact_kind"] = kind
    return dataclasses.replace(chunk, metadata=metadata)


def mark_requirement_evidence(chunk: Any, *, requirement: str = "") -> Any:
    """Marca el fragmento como evidencia de un requirement documentable."""
    metadata = {
        **(getattr(chunk, "metadata", None) or {}),
        REQUIREMENT_EVIDENCE_KEY: "true",
    }
    if requirement:
        metadata["requirement_id"] = requirement
    return dataclasses.replace(chunk, metadata=metadata)


def merge_must_keep(
    priority_chunks: list[Any],
    chunks: list[Any],
) -> list[Any]:
    """Une `priority_chunks` al frente de `chunks` sin repetir document_id.

    Si el chunk prioritario ya viene en la lista, gana la versión prioritaria
    (trae la metadata de must_keep); el resto conserva su orden original.
    """
    if not priority_chunks:
        return chunks
    prioridad = {chunk.document_id: chunk for chunk in priority_chunks}
    merged = list(prioridad.values())
    for chunk in chunks:
        if chunk.document_id in prioridad:
            continue
        merged.append(chunk)
    return merged


__all__ = [
    "MUST_KEEP_KEY",
    "REQUIREMENT_EVIDENCE_KEY",
    "is_exact_anchor",
    "is_must_keep",
    "is_requirement_evidence",
    "mark_must_keep",
    "mark_requirement_evidence",
    "merge_must_keep",
]
