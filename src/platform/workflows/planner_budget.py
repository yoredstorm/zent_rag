# =============================================================================
# Planner budget — estimación previa, reservas y shortfall explicable.
#
# No reemplaza el control duro de PlannerBudget: evita gastar llamadas cuando
# el presupuesto declarado no alcanza ni para entender+planificar+verificar.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Reserva mínima por fase (tokens de prompt+completion, no coste).
RESERVE_UNDERSTAND = 4_000
RESERVE_PLAN_VERIFY = 12_000
RESERVE_REPAIR = 4_000
RESERVE_CALLS = 3


@dataclass(frozen=True)
class BudgetEstimate:
    feasible: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    llm_calls: int
    tool_calls: int
    reserves: dict[str, int] = field(default_factory=dict)
    shortfall_tokens: int = 0
    shortfall_cost_usd: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "feasible": self.feasible,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "reserves": dict(self.reserves),
            "shortfall_tokens": self.shortfall_tokens,
            "shortfall_cost_usd": round(self.shortfall_cost_usd, 6),
            "reason": self.reason,
        }


def estimate_tokens(text: str | None) -> int:
    """Estimación conservadora sin tokenizer del proveedor: ~3 chars/token."""
    return max(1, (len(text or "") + 2) // 3)


def preflight_budget(
    budget: Any,
    *,
    prompt: str,
    system_prompt: str,
    catalog_chars: int = 0,
    max_steps: int | None = None,
    expecting_repairs: bool = True,
) -> BudgetEstimate:
    """Estima el coste mínimo y máximo razonable antes de la primera llamada."""
    payload = estimate_tokens(prompt) + estimate_tokens(system_prompt) + max(0, catalog_chars // 3)
    steps = max(1, int(max_steps or getattr(budget, "max_steps", 20)))
    calls = max(1, int(getattr(budget, "max_llm_calls", 16)))
    completion_per_call = max(600, min(2_500, payload // 2))
    prompt_tokens = payload + calls * 1_500
    completion_tokens = completion_per_call * calls
    total = prompt_tokens + completion_tokens
    reserves = {
        "understand": RESERVE_UNDERSTAND,
        "plan_verify": RESERVE_PLAN_VERIFY,
        "repairs": RESERVE_REPAIR if expecting_repairs else 0,
        "calls": RESERVE_CALLS,
    }
    required_tokens = max(total, sum(reserves.values()) + payload)
    required_cost = (
        prompt_tokens / 1000.0 * float(getattr(budget, "cost_per_1k_input", 0.0) or 0.0)
        + completion_tokens / 1000.0 * float(getattr(budget, "cost_per_1k_output", 0.0) or 0.0)
    )
    max_tokens = int(getattr(budget, "max_tokens", 0) or 0)
    max_cost = float(getattr(budget, "max_cost_usd", 0.0) or 0.0)
    short_tokens = max(0, required_tokens - max_tokens)
    short_cost = max(0.0, required_cost - max_cost)
    feasible = short_tokens == 0 and short_cost == 0 and calls >= min(RESERVE_CALLS, steps) + 1
    reason = ""
    if short_tokens:
        reason = "tokens"
    elif short_cost:
        reason = "cost"
    elif not feasible:
        reason = "llm_calls"
    return BudgetEstimate(
        feasible=feasible,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=required_tokens,
        estimated_cost_usd=required_cost,
        llm_calls=calls,
        tool_calls=int(getattr(budget, "max_tool_calls", 0) or 0),
        reserves=reserves,
        shortfall_tokens=short_tokens,
        shortfall_cost_usd=short_cost,
        reason=reason,
    )


__all__ = [
    "BudgetEstimate",
    "RESERVE_CALLS",
    "RESERVE_PLAN_VERIFY",
    "RESERVE_REPAIR",
    "RESERVE_UNDERSTAND",
    "estimate_tokens",
    "preflight_budget",
]
