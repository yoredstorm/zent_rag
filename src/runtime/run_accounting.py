# =============================================================================
# Contabilidad única de llamadas del run.
# Narrative Fast Path, ReAct, cierre y polish pasan por acá.
# El costo sale del provider o de la tabla de precios ya existente.
# =============================================================================
from __future__ import annotations

from typing import Any, Mapping

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


def evidence_count(meta: Any) -> int:
    if not isinstance(meta, dict):
        return 0
    evidence = meta.get("evidence")
    return len(evidence) if isinstance(evidence, list) else 0
