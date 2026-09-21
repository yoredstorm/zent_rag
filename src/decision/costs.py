# =============================================================================
# Decision cost resolution — Pricing Registry primero, settings legacy después.
# =============================================================================
# El Pricing Registry (src/platform/billing/pricing.py) es la fuente canónica
# de precio. Las settings `estimated_cost_per_1k` quedan como fallback temporal
# SOLO cuando el registry no está disponible (DB caída, tabla ausente, error).
#
# El esquema de precio lo define el registry: input_cost_per_1k,
# output_cost_per_1k, embedding_cost_per_1k, request_cost, cost_kind. Acá no
# se hardcodea ninguna fórmula por provider.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

JEV_PROVIDER = "jev"

# Origen del precio usado en una estimación.
SOURCE_REGISTRY = "registry"
SOURCE_LEGACY = "legacy"
SOURCE_NONE = "none"


@dataclass(frozen=True, kw_only=True)
class DecisionCost:
    amount: float = 0.0
    source: str = SOURCE_NONE
    provider: str = ""
    model: str = ""
    cost_kind: str = "provider"


def qualified_model(provider: str, model: str) -> str:
    """`jev` + `jev-latest` → `jev/jev-latest` (el registry resuelve provider)."""
    model = (model or "").strip()
    provider = (provider or "").strip()
    if not provider or provider == "default" or "/" in model:
        return model
    return f"{provider}/{model}" if model else provider


async def resolve_cost(
    *,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    embedding_tokens: int = 0,
    legacy_per_1k: float = 0.0,
) -> DecisionCost:
    """Costo estimado con prioridad: Pricing Registry → fallback legacy.

    Nunca lanza: ante cualquier error devuelve `source="none"` o el fallback.
    """
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    embeddings = max(0, int(embedding_tokens or 0))
    total = prompt + completion + embeddings
    if total <= 0:
        return DecisionCost(
            amount=0.0, source=SOURCE_NONE, provider=provider, model=model
        )
    try:
        from src.platform.billing.pricing import estimate_cost_from_price, get_price

        price = await get_price(qualified_model(provider, model))
        amount = estimate_cost_from_price(price, prompt, completion, embeddings)
        return DecisionCost(
            amount=max(0.0, float(amount)),
            source=SOURCE_REGISTRY,
            provider=price.provider,
            model=price.model,
            cost_kind=str(price.cost_kind or "provider"),
        )
    except Exception as exc:  # noqa: BLE001 — registry caído no rompe el juicio
        logger.debug("pricing registry unavailable", error=str(exc)[:160])
    fallback = float(legacy_per_1k or 0.0)
    if fallback > 0:
        return DecisionCost(
            amount=(total / 1000.0) * fallback,
            source=SOURCE_LEGACY,
            provider=provider,
            model=model,
        )
    return DecisionCost(
        amount=0.0, source=SOURCE_NONE, provider=provider, model=model
    )
