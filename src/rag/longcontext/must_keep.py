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
MUST_KEEP_LEVEL_KEY = "must_keep_level"
SUPPORTING_EXACT_KEY = "supporting_exact"
_EXACT_ANCHOR_KEY = "exact_anchor"
_TRUE = {"true", "1", "yes", "on", "si", "sí"}

#: Niveles de exactitud: no todo match vale lo mismo. El packager los usa para
#: prioridad (0 rule, 1 requirement/reference, 2 field, 4 supporting).
LEVEL_RULE = "rule"
LEVEL_FIELD = "field"
LEVEL_REFERENCE = "reference"
LEVEL_SUPPORTING = "supporting"

_ROLE_LEVELS = {
    "rule_anchor": LEVEL_RULE,
    "mask": LEVEL_RULE,
    "rule": LEVEL_RULE,
    "field_anchor": LEVEL_FIELD,
    "field": LEVEL_FIELD,
    "sigla": LEVEL_FIELD,
    "reference": LEVEL_REFERENCE,
    "entity": LEVEL_REFERENCE,
    "codigo": LEVEL_REFERENCE,
    "identifier": LEVEL_REFERENCE,
    "example_value": LEVEL_SUPPORTING,
    "example": LEVEL_SUPPORTING,
    "literal": LEVEL_REFERENCE,
}


def must_keep_level(chunk: Any) -> str:
    metadata = getattr(chunk, "metadata", None) or {}
    return str(metadata.get(MUST_KEEP_LEVEL_KEY, "") or "").strip().lower()


def is_supporting_exact(chunk: Any) -> bool:
    metadata = getattr(chunk, "metadata", None) or {}
    return str(metadata.get(SUPPORTING_EXACT_KEY, "")).strip().lower() in _TRUE


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


def mark_exact_hit(
    chunk: Any,
    *,
    needle: str = "",
    role: str = "",
    retrieval: str = "exact",
) -> Any:
    """Marca un acierto exacto con su NIVEL: no todo match vale lo mismo.

    rule/field/reference → MUST_KEEP (protegido). example/literal sin regla →
    supporting exact (prioridad baja, no expulsa a nadie).
    """
    level = _ROLE_LEVELS.get(str(role or "").strip().lower(), LEVEL_REFERENCE)
    metadata = {
        **(getattr(chunk, "metadata", None) or {}),
        _EXACT_ANCHOR_KEY: "true",
        MUST_KEEP_LEVEL_KEY: level,
        "retrieval": retrieval,
    }
    if needle:
        metadata["exact_needle"] = needle
    if role:
        metadata["exact_role"] = role
    if level == LEVEL_SUPPORTING:
        metadata[SUPPORTING_EXACT_KEY] = "true"
    else:
        metadata[MUST_KEEP_KEY] = "true"
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
    "LEVEL_FIELD",
    "LEVEL_REFERENCE",
    "LEVEL_RULE",
    "LEVEL_SUPPORTING",
    "MUST_KEEP_KEY",
    "MUST_KEEP_LEVEL_KEY",
    "REQUIREMENT_EVIDENCE_KEY",
    "SUPPORTING_EXACT_KEY",
    "is_exact_anchor",
    "is_must_keep",
    "is_requirement_evidence",
    "is_supporting_exact",
    "mark_exact_hit",
    "mark_must_keep",
    "mark_requirement_evidence",
    "merge_must_keep",
    "must_keep_level",
]
