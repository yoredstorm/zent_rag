# =============================================================================
# Enrichment — métricas Prometheus (fail-silent)
# =============================================================================
# Regla: NUNCA poner document_id/source_id como label (cardinalidad). Los ids
# concretos viven en logs/DB. Solo organization_id (ya usado por el resto del
# pipeline) y etiquetas de baja cardinalidad.
# =============================================================================
from __future__ import annotations

from prometheus_client import Counter, Histogram

try:  # pragma: no cover - import defensivo (tests sin prometheus)
    from src.infrastructure.observability.metrics import (
        knowledge_enrichment_aliases_total,
        knowledge_enrichment_questions_total,
        knowledge_enrichment_rejected_total,
        knowledge_enrichment_seconds,
        knowledge_enrichment_units_total,
        knowledge_nutrition_actions_total,
        knowledge_nutrition_score,
        knowledge_reindex_reason_total,
        knowledge_representation_rebuilds_total,
        knowledge_retrieval_acceptance_failures_total,
        knowledge_retrieval_acceptance_recall,
        knowledge_retrieval_acceptance_runs_total,
    )
except Exception:  # pragma: no cover - definición mínima si el módulo cambió
    knowledge_enrichment_units_total = Counter(
        "knowledge_enrichment_units_total", "Unidades enriquecidas", ["organization_id", "kind"]
    )
    knowledge_enrichment_aliases_total = Counter(
        "knowledge_enrichment_aliases_total", "Aliases de enrichment", ["organization_id"]
    )
    knowledge_enrichment_questions_total = Counter(
        "knowledge_enrichment_questions_total", "Preguntas sintéticas", ["organization_id"]
    )
    knowledge_enrichment_seconds = Histogram(
        "knowledge_enrichment_seconds", "Latencia de enrichment", ["organization_id"]
    )
    knowledge_enrichment_rejected_total = Counter(
        "knowledge_enrichment_rejected_total", "Items rechazados", ["organization_id", "reason"]
    )
    knowledge_representation_rebuilds_total = Counter(
        "knowledge_representation_rebuilds_total", "Reconstrucciones de representación", ["organization_id", "reason"]
    )
    knowledge_retrieval_acceptance_runs_total = Counter(
        "knowledge_retrieval_acceptance_runs_total", "Corridas de acceptance", ["organization_id", "outcome"]
    )
    knowledge_retrieval_acceptance_recall = Histogram(
        "knowledge_retrieval_acceptance_recall", "Recall@k de acceptance", ["organization_id", "k"]
    )
    knowledge_retrieval_acceptance_failures_total = Counter(
        "knowledge_retrieval_acceptance_failures_total", "Probes fallidos", ["organization_id", "query_type"]
    )
    knowledge_nutrition_actions_total = Counter(
        "knowledge_nutrition_actions_total", "Acciones de nutrition", ["organization_id", "action_type"]
    )
    knowledge_nutrition_score = Histogram(
        "knowledge_nutrition_score", "Nutrition score", ["organization_id", "scope"]
    )
    knowledge_reindex_reason_total = Counter(
        "knowledge_reindex_reason_total", "Reindex por razón", ["organization_id", "reason"]
    )


def observe_enrichment(organization_id, result) -> None:
    try:
        org = str(organization_id)
        knowledge_enrichment_units_total.labels(organization_id=org, kind="total").inc(
            result.statistics.units_total
        )
        knowledge_enrichment_aliases_total.labels(organization_id=org).inc(
            result.statistics.retrieval_aliases
        )
        knowledge_enrichment_questions_total.labels(organization_id=org).inc(
            result.statistics.synthetic_questions
        )
        knowledge_enrichment_seconds.labels(organization_id=org).observe(
            max(0.0, float(result.statistics.seconds))
        )
        if result.statistics.rejected_items:
            knowledge_enrichment_rejected_total.labels(
                organization_id=org, reason="provenance"
            ).inc(result.statistics.rejected_items)
    except Exception:  # noqa: BLE001
        return


def observe_representation_rebuild(organization_id, reason: str) -> None:
    try:
        knowledge_representation_rebuilds_total.labels(
            organization_id=str(organization_id), reason=reason
        ).inc()
    except Exception:  # noqa: BLE001
        return


def observe_reindex_reason(organization_id, reason: str) -> None:
    try:
        knowledge_reindex_reason_total.labels(
            organization_id=str(organization_id), reason=reason
        ).inc()
    except Exception:  # noqa: BLE001
        return
