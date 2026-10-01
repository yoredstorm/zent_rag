"""Catálogo de métricas y términos — códigos canónicos para tooltips (§11, §23, §26).

El backend NO compone texto de UI: declara rangos, origen y si la métrica es
experimental/comparable. El portal traduce desde su catálogo central
(`portal/src/pages/chat/traceabilityCatalog.ts`) usando estos códigos.

Toda métrica mostrada sin definición acá debe tratarse como interna; el portal
la marca como "métrica interna" en vez de mostrar el número desnudo.
"""

from __future__ import annotations

#: metric_code -> definición semántica
METRIC_DEFINITIONS: dict[str, dict[str, object]] = {
    "selected_probability": {
        "range": (0.0, 1.0),
        "origin": "jev.distribution.probabilities",
        "comparable": True,
        "experimental": False,
        "aggregation": "none",
    },
    "confidence": {
        "range": (0.0, 1.0),
        "origin": "jev.derived",
        "comparable": False,
        "experimental": False,
        "aggregation": "none",
    },
    "certainty": {
        "range": (0.0, 1.0),
        "origin": "jev.noul",
        "comparable": True,
        "experimental": False,
        "aggregation": "none",
    },
    "margin": {
        "range": (0.0, 1.0),
        "origin": "jev.distribution",
        "comparable": True,
        "experimental": False,
        "aggregation": "none",
    },
    "entropy": {
        "range": (0.0, 1.0),
        "origin": "jev.distribution",
        "comparable": True,
        "experimental": False,
        "aggregation": "none",
    },
    "entropy_bits": {
        "range": (0.0, None),
        "origin": "jev.distribution.entropy_bits",
        "comparable": False,
        "experimental": True,
        "aggregation": "none",
    },
    "quality": {
        "range": (0.0, 3.0),
        "origin": "answer_gate.quality",
        "comparable": False,
        "experimental": True,
        "aggregation": "none",
    },
    "coverage_ratio": {
        "range": (0.0, 1.0),
        "origin": "evidence.coverage",
        "comparable": True,
        "experimental": False,
        "aggregation": "none",
    },
    "score": {
        "range": (0.0, 1.0),
        "origin": "retrieval.score",
        "comparable": False,
        "experimental": False,
        "aggregation": "max",
    },
    "rerank_score": {
        "range": (None, None),
        "origin": "retrieval.rerank",
        "comparable": False,
        "experimental": True,
        "aggregation": "max",
    },
    "wall_clock_ms": {
        "range": (0.0, None),
        "origin": "timings.total_ms",
        "comparable": True,
        "experimental": False,
        "aggregation": "sum",
    },
    "accumulated_ms": {
        "range": (0.0, None),
        "origin": "timings.spans",
        "comparable": False,
        "experimental": False,
        "aggregation": "sum",
    },
    "cost_usd": {
        "range": (0.0, None),
        "origin": "generation.cost",
        "comparable": True,
        "experimental": False,
        "aggregation": "sum",
    },
}

#: Términos del glosario con definición corta en el portal (§23).
GLOSSARY_TERMS: tuple[str, ...] = (
    "jev",
    "gate",
    "retrieval",
    "reranking",
    "evidence",
    "semantic_unit",
    "fallback",
    "grounding",
    "verified",
    "entropy",
    "margin",
    "span",
    "wall_clock",
    "canonical_event",
    "deduplication",
    "canonical_source",
    "evidence_id",
    "intervention",
    "warning",
    "material_effect",
)


def metric_refs_for_trace(
    *,
    judgments: list[dict] | None = None,
    evidence: dict | None = None,
    timing: dict | None = None,
    cost: dict | None = None,
    verification: dict | None = None,
) -> list[str]:
    """Solo las métricas realmente presentes en la ejecución (sin ruido)."""
    refs: list[str] = []
    for judgment in judgments or []:
        interpretation = judgment.get("interpretation") or {}
        if interpretation.get("selected_probability") is not None:
            refs.append("selected_probability")
        if interpretation.get("confidence") is not None:
            refs.append("confidence")
        if interpretation.get("certainty") is not None:
            refs.append("certainty")
        if interpretation.get("margin") is not None:
            refs.append("margin")
        if interpretation.get("entropy") is not None:
            refs.append("entropy")
    if (evidence or {}).get("coverage_ratio") is not None:
        refs.append("coverage_ratio")
    for item in (evidence or {}).get("canonical_evidence") or []:
        if item.get("score") is not None:
            refs.append("score")
        if item.get("rerank_score") is not None:
            refs.append("rerank_score")
    if (timing or {}).get("wall_clock_ms") is not None:
        refs.append("wall_clock_ms")
    if (timing or {}).get("accumulated_ms") is not None:
        refs.append("accumulated_ms")
    if (cost or {}).get("total_usd") is not None:
        refs.append("cost_usd")
    for check in (verification or {}).get("checks") or []:
        if check.get("quality") is not None:
            refs.append("quality")
    seen: list[str] = []
    for ref in refs:
        if ref not in seen:
            seen.append(ref)
    return seen


__all__ = ["GLOSSARY_TERMS", "METRIC_DEFINITIONS", "metric_refs_for_trace"]
