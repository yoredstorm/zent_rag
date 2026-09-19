# =============================================================================
# AI Efficiency Score — visible components; weights configurable, never invented.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WEIGHTS = {
    "quality": 0.40,
    "cost": 0.25,
    "latency": 0.20,
    "fallback": 0.15,
}


@dataclass(frozen=True)
class EfficiencyComponents:
    quality: float
    cost: float
    latency: float
    fallback: float


def normalize_weights(raw: dict | None) -> dict[str, float]:
    src = dict(DEFAULT_WEIGHTS)
    if isinstance(raw, dict):
        for key in DEFAULT_WEIGHTS:
            if raw.get(key) is None:
                continue
            try:
                src[key] = max(0.0, float(raw[key]))
            except (TypeError, ValueError):
                continue
    total = sum(src.values()) or 1.0
    return {k: round(v / total, 4) for k, v in src.items()}


def composite_score(components: EfficiencyComponents, weights: dict[str, float] | None = None) -> float:
    w = normalize_weights(weights)
    value = (
        components.quality * w["quality"]
        + components.cost * w["cost"]
        + components.latency * w["latency"]
        + components.fallback * w["fallback"]
    )
    return round(min(1.0, max(0.0, value)), 4)


def from_dashboard(
    *,
    average_confidence: float,
    fallback_rate: float,
    average_latency_ms: float,
    target_latency_ms: float = 800.0,
    cost_index: float = 1.0,
) -> tuple[EfficiencyComponents, float, dict[str, float]]:
    """Map visible metrics to 0-1 components. Higher is better."""
    quality = min(1.0, max(0.0, float(average_confidence or 0.0)))
    fallback = min(1.0, max(0.0, 1.0 - float(fallback_rate or 0.0)))
    latency = min(1.0, max(0.0, 1.0 - (float(average_latency_ms or 0.0) / max(target_latency_ms, 1.0))))
    cost = min(1.0, max(0.0, float(cost_index)))
    components = EfficiencyComponents(quality=quality, cost=cost, latency=latency, fallback=fallback)
    weights = dict(DEFAULT_WEIGHTS)
    return components, composite_score(components, weights), weights
