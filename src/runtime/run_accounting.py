# =============================================================================
# Contabilidad única de llamadas del run.
# Narrative Fast Path, ReAct, cierre y polish pasan por acá.
# El costo sale del provider o de la tabla de precios ya existente.
# =============================================================================
from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

PURPOSE_NARRATIVE = "narrative_generation"
PURPOSE_REASONING = "reasoning"
PURPOSE_GENERATION = "generation"
PURPOSE_POLISH = "personality_polish"
PURPOSE_REVISION = "answer_revision"

_ANSWER_PURPOSES = frozenset({PURPOSE_NARRATIVE, PURPOSE_GENERATION, PURPOSE_POLISH})
_TRUNCATION = frozenset({"length", "max_tokens"})


def normalize_finish_reason(raw: str) -> str:
    text = str(raw or "").strip().lower()
    if text in {"", "stop", "end"}:
        return "stop"
    if text in _TRUNCATION:
        return text
    return text or "stop"


def _provider_of(model: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    text = str(model or "")
    if "/" in text:
        return text.split("/", 1)[0]
    return ""


async def resolve_call_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    provider_cost: Any = None,
) -> tuple[float | None, str, str]:
    """(costo, known|unknown, razón). UNKNOWN no se disfraza de cero."""
    if isinstance(provider_cost, (int, float)) and not isinstance(provider_cost, bool):
        return float(provider_cost), "known", "provider"
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return None, "unknown", "no_tokens"
    try:
        from src.runtime.run_budget import usage_cost

        return (
            float(await usage_cost(model, prompt_tokens, completion_tokens)),
            "known",
            "pricing_table",
        )
    except Exception as exc:  # noqa: BLE001 — sin precio no inventamos 0
        return None, "unknown", type(exc).__name__


async def record_llm_call(
    result: Any,
    ledger: Any,
    response: Any = None,
    *,
    purpose: str,
    model: str,
    latency_ms: float,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    provider: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Unico escritor de tokens, costo y el paso `llm`."""
    prompt = int(
        prompt_tokens
        if prompt_tokens is not None
        else getattr(response, "prompt_tokens", 0) or 0
    )
    completion = int(
        completion_tokens
        if completion_tokens is not None
        else getattr(response, "completion_tokens", 0) or 0
    )
    total = int(
        total_tokens
        if total_tokens is not None
        else getattr(response, "total_tokens", 0) or 0
    )
    if total <= 0:
        total = prompt + completion
    finish = normalize_finish_reason(str(getattr(response, "finish_reason", "") or ""))
    used_model = str(getattr(response, "model", "") or model or "")
    used_provider = _provider_of(used_model, provider or str(getattr(response, "provider", "") or ""))
    cost, cost_status, cost_reason = await resolve_call_cost(
        used_model,
        prompt,
        completion,
        provider_cost=getattr(response, "cost", None) if response is not None else None,
    )
    ledger.account_llm_usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cost_usd=0.0 if cost is None else cost,
    )
    if used_model:
        result.model = used_model
    if used_provider:
        result.provider = used_provider
    if cost_status == "unknown":
        result.cost_status = "unknown"
        result.cost_reason = cost_reason
    elif not str(getattr(result, "cost_status", "") or ""):
        result.cost_status = "known"
        result.cost_reason = cost_reason
    step: dict[str, Any] = {
        "type": "llm",
        "purpose": purpose,
        "model": used_model,
        "provider": used_provider,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "tokens": total,
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "finish_reason": finish,
        "cost_status": cost_status,
        "cost_reason": cost_reason,
    }
    if cost is not None:
        step["cost"] = round(cost, 6)
    if extra:
        for key, value in extra.items():
            if key not in {"type", "purpose"}:
                step[key] = value
    result.steps.append(step)
    spans = getattr(result, "spans", None)
    if isinstance(spans, list):
        spans.append(
            {
                "stage": "llm",
                "name": f"llm:{used_model or purpose}",
                "duration_ms": round(float(latency_ms or 0.0), 2),
                "tokens": total,
                "metadata": {
                    "purpose": purpose,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "finish_reason": finish,
                },
            }
        )
    return step


def record_judge_call(
    result: Any,
    *,
    purpose: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Suma tokens JEV al run (única vía; el precio del juez puede ser desconocido).

    El ledger lee `result.*` dinámicamente: desde la próxima construcción el
    presupuesto TOTAL ve estos tokens (antes JEV quedaba fuera del ledger).
    No estima costo: sin tarifa conocida el costo del juez no se inventa.
    """
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    if prompt + completion <= 0:
        return
    result.prompt_tokens = int(getattr(result, "prompt_tokens", 0) or 0) + prompt
    result.completion_tokens = int(
        getattr(result, "completion_tokens", 0) or 0
    ) + completion
    result.total_tokens = int(getattr(result, "total_tokens", 0) or 0) + prompt + completion
    result.steps.append(
        {
            "type": "jev_usage",
            "purpose": purpose,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "tokens": prompt + completion,
        }
    )


def record_search_call(
    result: Any,
    *,
    query: str,
    latency_ms: float,
    evidence_added: int,
    result_count: int,
    error: str = "",
) -> dict[str, Any]:
    """search_knowledge del fast path es un tool_call, no un detalle escondido."""
    step: dict[str, Any] = {
        "type": "tool_call",
        "tool": "search_knowledge",
        "query": str(query or "")[:300],
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "result_count": max(0, int(result_count or 0)),
        "evidence_added": max(0, int(evidence_added or 0)),
    }
    if error:
        step["error"] = str(error)[:500]
    result.steps.append(step)
    spans = getattr(result, "spans", None)
    if isinstance(spans, list):
        spans.append(
            {
                "stage": "retrieval",
                "name": "tool:search_knowledge",
                "duration_ms": step["latency_ms"],
                "tokens": 0,
                "status": "error" if error else "ok",
                "metadata": {"tool": "search_knowledge", "query": step["query"]},
            }
        )
    return step


async def _embedding_cost(model: str, tokens: int) -> tuple[float | None, str, str]:
    """(costo, known|unknown, razón). Sin tarifa no se inventa un cero."""
    if tokens <= 0:
        return 0.0, "known", "no_tokens"
    try:
        from src.platform.billing.pricing import get_price

        price = await get_price(model or "default")
        return (
            float(tokens) / 1000.0 * float(price.embedding_cost_per_1k),
            "known",
            "pricing_table",
        )
    except Exception as exc:  # noqa: BLE001 — sin tarifa, costo desconocido
        return None, "unknown", type(exc).__name__


async def record_embedding_call(
    result: Any,
    ledger: Any,
    *,
    model: str,
    tokens: int,
    purpose: str = "embedding",
    latency_ms: float = 0.0,
    provider: str = "",
) -> dict[str, Any]:
    """Línea de embeddings del run: tokens siempre; costo solo con tarifa."""
    counted = max(0, int(tokens or 0))
    cost, cost_status, cost_reason = await _embedding_cost(model, counted)
    ledger.account_embedding_usage(tokens=counted, cost_usd=0.0 if cost is None else cost)
    if cost_status == "unknown":
        result.cost_status = "unknown"
        result.cost_reason = cost_reason
    elif not str(getattr(result, "cost_status", "") or ""):
        result.cost_status = "known"
        result.cost_reason = cost_reason
    step: dict[str, Any] = {
        "type": "embedding",
        "purpose": purpose,
        "model": model,
        "provider": _provider_of(model, provider),
        "tokens": counted,
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "cost_status": cost_status,
        "cost_reason": cost_reason,
    }
    if cost is not None:
        step["cost"] = round(cost, 6)
    result.steps.append(step)
    return step


def record_rerank_call(
    result: Any,
    *,
    count: int,
    purpose: str = "reranking",
    latency_ms: float = 0.0,
) -> dict[str, Any] | None:
    """Línea de reranking: explícita; sin tarifa conocida no se inventa costo."""
    counted = max(0, int(count or 0))
    if counted <= 0:
        return None
    step: dict[str, Any] = {
        "type": "rerank",
        "purpose": purpose,
        "count": counted,
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "cost_status": "unknown",
        "cost_reason": "no_pricing",
    }
    result.steps.append(step)
    return step


def record_charge(result: Any, ledger: Any, *, cost_usd: float, purpose: str) -> dict[str, Any] | None:
    """Cargo externo ya reportado por un subsistema (no se estima)."""
    amount = float(cost_usd or 0.0)
    if amount <= 0:
        return None
    ledger.account_charge(cost_usd=amount)
    step: dict[str, Any] = {
        "type": "charge",
        "purpose": purpose,
        "cost": round(amount, 6),
        "cost_status": "known",
        "cost_reason": "provider_reported",
    }
    result.steps.append(step)
    return step


def record_provider_attempt(
    result: Any,
    *,
    provider: str,
    model: str,
    status: str,
    latency_ms: float = 0.0,
    retry: bool = False,
    detail: str = "",
) -> dict[str, Any]:
    """Intento de provider (fallido o fallback) como línea explícita.

    No suma tokens ni costo (el intento fallido no siempre factura): deja el
    primer intento reconstruible — el failover no se esconde.
    """
    step: dict[str, Any] = {
        "type": "provider_attempt",
        "provider": str(provider or ""),
        "model": str(model or ""),
        "status": str(status or ""),
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "retry": bool(retry),
        "cost_status": "unknown",
        "cost_reason": "attempt_not_priced",
    }
    if detail:
        step["detail"] = str(detail)[:200]
    result.steps.append(step)
    return step


def record_jev_observation(
    result: Any,
    *,
    tokens: int = 0,
    cost_usd: float = 0.0,
    purpose: str = "jev",
    provider: str = "",
    model: str = "",
    latency_ms: float = 0.0,
) -> dict[str, Any] | None:
    """JEV observado en el run: línea explícita, sin tocar los totales.

    El juez factura por su propio usage event; sumarlo acá sería doble conteo.
    Los tokens y el costo (si el proveedor lo reportó) quedan reconstruibles.
    """
    counted = max(0, int(tokens or 0))
    amount = float(cost_usd or 0.0)
    if counted <= 0 and amount <= 0:
        return None
    step: dict[str, Any] = {
        "type": "jev_usage",
        "purpose": purpose,
        "tokens": counted,
        "provider": provider,
        "model": model,
        "latency_ms": round(float(latency_ms or 0.0), 2),
        "cost_status": "known" if amount > 0 else "unknown",
        "cost_reason": "provider_reported" if amount > 0 else "no_pricing",
        "billed_separately": True,
    }
    if amount > 0:
        step["cost"] = round(amount, 6)
    result.steps.append(step)
    return step


async def account_rag_result(
    result: Any,
    *,
    query: str,
    model: str = "",
    reranking_count: int = 0,
    latency_ms: float = 0.0,
) -> None:
    """Contabilidad única del camino RAG: un writer, un ledger por run.

    Idempotente: si el run ya se contabilizó, no vuelve a sumar. El evento de
    uso posterior LEE los totales del ledger (result.*), no los recalcula.
    """
    if getattr(result, "_usage_accounted", False):
        return
    from src.runtime.run_budget import RunBudgetLedger

    ledger = RunBudgetLedger(result, max_steps=0, max_tokens=0, max_cost_usd=None)
    llm = getattr(result, "llm_response", None)
    if llm is not None:
        await record_llm_call(
            result,
            ledger,
            response=llm,
            purpose=PURPOSE_GENERATION,
            model=str(getattr(llm, "model", "") or model or ""),
            latency_ms=float(getattr(llm, "latency_ms", 0.0) or latency_ms or 0.0),
        )
    embedding_model = model or str(getattr(llm, "model", "") or "")
    # Misma estimación que el evento histórico (~4 chars/token), ahora explícita.
    await record_embedding_call(
        result,
        ledger,
        model=embedding_model,
        tokens=max(len(query or "") // 4, 1),
        purpose="query_embedding",
    )
    record_rerank_call(result, count=reranking_count)
    record_charge(
        result,
        ledger,
        cost_usd=float(getattr(result, "cognitive_cost_usd", 0.0) or 0.0),
        purpose="cognitive_deep",
    )
    try:
        preflight = (getattr(result, "flow", None) or {}).get("jev_preflight") or {}
        if isinstance(preflight, dict):
            tokens_block = preflight.get("tokens")
            jev_tokens = 0
            if isinstance(tokens_block, dict):
                jev_tokens = int(tokens_block.get("input") or 0) + int(
                    tokens_block.get("output") or 0
                )
            record_jev_observation(
                result,
                tokens=jev_tokens,
                cost_usd=float(preflight.get("cost_usd") or 0.0),
                purpose="jev_preflight",
                provider=str(preflight.get("provider") or ""),
                model=str(preflight.get("model") or ""),
            )
    except Exception as exc:  # noqa: BLE001 — telemetría, nunca rompe la contabilidad
        logger.warning("jev observation failed", error=str(exc)[:150])
    result._usage_accounted = True


def evidence_count(meta: Any) -> int:
    if not isinstance(meta, dict):
        return 0
    evidence = meta.get("evidence")
    return len(evidence) if isinstance(evidence, list) else 0
