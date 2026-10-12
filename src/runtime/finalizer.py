# =============================================================================
# Finalizer — cierre del run: presupuesto, prompt y entrega final.
# =============================================================================
# El finalizer NO decide si el run puede finalizar (eso es FinalizationPolicy).
# Construye la respuesta final con parámetros explícitos y una sola fuente de
# presupuesto (RunBudgetLedger). La contabilidad sigue en `run_accounting`.
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinalizeBudget:
    """Presupuesto aprobado para la llamada de cierre."""

    ledger: object
    max_tokens: int
    call_plan: object


async def plan_finalize_budget(
    result: object,
    config: dict,
    *,
    prompt: str,
    question: str,
    configured_max_tokens: int,
    answer_max_tokens: int,
) -> FinalizeBudget | None:
    """Arma el tope de UNA llamada de cierre desde el ledger del run.

    None = el ledger no da margen: el cierre no genera y el caller aplica su
    fallback determinista (nunca una respuesta vacía).
    """
    from src.runtime.run_budget import (
        EXHAUSTED,
        RunBudgetLedger,
        estimate_prompt_tokens,
        lookup_token_rates,
        plan_response_budget,
    )

    per_call = int(configured_max_tokens or 0) or int(answer_max_tokens)
    model_limit = int(answer_max_tokens)
    ledger = RunBudgetLedger.from_config(result, config)
    rates = await lookup_token_rates(str(config.get("model") or ""))
    call_plan = plan_response_budget(
        ledger,
        estimated_prompt_tokens=estimate_prompt_tokens(prompt),
        desired_completion_tokens=min(per_call, model_limit),
        model_output_limit=model_limit,
        question=question,
        followup_llm=False,
        input_cost_per_1k=None if rates is None else rates[0],
        output_cost_per_1k=None if rates is None else rates[1],
    )
    if (
        call_plan.budget_pressure == EXHAUSTED
        or call_plan.allowed_completion_tokens <= 0
    ):
        return None
    return FinalizeBudget(
        ledger=ledger,
        max_tokens=int(call_plan.allowed_completion_tokens),
        call_plan=call_plan,
    )
