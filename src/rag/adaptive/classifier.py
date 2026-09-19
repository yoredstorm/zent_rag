# =============================================================================
# RulesClassifier + optional JEV overlay. classify_query stays the fallback.
# =============================================================================
from __future__ import annotations

from src.rag.retrieval.classify import classify_query
from src.rag.retrieval.models import QueryClassification


class RulesClassifier:
    """Deterministic wrapper around classify_query. Do not delete classify.py."""

    def classify(self, query: str) -> QueryClassification:
        return classify_query(query)


def overlay_strategy(
    *,
    rules_strategy: str,
    jev_strategy: str | None,
    jev_confidence: float,
    high_confidence: float,
) -> str:
    """Keep the rules strategy unless JEV Choice is confident and valid."""
    allowed = {"exact", "lexical", "vector", "hybrid", "structured", "mixed"}
    if jev_strategy in allowed and jev_confidence >= high_confidence:
        return jev_strategy
    return rules_strategy


def overlay_modality(
    *,
    rules_modality: str,
    jev_modality: str | None,
    jev_confidence: float,
    high_confidence: float,
) -> str:
    allowed = {
        "documents",
        "structured_data",
        "mixed",
        "tool",
        "workflow",
        "conversational",
    }
    if jev_modality in allowed and jev_confidence >= high_confidence:
        return jev_modality
    return rules_modality
