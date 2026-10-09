# =============================================================================
# Narrative Coverage Closure — un top-k no es ausencia del corpus.
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.runtime.evidence import EvidenceRegistry
from src.runtime.narrative_coverage import (
    COVERED,
    MISSING,
    NOT_FOUND_AFTER_COVERAGE_SEARCH,
    NOT_FOUND_IN_CURRENT_RETRIEVAL,
    PARTIAL,
    SUPPORTED,
    apply_coverage_limitation,
    build_coverage_query,
    coverage_needs_jev,
    decide_coverage_round,
    ensure_concept_representation,
    extract_narrative_concepts,
    measure_coverage,
    narrative_coverage_applies,
)

QUESTION = "cuentame sobre el record 2 y el cambio de fechas de efectividad"
DATE_ALIASES = {
    "cambio de fechas de efectividad": (
        "effective date",
        "eff date",
        "discontinue date",
        "disc date",
        "date processing",
        "date change",
    )
}
RECORD_ONLY = (
    "Record 2 footnote fare class.",
    "Record 2 fare family uses & and hyphen.",
)


def test_multi_topic_extracts_record_and_date_change() -> None:
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    labels = [concept.label.lower() for concept in plan.concepts]
    assert len(plan.concepts) == 2
    assert any("record 2" in label for label in labels)
    date = next(concept for concept in plan.concepts if "fecha" in concept.label.lower())
    assert "effective date" in [alias.lower() for alias in date.aliases]


def test_initial_topk_miss_is_not_corpus_absence() -> None:
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    measured = measure_coverage(plan, RECORD_ONLY, searched=False)
    by_label = {item.label.lower(): item for item in measured}
    record = next(item for label, item in by_label.items() if "record 2" in label)
    date = next(item for label, item in by_label.items() if "fecha" in label)
    assert record.status == COVERED
    assert record.epistemic == SUPPORTED
    assert date.status == MISSING
    assert date.epistemic == NOT_FOUND_IN_CURRENT_RETRIEVAL
    query = build_coverage_query(
        date,
        anchors=(record.label,),
        headings=("Footnote", "Fare Class"),
    )
    assert query != QUESTION
    assert "cuentame" not in query.lower()
    assert "record 2" in query.lower()
    assert "effective date" in query.lower()
    assert "footnote" not in query.lower()
    assert "el documento no contiene" not in query.lower()


def test_second_retrieval_can_cover_the_date_concept() -> None:
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    found = measure_coverage(
        plan,
        (
            *RECORD_ONLY,
            "Record 2 date processing uses the effective date and discontinue date.",
        ),
        searched=True,
    )
    date = next(item for item in found if "fecha" in item.label.lower())
    assert date.status == COVERED
    assert date.epistemic == SUPPORTED


def test_still_missing_uses_a_soft_limitation() -> None:
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    measured = measure_coverage(plan, RECORD_ONLY, searched=True)
    draft = (
        'La evidencia disponible no contiene información sobre '
        '"cambio de fechas de efectividad". El documento no contiene ese tema.'
    )
    limited = apply_coverage_limitation(draft, measured)
    assert "no encontré evidencia suficiente" in limited.lower()
    assert "fuentes disponibles" in limited.lower()
    assert "el documento no contiene" not in limited.lower()
    assert "no contiene información" not in limited.lower()
    date = next(item for item in measured if "fecha" in item.label.lower())
    assert date.epistemic == NOT_FOUND_AFTER_COVERAGE_SEARCH
    assert date.status == MISSING


def test_single_concept_does_not_request_another_search() -> None:
    plan = extract_narrative_concepts("qué significa & en Record 2")
    assert len(plan.concepts) == 1
    measured = measure_coverage(plan, ("Record 2 byte uses &.",), searched=False)
    assert measured[0].status in {COVERED, PARTIAL}
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=4,
    )
    assert decision.search is False
    assert decision.stop_reason == "initial_sufficient"


def test_adversarial_one_round_asks_for_the_missing_topics() -> None:
    question = "explícame alpha, beta y gamma"
    plan = extract_narrative_concepts(question)
    assert len(plan.concepts) == 3
    measured = measure_coverage(plan, ("alpha domina el fragmento.",), searched=False)
    missing = [item for item in measured if item.status == MISSING]
    assert {item.label.lower() for item in missing} == {"beta", "gamma"}
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=4,
        anchors=("alpha",),
    )
    assert decision.search is True
    assert "beta" in decision.query.lower()
    assert "gamma" in decision.query.lower()
    assert "explícame" not in decision.query.lower()
    again = decide_coverage_round(
        measured,
        rounds_done=1,
        max_rounds=1,
        remaining_steps=4,
    )
    assert again.search is False
    assert again.stop_reason == "max_rounds"


def test_budget_skips_the_coverage_search() -> None:
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    measured = measure_coverage(plan, RECORD_ONLY, searched=False)
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=1,
    )
    assert decision.search is False
    assert decision.coverage_search_skipped == "budget"
    assert decision.stop_reason == "budget"


def test_executable_query_is_out_of_scope() -> None:
    assert narrative_coverage_applies("&&&F vs ABCFGEGE cumple?") is False
    assert narrative_coverage_applies(QUESTION) is True
    assert coverage_needs_jev(conflicts=0, ambiguous=False) is False
    assert coverage_needs_jev(conflicts=1, ambiguous=False) is True


def test_same_registry_keeps_growing_ids_and_diversity() -> None:
    registry = EvidenceRegistry()
    first = [
        EvidenceItem(source_type="qdrant", content=f"Record 2 chunk {index}", score=0.9)
        for index in range(5)
    ]
    second = [
        EvidenceItem(
            source_type="qdrant",
            content="Effective date and discontinue date processing.",
            score=0.4,
        )
    ]
    registry.add(first)
    registry.add(second)
    assert [item.evidence_id for item in registry.all_items()] == [
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
        "E6",
    ]
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    dominant = list(registry.all_items())[:5]
    mixed = ensure_concept_representation(dominant, registry.all_items(), plan.concepts)
    blob = " ".join(item.content for item in mixed).lower()
    assert "record 2" in blob
    assert "effective date" in blob


def test_partial_token_overlap_is_not_covered() -> None:
    plan = extract_narrative_concepts(QUESTION, vocabulary=DATE_ALIASES)
    measured = measure_coverage(
        plan,
        ("Record 2 menciona fechas del calendario.",),
        searched=False,
    )
    date = next(item for item in measured if "fecha" in item.label.lower())
    assert date.status == PARTIAL
