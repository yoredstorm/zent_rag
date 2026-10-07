# =============================================================================
# Semantic Clause Decomposition — segmentación lingüística general
# =============================================================================
# Un párrafo de manual puede contener en UN solo bloque:
#   - definición de símbolo
#   - semántica de matching
#   - política de longitud
# El compiler no debe depender de que cada premisa llegue en un chunk
# separado ni de los saltos de línea del parser. Esta fase parte el texto en
# cláusulas semánticamente independientes (oraciones, `;`, conectores
# normativos), analiza cada una y FUSIONA las propiedades manteniendo el
# mismo provenance (mismo evidence_id) y el matched_text de su cláusula.
#
# Determinista, domain-agnostic. No hardcodea frases del dominio.
# =============================================================================
from __future__ import annotations

import re

from src.knowledge.rule_compiler.language import StatementAnalysis, analyze_statement

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÁÉÍÓÚÑÜ“\"'¿¡(])", re.UNICODE)
_CONNECTOR_SPLIT = re.compile(
    r"\s+(?=(?:When|Whenever|If|Where|While|An|The|Salvo|Si|Cuando)\b)",
    re.UNICODE,
)
_MIN_CLAUSE = 12
_WHOLE_TEXT_BUDGET = 260


def decompose_clauses(text: str) -> list[str]:
    """Cláusulas independientes de un texto; el texto corto queda entero."""
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    if len(normalized) <= _WHOLE_TEXT_BUDGET and normalized.count(".") <= 1:
        return [normalized]
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(normalized) if part.strip()]
    expanded: list[str] = []
    for part in parts:
        if len(part) > _WHOLE_TEXT_BUDGET + 120:
            expanded.extend(
                chunk.strip() for chunk in _CONNECTOR_SPLIT.split(part) if chunk.strip()
            )
        else:
            expanded.append(part)
    clauses = [clause for clause in expanded if len(clause) >= _MIN_CLAUSE]
    return clauses or [normalized]


def _union(first: list[str], second: list[str]) -> list[str]:
    merged = list(first)
    for item in second:
        if item not in merged:
            merged.append(item)
    return merged


def merge_statement_analyses(analyses: list[StatementAnalysis]) -> StatementAnalysis:
    """Fusiona análisis de cláusulas: propiedades por nombre, provenance intacta."""
    if not analyses:
        raise ValueError("merge_statement_analyses requires at least one analysis")
    if len(analyses) == 1:
        return analyses[0]
    base = analyses[0]
    properties: dict = {}
    for analysis in analyses:
        for name, prop in analysis.properties.items():
            current = properties.get(name)
            if current is None:
                properties[name] = prop
                continue
            if not getattr(current, "known", False) and getattr(prop, "known", False):
                properties[name] = prop
    formula = next(
        (item.formula for item in analyses if getattr(item.formula, "expression", "")),
        base.formula,
    )
    enumeration = next(
        (
            item.enumeration
            for item in analyses
            if getattr(item.enumeration, "values", None)
            or getattr(item.enumeration, "allowed", None)
        ),
        base.enumeration,
    )
    temporal = next(
        (
            item.temporal
            for item in analyses
            if getattr(item.temporal, "value", "") or getattr(item.temporal, "relation", "")
        ),
        base.temporal,
    )
    conditions = list(base.conditions)
    exceptions = list(base.exceptions)
    consequences = list(base.consequences)
    ambiguities = list(base.ambiguities)
    missing = list(base.missing_premises)
    for analysis in analyses[1:]:
        conditions = _union(conditions, analysis.conditions)
        exceptions = _union(exceptions, analysis.exceptions)
        consequences = _union(consequences, analysis.consequences)
        ambiguities = _union(ambiguities, analysis.ambiguities)
        missing = _union(missing, analysis.missing_premises)
    operator = ""
    for name in (
        "matching.operator",
        "comparison.operator",
        "length.policy",
        "temporal.relation",
        "formula.expression",
    ):
        prop = properties.get(name)
        if prop is not None and getattr(prop, "known", False):
            operator = name
            break
    return StatementAnalysis(
        statement=base.statement,
        kind=base.kind,
        properties=properties,
        formula=formula,
        enumeration=enumeration,
        temporal=temporal,
        exceptions=exceptions,
        conditions=conditions,
        consequences=consequences,
        ambiguities=ambiguities,
        missing_premises=missing,
        signals=base.signals,
        scope_priority=max(int(getattr(item, "scope_priority", 0) or 0) for item in analyses),
    )


def analyze_with_clauses(text: str, *, evidence_id: str) -> StatementAnalysis:
    """analyze_statement por cláusula + fusión, con el mismo provenance.

    El análisis del texto completo va PRIMERO: preserva señales que cruzan
    cláusulas (p. ej. `matching.operator` por contexto de "match" + "position").
    Las cláusulas rellenan propiedades que el texto completo no capturó, sin
    degradar las ya obtenidas.
    """
    clauses = decompose_clauses(text)
    if len(clauses) <= 1:
        return analyze_statement(text, evidence_id=evidence_id)
    analyses = [analyze_statement(text, evidence_id=evidence_id)]
    for clause in clauses:
        if clause.strip() == " ".join(str(text or "").split()):
            continue
        analyses.append(analyze_statement(clause, evidence_id=evidence_id))
    merged = merge_statement_analyses(analyses)
    merged.statement = " ".join(str(text or "").split())
    return merged


__all__ = [
    "analyze_with_clauses",
    "decompose_clauses",
    "merge_statement_analyses",
]
