# =============================================================================
# P18.2-08 — Clasificación no destructiva de objetos históricos
# =============================================================================
# Decide qué se puede ocultar de la vista natural y qué exige revisión humana.
# No borra, no reescribe evidencia y no cambia IDs canónicos.
# =============================================================================
from __future__ import annotations

from src.knowledge.compiler.candidates import assess_entity_candidate

_CLASSIFICATIONS = {
    "invalid_label",
    "needs_context",
    "weak_evidence",
    "misclassified_genre",
    "potentially_valid",
    "requires_human_review",
}
_SAFE_TO_HIDE = {"invalid_label", "needs_context", "weak_evidence"}


def classify_historical_object(
    *,
    name: str,
    kind: str,
    description: str = "",
    evidence_count: int = 0,
    document_genre: str | None = None,
) -> dict:
    label = (name or "").strip()
    decision = assess_entity_candidate(
        label,
        kind=(kind or "concept"),
        text=description or "",
        has_locator=evidence_count > 0,
    )
    if evidence_count <= 0:
        classification = "weak_evidence"
        why = "sin evidencia registrada"
    elif document_genre in {"narrative", "educational"} and kind in {
        "business_rule",
        "rule",
        "constraint",
    }:
        classification = "misclassified_genre"
        why = "regla en un documento narrativo/educativo; revisar antes de ocultar"
    elif decision.reason in {
        "QUESTION_OR_DIALOGUE",
        "DIALOGUE_FRAGMENT",
        "ISOLATED_NUMBER",
        "NON_TERM_LABEL",
    }:
        classification = "invalid_label"
        why = decision.detail or decision.reason
    elif not decision.accepted:
        classification = "needs_context"
        why = decision.detail or decision.reason
    elif decision.accepted and evidence_count >= 2:
        classification = "potentially_valid"
        why = "etiqueta autónoma con evidencia; no ocultar sin revisión"
    else:
        classification = "requires_human_review"
        why = "evidencia insuficiente o contexto ambiguo"
    if classification not in _CLASSIFICATIONS:
        classification = "requires_human_review"
    return {
        "classification": classification,
        "recommended_action": "hide" if classification in _SAFE_TO_HIDE else "review",
        "safe_to_hide": classification in _SAFE_TO_HIDE,
        "why": why,
        "semantic_gate": decision.reason,
        "needs_review": decision.needs_review,
    }


__all__ = ["classify_historical_object"]
