# =============================================================================
# QueryViews — los tres canales de la consulta técnica, en paralelo
# =============================================================================
# RAW      : la consulta exacta del usuario, nunca modificada.
# semantic : prosa para el embedding (sin tokens opacos) + semantic_hint de
#            plugins. El core no inventa hints.
# lexical  : términos útiles para la pata léxica (campos, valores, conceptos).
# exact    : tokens que la pata exacta busca literales (máscaras, códigos).
#
# Ejemplo: "consulta si FCLAS &&&F acepta QNNF0SME"
#   semantic      -> "consulta si FCLAS acepta"   (sin la máscara)
#   lexical_terms -> FCLAS, QNNF0SME, ...         (+ expansion_terms del plugin)
#   exact_terms   -> FCLAS, &&&F, QNNF0SME
# =============================================================================
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any

from src.intelligence.response.anchors import Anchor, dense_query_rewrite, extract_anchors
from src.rag.longcontext.exact_tokens import extract_exact_tokens
from src.rag.longcontext.roles import AnchorRole, assign_roles, is_documentable

MAX_VIEW_TERMS = 16
MAX_VIEW_EXACT = 12


@dataclass(frozen=True, kw_only=True)
class QueryViews:
    raw: str
    semantic: str
    lexical_terms: tuple[str, ...] = ()
    exact_terms: tuple[str, ...] = ()
    anchors: tuple[Anchor, ...] = ()
    entities: tuple[Any, ...] = ()
    examples: tuple[str, ...] = ()

    @property
    def has_technical_anchors(self) -> bool:
        return bool(self.exact_terms)

    @property
    def documentable_anchors(self) -> tuple[Anchor, ...]:
        return tuple(
            anchor
            for anchor in self.anchors
            if is_documentable(str(getattr(anchor, "role", "")))
        )

    def to_public_dict(self) -> dict[str, Any]:
        anchors_payload: list[dict[str, Any]] = []
        for anchor in self.anchors:
            role = str(getattr(anchor, "role", "") or "")
            item: dict[str, Any] = {
                "value": anchor.value,
                "kind": anchor.kind,
                "role": role,
                "label": anchor.label,
                "needles": [str(needle) for needle in anchor.needles[:4]],
            }
            hint = str(getattr(anchor, "semantic_hint", "") or "")
            if hint:
                item["semantic_hint"] = hint
            anchors_payload.append(item)
        return {
            "semantic_query": self.semantic,
            "lexical_terms": list(self.lexical_terms),
            "exact_terms": list(self.exact_terms),
            "anchors": anchors_payload,
            "examples": list(self.examples),
            "entities": [
                entity.to_public_dict()
                for entity in self.entities
                if hasattr(entity, "to_public_dict")
            ],
        }


def build_query_views(
    query: str,
    *,
    anchors: list[Anchor] | tuple[Anchor, ...] | None = None,
    entities: list[Any] | tuple[Any, ...] | None = None,
    max_terms: int = MAX_VIEW_TERMS,
    max_exact: int = MAX_VIEW_EXACT,
) -> QueryViews:
    """Construye los tres canales. Nunca lanza: fail-soft a la query cruda."""
    raw = str(query or "")
    try:
        resolved = assign_roles(
            raw, list(anchors) if anchors is not None else extract_anchors(raw)
        )
    except Exception:  # noqa: BLE001
        resolved = list(anchors or ())
    try:
        resolved_entities = (
            list(entities) if entities is not None else _asked_entities(raw)
        )
    except Exception:  # noqa: BLE001
        resolved_entities = []

    examples: list[str] = []
    lexical: list[str] = []
    exact: list[str] = []
    for anchor in resolved:
        value = str(anchor.value or "").strip()
        if not value:
            continue
        role = str(getattr(anchor, "role", "") or "")
        if role == AnchorRole.EXAMPLE_VALUE.value:
            if value not in examples:
                examples.append(value)
        if value not in lexical:
            lexical.append(value)
        for term in getattr(anchor, "expansion_terms", ()) or ():
            term = str(term or "").strip()
            if term and term not in lexical:
                lexical.append(term)
        hint = str(getattr(anchor, "semantic_hint", "") or "").strip()
        if hint and hint not in lexical:
            lexical.append(hint)
        if getattr(anchor, "must_search_exact", True) and value not in exact:
            exact.append(value)

    for entity in resolved_entities:
        label = str(getattr(entity, "label", "") or "").strip()
        if label and label not in lexical:
            lexical.append(label)

    # Formas extras (comillas, campos, hex, porcentajes) que anchors no cubre.
    try:
        for token in extract_exact_tokens(raw):
            if token.value not in exact:
                exact.append(token.value)
    except Exception:  # noqa: BLE001
        pass

    semantic = _semantic_text(raw, resolved)
    return QueryViews(
        raw=raw,
        semantic=semantic,
        lexical_terms=tuple(lexical[: max(1, int(max_terms))]),
        exact_terms=tuple(exact[: max(1, int(max_exact))]),
        anchors=tuple(resolved),
        entities=tuple(resolved_entities),
        examples=tuple(examples),
    )


def _semantic_text(raw: str, anchors: list[Anchor]) -> str:
    """Prosa para el embedding + hints de dominio; nunca inventa semántica."""
    try:
        base = dense_query_rewrite(raw, anchors)
    except Exception:  # noqa: BLE001
        base = raw
    parts = [base.strip()]
    for anchor in anchors:
        hint = str(getattr(anchor, "semantic_hint", "") or "").strip()
        if hint:
            parts.append(hint)
        for term in getattr(anchor, "expansion_terms", ()) or ():
            term = str(term or "").strip()
            if term:
                parts.append(term)
    semantic = " ".join(part for part in parts if part).strip()
    if len(semantic) < 3:
        return raw
    return semantic


def _asked_entities(query: str) -> list[Any]:
    try:
        from src.intelligence.response.entities import asked_entities

        return list(asked_entities(query))
    except Exception:  # noqa: BLE001
        return []


def summarize_views_for_flow(
    views_public: dict[str, Any] | None,
    evidence_texts: list[str] | tuple[str, ...],
) -> dict[str, Any] | None:
    """Resumen humano para «Ver flujo»: qué se pidió, qué se encontró.

    Separa FIELD/RULE/REFERENCE (documentables) de USER EXAMPLE (no exige
    match en fuentes). `rule_evidence` resume si la regla está completa.
    """
    if not isinstance(views_public, dict):
        return None
    joined = "\n".join(
        html.unescape(str(text or "")).lower() for text in (evidence_texts or ())
    )
    fields: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    entities: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    documentable = 0
    documentable_found = 0

    def _found(entry: dict[str, Any]) -> bool:
        needles = [str(needle).lower() for needle in entry.get("needles") or ()]
        value = str(entry.get("value") or "").lower()
        if value:
            needles.append(value)
        return bool(joined) and any(
            needle and needle in joined for needle in needles
        )

    for entry in views_public.get("anchors") or ():
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        found = _found(entry)
        record = {"value": entry.get("value"), "role": role, "found": found}
        if role == AnchorRole.RULE_ANCHOR.value:
            rules.append(record)
            documentable += 1
            documentable_found += int(found)
        elif role == AnchorRole.FIELD_ANCHOR.value:
            fields.append(record)
            documentable += 1
            documentable_found += int(found)
        elif role == AnchorRole.EXAMPLE_VALUE.value:
            examples.append(
                {
                    "value": entry.get("value"),
                    "role": role,
                    "found_in_evidence": found,
                    "requires_source_match": False,
                }
            )
        else:
            references.append(record)
            documentable += 1
            documentable_found += int(found)

    for entity in views_public.get("entities") or ():
        if not isinstance(entity, dict):
            continue
        label = str(entity.get("label") or "")
        found = bool(joined) and label.lower() in joined
        entities.append({"value": label, "role": AnchorRole.ENTITY.value, "found": found})
        documentable += 1
        documentable_found += int(found)

    if documentable == 0 and not examples:
        return None

    rule_evidence = (
        "not_applicable"
        if documentable == 0
        else ("complete" if documentable_found == documentable else "incomplete")
    )
    parts: list[str] = []
    for record in fields:
        parts.append(
            f"FIELD {record['value']} {'FOUND' if record['found'] else 'MISSING'}"
        )
    for record in rules:
        parts.append(
            f"RULE ANCHOR {record['value']} {'FOUND' if record['found'] else 'MISSING'}"
        )
    for record in references:
        parts.append(
            f"REFERENCE {record['value']} {'FOUND' if record['found'] else 'MISSING'}"
        )
    for record in entities:
        parts.append(
            f"ENTITY {record['value']} {'FOUND' if record['found'] else 'MISSING'}"
        )
    for record in examples:
        parts.append(
            f"USER EXAMPLE {record['value']} (no requiere match en fuentes)"
        )
    parts.append(
        "RULE EVIDENCE "
        + (
            "COMPLETE"
            if rule_evidence == "complete"
            else "INCOMPLETE" if rule_evidence == "incomplete" else "N/A"
        )
    )
    return {
        "status": "ok" if rule_evidence != "incomplete" else "warn",
        "detail": " · ".join(parts),
        "fields": fields,
        "rules": rules,
        "references": references,
        "entities": entities,
        "examples": examples,
        "rule_evidence": rule_evidence,
        "documentable_requested": documentable,
        "documentable_found": documentable_found,
        "application": "LLM reasoning" if examples else "",
    }


__all__ = ["QueryViews", "build_query_views", "summarize_views_for_flow"]
