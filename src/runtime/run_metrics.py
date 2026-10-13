# =============================================================================
# Run metrics — publicación run-level en un solo punto.
# =============================================================================
# Un run cierra y publica sus métricas UNA vez: fase, latencia, LLM, tokens,
# costo (known vs unknown), tool calls, suficiente de evidencia y acción de
# finalización. Labels acotados (path, phase, status, kind, action,
# reason_code): nunca run_id, user_id, conversation_id ni la query.
#
# Fail-soft: la observabilidad no cambia el resultado ni rompe el run.
# =============================================================================
from __future__ import annotations

from typing import Any

RUN_METRICS_VERSION = "run-metrics-1"

PATH_AGENT = "agent"
PATH_RAG = "rag"


def _evidence_status(state: Any) -> str:
    evidence = getattr(state, "evidence", None)
    if evidence is None:
        return "unknown"
    if bool(getattr(evidence, "retrieval_failed", False)) and not bool(
        getattr(evidence, "complete", False)
    ):
        return "failed"
    if bool(getattr(evidence, "complete", False)):
        return "complete"
    if bool(getattr(evidence, "insufficient", False)):
        return "insufficient"
    return "unknown"


def publish_run_metrics(
    state: Any,
    *,
    path: str,
    result: Any = None,
) -> None:
    """Publica las métricas del run cerrado. Nunca lanza."""
    try:
        _publish(state, path=path, result=result)
    except Exception:  # noqa: BLE001 — observabilidad, jamás rompe el run
        pass


def _publish(state: Any, *, path: str, result: Any) -> None:
    from src.infrastructure.observability.metrics import (
        zent_run_evidence_total,
        zent_llm_calls_total,
        zent_llm_tokens_total,
        zent_run_cost_unknown_total,
        zent_run_cost_usd_total,
        zent_run_latency_seconds,
        zent_run_tool_calls_total,
        zent_runs_total,
    )

    phase = str(getattr(state, "phase", "") or "UNKNOWN")
    label_path = str(path or PATH_AGENT)

    zent_runs_total.labels(path=label_path, phase=phase).inc()

    trace = getattr(state, "trace", None)
    latency_ms = float(getattr(trace, "latency_ms", 0.0) or 0.0)
    if latency_ms > 0:
        zent_run_latency_seconds.labels(path=label_path).observe(latency_ms / 1000.0)

    zent_run_evidence_total.labels(
        path=label_path, status=_evidence_status(state)
    ).inc()

    # Acción de finalización resuelta (bounded: 7 acciones × ~30 reason codes).
    decisions = getattr(state, "decisions", None)
    policy = getattr(decisions, "finalization", None) if decisions is not None else None
    if isinstance(policy, dict) and policy.get("action"):
        from src.infrastructure.observability.metrics import (
            zent_finalization_actions_total,
        )

        zent_finalization_actions_total.labels(
            action=str(policy.get("action")),
            reason_code=str(policy.get("reason_code") or "UNKNOWN"),
        ).inc()

    if result is None:
        return
    prompt = int(getattr(result, "prompt_tokens", 0) or 0)
    completion = int(getattr(result, "completion_tokens", 0) or 0)
    calls = int(getattr(result, "llm_calls", 0) or 0)
    tool_calls = int(getattr(result, "tool_calls", 0) or 0)
    cost = float(getattr(result, "cost", 0.0) or 0.0)
    if calls:
        zent_llm_calls_total.labels(path=label_path).inc(calls)
    if prompt:
        zent_llm_tokens_total.labels(path=label_path, kind="prompt").inc(prompt)
    if completion:
        zent_llm_tokens_total.labels(path=label_path, kind="completion").inc(
            completion
        )
    if tool_calls:
        zent_run_tool_calls_total.labels(path=label_path).inc(tool_calls)
    if cost > 0:
        zent_run_cost_usd_total.labels(path=label_path).inc(cost)
    if str(getattr(result, "cost_status", "") or "") == "unknown":
        zent_run_cost_unknown_total.labels(path=label_path).inc()


__all__ = [
    "PATH_AGENT",
    "PATH_RAG",
    "RUN_METRICS_VERSION",
    "publish_run_metrics",
]
