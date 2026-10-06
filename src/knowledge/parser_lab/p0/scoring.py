# =============================================================================
# P0 — Scoring: Knowledge Completeness Score (KCS), ZentPdfKnowledgeScore y
# umbral de migración. Pesos explícitos y documentados (nada arbitrario).
# =============================================================================
from __future__ import annotations

from typing import Any

#: Pesos del KCS. Positivos suman 1.00; los negativos penalizan conocimiento
#: falso con más fuerza que la falta de conocimiento (brief §18).
KCS_WEIGHTS: dict[str, float] = {
    "canonical_rule_recall": 0.25,
    "knowledge_recall": 0.10,
    "semantic_unit_recall": 0.10,
    "premise_coverage": 0.10,
    "retrieval_recall": 0.10,
    "answer_accuracy": 0.10,
    "deterministic_decision": 0.05,
    "provenance": 0.10,
    "structural_fidelity": 0.05,
    "knowledge_precision": 0.05,
    "false_rule_penalty": -0.30,
    "contradiction_penalty": -0.20,
    "fragmentation_penalty": -0.10,
    "hallucination_penalty": -0.20,
}

#: Pesos del score de decisión final (prioridad del brief §21). Performance
#: tiene peso mínimo y un gate operativo aparte.
ZPKS_WEIGHTS: dict[str, float] = {
    "canonical_rule_precision": 0.30,
    "canonical_rule_recall": 0.20,
    "premise_coverage": 0.15,
    "answer_accuracy": 0.10,
    "retrieval_recall": 0.10,
    "deterministic_decision": 0.05,
    "provenance": 0.05,
    "structural_fidelity": 0.03,
    "performance": 0.02,
    "false_rule_penalty": -0.30,
    "contradiction_penalty": -0.20,
    "hallucination_penalty": -0.20,
}

#: Segundos por página a partir de los cuales la performance es inviable.
PERFORMANCE_VIABLE_SECONDS_PER_PAGE = 5.0


def _value(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    if value is None:
        return 0.0
    return float(value)


def _mean(values: list[float | None]) -> float:
    present = [float(value) for value in values if value is not None]
    if not present:
        return 0.0
    return round(sum(present) / len(present), 4)


def kcs_components(metrics: dict[str, Any]) -> dict[str, float]:
    structural = metrics.get("structural") or {}
    semantic = metrics.get("semantic") or {}
    knowledge = metrics.get("knowledge") or {}
    canonical = metrics.get("canonical") or {}
    premise = metrics.get("premise") or {}
    runtime = metrics.get("runtime") or {}
    retrieval = runtime.get("retrieval") or {}
    decision = runtime.get("decision") or {}
    performance = metrics.get("performance") or {}

    structural_fidelity = _mean(
        [
            structural.get("heading_accuracy"),
            structural.get("table_structure_accuracy"),
            structural.get("symbol_preservation"),
            structural.get("reading_order_accuracy"),
        ]
    )
    seconds_per_page = performance.get("seconds_per_page")
    performance_score = (
        0.0
        if seconds_per_page is None
        else round(1.0 / (1.0 + max(float(seconds_per_page), 0.0)), 4)
    )
    return {
        "canonical_rule_recall": _value(canonical, "canonical_rule_recall"),
        "canonical_rule_precision": _value(canonical, "canonical_rule_precision"),
        "knowledge_recall": _value(knowledge, "knowledge_recall_avg"),
        "knowledge_precision": _value(knowledge, "knowledge_precision"),
        "semantic_unit_recall": _value(semantic, "semantic_unit_recall"),
        "premise_coverage": _value(premise, "premise_coverage_recall"),
        "retrieval_recall": _value(retrieval, "recall_at_k"),
        "answer_accuracy": _value(decision, "answer_accuracy"),
        "deterministic_decision": _value(decision, "deterministic_decision_rate"),
        "provenance": _value(canonical, "property_provenance_completeness"),
        "structural_fidelity": structural_fidelity,
        "false_rule_penalty": _value(canonical, "false_rule_rate"),
        "contradiction_penalty": _value(canonical, "contradiction_rate"),
        "fragmentation_penalty": _value(semantic, "fragmentation_rate"),
        "hallucination_penalty": _value(decision, "unsupported_hallucination_rate"),
        "performance_score": performance_score,
    }


def knowledge_completeness_score(metrics: dict[str, Any]) -> dict[str, Any]:
    components = kcs_components(metrics)
    value = 0.0
    for key, weight in KCS_WEIGHTS.items():
        value += weight * components.get(key, 0.0)
    return {
        "value": round(value, 4),
        "clamped": round(max(0.0, min(1.0, value)), 4),
        "weights": dict(KCS_WEIGHTS),
        "components": components,
    }


def zent_pdf_knowledge_score(metrics: dict[str, Any]) -> dict[str, Any]:
    components = kcs_components(metrics)
    value = 0.0
    for key, weight in ZPKS_WEIGHTS.items():
        if key == "performance":
            value += weight * components.get("performance_score", 0.0)
        else:
            value += weight * components.get(key, 0.0)
    seconds_per_page = (metrics.get("performance") or {}).get("seconds_per_page")
    viable = (
        seconds_per_page is None
        or float(seconds_per_page) <= PERFORMANCE_VIABLE_SECONDS_PER_PAGE
    )
    return {
        "value": round(value, 4),
        "weights": dict(ZPKS_WEIGHTS),
        "performance_viable": viable,
        "performance_seconds_per_page": seconds_per_page,
        "components": components,
    }


def _metric(metrics: dict[str, Any], path: tuple[str, ...]) -> float | None:
    node: Any = metrics
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if node is None:
        return None
    return float(node)


def _consistency_ok(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Consistencia evaluable: None = sin queries ejecutables resueltas."""
    consistency_a = _metric(a, ("runtime", "consistency", "consistency_rate"))
    consistency_b = _metric(b, ("runtime", "consistency", "consistency_rate"))
    if consistency_b is None:
        return consistency_a is None
    return consistency_b >= max((consistency_a or 0.0) - 0.01, 0.99)


def migration_recommendation(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    hybrid: dict[str, Any] | None = None,
    corpus_complete: bool = True,
) -> dict[str, Any]:
    """Umbral de migración del brief §22. a = pdfplumber, b = ODL local."""

    def get(metrics: dict[str, Any], path: tuple[str, ...]) -> float:
        return _metric(metrics, path) or 0.0

    criteria = {
        "knowledge_precision_not_reduced": get(b, ("knowledge", "knowledge_precision"))
        >= get(a, ("knowledge", "knowledge_precision")) - 0.02,
        "rule_precision_not_reduced": get(b, ("canonical", "canonical_rule_precision"))
        >= get(a, ("canonical", "canonical_rule_precision")) - 0.02,
        "structural_fidelity_maintained": get(b, ("structural", "heading_accuracy"))
        >= get(a, ("structural", "heading_accuracy")) - 0.05,
        "semantic_unit_quality_increased": get(b, ("semantic", "semantic_unit_recall"))
        >= get(a, ("semantic", "semantic_unit_recall")),
        "canonical_rule_recall_increased": get(b, ("canonical", "canonical_rule_recall"))
        >= get(a, ("canonical", "canonical_rule_recall")) + 0.01,
        "premise_coverage_not_reduced": get(b, ("premise", "premise_coverage_recall"))
        >= get(a, ("premise", "premise_coverage_recall")) - 0.02,
        "false_abstentions_reduced": get(b, ("runtime", "decision", "false_abstention_rate"))
        <= get(a, ("runtime", "decision", "false_abstention_rate")) + 0.02,
        "hallucinations_not_increased": get(
            b, ("runtime", "decision", "unsupported_hallucination_rate")
        )
        <= get(a, ("runtime", "decision", "unsupported_hallucination_rate")) + 0.01,
        "consistency_maintained": _consistency_ok(a, b),
        "provenance_not_worse": get(b, ("canonical", "property_provenance_completeness"))
        >= get(a, ("canonical", "property_provenance_completeness")) - 0.02,
    }
    b_zpks = zent_pdf_knowledge_score(b)
    performance_viable = bool(b_zpks["performance_viable"])
    false_knowledge_ok = (
        criteria["knowledge_precision_not_reduced"]
        and criteria["rule_precision_not_reduced"]
        and criteria["hallucinations_not_increased"]
    )
    improvement = (
        criteria["canonical_rule_recall_increased"]
        or criteria["semantic_unit_quality_increased"]
        or criteria["false_abstentions_reduced"]
        or criteria["premise_coverage_not_reduced"]
    )
    if not corpus_complete:
        verdict = "D_NEED_MORE_DATA"
    elif not false_knowledge_ok:
        verdict = "A_KEEP_PDFPLUMBER"
    elif improvement and performance_viable and all(criteria.values()):
        verdict = "B_ADOPT_OPENDATALOADER"
    elif improvement and performance_viable:
        failing = [name for name, ok in criteria.items() if not ok]
        verdict = "D_NEED_MORE_DATA" if failing else "B_ADOPT_OPENDATALOADER"
    elif hybrid is not None:
        hybrid_improves = zent_pdf_knowledge_score(hybrid)["value"] > b_zpks["value"]
        verdict = "C_ADOPT_OPENDATALOADER_HYBRID_SELECTIVE" if hybrid_improves else "A_KEEP_PDFPLUMBER"
    else:
        verdict = "A_KEEP_PDFPLUMBER"
    return {
        "verdict": verdict,
        "criteria": criteria,
        "performance_viable": performance_viable,
        "zent_score": {"pdfplumber": zent_pdf_knowledge_score(a), "opendataloader": b_zpks},
    }


def weights_documentation() -> dict[str, Any]:
    return {
        "kcs": dict(KCS_WEIGHTS),
        "zent_pdf_knowledge_score": dict(ZPKS_WEIGHTS),
        "performance_viable_seconds_per_page": PERFORMANCE_VIABLE_SECONDS_PER_PAGE,
        "rationale": (
            "La correctitud manda: precision de reglas/conocimiento y penalizaciones "
            "por conocimiento falso pesan más que la cobertura. Performance solo "
            "pesa 0.02 y tiene un gate operativo de 5 s/página."
        ),
    }


__all__ = [
    "KCS_WEIGHTS",
    "PERFORMANCE_VIABLE_SECONDS_PER_PAGE",
    "ZPKS_WEIGHTS",
    "kcs_components",
    "knowledge_completeness_score",
    "migration_recommendation",
    "weights_documentation",
    "zent_pdf_knowledge_score",
]
