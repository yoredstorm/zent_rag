# =============================================================================
# Adaptive RAG Prometheus metrics — low cardinality labels.
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import AdaptivePlan, EvidenceQuality

_STRATEGIES = ("exact", "lexical", "vector", "hybrid", "structured", "mixed")
_ROUTES = (
    "knowledge.search",
    "database.query",
    "mixed",
    "direct",
    "tool",
    "workflow",
    "agent",
)
_PATHS = ("fast", "standard", "complex")
_MODES = ("off", "shadow", "active", "canary")


def _lab(value: str, allowed: tuple[str, ...]) -> str:
    return value if value in allowed else "other"


def record_plan(plan: AdaptivePlan) -> None:
    try:
        import src.infrastructure.observability.metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_adaptive_requests_total.labels(
        mode=_lab(plan.mode, _MODES),
        path=_lab(plan.path, _PATHS),
        applied=str(plan.apply).lower(),
    ).inc()
    m.zent_adaptive_strategy_total.labels(
        strategy=_lab(plan.retrieval_strategy, _STRATEGIES)
    ).inc()
    m.zent_adaptive_source_route_total.labels(
        route=_lab(plan.source_route, _ROUTES)
    ).inc()
    m.zent_adaptive_top_k.observe(max(0, plan.top_k))
    m.zent_adaptive_decision_confidence.observe(min(1.0, max(0.0, plan.confidence)))
    if plan.cache_hit:
        m.zent_adaptive_cache_hit_total.labels(kind="plan").inc()


def record_quality(quality: EvidenceQuality) -> None:
    try:
        import src.infrastructure.observability.metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_adaptive_evidence_quality.observe(min(1.0, max(0.0, quality.score)))


def record_attempts(n: int) -> None:
    try:
        import src.infrastructure.observability.metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_adaptive_retrieval_attempts.observe(max(1, n))


def record_llm_skipped() -> None:
    try:
        import src.infrastructure.observability.metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_adaptive_llm_skipped_total.inc()


def record_grounding(score: float) -> None:
    try:
        import src.infrastructure.observability.metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_adaptive_grounding_score.observe(min(1.0, max(0.0, score)))


def record_tokens(before: int, after: int) -> None:
    try:
        import src.infrastructure.observability.metrics as m
    except Exception:  # noqa: BLE001
        return
    m.zent_adaptive_context_tokens.labels(stage="before").observe(max(0, before))
    m.zent_adaptive_context_tokens.labels(stage="after").observe(max(0, after))
