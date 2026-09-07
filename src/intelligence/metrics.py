# =============================================================================
# Intelligence Metrics — observabilidad del Answerability Engine
# =============================================================================
# Contadores de baja cardinalidad (label organization_id + estado). Convención
# de naming rag_* del repo. La decisión de abstención se registra con el
# estado formal (10 valores posibles).
# =============================================================================
from __future__ import annotations

from src.core.domain.intelligence import AnswerabilityDecision
from src.infrastructure.observability.metrics import (
    rag_abstained_queries_total,
    rag_ambiguous_queries_total,
    rag_answerable_queries_total,
    rag_context_missing_total,
    rag_data_missing_total,
    rag_execution_failures_total,
    rag_source_conflicts_total,
)

_ABSTENTION_BY_STATUS = {
    "CLARIFICATION_REQUIRED": rag_ambiguous_queries_total,
    "AMBIGUOUS": rag_ambiguous_queries_total,
    "CONTEXT_MISSING": rag_context_missing_total,
    "DATA_MISSING": rag_data_missing_total,
    "SOURCE_CONFLICT": rag_source_conflicts_total,
    "EXECUTION_FAILED": rag_execution_failures_total,
}


def record_answerability(
    organization_id: str,
    decision: AnswerabilityDecision,
) -> None:
    """Registra la decisión de answerability en métricas Prometheus."""
    org = organization_id
    if decision.answerable:
        rag_answerable_queries_total.labels(organization_id=org).inc()
        return
    rag_abstained_queries_total.labels(
        organization_id=org, reason=decision.status.value
    ).inc()
    counter = _ABSTENTION_BY_STATUS.get(decision.status.value)
    if counter is not None:
        counter.labels(organization_id=org).inc()
