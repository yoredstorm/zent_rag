# =============================================================================
# Budget-aware intelligence — resumen seguro para el Judgment Fabric.
# =============================================================================
# JEV recibe un RESUMEN (budget_class, remaining_ratio, cost_pressure), nunca
# balances financieros. El código decide los límites; JEV sólo puede sesgar la
# elección dentro de lo ya permitido. Ninguna degradación de seguridad por
# presupuesto: risk policy manda sobre cost pressure.
# =============================================================================
from __future__ import annotations

from typing import Any

BUDGET_UNKNOWN = "unknown"
BUDGET_DEPLETED = "depleted"
BUDGET_LOW = "low"
BUDGET_NORMAL = "normal"
BUDGET_HEALTHY = "healthy"

_SAFE_LIMIT_KEYS = (
    "request_limit",
    "token_limit",
    "agent_run_limit",
    "workflow_run_limit",
)


def budget_summary(
    budget: dict[str, Any] | None,
    *,
    low_ratio: float = 0.15,
    healthy_ratio: float = 0.50,
) -> dict[str, Any]:
    """Clase de presupuesto sin exponer saldos.

    `remaining_ratio` es remaining/granted (0-1) o None si no hay wallet.
    """
    data = dict(budget or {})
    granted = _positive(data.get("granted"))
    remaining = data.get("remaining")
    if granted is None:
        budget_class = BUDGET_UNKNOWN
        remaining_ratio: float | None = None
    else:
        ratio = max(0.0, min(1.0, (_positive(remaining) or 0.0) / granted))
        remaining_ratio = round(ratio, 4)
        if ratio <= 0.0:
            budget_class = BUDGET_DEPLETED
        elif ratio <= max(0.0, min(1.0, low_ratio)):
            budget_class = BUDGET_LOW
        elif ratio < max(0.0, min(1.0, healthy_ratio)):
            budget_class = BUDGET_NORMAL
        else:
            budget_class = BUDGET_HEALTHY
    prefer_cheap = bool(data.get("prefer_cheap")) or budget_class in {
        BUDGET_DEPLETED,
        BUDGET_LOW,
    }
    return {
        "budget_class": budget_class,
        "remaining_ratio": remaining_ratio,
        "cost_pressure": prefer_cheap,
        "prefer_cheap": prefer_cheap,
        "on_limit": str(data.get("on_limit") or "block")[:20],
        "limits": {
            key: data.get(key)
            for key in _SAFE_LIMIT_KEYS
            if data.get(key) is not None
        },
    }


def cheap_path_hints(summary: dict[str, Any] | None) -> dict[str, bool]:
    """Sesgos permitidos por presupuesto. Nunca tocan seguridad ni policy."""
    data = summary or {}
    pressure = bool(data.get("cost_pressure"))
    return {
        "prefer_cheap": pressure,
        "prefer_deterministic": pressure,
        "reduce_top_k": pressure,
        "prefer_small_model": pressure,
    }


def enrich_budget(budget: dict[str, Any] | None) -> dict[str, Any]:
    """Budget original + resumen, para DecisionContext.budget."""
    data = dict(budget or {})
    data["summary"] = budget_summary(data)
    return data


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
