# =============================================================================
# Evidence Reasoning — métricas (§64)
# =============================================================================
# Fail-soft: si prometheus_client no está, los emisores son no-op.
# =============================================================================
from __future__ import annotations

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - dependencia opcional
    from prometheus_client import Counter, Histogram

    reasoning_requests_total = Counter(
        "zent_reasoning_requests_total",
        "Preguntas clasificadas por forma de razonamiento",
        labelnames=["shape"],
    )
    reasoning_activation_total = Counter(
        "zent_reasoning_activation_total",
        "Requests que activaron el motor de razonamiento",
        labelnames=["shape", "mode"],
    )
    scenario_events_total = Counter(
        "zent_scenario_events_total",
        "Eventos parseados de escenarios",
        labelnames=["organization_id"],
    )
    scenario_parse_failures_total = Counter(
        "zent_scenario_parse_failures_total",
        "Escenarios que quedaron parciales",
        labelnames=["reason"],
    )
    reasoning_requirements_total = Counter(
        "zent_reasoning_requirements_total",
        "Requisitos de evidencia por estado",
        labelnames=["kind", "status"],
    )
    state_transitions_total = Counter(
        "zent_state_transitions_total",
        "Transiciones de estado derivadas",
        labelnames=["status"],
    )
    hypotheses_total = Counter(
        "zent_hypotheses_total",
        "Hipótesis por veredicto",
        labelnames=["verdict", "origin"],
    )
    inference_verdict_total = Counter(
        "zent_inference_verdict_total",
        "Inferencias verificadas por veredicto",
        labelnames=["verdict"],
    )
    reasoning_completion_total = Counter(
        "zent_reasoning_completion_total",
        "Gate de completitud por estado",
        labelnames=["status"],
    )
    reasoning_retrieval_rounds = Histogram(
        "zent_reasoning_retrieval_rounds",
        "Rondas de adquisición de evidencia por request",
        buckets=(0, 1, 2, 3, 4, 6, 8),
    )
    reasoning_latency = Histogram(
        "zent_reasoning_latency_seconds",
        "Latencia del motor de razonamiento",
        labelnames=["shape"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    reasoning_cost_total = Counter(
        "zent_reasoning_cost_total",
        "Costo estimado del razonamiento",
        labelnames=["shape"],
    )
    reasoning_company_context_hits_total = Counter(
        "zent_reasoning_company_context_hits_total",
        "Uso de Company Context en razonamiento",
        labelnames=["section"],
    )
    reasoning_memory_hits_total = Counter(
        "zent_reasoning_memory_hits_total",
        "Uso de memoria operativa en razonamiento",
    )
except Exception:  # noqa: BLE001 - métricas nunca rompen el runtime
    reasoning_requests_total = None  # type: ignore[assignment]
    reasoning_activation_total = None  # type: ignore[assignment]
    scenario_events_total = None  # type: ignore[assignment]
    scenario_parse_failures_total = None  # type: ignore[assignment]
    reasoning_requirements_total = None  # type: ignore[assignment]
    state_transitions_total = None  # type: ignore[assignment]
    hypotheses_total = None  # type: ignore[assignment]
    inference_verdict_total = None  # type: ignore[assignment]
    reasoning_completion_total = None  # type: ignore[assignment]
    reasoning_retrieval_rounds = None  # type: ignore[assignment]
    reasoning_latency = None  # type: ignore[assignment]
    reasoning_cost_total = None  # type: ignore[assignment]
    reasoning_company_context_hits_total = None  # type: ignore[assignment]
    reasoning_memory_hits_total = None  # type: ignore[assignment]


def _label(value: object) -> str:
    return str(value)[:120]


def record_classification(shape: str) -> None:
    if reasoning_requests_total is None:
        return
    try:
        reasoning_requests_total.labels(shape=shape).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="requests")


def record_activation(shape: str, mode: str) -> None:
    if reasoning_activation_total is None:
        return
    try:
        reasoning_activation_total.labels(shape=shape, mode=mode).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="activation")


def record_scenario(organization_id: object, events: int, partial_reason: str = "") -> None:
    try:
        if scenario_events_total is not None and events:
            scenario_events_total.labels(organization_id=_label(organization_id)).inc(
                events
            )
        if scenario_parse_failures_total is not None and partial_reason:
            scenario_parse_failures_total.labels(reason=partial_reason).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="scenario")


def record_requirements(items) -> None:
    if reasoning_requirements_total is None:
        return
    try:
        for item in items:
            reasoning_requirements_total.labels(
                kind=item.kind.value, status="resolved" if item.resolved else "missing"
            ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="requirements")


def record_transitions(transitions) -> None:
    if state_transitions_total is None or transitions is None:
        return
    try:
        for item in transitions.transitions:
            state_transitions_total.labels(status=item.status.value).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="transitions")


def record_hypotheses(hypotheses) -> None:
    if hypotheses_total is None or hypotheses is None:
        return
    try:
        for item in hypotheses.hypotheses:
            hypotheses_total.labels(
                verdict=item.verdict.value, origin=item.origin.value
            ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="hypotheses")


def record_inferences(inferences) -> None:
    if inference_verdict_total is None:
        return
    try:
        for item in inferences:
            inference_verdict_total.labels(verdict=item.verdict.value).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="inferences")


def record_completion(complete: bool) -> None:
    if reasoning_completion_total is None:
        return
    try:
        reasoning_completion_total.labels(
            status="complete" if complete else "incomplete"
        ).inc()
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="completion")


def record_run(
    *, shape: str, seconds: float, cost_usd: float, retrieval_rounds: int
) -> None:
    try:
        if reasoning_latency is not None:
            reasoning_latency.labels(shape=shape).observe(max(0.0, seconds))
        if reasoning_cost_total is not None and cost_usd:
            reasoning_cost_total.labels(shape=shape).inc(cost_usd)
        if reasoning_retrieval_rounds is not None:
            reasoning_retrieval_rounds.observe(max(0, retrieval_rounds))
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="run")


def record_company_context(sections: dict) -> None:
    if reasoning_company_context_hits_total is None:
        return
    try:
        for section, count in (sections or {}).items():
            if count:
                reasoning_company_context_hits_total.labels(
                    section=str(section)[:40]
                ).inc(int(count))
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="company_context")


def record_memory_hits(count: int) -> None:
    if reasoning_memory_hits_total is None or not count:
        return
    try:
        reasoning_memory_hits_total.inc(int(count))
    except Exception:  # noqa: BLE001
        logger.debug("reasoning metric failed", metric="memory_hits")
