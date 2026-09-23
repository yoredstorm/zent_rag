# =============================================================================
# Company Discovery — métricas (§24)
# =============================================================================
# Fail-soft: si prometheus_client no está disponible, los emisores son no-op.
# Métricas de descubrimiento, resolución y compilación de contexto.
# =============================================================================
from __future__ import annotations

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - dependencia opcional
    from prometheus_client import Counter, Gauge, Histogram

    entities_discovered_total = Counter(
        "company_entities_discovered_total",
        "Entidades propuestas al Company Graph",
        labelnames=["organization_id", "entity_type", "stage"],
    )
    entities_confirmed_total = Counter(
        "company_entities_confirmed_total",
        "Entidades confirmadas y materializadas en el Company Graph",
        labelnames=["organization_id", "entity_type"],
    )
    relationships_discovered_total = Counter(
        "company_relationships_discovered_total",
        "Relaciones propuestas al Company Graph",
        labelnames=["organization_id", "relationship_type", "stage"],
    )
    relationships_confirmed_total = Counter(
        "company_relationships_confirmed_total",
        "Relaciones confirmadas y materializadas",
        labelnames=["organization_id", "relationship_type"],
    )
    candidates_total = Counter(
        "company_discovery_candidates_total",
        "Candidatos observados por tipo y etapa",
        labelnames=["organization_id", "kind", "stage"],
    )
    entity_resolution_conflicts_total = Counter(
        "company_entity_resolution_conflicts_total",
        "Resoluciones ambiguas (no se fusiona automáticamente)",
        labelnames=["organization_id"],
    )
    knowledge_gaps_total = Counter(
        "company_knowledge_gaps_total",
        "Huecos de conocimiento detectados",
        labelnames=["organization_id", "gap_kind"],
    )
    discovery_run_duration = Histogram(
        "company_discovery_run_duration_seconds",
        "Duración de una corrida de descubrimiento",
        labelnames=["organization_id", "trigger"],
        buckets=(0.05, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    )
    context_compile_latency = Histogram(
        "company_context_compile_latency_seconds",
        "Latencia de compilación del contexto empresarial",
        labelnames=["organization_id"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    )
    context_entities_used = Gauge(
        "company_context_entities_used",
        "Entidades incluidas en el contexto compilado",
        labelnames=["organization_id"],
    )
    context_relationships_used = Gauge(
        "company_context_relationships_used",
        "Relaciones incluidas en el contexto compilado",
        labelnames=["organization_id"],
    )
    context_tokens_estimate = Gauge(
        "company_context_tokens_estimate",
        "Estimación de tokens del contexto compilado",
        labelnames=["organization_id"],
    )
except Exception:  # noqa: BLE001 - métricas nunca rompen el runtime
    entities_discovered_total = None  # type: ignore[assignment]
    entities_confirmed_total = None  # type: ignore[assignment]
    relationships_discovered_total = None  # type: ignore[assignment]
    relationships_confirmed_total = None  # type: ignore[assignment]
    candidates_total = None  # type: ignore[assignment]
    entity_resolution_conflicts_total = None  # type: ignore[assignment]
    knowledge_gaps_total = None  # type: ignore[assignment]
    discovery_run_duration = None  # type: ignore[assignment]
    context_compile_latency = None  # type: ignore[assignment]
    context_entities_used = None  # type: ignore[assignment]
    context_relationships_used = None  # type: ignore[assignment]
    context_tokens_estimate = None  # type: ignore[assignment]


def _label(value: object) -> str:
    return str(value)[:120]


def record_candidate(organization_id: object, kind: str, stage: str) -> None:
    if candidates_total is None:
        return
    try:
        candidates_total.labels(
            organization_id=_label(organization_id), kind=kind, stage=stage
        ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("company discovery metric failed", metric="candidates")


def record_resolution_conflict(organization_id: object) -> None:
    if entity_resolution_conflicts_total is None:
        return
    try:
        entity_resolution_conflicts_total.labels(
            organization_id=_label(organization_id)
        ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("company discovery metric failed", metric="resolution_conflict")


def record_knowledge_gap(organization_id: object, gap_kind: str) -> None:
    if knowledge_gaps_total is None:
        return
    try:
        knowledge_gaps_total.labels(
            organization_id=_label(organization_id), gap_kind=gap_kind
        ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("company discovery metric failed", metric="knowledge_gap")


def record_run(organization_id: object, trigger: str, seconds: float) -> None:
    if discovery_run_duration is None:
        return
    try:
        discovery_run_duration.labels(
            organization_id=_label(organization_id), trigger=trigger
        ).observe(max(0.0, seconds))
    except Exception:  # noqa: BLE001
        logger.debug("company discovery metric failed", metric="run_duration")


def record_context_compile(
    organization_id: object,
    *,
    seconds: float,
    entities: int,
    relationships: int,
    tokens: int,
) -> None:
    label = _label(organization_id)
    try:
        if context_compile_latency is not None:
            context_compile_latency.labels(organization_id=label).observe(
                max(0.0, seconds)
            )
        if context_entities_used is not None:
            context_entities_used.labels(organization_id=label).set(entities)
        if context_relationships_used is not None:
            context_relationships_used.labels(organization_id=label).set(relationships)
        if context_tokens_estimate is not None:
            context_tokens_estimate.labels(organization_id=label).set(tokens)
    except Exception:  # noqa: BLE001
        logger.debug("company discovery metric failed", metric="context_compile")
