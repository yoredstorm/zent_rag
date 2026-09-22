# =============================================================================
# Especialistas de aprendizaje. Interpretan números ya calculados.
# No se agregan al grafo de ejecución del Cognitive OS.
# =============================================================================
from __future__ import annotations

from src.core.domain.learning_cycle import Finding, Hypothesis, Recommendation

SPECIALISTS = (
    "retrieval_analyst",
    "knowledge_analyst",
    "decision_analyst",
    "agent_analyst",
    "finops_analyst",
)

_CATEGORY = {
    "retrieval": "retrieval_analyst",
    "grounding": "knowledge_analyst",
    "knowledge": "knowledge_analyst",
    "decision": "decision_analyst",
    "agent": "agent_analyst",
    "cost": "finops_analyst",
}


def explain_finding(finding: Finding) -> dict:
    specialist = _CATEGORY.get(finding.category, "knowledge_analyst")
    if finding.sample_size < 1 or not finding.observed.strip():
        text = "insufficient data"
    else:
        text = (
            f"{finding.pattern_key}: {finding.observed}. "
            f"Alternative: {finding.alternative or 'none'}. "
            f"Sample {finding.sample_size}. Window {finding.window}. "
            f"Confidence {finding.confidence}."
        )
    return {
        "specialist": specialist,
        "finding_id": str(finding.id),
        "interpretation": text,
        "invented_metrics": False,
    }


def explain_recommendation(recommendation: Recommendation) -> dict:
    specialist = "finops_analyst" if "cost" in recommendation.metrics else "retrieval_analyst"
    text = recommendation.explanation.strip() or "insufficient data"
    return {
        "specialist": specialist,
        "recommendation_id": str(recommendation.id),
        "interpretation": text,
        "invented_metrics": False,
    }


def explain_hypothesis(hypothesis: Hypothesis) -> dict:
    return {
        "specialist": "retrieval_analyst",
        "hypothesis_id": str(hypothesis.id),
        "interpretation": hypothesis.statement,
        "invented_metrics": False,
    }
