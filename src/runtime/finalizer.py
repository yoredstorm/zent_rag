# =============================================================================
# Finalizer — cierre del run: presupuesto, prompt y entrega final.
# =============================================================================
# El finalizer NO decide si el run puede finalizar (eso es FinalizationPolicy).
# Construye la respuesta final con parámetros explícitos y una sola fuente de
# presupuesto (RunBudgetLedger). La contabilidad sigue en `run_accounting`.
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


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


FINALIZE_TEMPLATE = """You already collected tool observations. Answer the user now.

Rules:
- Write ONLY the final text for the user (Markdown allowed). No JSON, no wrappers,
  no labels like "answer:" or "direct_answer:".
- Do not call tools.
- Domain facts and rules must be supported by the observations. User-provided
  values are valid scenario data: apply them against documented rules; do not
  treat them as missing evidence. Deterministic results derived from grounded
  premises are valid even if not written verbatim.
- If a domain premise is missing, state exactly which one; never fill it with
  model knowledge.

USER QUESTION: {question}

{analytical_workspace}
{response_shape}
## HISTORY
{history}

Final answer (text only, no JSON):"""


def build_finalize_prompt(
    *,
    question: str,
    history: list[str],
    analytical_workspace: str = "",
    response_shape: str = "",
) -> str:
    """Prompt del cierre estándar: última generación sin tools.

    El caller aporta el workspace analítico (si hay razonamiento) y el contrato
    de forma; acá solo se formatea (misma plantilla de siempre).
    """
    return FINALIZE_TEMPLATE.format(
        question=question,
        history="\n".join(list(history or ())[-10:]),
        analytical_workspace=analytical_workspace,
        response_shape=response_shape,
    )


def citations_from_evidence(draft: str, selection: Any) -> list[dict[str, Any]]:
    """Citas del run ligadas a `evidence_id` (la numeración no rompe provenance)."""
    if selection is None or getattr(selection, "empty", True):
        return []
    cited: set[str] = set()
    for match in re.finditer(r"\[(?:Doc|doc)\s*[: ]?\s*(\d{1,3})\b", draft or ""):
        index = int(match.group(1)) - 1
        if 0 <= index < len(selection.items):
            cited.add(selection.items[index].evidence_id)
    from src.runtime.evidence import citations_payload

    return citations_payload(selection, cited_ids=cited)


def limits_note(missing_labels: list[str]) -> str:
    """Nota determinista de límites: qué no está en las fuentes consultadas."""
    if not missing_labels:
        return ""
    listed = ", ".join(str(label) for label in missing_labels[:4])
    return (
        "\n\nNota: las fuentes consultadas no cubren "
        f"{listed}. Lo anterior responde sólo lo que sí está respaldado."
    )


def finalize_answer_delivery(
    result: object,
    *,
    answer: str,
    reason: str,
    selection: object = None,
) -> None:
    """Entrega final: answer + citas + status + step `final` (una sola fuente)."""
    result.answer = answer
    result.citations = citations_from_evidence(answer, selection)
    result.status = "completed"
    result.steps.append(
        {
            "type": "final",
            "answer": answer[:500],
            "detail": f"finalized after {reason}",
        }
    )
