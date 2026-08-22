# =============================================================================
# Retrieval Config — configuración por tenant con resolución en cascada
# =============================================================================
# Precedencia: request > organization.config_json["retrieval"] > settings.
# Sin imports de infraestructura: settings vienen de src.core.config.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from src.core.config import get_settings
from src.rag.retrieval.models import (
    FUSION_RRF,
    RETRIEVAL_STRATEGIES,
    STRATEGY_VECTOR,
)

_VALID_KEYS = {
    "strategy",
    "top_k",
    "rerank_top_k",
    "score_threshold",
    "reranker",
    "fusion",
    "rrf_k",
    "lexical_weight",
    "language",
    "doc_type_priority",
}


@dataclass(kw_only=True, frozen=True)
class RetrievalConfig:
    """Configuración efectiva del motor de retrieval para un tenant/query."""

    strategy: str = STRATEGY_VECTOR
    top_k: int = 200
    rerank_top_k: int = 20
    score_threshold: float = 0.1
    reranker: str | None = None
    fusion: str = FUSION_RRF
    rrf_k: int = 60
    lexical_weight: float = 0.3
    language: str | None = None
    doc_type_priority: list[str] = field(default_factory=lambda: ["aggregated"])


def _clean_overrides(raw: dict[str, Any] | None) -> dict[str, Any]:
    if not raw:
        return {}
    return {k: v for k, v in raw.items() if k in _VALID_KEYS and v is not None}


def resolve_retrieval_config(
    request_overrides: dict[str, Any] | None = None,
    organization_config: dict[str, Any] | None = None,
) -> RetrievalConfig:
    """Resuelve config en cascada: request > config_json org > settings.

    Las claves desconocidas se ignoran (config_json es libre; el motor solo
    consume las que entiende). Los valores inválidos caen a defaults.
    """
    settings = get_settings()
    base = RetrievalConfig(
        strategy=settings.RAG_RETRIEVAL_STRATEGY
        if settings.RAG_RETRIEVAL_STRATEGY in RETRIEVAL_STRATEGIES
        else STRATEGY_VECTOR,
        top_k=settings.RAG_TOP_K,
        rerank_top_k=settings.RAG_RERANK_TOP_N,
        score_threshold=settings.RAG_SCORE_THRESHOLD,
        reranker=settings.RAG_RERANKER or None,
        fusion=settings.RAG_HYBRID_FUSION,
        rrf_k=settings.RAG_RRF_K,
        lexical_weight=settings.RAG_HYBRID_LEXICAL_WEIGHT,
    )

    org_overrides = _clean_overrides(
        (organization_config or {}).get("retrieval")
        if isinstance(organization_config, dict)
        else None
    )
    request = _clean_overrides(request_overrides)

    config = base
    for overrides in (org_overrides, request):
        if "doc_type_priority" in overrides:
            priority = overrides.pop("doc_type_priority")
            if isinstance(priority, list) and priority:
                config = replace(config, doc_type_priority=[str(p) for p in priority])
        config = replace(config, **overrides)

    if config.top_k < 1:
        config = replace(config, top_k=1)
    if config.rerank_top_k > config.top_k:
        config = replace(config, rerank_top_k=config.top_k)
    if not 0.0 <= config.score_threshold <= 1.0:
        config = replace(config, score_threshold=0.1)
    return config
