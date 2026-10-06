# =============================================================================
# P0 — Scoring: KCS, ZentPdfKnowledgeScore y umbral de migración
# =============================================================================
from __future__ import annotations

from src.knowledge.parser_lab.p0.scoring import (
    KCS_WEIGHTS,
    ZPKS_WEIGHTS,
    knowledge_completeness_score,
    migration_recommendation,
    weights_documentation,
    zent_pdf_knowledge_score,
)


def _metrics(
    *,
    rule_recall: float = 0.5,
    rule_precision: float = 1.0,
    premise: float = 0.5,
    answer_accuracy: float = 0.5,
    false_rule_rate: float = 0.0,
    hallucination: float = 0.0,
    seconds_per_page: float = 0.1,
    consistency: float = 1.0,
) -> dict:
    return {
        "structural": {
            "heading_accuracy": 0.8,
            "table_structure_accuracy": 0.8,
            "symbol_preservation": 1.0,
            "reading_order_accuracy": 0.9,
        },
        "semantic": {"semantic_unit_recall": 0.7, "fragmentation_rate": 0.1},
        "knowledge": {"knowledge_recall_avg": 0.6, "knowledge_precision": 0.9},
        "canonical": {
            "canonical_rule_recall": rule_recall,
            "canonical_rule_precision": rule_precision,
            "property_provenance_completeness": 0.9,
            "false_rule_rate": false_rule_rate,
            "contradiction_rate": 0.0,
        },
        "premise": {"premise_coverage_recall": premise},
        "runtime": {
            "retrieval": {"recall_at_k": 0.6},
            "decision": {
                "answer_accuracy": answer_accuracy,
                "deterministic_decision_rate": 0.4,
                "unsupported_hallucination_rate": hallucination,
            },
            "consistency": {"consistency_rate": consistency},
        },
        "performance": {"seconds_per_page": seconds_per_page},
    }


def test_weights_documented_and_positive_sum() -> None:
    documentation = weights_documentation()
    assert documentation["kcs"] == KCS_WEIGHTS
    assert documentation["zent_pdf_knowledge_score"] == ZPKS_WEIGHTS
    positives = sum(value for value in KCS_WEIGHTS.values() if value > 0)
    assert abs(positives - 1.0) < 1e-9
    positives_zpks = sum(value for value in ZPKS_WEIGHTS.values() if value > 0)
    assert abs(positives_zpks - 1.0) < 1e-9


def test_false_knowledge_penalized_more_than_missing() -> None:
    clean = knowledge_completeness_score(_metrics(false_rule_rate=0.0))
    false_rules = knowledge_completeness_score(_metrics(false_rule_rate=0.5))
    missing = knowledge_completeness_score(_metrics(rule_recall=0.25))
    assert false_rules["value"] < clean["value"]
    assert clean["value"] - false_rules["value"] > clean["value"] - missing["value"]


def test_zent_score_prefers_precision() -> None:
    precise = zent_pdf_knowledge_score(_metrics(rule_precision=1.0, rule_recall=0.5))
    noisy = zent_pdf_knowledge_score(_metrics(rule_precision=0.5, rule_recall=1.0))
    assert precise["value"] > noisy["value"]


def test_performance_gate() -> None:
    slow = zent_pdf_knowledge_score(_metrics(seconds_per_page=10.0))
    fast = zent_pdf_knowledge_score(_metrics(seconds_per_page=0.1))
    assert slow["performance_viable"] is False
    assert fast["performance_viable"] is True
    assert fast["value"] > slow["value"]


def test_migration_keep_when_precision_drops() -> None:
    a = _metrics(rule_precision=1.0, rule_recall=0.4)
    b = _metrics(rule_precision=0.5, rule_recall=0.9)
    recommendation = migration_recommendation(a, b)
    assert recommendation["verdict"] == "A_KEEP_PDFPLUMBER"


def test_migration_adopt_when_knowledge_improves_without_false_knowledge() -> None:
    a = _metrics(rule_recall=0.3, premise=0.5, answer_accuracy=0.4)
    b = _metrics(rule_recall=0.7, premise=0.9, answer_accuracy=0.8)
    recommendation = migration_recommendation(a, b)
    assert recommendation["verdict"] == "B_ADOPT_OPENDATALOADER"


def test_migration_needs_more_data_when_corpus_incomplete() -> None:
    a = _metrics()
    b = _metrics(rule_recall=0.9)
    recommendation = migration_recommendation(a, b, corpus_complete=False)
    assert recommendation["verdict"] == "D_NEED_MORE_DATA"
