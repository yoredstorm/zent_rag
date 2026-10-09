# =============================================================================
# Presupuesto jerárquico del run.
# max_tokens / max_cost_usd / max_steps del agente son la autoridad.
# El tope de UNA llamada es un target derivado, nunca un techo paralelo.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from src.intelligence.response.entities import asked_concepts

NORMAL = "NORMAL"
CONSTRAINED = "CONSTRAINED"
CRITICAL = "CRITICAL"
EXHAUSTED = "EXHAUSTED"

COMPACT_INSTRUCTION = (
    "Prioriza cubrir todos los puntos pedidos en forma compacta. "
    "No abras una sección que no puedas cerrar."
)

MIN_USEFUL_COMPLETION = 80
COMPACT_SLACK = 50
SAFETY_RESERVE_CAP = 300
SAFETY_RESERVE_DEFAULT = 200

_AND_SPLIT = re.compile(r"\s+\b(?:y|e|and)\b\s+", re.IGNORECASE)
_CONTENT_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}")
_CONCISE = (
    "muy conciso",
    "conciso",
    "breve",
    "en una línea",
    "en una linea",
    "be brief",
    "very concise",
)
_DETAILED = (
    "explica con detalle",
    "en detalle",
    "con detalle",
    "detallado",
    "en profundidad",
    "a fondo",
    "paso a paso",
)


def estimate_prompt_tokens(text: str) -> int:
    """Aproximación estable antes de que el provider cuente los tokens reales."""
    body = text or ""
    if not body.strip():
        return 0
    return max(1, (len(body) + 3) // 4)


def concept_count_for_budget(question: str, *, explicit: int | None = None) -> int:
    """Conceptos que alargan la respuesta. No usa solo el blueprint.

    `asked_concepts` cubre entidades («record 2»). La conjunción «y» / «and»
    suma el otro tema («cambio de fechas de efectividad») cuando la entidad
    sola no llega a dos.
    """
    if explicit is not None and int(explicit) >= 0:
        named = int(explicit)
    else:
        named = len(asked_concepts(question or ""))
    parts = [part.strip() for part in _AND_SPLIT.split(question or "") if part.strip()]
    rich = 0
    if len(parts) > 1:
        rich = sum(1 for part in parts if _CONTENT_WORD.search(part))
    counted = max(named, rich)
    if counted <= 0 and (question or "").strip():
        return 1
    return counted


def retrieval_rounds_allowed(*, rounds_left: int, steps_left: int) -> int:
    """Una ronda nueva de retrieval no puede ignorar los pasos que quedan."""
    return max(0, min(int(rounds_left or 0), int(steps_left or 0)))


def _band(blueprint: str, detail: str, concept_count: int) -> tuple[int, int]:
    kind = f"{blueprint or ''} {detail or ''}".lower()
    if "direct_fact" in kind or "direct fact" in kind:
        return (200, 400)
    if "definition" in kind:
        return (450, 900)
    if "comparison" in kind:
        return (900, 1800)
    if "scenario" in kind:
        return (1200, 2400)
    if any(token in kind for token in ("tutorial", "deep", "en profundidad", "desde cero")):
        return (2000, 4000)
    if concept_count >= 2:
        return (1200, 2200)
    return (800, 1400)


def _verbosity_factor(personality: str) -> float:
    text = (personality or "").lower()
    concise = any(token in text for token in _CONCISE)
    detailed = any(token in text for token in _DETAILED)
    if detailed and not concise:
        return 1.2
    if concise and not detailed:
        return 0.75
    return 1.0


def desired_output_token_budget(
    blueprint: str,
    *,
    detail: str = "",
    concept_count: int = 1,
    evidence_count: int = 0,
    needs_table: bool = False,
    needs_list: bool = False,
    needs_example: bool = False,
    needs_definition: bool = False,
    personality: str = "",
) -> int:
    """Target de completion. No se manda tal cual al modelo."""
    low, high = _band(blueprint, detail, concept_count)
    detail_l = (detail or "").lower()
    if detail_l in {"brief", "concise"}:
        base = low
    elif detail_l in {"deep", "detailed"} or "en profundidad" in detail_l:
        base = high
    else:
        base = low + ((high - low) * 3) // 5
    if needs_table:
        base = min(high, int(base * 1.15) + 80)
    if needs_list:
        base = min(high, int(base * 1.08))
    if needs_example:
        base = min(high, int(base * 1.08))
    if needs_definition and "definition" not in (blueprint or "").lower():
        base = min(high, base + 80)
    if evidence_count >= 4:
        base = min(high, base + 30)
    factor = _verbosity_factor(personality)
    scaled = int(base * factor)
    if factor > 1:
        ceiling = int(high * 1.25)
        floor = low
    elif factor < 1:
        ceiling = high
        floor = max(120, int(low * 0.75))
    else:
        ceiling = high
        floor = low
    return max(floor, min(ceiling, scaled))


def safety_reserve_for(
    *,
    followup_llm: bool,
    max_tokens: int,
    configured: int | None = None,
) -> int:
    """Margen chico para una reparación o un cierre que sí llame al modelo."""
    if configured is not None:
        return max(0, min(SAFETY_RESERVE_CAP, int(configured)))
    if not followup_llm:
        return 0
    return min(SAFETY_RESERVE_CAP, max(0, min(SAFETY_RESERVE_DEFAULT, int(max_tokens) // 10)))


class RunBudgetLedger:
    """Vista del presupuesto sobre las métricas reales del AgentRunResult.

    No guarda un contador paralelo: lee y escribe `prompt_tokens`,
    `completion_tokens`, `total_tokens`, `cost` y los pasos del mismo result.
    """

    def __init__(
        self,
        result: Any,
        *,
        max_steps: int,
        max_tokens: int,
        max_cost_usd: float | None,
    ) -> None:
        self.result = result
        self.max_steps = int(max_steps)
        self.max_tokens = int(max_tokens)
        self.max_cost_usd = None if max_cost_usd is None else float(max_cost_usd)

    @classmethod
    def from_config(cls, result: Any, config: Mapping[str, Any]) -> RunBudgetLedger:
        if "max_cost_usd" in config:
            max_cost: float | None = float(config.get("max_cost_usd") or 0)
        elif "max_cost" in config:
            max_cost = float(config.get("max_cost") or 0)
        else:
            max_cost = None
        return cls(
            result,
            max_steps=int(config.get("max_steps") or 0),
            max_tokens=int(config.get("max_tokens") or 0),
            max_cost_usd=max_cost,
        )

    @property
    def consumed_prompt_tokens(self) -> int:
        return int(getattr(self.result, "prompt_tokens", 0) or 0)

    @property
    def consumed_completion_tokens(self) -> int:
        return int(getattr(self.result, "completion_tokens", 0) or 0)

    @property
    def consumed_total_tokens(self) -> int:
        return int(getattr(self.result, "total_tokens", 0) or 0)

    @property
    def consumed_cost_usd(self) -> float:
        return float(getattr(self.result, "cost", 0.0) or 0.0)

    @property
    def llm_calls(self) -> int:
        return int(getattr(self.result, "llm_calls", 0) or 0)

    @property
    def tool_calls(self) -> int:
        return int(getattr(self.result, "tool_calls", 0) or 0)

    @property
    def logical_steps(self) -> int:
        return int(getattr(self.result, "logical_steps", 0) or 0)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.max_tokens - self.consumed_total_tokens)

    @property
    def remaining_cost_usd(self) -> float:
        if self.max_cost_usd is None:
            return float("inf")
        return max(0.0, round(self.max_cost_usd - self.consumed_cost_usd, 6))

    @property
    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self.logical_steps)

    def charge_tool_step(self) -> None:
        self.result.tool_calls = self.tool_calls + 1
        self.result.logical_steps = self.logical_steps + 1

    def account_llm_usage(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int | None = None,
        cost_usd: float = 0.0,
    ) -> None:
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        total = prompt + completion if total_tokens is None else int(total_tokens)
        if total <= 0:
            total = prompt + completion
        self.result.prompt_tokens = self.consumed_prompt_tokens + prompt
        self.result.completion_tokens = self.consumed_completion_tokens + completion
        self.result.total_tokens = self.consumed_total_tokens + max(0, total)
        self.result.cost = round(self.consumed_cost_usd + max(0.0, float(cost_usd or 0.0)), 6)
        self.result.llm_calls = self.llm_calls + 1
        self.result.logical_steps = self.logical_steps + 1


@dataclass(frozen=True)
class ResponseBudgetPlan:
    desired_completion_tokens: int
    allowed_completion_tokens: int
    safety_reserve_tokens: int
    budget_reason: str
    budget_pressure: str
    agent_max_tokens: int
    tokens_consumed_before_call: int
    estimated_prompt_tokens: int
    remaining_tokens_after_call: int
    compact_instruction: str = ""
    estimated_prompt_cost: float = 0.0
    estimated_max_completion_cost: float = 0.0

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "agent_max_tokens": self.agent_max_tokens,
            "tokens_consumed_before_call": self.tokens_consumed_before_call,
            "estimated_prompt_tokens": self.estimated_prompt_tokens,
            "desired_completion_tokens": self.desired_completion_tokens,
            "allowed_completion_tokens": self.allowed_completion_tokens,
            "safety_reserve_tokens": self.safety_reserve_tokens,
            "remaining_tokens_after_call": self.remaining_tokens_after_call,
            "budget_pressure": self.budget_pressure,
            "budget_reason": self.budget_reason,
        }
        if self.compact_instruction:
            payload["compact_instruction"] = self.compact_instruction
        if self.estimated_prompt_cost or self.estimated_max_completion_cost:
            payload["estimated_prompt_cost"] = round(self.estimated_prompt_cost, 6)
            payload["estimated_max_completion_cost"] = round(
                self.estimated_max_completion_cost, 6
            )
        return payload


def _pressure(desired: int, allowed: int) -> str:
    if allowed <= 0 or allowed < MIN_USEFUL_COMPLETION:
        return EXHAUSTED
    if desired <= 0 or allowed >= desired:
        return NORMAL
    if allowed >= max(MIN_USEFUL_COMPLETION, int(desired * 0.45)):
        return CONSTRAINED
    return CRITICAL


def _limit_by_cost(
    allowed: int,
    *,
    prompt_tokens: int,
    remaining_cost: float,
    input_per_1k: float,
    output_per_1k: float,
) -> tuple[int, str, float, float]:
    prompt_cost = max(0.0, prompt_tokens) / 1000.0 * max(0.0, input_per_1k)
    if remaining_cost <= 0 or prompt_cost > remaining_cost + 1e-12:
        return 0, "budget_exhausted_cost", prompt_cost, 0.0
    if output_per_1k <= 0:
        completion_cost = 0.0
        return allowed, "", prompt_cost, completion_cost
    affordable = int((remaining_cost - prompt_cost) / output_per_1k * 1000)
    if affordable < MIN_USEFUL_COMPLETION:
        return 0, "budget_exhausted_cost", prompt_cost, 0.0
    if affordable < allowed:
        capped = affordable
        if capped > MIN_USEFUL_COMPLETION + COMPACT_SLACK:
            capped -= COMPACT_SLACK
        completion_cost = capped / 1000.0 * output_per_1k
        return capped, "cost_reduced_completion", prompt_cost, completion_cost
    completion_cost = allowed / 1000.0 * output_per_1k
    return allowed, "", prompt_cost, completion_cost


def plan_response_budget(
    ledger: RunBudgetLedger,
    *,
    estimated_prompt_tokens: int,
    blueprint: str = "",
    question: str = "",
    detail_level: str = "",
    concept_count: int | None = None,
    evidence_count: int = 0,
    needs_table: bool = False,
    needs_list: bool = False,
    needs_example: bool = False,
    needs_definition: bool = False,
    personality: str = "",
    model_output_limit: int = 4096,
    followup_llm: bool = False,
    safety_reserve_tokens: int | None = None,
    desired_completion_tokens: int | None = None,
    input_cost_per_1k: float | None = None,
    output_cost_per_1k: float | None = None,
    decision_llm: bool = True,
) -> ResponseBudgetPlan:
    """Arma el tope de UNA llamada a partir de lo que queda del run."""
    consumed = ledger.consumed_total_tokens
    if not decision_llm:
        return ResponseBudgetPlan(
            desired_completion_tokens=0,
            allowed_completion_tokens=0,
            safety_reserve_tokens=0,
            budget_reason="deterministic_no_decision_llm",
            budget_pressure=NORMAL,
            agent_max_tokens=ledger.max_tokens,
            tokens_consumed_before_call=consumed,
            estimated_prompt_tokens=0,
            remaining_tokens_after_call=ledger.remaining_tokens,
        )

    inferred = concept_count_for_budget(question) if question else 0
    count = inferred if concept_count is None else max(int(concept_count), inferred)
    if desired_completion_tokens is None:
        desired = desired_output_token_budget(
            blueprint,
            detail=detail_level,
            concept_count=count,
            evidence_count=evidence_count,
            needs_table=needs_table,
            needs_list=needs_list,
            needs_example=needs_example,
            needs_definition=needs_definition,
            personality=personality,
        )
    else:
        desired = max(0, int(desired_completion_tokens))

    reserve = safety_reserve_for(
        followup_llm=followup_llm,
        max_tokens=ledger.max_tokens,
        configured=safety_reserve_tokens,
    )
    prompt_tokens = max(0, int(estimated_prompt_tokens or 0))
    room = ledger.max_tokens - consumed - prompt_tokens - reserve
    model_limit = max(0, int(model_output_limit or 0))

    if room < MIN_USEFUL_COMPLETION:
        allowed = 0
        pressure = EXHAUSTED
        reason = "budget_exhausted_tokens"
    else:
        fits_model = model_limit <= 0 or model_limit >= desired
        if room >= desired and fits_model:
            allowed = desired
            pressure = NORMAL
            reason = "adaptive_target"
        else:
            slack = COMPACT_SLACK if room < desired and room > MIN_USEFUL_COMPLETION + COMPACT_SLACK else 0
            caps = [desired, room - slack]
            if model_limit > 0:
                caps.append(model_limit)
            allowed = max(0, min(caps))
            if allowed < MIN_USEFUL_COMPLETION:
                fallback_caps = [room]
                if model_limit > 0:
                    fallback_caps.append(model_limit)
                allowed = max(0, min(fallback_caps))
            if allowed < MIN_USEFUL_COMPLETION:
                allowed = 0
                pressure = EXHAUSTED
                reason = "budget_exhausted_tokens"
            else:
                binding_model = (
                    model_limit > 0
                    and allowed >= model_limit
                    and model_limit < desired
                    and room >= model_limit
                )
                pressure = _pressure(desired, allowed)
                if binding_model:
                    reason = "model_output_limit"
                elif pressure == CRITICAL:
                    reason = "critical_minimum"
                elif pressure == CONSTRAINED:
                    reason = "compact_to_remaining"
                else:
                    reason = "adaptive_target"

    prompt_cost = 0.0
    completion_cost = 0.0
    if (
        allowed > 0
        and ledger.max_cost_usd is not None
        and input_cost_per_1k is not None
        and output_cost_per_1k is not None
    ):
        allowed, cost_reason, prompt_cost, completion_cost = _limit_by_cost(
            allowed,
            prompt_tokens=prompt_tokens,
            remaining_cost=ledger.remaining_cost_usd,
            input_per_1k=float(input_cost_per_1k),
            output_per_1k=float(output_cost_per_1k),
        )
        if cost_reason:
            reason = cost_reason
            pressure = EXHAUSTED if allowed < MIN_USEFUL_COMPLETION else _pressure(desired, allowed)
            if allowed < MIN_USEFUL_COMPLETION:
                allowed = 0
                completion_cost = 0.0

    if pressure in {CONSTRAINED, CRITICAL} and allowed > 0:
        compact = COMPACT_INSTRUCTION
    else:
        compact = ""

    remaining_after = max(0, ledger.max_tokens - consumed - prompt_tokens - allowed)
    return ResponseBudgetPlan(
        desired_completion_tokens=desired,
        allowed_completion_tokens=allowed,
        safety_reserve_tokens=reserve,
        budget_reason=reason,
        budget_pressure=pressure,
        agent_max_tokens=ledger.max_tokens,
        tokens_consumed_before_call=consumed,
        estimated_prompt_tokens=prompt_tokens,
        remaining_tokens_after_call=remaining_after,
        compact_instruction=compact,
        estimated_prompt_cost=prompt_cost,
        estimated_max_completion_cost=completion_cost,
    )


def signals_from_plan(plan: Any) -> dict[str, Any]:
    """Señales ya compuestas por Response Intelligence. Vacío si no hay contrato."""
    contract = getattr(plan, "contract", None)
    if contract is None:
        return {}
    formatting = getattr(contract, "formatting", {}) or {}
    sections = tuple(getattr(contract, "sections", ()) or ())
    presentation = getattr(contract, "presentation", {}) or {}
    if not isinstance(presentation, dict):
        presentation = {}
    concepts = presentation.get("concepts") or ()
    return {
        "blueprint": str(getattr(contract, "blueprint", "") or ""),
        "detail_level": str(getattr(contract, "detail", "") or ""),
        "needs_table": bool(formatting.get("table")),
        "needs_list": bool(presentation.get("needs_list")),
        "needs_example": "example" in sections,
        "needs_definition": "definition" in sections,
        "concept_count": len(tuple(concepts)) if concepts else None,
        "personality": " ".join(
            part
            for part in (
                str(getattr(contract, "custom_instructions", "") or ""),
                str(getattr(contract, "tone", "") or ""),
            )
            if part
        ),
    }


def budget_overrun(ledger: RunBudgetLedger) -> dict[str, Any]:
    """Discrepancia del provider por encima del techo. Vacío si no la hay."""
    token_over = max(0, ledger.consumed_total_tokens - ledger.max_tokens)
    cost_over = 0.0
    if ledger.max_cost_usd is not None:
        cost_over = max(0.0, round(ledger.consumed_cost_usd - ledger.max_cost_usd, 6))
    if token_over <= 0 and cost_over <= 0:
        return {}
    return {
        "budget_overrun": True,
        "token_overrun": token_over,
        "cost_overrun_usd": cost_over,
    }


async def lookup_token_rates(model: str) -> tuple[float, float] | None:
    """Precios por 1k. None si el registry no responde: no se inventa un corte."""
    try:
        from src.platform.billing.pricing import get_price

        price = await get_price(model or "default")
        return float(price.input_cost_per_1k), float(price.output_cost_per_1k)
    except Exception:  # noqa: BLE001 — sin precio no se recorta por costo
        return None


async def usage_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Costo de una llamada ya hecha. Con tokens y sin registry, usa la tarifa default."""
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    if prompt <= 0 and completion <= 0:
        return 0.0
    try:
        from src.platform.billing.pricing import estimate_cost

        return float(
            await estimate_cost(
                model or "default",
                prompt_tokens=prompt,
                completion_tokens=completion,
            )
        )
    except Exception:  # noqa: BLE001 — el provider ya entregó tokens
        from src.platform.billing.pricing import PriceRecord, estimate_cost_from_price

        return float(
            estimate_cost_from_price(
                PriceRecord(
                    provider="default",
                    model="default",
                    input_cost_per_1k=0.00015,
                    output_cost_per_1k=0.00060,
                    embedding_cost_per_1k=0.0,
                ),
                prompt,
                completion,
            )
        )
