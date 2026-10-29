# =============================================================================
# P18.2-08 — Reparación histórica no destructiva
# =============================================================================
from __future__ import annotations

from src.knowledge.understanding.cleanup import classify_historical_object


def _classify(name: str, **overrides) -> dict:
    return classify_historical_object(
        name=name,
        kind=overrides.pop("kind", "concept"),
        description=overrides.pop("description", "descripción"),
        evidence_count=overrides.pop("evidence_count", 2),
        document_genre=overrides.pop("document_genre", "narrative"),
    )


def test_question_and_dialogue_are_invalid_labels_not_concepts() -> None:
    assert _classify("planeta?")["classification"] == "invalid_label"
    assert _classify("—dijo el zorro")["classification"] == "invalid_label"
    assert _classify("52")["classification"] == "invalid_label"


def test_well_formed_repeated_label_needs_review_not_automatic_hide() -> None:
    result = _classify("El principito", evidence_count=48)
    assert result["classification"] == "potentially_valid"
    assert result["safe_to_hide"] is False
    assert result["recommended_action"] == "review"


def test_missing_evidence_is_weak_not_potentially_valid() -> None:
    result = _classify("Término sin respaldo", evidence_count=0)
    assert result["classification"] == "weak_evidence"
    assert result["safe_to_hide"] is True


def test_business_rule_in_narrative_is_flagged_for_review() -> None:
    result = _classify(
        "El rey ordenó",
        kind="business_rule",
        document_genre="narrative",
        evidence_count=3,
    )
    assert result["classification"] == "misclassified_genre"
    assert result["safe_to_hide"] is False


def test_ambiguous_fragment_is_not_promoted() -> None:
    result = _classify("deese modo enteré", evidence_count=1)
    assert result["classification"] in {
        "needs_context",
        "requires_human_review",
        "invalid_label",
    }
    assert result["classification"] != "potentially_valid"
