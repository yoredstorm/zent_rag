# =============================================================================
# Knowledge Compiler — CONFLICT ENGINE
# =============================================================================
# Encontrar "mismo sujeto, mismo predicado, valores distintos" NO es encontrar
# un conflicto. Es generar un CANDIDATO que debe pasar por:
#
#   1. generación de candidato    (sujeto + predicado + valores + evidencia)
#   2. adjudicación semántica     (taxonomía completa, no true/false)
#   3. gate estricto              (evidencia y fuentes de ambos lados)
#   4. materialidad               (impacto potencial)
#
# Reglas duras:
#   - Los alias de una misma entidad NUNCA son conflicto (ALIAS_VARIATION).
#   - Un fragmento de parsing NUNCA es conflicto (PARSER_FRAGMENT).
#   - Sin evidencia y sin fuente en AMBOS lados no hay conflicto mostrable:
#     es INSUFFICIENT_CONTEXT y va a la cola de calidad de ingesta.
#   - Dos valores pueden ser distintos y complementarios: eso no es conflicto.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.compiler.model import (
    DISPLAYABLE_CLASSIFICATIONS,
    NON_CONFLICT_CLASSIFICATIONS,
    ConflictCandidate,
    ConflictMateriality,
    ConflictType,
    FactCandidate,
    FactKind,
    normalize_term,
)
from src.knowledge.quality.fragments import (
    TextQualityStatus,
    analyze_text_quality,
    completeness_score,
)

_EXCEPTION_MARKERS = re.compile(
    r"\b(except|excepto|salvo|a\s+menos\s+que|unless|salvando|con\s+excepci[oó]n)\b",
    flags=re.IGNORECASE,
)

_VALUE_EQUIVALENCE = re.compile(r"[\s\-_./]+")

_NUMERIC_VALUE = re.compile(r"^[<>≤≥=]?\s*[\d.,%$€£¥\s-]+$")
_SHORT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,11}$")

#: Predicados de identidad: sus valores son alias, jamás contradicciones.
_IDENTITY_PREDICATES = frozenset({"also_known_as"})

#: Predicados donde una diferencia es información complementaria por diseño.
_COMPLEMENTARY_PREDICATES = frozenset(
    {"defined_as", "described_as", "field_meaning", "referenced_by"}
)

#: Predicados estructurales: dependen de un scope (tabla/hoja). Diferencias
#: entre scopes distintos no son contradicciones; dentro del mismo scope sí.
_STRUCTURAL_PREDICATES = frozenset(
    {
        "belongs_to_table",
        "has_position",
        "starts_at_position",
        "has_length",
        "has_excel_letter",
        "has_row_count",
        "has_column_count",
        "has_type",
        "has_semantic_type",
        "has_pattern",
    }
)

_MATERIALITY_BY_PREDICATE: dict[str, str] = {
    "business_rule": ConflictMateriality.HIGH.value,
    "constraint": ConflictMateriality.HIGH.value,
    "has_length": ConflictMateriality.LOW.value,
    "starts_at_position": ConflictMateriality.LOW.value,
    "has_position": ConflictMateriality.LOW.value,
    "has_excel_letter": ConflictMateriality.LOW.value,
    "has_row_count": ConflictMateriality.LOW.value,
    "has_column_count": ConflictMateriality.LOW.value,
    "belongs_to_table": ConflictMateriality.LOW.value,
    "described_as": ConflictMateriality.LOW.value,
    "field_meaning": ConflictMateriality.MEDIUM.value,
    "defined_as": ConflictMateriality.MEDIUM.value,
}

_MATERIALITY_BY_KIND: dict[str, str] = {
    FactKind.RULE.value: ConflictMateriality.HIGH.value,
    FactKind.CONSTRAINT.value: ConflictMateriality.HIGH.value,
    FactKind.METRIC.value: ConflictMateriality.HIGH.value,
    FactKind.PROCESS_STEP.value: ConflictMateriality.HIGH.value,
    FactKind.STRUCTURAL.value: ConflictMateriality.LOW.value,
}

#: Confianza mínima por clasificación (explica el veredicto, no lo esconde).
_CONFIDENCE_FLOOR: dict[str, float] = {
    ConflictType.PARSER_FRAGMENT.value: 0.9,
    ConflictType.DUPLICATE.value: 0.9,
    ConflictType.POSSIBLE_DUPLICATE.value: 0.9,
    ConflictType.ALIAS_VARIATION.value: 0.85,
    ConflictType.TEMPORAL_CHANGE.value: 0.85,
    ConflictType.VERSION_CHANGE.value: 0.8,
    ConflictType.SCOPE_DIFFERENCE.value: 0.75,
    ConflictType.COMPLEMENTARY_INFORMATION.value: 0.7,
    ConflictType.EXCEPTION.value: 0.7,
}


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


def _looks_like_fragment(
    value: str | None, *, references: tuple[str, ...] = ()
) -> bool:
    text = (value or "").strip()
    if _NUMERIC_VALUE.fullmatch(text) or _SHORT_CODE.fullmatch(text):
        return False
    quality = analyze_text_quality(
        text,
        references=references,
        min_length=1,
        max_words=60,
        max_length=600,
    )
    return quality.status != TextQualityStatus.OK.value


def _contains_other(left: str, right: str) -> bool:
    """¿Un valor contiene al otro como texto completo (no fragmento)?"""
    left_folded, right_folded = _value_fold(left), _value_fold(right)
    if not left_folded or not right_folded or left_folded == right_folded:
        return False
    shorter, longer = sorted((left_folded, right_folded), key=len)
    if len(shorter) < 8:
        return False
    pattern = re.compile(rf"(?<!\w){re.escape(shorter)}(?!\w)")
    return bool(pattern.search(longer))


def _abbreviation_variant(left: str, right: str) -> bool:
    """`cat 31` vs `category 31`: abreviatura del mismo nombre, no choque."""
    a_tokens = re.findall(r"[a-z0-9]+", normalize_term(left))
    b_tokens = re.findall(r"[a-z0-9]+", normalize_term(right))
    if not a_tokens or len(a_tokens) != len(b_tokens):
        return False
    differences = 0
    for x, y in zip(a_tokens, b_tokens):
        if x == y:
            continue
        if x.isdigit() or y.isdigit():
            return False
        if x.startswith(y) or y.startswith(x):
            differences += 1
            continue
        return False
    return differences > 0


def _materiality_for(fact: FactCandidate) -> str:
    value = _MATERIALITY_BY_KIND.get(fact.fact_kind)
    if value:
        return value
    return _MATERIALITY_BY_PREDICATE.get(fact.predicate, ConflictMateriality.MEDIUM.value)


def _scope_of(fact: FactCandidate) -> str:
    for key in ("scope", "table", "table_reference", "sheet"):
        value = fact.attributes.get(key)
        if isinstance(value, str) and value.strip():
            return normalize_term(value)
    return normalize_term(fact.temporal.scope or "")


def _source_of(fact: FactCandidate, override: str | None = None) -> str | None:
    if override:
        return override
    label = fact.attributes.get("source_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    if fact.temporal.version_label:
        return f"version:{fact.temporal.version_label}"
    return None


def _confidence_components(
    fact_a: FactCandidate, fact_b: FactCandidate
) -> dict[str, float]:
    """Nada de un único confidence mágico: se guardan los componentes."""
    evidence = [item for fact in (fact_a, fact_b) for item in fact.evidence]
    evidence_quality = (
        sum(item.strength for item in evidence) / len(evidence) if evidence else 0.0
    )
    extraction = min(fact_a.confidence, fact_b.confidence)
    semantic = min(
        completeness_score(fact_a.object_value or ""),
        completeness_score(fact_b.object_value or ""),
    )
    source_a, source_b = _source_of(fact_a), _source_of(fact_b)
    source_quality = 0.9 if source_a and source_b else 0.3
    components = {
        "extraction_confidence": round(extraction, 4),
        "evidence_quality": round(evidence_quality, 4),
        "semantic_completeness": round(semantic, 4),
        "source_quality": source_quality,
        "entity_resolution_confidence": round(
            min(fact_a.confidence, fact_b.confidence), 4
        ),
    }
    weighted = (
        extraction * 0.25
        + evidence_quality * 0.25
        + semantic * 0.25
        + source_quality * 0.25
    )
    components["conflict_confidence"] = round(weighted, 4)
    return components


def _classify(
    fact_a: FactCandidate,
    fact_b: FactCandidate,
    *,
    source_a: str | None,
    source_b: str | None,
) -> tuple[str, str, str, str, str]:
    """(classification, conflict_type, reason, explanation, temporal_relation)."""
    value_a = fact_a.object_value or ""
    value_b = fact_b.object_value or ""
    predicate = fact_a.predicate

    if predicate in _IDENTITY_PREDICATES:
        return (
            ConflictType.ALIAS_VARIATION.value,
            ConflictType.ALIAS_VARIATION.value,
            "Los valores son alias del mismo sujeto: nunca son una contradicción.",
            "Un mismo canónico puede tener múltiples alias legítimos.",
            None,
        )

    if _looks_like_fragment(value_a, references=(value_b,)) or _looks_like_fragment(
        value_b, references=(value_a,)
    ):
        broken = (
            value_a
            if _looks_like_fragment(value_a, references=(value_b,))
            else value_b
        )
        return (
            ConflictType.PARSER_FRAGMENT.value,
            ConflictType.PARSER_FRAGMENT.value,
            (
                "Al menos un valor es un fragmento/artefacto de extracción "
                f"({broken[:80]!r}): no es una afirmación completa."
            ),
            "El parser o el layout cortaron el texto antes de que llegara al compilador.",
            None,
        )

    if values_equivalent(value_a, value_b):
        return (
            ConflictType.DUPLICATE.value,
            ConflictType.POSSIBLE_DUPLICATE.value,
            (
                "Los valores describen el mismo hecho con distinta forma; "
                "probable duplicado, no contradicción."
            ),
            "Mismo valor normalizado o uno contiene al otro como nombre calificado.",
            None,
        )

    if _contains_other(value_a, value_b):
        return (
            ConflictType.COMPLEMENTARY_INFORMATION.value,
            ConflictType.UNRESOLVED.value,
            "Un valor contiene al otro: es información complementaria, no incompatible.",
            "Los dos valores pueden ser ciertos al mismo tiempo.",
            None,
        )

    if _abbreviation_variant(value_a, value_b):
        return (
            ConflictType.ALIAS_VARIATION.value,
            ConflictType.ALIAS_VARIATION.value,
            "Un valor es la abreviatura/nombre corto del otro: variación léxica.",
            "Mismo concepto escrito con distinta extensión.",
            None,
        )

    temporal_a, temporal_b = fact_a.temporal, fact_b.temporal
    if temporal_a.effective_from and temporal_b.effective_from:
        a_end = temporal_a.effective_to
        b_end = temporal_b.effective_to
        disjoint = (a_end and a_end < temporal_b.effective_from) or (
            b_end and b_end < temporal_a.effective_from
        )
        if disjoint:
            relation = (
                f"{a_end or '∞'} < {temporal_b.effective_from}"
                if a_end and a_end < temporal_b.effective_from
                else f"{b_end or '∞'} < {temporal_a.effective_from}"
            )
            return (
                ConflictType.TEMPORAL_CHANGE.value,
                ConflictType.TEMPORAL_CHANGE.value,
                (
                    "Las vigencias no se solapan: es evolución temporal del "
                    "mismo conocimiento, no contradicción."
                ),
                "Cada valor rige en una ventana distinta.",
                relation,
            )
        overlap = not disjoint
        if overlap and a_end and b_end:
            temporal_relation = "overlapping"
        else:
            temporal_relation = "overlapping_open" if overlap else None
    else:
        temporal_relation = None

    if temporal_a.version_label and temporal_b.version_label:
        if temporal_a.version_label != temporal_b.version_label:
            return (
                ConflictType.VERSION_CHANGE.value,
                ConflictType.VERSION_CHANGE.value,
                (
                    f"Versiones distintas ({temporal_a.version_label} vs "
                    f"{temporal_b.version_label}): una reemplaza a la otra."
                ),
                "La fuente declara versiones explícitas y distintas.",
                temporal_relation,
            )

    if temporal_a.scope and temporal_b.scope and temporal_a.scope != temporal_b.scope:
        return (
            ConflictType.SCOPE_DIFFERENCE.value,
            ConflictType.SCOPE_DIFFERENCE.value,
            (
                f"Alcances distintos ('{temporal_a.scope}' vs "
                f"'{temporal_b.scope}'): cada valor puede ser correcto en su ámbito."
            ),
            "El alcance declarado difiere; no hay contradicción.",
            temporal_relation,
        )

    statement_a = f"{value_a} {fact_a.attributes.get('statement') or ''}"
    statement_b = f"{value_b} {fact_b.attributes.get('statement') or ''}"
    if bool(_EXCEPTION_MARKERS.search(statement_a)) != bool(
        _EXCEPTION_MARKERS.search(statement_b)
    ):
        return (
            ConflictType.EXCEPTION.value,
            ConflictType.EXCEPTION.value,
            (
                "Una de las afirmaciones se declara como excepción de la otra; "
                "pueden convivir con ámbitos distintos."
            ),
            "Una regla general y su excepción no se contradicen.",
            temporal_relation,
        )

    if predicate in _STRUCTURAL_PREDICATES:
        if _scope_of(fact_a) and _scope_of(fact_b) and _scope_of(fact_a) != _scope_of(fact_b):
            return (
                ConflictType.SCOPE_DIFFERENCE.value,
                ConflictType.SCOPE_DIFFERENCE.value,
                "Los hechos estructurales pertenecen a tablas/hojas distintas.",
                "Cada valor describe un scope diferente.",
                temporal_relation,
            )
        if predicate == "belongs_to_table":
            return (
                ConflictType.COMPLEMENTARY_INFORMATION.value,
                ConflictType.UNRESOLVED.value,
                "Un nombre puede existir en más de una tabla: pertenencia múltiple.",
                "No toda diferencia de pertenencia es una contradicción.",
                temporal_relation,
            )

    is_complementary = predicate in _COMPLEMENTARY_PREDICATES
    have_sources = bool(source_a) and bool(source_b)
    have_evidence = bool(fact_a.evidence) and bool(fact_b.evidence)

    if is_complementary and not have_sources:
        return (
            ConflictType.COMPLEMENTARY_INFORMATION.value,
            ConflictType.UNRESOLVED.value,
            "Dos descripciones distintas del mismo sujeto suelen ser complementarias.",
            "No hay fuentes independientes que se contradigan.",
            temporal_relation,
        )

    if have_sources and source_a == source_b:
        return (
            ConflictType.TRUE_CONFLICT.value,
            ConflictType.SOURCE_CONFLICT.value,
            "Dos afirmaciones incompatibles dentro de la MISMA fuente.",
            (
                "No hay independencia de fuentes: puede ser inconsistencia "
                "interna del documento, no una contradicción entre fuentes."
            ),
            temporal_relation,
        )

    if have_sources:
        return (
            ConflictType.TRUE_CONFLICT.value,
            ConflictType.SOURCE_CONFLICT.value,
            (
                "Fuentes independientes sostienen valores incompatibles para el "
                "mismo sujeto y predicado."
            ),
            (
                "No se encontró una diferencia temporal, de versión o de ámbito "
                "que explique el cambio."
            ),
            temporal_relation,
        )

    return (
        ConflictType.INSUFFICIENT_CONTEXT.value,
        ConflictType.UNRESOLVED.value,
        "Sin evidencia o sin fuente en ambos lados no hay conflicto verificable.",
        "Puede ser un problema de procedencia, no una contradicción.",
        temporal_relation,
    )


def classify_conflict(
    fact_a: FactCandidate,
    fact_b: FactCandidate,
    *,
    source_label_a: str | None = None,
    source_label_b: str | None = None,
) -> ConflictCandidate:
    """Clasifica la incompatibilidad con la evidencia disponible."""
    source_a = _source_of(fact_a, source_label_a)
    source_b = _source_of(fact_b, source_label_b)
    (
        classification,
        conflict_type,
        reason,
        explanation,
        temporal_relation,
    ) = _classify(fact_a, fact_b, source_a=source_a, source_b=source_b)

    evidence = (list(fact_a.evidence) + list(fact_b.evidence))[:6]
    components = _confidence_components(fact_a, fact_b)
    confidence = float(components["conflict_confidence"])
    confidence = max(confidence, _CONFIDENCE_FLOOR.get(classification, 0.0))
    if classification in DISPLAYABLE_CLASSIFICATIONS:
        confidence = max(confidence, 0.6)
    values_same = values_equivalent(fact_a.object_value, fact_b.object_value)

    scope_a, scope_b = _scope_of(fact_a), _scope_of(fact_b)
    scope_relation = None
    if scope_a or scope_b:
        scope_relation = "same_scope" if scope_a == scope_b else "different_scope"
    if source_a and source_b:
        source_independence = (
            "same_source" if source_a == source_b else "independent_sources"
        )
    else:
        source_independence = "unknown"

    materiality_rank = {
        ConflictMateriality.CRITICAL.value: 3,
        ConflictMateriality.HIGH.value: 2,
        ConflictMateriality.MEDIUM.value: 1,
        ConflictMateriality.LOW.value: 0,
    }
    materiality = max(
        (_materiality_for(fact_a), _materiality_for(fact_b)),
        key=lambda value: materiality_rank.get(value, 1),
    )

    return ConflictCandidate(
        subject=fact_a.subject,
        predicate=fact_a.predicate,
        value_a=fact_a.object_value or "",
        value_b=fact_b.object_value or "",
        conflict_type=conflict_type,
        classification=classification,
        confidence=round(min(1.0, confidence), 4),
        reason=reason,
        possible_explanation=explanation,
        source_a=source_a,
        source_b=source_b,
        values_equivalent=values_same,
        evidence=evidence,
        statement_a=(fact_a.attributes.get("statement") or fact_a.object_value or "")[:600],
        statement_b=(fact_b.attributes.get("statement") or fact_b.object_value or "")[:600],
        temporal_relation=temporal_relation,
        scope_relation=scope_relation,
        materiality=materiality,
        source_independence=source_independence,
        comparison_meaningful=not values_same,
        confidence_components=components,
    )


def _bucket_key(fact: FactCandidate) -> tuple[str, str]:
    return (normalize_term(fact.subject), fact.predicate)


def _comparable(fact_a: FactCandidate, fact_b: FactCandidate) -> bool:
    """¿Tiene sentido comparar estos dos hechos?"""
    if normalize_term(fact_a.subject) != normalize_term(fact_b.subject):
        return False
    if fact_a.predicate != fact_b.predicate:
        return False
    if fact_a.predicate in _IDENTITY_PREDICATES:
        return False
    if fact_a.predicate in _STRUCTURAL_PREDICATES:
        # Entre tablas/hojas distintas son cosas distintas, no contradicciones.
        if _scope_of(fact_a) and _scope_of(fact_b) and _scope_of(fact_a) != _scope_of(fact_b):
            return False
    subject = normalize_term(fact_a.subject)
    if not subject or len(subject) < 2:
        return False
    if not (fact_a.object_value or "").strip() or not (fact_b.object_value or "").strip():
        return False
    return True


def detect_conflicts(facts: list[FactCandidate]) -> list[ConflictCandidate]:
    """Candidatos de conflicto entre hechos comparables del mismo sujeto.

    Genera ConflictCandidate, NO Conflict: el gate estricto decide si alguno
    puede mostrarse. Los alias de identidad nunca generan candidato.
    """
    buckets: dict[tuple[str, str], list[FactCandidate]] = {}
    for fact in facts:
        value = (fact.object_value or "").strip()
        if not value or fact.predicate in _IDENTITY_PREDICATES:
            continue
        buckets.setdefault(_bucket_key(fact), []).append(fact)

    conflicts: list[ConflictCandidate] = []
    for (_subject_key, _predicate), group in buckets.items():
        for index, fact_a in enumerate(group):
            for fact_b in group[index + 1 :]:
                if not _comparable(fact_a, fact_b):
                    continue
                if values_equivalent(fact_a.object_value, fact_b.object_value):
                    continue
                conflicts.append(classify_conflict(fact_a, fact_b))
    return conflicts


def is_auto_resolvable(conflict: ConflictCandidate) -> bool:
    """Clasificaciones que no deben molestar a un humano (§17)."""
    classification = conflict.classification or conflict.conflict_type
    return classification in NON_CONFLICT_CLASSIFICATIONS


__all__ = [
    "classify_conflict",
    "detect_conflicts",
    "is_auto_resolvable",
    "values_equivalent",
]
