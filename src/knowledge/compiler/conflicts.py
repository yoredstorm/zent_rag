# =============================================================================
# Knowledge Compiler — CONFLICT ENGINE
# =============================================================================
# Encontrar "mismo sujeto, mismo predicado, valores incompatibles" NO es
# decidir quién está mal. Es clasificar la causa probable:
#
#   POSSIBLE_DUPLICATE  los valores son el mismo hecho escrito distinto
#   TEMPORAL_CHANGE     ventanas de vigencia disjuntas (evolución en el tiempo)
#   VERSION_CHANGE      etiquetas de versión distintas (una reemplaza a la otra)
#   SCOPE_DIFFERENCE    alcances declarados distintos (ambos pueden ser ciertos)
#   EXCEPTION           una de las afirmaciones es una excepción de la otra
#   SOURCE_CONFLICT     fuentes distintas, mismo periodo: contradicción real
#   UNRESOLVED          sin señal suficiente para clasificar
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.compiler.model import (
    ConflictCandidate,
    ConflictType,
    FactCandidate,
    normalize_term,
)

_EXCEPTION_MARKERS = re.compile(
    r"\b(except|excepto|salvo|a\s+menos\s+que|unless|salvando|con\s+excepci[oó]n)\b",
    flags=re.IGNORECASE,
)

_VALUE_EQUIVALENCE = re.compile(r"[\s\-_./]+")


def _value_fold(value: str | None) -> str:
    """Forma comparable de un valor: mismo hecho escrito distinto colapsa."""
    text = normalize_term(value or "")
    text = _VALUE_EQUIVALENCE.sub(" ", text)
    return " ".join(text.split())


def values_equivalent(left: str | None, right: str | None) -> bool:
    left_folded, right_folded = _value_fold(left), _value_fold(right)
    if not left_folded or not right_folded:
        return False
    if left_folded == right_folded:
        return True
    shorter, longer = sorted((left_folded, right_folded), key=len)
    if len(shorter) < 4:
        return False
    # Prefijo o sufijo con separador: "ATPCO Record 4" ≡ "Record 4".
    if longer.startswith(shorter) and longer[len(shorter)] in " ([:,-":
        return True
    if longer.endswith(shorter) and longer[-len(shorter) - 1] in " ([:,-":
        return True
    return False


def classify_conflict(
    fact_a: FactCandidate,
    fact_b: FactCandidate,
    *,
    source_label_a: str | None = None,
    source_label_b: str | None = None,
) -> ConflictCandidate:
    """Clasifica la incompatibilidad con la evidencia disponible."""
    base = {
        "subject": fact_a.subject,
        "predicate": fact_a.predicate,
        "value_a": fact_a.object_value or "",
        "value_b": fact_b.object_value or "",
        "source_a": source_label_a or str(fact_a.attributes.get("source_label") or "") or None,
        "source_b": source_label_b or str(fact_b.attributes.get("source_label") or "") or None,
        "evidence": (list(fact_a.evidence) + list(fact_b.evidence))[:6],
    }

    if values_equivalent(fact_a.object_value, fact_b.object_value):
        return ConflictCandidate(
            **base,
            conflict_type=ConflictType.POSSIBLE_DUPLICATE.value,
            confidence=0.9,
            reason=(
                "Los valores describen el mismo hecho con distinta forma; "
                "probable duplicado, no contradicción."
            ),
            values_equivalent=True,
        )

    temporal_a, temporal_b = fact_a.temporal, fact_b.temporal
    if temporal_a.effective_from and temporal_b.effective_from:
        a_end = temporal_a.effective_to
        b_end = temporal_b.effective_to
        disjoint = (a_end and a_end < temporal_b.effective_from) or (
            b_end and b_end < temporal_a.effective_from
        )
        if disjoint:
            return ConflictCandidate(
                **base,
                conflict_type=ConflictType.TEMPORAL_CHANGE.value,
                confidence=0.85,
                reason=(
                    "Las vigencias no se solapan: es evolución temporal del "
                    "mismo conocimiento, no contradicción."
                ),
            )

    if temporal_a.version_label and temporal_b.version_label:
        if temporal_a.version_label != temporal_b.version_label:
            return ConflictCandidate(
                **base,
                conflict_type=ConflictType.VERSION_CHANGE.value,
                confidence=0.8,
                reason=(
                    f"Versiones distintas ({temporal_a.version_label} vs "
                    f"{temporal_b.version_label}): una reemplaza a la otra."
                ),
            )

    if temporal_a.scope and temporal_b.scope and temporal_a.scope != temporal_b.scope:
        return ConflictCandidate(
            **base,
            conflict_type=ConflictType.SCOPE_DIFFERENCE.value,
            confidence=0.75,
            reason=(
                f"Alcances distintos ('{temporal_a.scope}' vs "
                f"'{temporal_b.scope}'): cada valor puede ser correcto en su ámbito."
            ),
        )

    statement_a = f"{fact_a.object_value or ''} {fact_a.attributes.get('statement') or ''}"
    statement_b = f"{fact_b.object_value or ''} {fact_b.attributes.get('statement') or ''}"
    if bool(_EXCEPTION_MARKERS.search(statement_a)) != bool(
        _EXCEPTION_MARKERS.search(statement_b)
    ):
        return ConflictCandidate(
            **base,
            conflict_type=ConflictType.EXCEPTION.value,
            confidence=0.7,
            reason=(
                "Una de las afirmaciones se declara como excepción de la otra; "
                "pueden convivir con ámbitos distintos."
            ),
        )

    source_a = base["source_a"]
    source_b = base["source_b"]
    if source_a and source_b and source_a != source_b:
        return ConflictCandidate(
            **base,
            conflict_type=ConflictType.SOURCE_CONFLICT.value,
            confidence=0.65,
            reason=(
                "Fuentes independientes sostienen valores incompatibles para el "
                "mismo sujeto y predicado en el mismo periodo."
            ),
        )

    return ConflictCandidate(
        **base,
        conflict_type=ConflictType.UNRESOLVED.value,
        confidence=0.4,
        reason="Sin señal suficiente para clasificar la causa; requiere revisión.",
    )


def detect_conflicts(facts: list[FactCandidate]) -> list[ConflictCandidate]:
    """Pares incompatibles entre hechos del mismo sujeto y predicado.

    Solo compara hechos con valor textual: los hechos sin objeto no pueden ser
    incompatibles. La comparación es determinista y estable en el orden.
    """
    buckets: dict[tuple[str, str], list[FactCandidate]] = {}
    for fact in facts:
        value = (fact.object_value or "").strip()
        if not value:
            continue
        buckets.setdefault((normalize_term(fact.subject), fact.predicate), []).append(fact)

    conflicts: list[ConflictCandidate] = []
    for (_subject_key, _predicate), group in buckets.items():
        for index, fact_a in enumerate(group):
            for fact_b in group[index + 1 :]:
                if values_equivalent(fact_a.object_value, fact_b.object_value):
                    continue
                conflicts.append(classify_conflict(fact_a, fact_b))
    return conflicts
