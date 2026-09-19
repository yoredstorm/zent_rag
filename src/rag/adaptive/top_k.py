# =============================================================================
# Dynamic top_k — global and per-tenant caps. Never unbounded.
# =============================================================================
from __future__ import annotations

from src.rag.adaptive.settings import AdaptiveRagSettings


def resolve_top_k(
    *,
    path: str,
    complexity: str,
    settings: AdaptiveRagSettings,
    tenant_max: int | None = None,
) -> int:
    if path == "fast" or complexity == "trivial":
        value = settings.top_k_lookup
    elif path == "complex" or complexity == "reasoning":
        value = settings.top_k_multi
    elif complexity == "multi_step":
        value = settings.top_k_compare
    else:
        value = settings.top_k_compare
    value = max(settings.top_k_min, min(settings.top_k_max, value))
    if tenant_max is not None and tenant_max > 0:
        value = min(value, tenant_max)
    return value
