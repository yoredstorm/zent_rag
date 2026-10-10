# =============================================================================
# Narrative Coverage Closure — un top-k no es ausencia del corpus.
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import EvidenceItem
from src.runtime.evidence import EvidenceRegistry
from src.runtime.narrative_coverage import (
    BUDGET,
    COVERED,
    INITIAL_COMPLETE,
    MAX_ROUNDS,
    MISSING,
    NOT_FOUND_AFTER_COVERAGE_SEARCH,
    NOT_FOUND_IN_CURRENT_RETRIEVAL,
    PARTIAL,
    PARTIAL_MATERIAL,
    SUPPORTED,
    apply_coverage_limitation,
    build_coverage_query,
    coverage_needs_jev,
    coverage_requires_search,
    decide_coverage_round,
    ensure_concept_representation,
    extract_narrative_concepts,
    measure_coverage,
    narrative_coverage_applies,
    prefer_aspect_items,
    vocabulary_from_activation,
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
    assert decision.stop_reason == INITIAL_COMPLETE


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
    assert again.stop_reason == MAX_ROUNDS


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
    assert decision.coverage_search_skipped == BUDGET
    assert decision.stop_reason == BUDGET


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


# -----------------------------------------------------------------------------
# Regresión del caso vivo: «cuentame sobre el cambio de fechas en el record 2»
# -----------------------------------------------------------------------------
REGRESSION_QUESTION = "cuentame sobre el cambio de fechas en el record 2"


def test_entity_does_not_cover_aspect_in_same_frame() -> None:
    plan = extract_narrative_concepts(REGRESSION_QUESTION, vocabulary=DATE_ALIASES)
    assert len(plan.frames) == 1
    frame = plan.frames[0]
    assert frame.entity.lower() == "record 2"
    assert frame.aspect.lower() == "cambio de fechas"
    assert frame.relation == "aspect_of"
    measured = measure_coverage(plan, RECORD_ONLY, searched=False)
    [coverage] = measured
    assert coverage.entity_status == COVERED
    assert coverage.aspect_status == MISSING
    assert coverage.status == PARTIAL_MATERIAL
    assert coverage.material_gap is True
    assert coverage_requires_search(coverage, coverage.role) is True
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=4,
        headings=("Footnote", "Fare Class"),
    )
    assert decision.search is True
    assert decision.query.strip() != REGRESSION_QUESTION
    assert "record 2" in decision.query.lower()
    assert "effective date" in decision.query.lower()
    assert "cuentame" not in decision.query.lower()


def test_partial_material_aspect_coverage_triggers_search() -> None:
    plan = extract_narrative_concepts(REGRESSION_QUESTION, vocabulary=DATE_ALIASES)
    measured = measure_coverage(
        plan,
        ("Record 2 menciona fechas del calendario.",),
        searched=False,
    )
    [coverage] = measured
    assert coverage.status == PARTIAL_MATERIAL
    assert coverage.aspect_status == PARTIAL
    assert coverage_requires_search(coverage, coverage.role) is True


def test_multitopic_decomposes_entity_and_effective_dates() -> None:
    plan = extract_narrative_concepts(
        "cuentame sobre record 2 y las fechas de efectividad",
        vocabulary=DATE_ALIASES,
    )
    entities = [frame for frame in plan.frames if frame.entity]
    assert [frame.entity.lower() for frame in entities] == ["record 2"]
    aspects = " ".join(frame.aspect for frame in plan.frames).lower()
    assert "efectividad" in aspects


def test_simple_query_does_not_open_a_coverage_round() -> None:
    plan = extract_narrative_concepts("qué significa & en Record 2")
    assert len(plan.frames) == 1
    measured = measure_coverage(plan, ("Record 2 byte uses &.",), searched=False)
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=4,
    )
    assert decision.search is False
    assert decision.stop_reason == INITIAL_COMPLETE


def test_spanish_date_aspect_does_not_invent_english_aliases(monkeypatch) -> None:
    from src.runtime import narrative_coverage as nc

    monkeypatch.setattr(nc, "_pack_aliases", lambda label: ())
    plan = extract_narrative_concepts("cuentame sobre el record 2 y el cambio de fechas")
    date = next(concept for concept in plan.concepts if "fecha" in concept.label.lower())
    assert date.aliases == ()


def test_known_alias_pack_expands_the_date_aspect(monkeypatch) -> None:
    """El pack vertical es metadata de aliases: la lógica genérica solo lo consulta."""
    from src.runtime import narrative_coverage as nc

    monkeypatch.setattr(
        nc,
        "_pack_aliases",
        lambda label: ("Eff Date", "Disc Date") if "fecha" in label.lower() else (),
    )
    plan = extract_narrative_concepts("cuentame sobre el cambio de fechas en el record 2")
    date = next(concept for concept in plan.concepts if "fecha" in concept.label.lower())
    assert "Eff Date" in date.aliases
    measured = measure_coverage(plan, RECORD_ONLY, searched=False)
    [coverage] = measured
    assert coverage.status == PARTIAL_MATERIAL
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=4,
    )
    assert decision.search is True
    query = decision.query.lower()
    assert "eff date" in query
    assert "disc date" in query
    found = measure_coverage(
        plan,
        ("Record 2 uses the Eff Date and Disc Date fields.",),
        searched=True,
    )
    [covered] = found
    assert covered.status == COVERED


def test_learned_fabric_labels_cover_the_date_aspect() -> None:
    question = "cuentame sobre el record 2 y el cambio de fechas"
    vocabulary = vocabulary_from_activation(question, ("Eff Date", "Disc Date"))
    plan = extract_narrative_concepts(question, vocabulary=vocabulary)
    date = next(concept for concept in plan.concepts if "fecha" in concept.label.lower())
    assert "eff date" in [alias.lower() for alias in date.aliases]
    evidence = (
        "Footnote Record 2 is an exact match.",
        "Eff Date | Disc Date | See the Date processing Section on Effective date Matching.",
    )
    measured = measure_coverage(plan, evidence, searched=False)
    covered = next(item for item in measured if "fecha" in item.label.lower())
    assert covered.status == COVERED
    limited = apply_coverage_limitation(
        "Record 2 matchea Eff Date y Disc Date [Doc: 1].",
        measured,
    )
    assert "no encontré evidencia suficiente" not in limited.lower()


def test_missing_date_aspect_does_not_inject_a_domain_dictionary(monkeypatch) -> None:
    from src.runtime import narrative_coverage as nc

    monkeypatch.setattr(nc, "_pack_aliases", lambda label: ())
    plan = extract_narrative_concepts("cuentame sobre el cambio de fechas en el record 2")
    measured = measure_coverage(plan, RECORD_ONLY, searched=False)
    [coverage] = measured
    assert coverage.status == PARTIAL_MATERIAL
    decision = decide_coverage_round(
        measured,
        rounds_done=0,
        max_rounds=1,
        remaining_steps=4,
    )
    assert decision.search is True
    query = decision.query.lower()
    assert "effective date" not in query
    assert "cambio de fechas" in query
    assert "record 2" in query


def test_aspect_evidence_leads_and_unrelated_sections_stay_short() -> None:
    question = "cuentame sobre el record 2 y el cambio de fechas"
    plan = extract_narrative_concepts(
        question,
        vocabulary=vocabulary_from_activation(question, ("Eff Date", "Disc Date")),
    )
    items = [
        EvidenceItem(source_type="qdrant", content="Footnote Record 2 exact match.", score=0.9),
        EvidenceItem(source_type="qdrant", content="Fare class hyphen family.", score=0.8),
        EvidenceItem(source_type="qdrant", content="Stringing exceptions AND OR.", score=0.7),
        EvidenceItem(
            source_type="qdrant",
            content="Eff Date and Disc Date. See the Date processing Section.",
            score=0.4,
        ),
    ]
    ordered = prefer_aspect_items(items, plan.concepts)
    assert "eff date" in ordered[0].content.lower()
    assert len(ordered) <= 3
