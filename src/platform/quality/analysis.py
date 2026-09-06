"""AI Quality Root Cause (FASE 03, S3).

Clasifica posibles causas de una respuesta con feedback negativo o fallo
usando SOLO señales reales del run. Nunca presenta inferencia probabilística
como hecho: usa "Probable cause" / "Possible contributing factor".
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

REASON_MAP = {
    "wrong_answer": "respuesta incorrecta",
    "too_long": "respuesta demasiado extensa",
    "too_slow": "respuesta demasiado lenta",
    "confusing": "respuesta confusa",
    "other": "otro motivo",
}

TOOL_KINDS = {
    "retrieval": ("kb", "search", "retrieve", "rag", "document"),
    "sql": ("sql", "query_database", "database"),
    "tool": ("api", "call_api", "webhook", "http"),
}


def _kind_of(tool: str) -> str:
    low = tool.lower()
    for kind, needles in TOOL_KINDS.items():
        if any(n in low for n in needles):
            return kind
    return "tool"


async def _agent_avg_latency(organization_id: UUID, agent_id: UUID) -> dict:
    """p50/p95 de latencia del agente (mismo agente, últimos 7 días)."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_latency_ms) AS p50, "
                    "PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95 "
                    "FROM agent_runs "
                    "WHERE organization_id = :oid AND agent_id = :aid "
                    "AND created_at > NOW() - INTERVAL '7 days' "
                    "AND total_latency_ms > 0"
                ),
                {"oid": organization_id, "aid": agent_id},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "p50_ms": round(float(row.p50 or 0), 1) if row and row.p50 else None,
        "p95_ms": round(float(row.p95 or 0), 1) if row and row.p95 else None,
    }


async def analyze_run(organization_id: UUID, run_id: UUID) -> dict:
    """Análisis determinista sobre señales reales del run + feedback."""
    from src.agents.runtime.trace_store import get_run

    run = await get_run(organization_id, run_id)
    if run is None:
        return {"error": "run_not_found"}

    steps = run.get("steps") or []
    feedback = await _feedback_for_run(run_id)
    tool_errors = [s for s in steps if s.get("type") == "tool_call" and s.get("error")]
    guardrails = [s for s in steps if s.get("type") == "guardrail"]
    fallbacks = [s for s in steps if s.get("type") == "router_fallback"]
    tool_calls = [s for s in steps if s.get("type") == "tool_call"]
    latency = float(run.get("total_latency_ms") or 0)
    baseline = await _agent_avg_latency(organization_id, UUID(run["agent_id"]))

    signals: dict = {
        "status": run.get("status"),
        "latency_ms": round(latency, 1),
        "baseline_p50_ms": baseline["p50_ms"],
        "baseline_p95_ms": baseline["p95_ms"],
        "total_tokens": run.get("total_tokens"),
        "cost": run.get("cost"),
        "tool_calls": len(tool_calls),
        "tool_errors": len(tool_errors),
        "guardrails": [g.get("detail", "")[:200] for g in guardrails][:5],
        "fallback_used": bool(fallbacks),
        "fallback_attempts": (fallbacks[0].get("attempts") if fallbacks else None),
        "answer_length": len(run.get("answer") or ""),
        "feedback": feedback,
    }

    probable: list[dict] = []
    possible: list[dict] = []

    # 1) Fallo estructural del run.
    if run.get("status") not in ("completed",):
        detail = (guardrails[0].get("detail") if guardrails else None) or (
            tool_errors[0].get("error") if tool_errors else None
        )
        probable.append(
            {
                "factor": "run_failed",
                "label": "El run no completó",
                "evidence": [f"status={run.get('status')}", detail or "sin detalle"],
            }
        )
        return {"probable_causes": probable, "possible_contributing_factors": possible, "signals": signals}

    # 2) Errores de tools/SQL.
    for err in tool_errors[:3]:
        tool = err.get("tool", "")
        kind = _kind_of(tool)
        if kind == "sql":
            probable.append(
                {
                    "factor": "sql_failure",
                    "label": "Falló la consulta SQL",
                    "evidence": [f"tool={tool}", str(err.get("error", ""))[:300]],
                }
            )
        elif kind == "retrieval":
            probable.append(
                {
                    "factor": "retrieval_failure",
                    "label": "Falló la búsqueda de contexto",
                    "evidence": [f"tool={tool}", str(err.get("error", ""))[:300]],
                }
            )
        else:
            probable.append(
                {
                    "factor": "tool_failure",
                    "label": "Falló la herramienta externa",
                    "evidence": [f"tool={tool}", str(err.get("error", ""))[:300]],
                }
            )

    # 3) Feedback negativo.
    fb = feedback or {}
    if fb.get("rating") == "down":
        reason = fb.get("reason") or "other"
        if reason in ("wrong_answer",):
            has_retrieval = any(_kind_of(s.get("tool", "")) == "retrieval" for s in tool_calls)
            if not has_retrieval and tool_calls:
                possible.append(
                    {
                        "factor": "insufficient_context",
                        "label": "Contexto insuficiente",
                        "evidence": [
                            "No se ejecutó ninguna búsqueda de conocimiento",
                            "Posible contributing factor: la respuesta pudo generarse sin contexto.",
                        ],
                    }
                )
            possible.append(
                {
                    "factor": "possible_hallucination",
                    "label": "Posible alucinación o contexto incorrecto",
                    "evidence": [
                        "Feedback negativo por respuesta incorrecta",
                        "Validar contra las fuentes citadas antes de concluir.",
                    ],
                }
            )
        elif reason == "too_slow":
            if latency > 0 and baseline["p95_ms"] and latency > baseline["p95_ms"]:
                probable.append(
                    {
                        "factor": "latency_issue",
                        "label": "Latencia superior al p95 del agente",
                        "evidence": [
                            f"latencia={round(latency, 0)}ms vs p95={baseline['p95_ms']}ms",
                            f"feedback reason={REASON_MAP.get(reason, reason)}",
                        ],
                    }
                )
            else:
                possible.append(
                    {
                        "factor": "latency_issue",
                        "label": "Posible problema de latencia",
                        "evidence": [f"latencia={round(latency, 0)}ms"],
                    }
                )
        elif reason == "too_long":
            possible.append(
                {
                    "factor": "answer_verbosity",
                    "label": "Respuesta demasiado extensa",
                    "evidence": [f"longitud={len(run.get('answer') or '')} caracteres"],
                }
            )
        elif reason == "confusing":
            possible.append(
                {
                    "factor": "answer_quality",
                    "label": "Formato o claridad de la respuesta",
                    "evidence": [f"feedback reason={REASON_MAP.get(reason, reason)}"],
                }
            )

    # 4) Fallbacks de modelo (señal, no hecho).
    if fallbacks:
        possible.append(
            {
                "factor": "model_failure",
                "label": "Falló el modelo primario y se usó respaldo",
                "evidence": [
                    f"intentos={fallbacks[0].get('attempts')}",
                    "El fallback pudo afectar la calidad de la respuesta.",
                ],
            }
        )

    # 5) Guardrails (política/budget) que cortaron el run.
    for g in guardrails[:2]:
        detail = str(g.get("detail", ""))
        if "budget" in detail or "limit" in detail:
            probable.append(
                {
                    "factor": "budget_or_limit",
                    "label": "Límite de presupuesto o tokens",
                    "evidence": [detail[:200]],
                }
            )
        else:
            possible.append(
                {
                    "factor": "policy_block",
                    "label": "Bloqueado por política",
                    "evidence": [detail[:200]],
                }
            )

    return {
        "probable_causes": probable,
        "possible_contributing_factors": possible,
        "signals": signals,
    }


async def _feedback_for_run(run_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT rating, reason, comment, created_at FROM feedback "
                    "WHERE run_id = :rid ORDER BY created_at LIMIT 1"
                ),
                {"rid": run_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "rating": row.rating,
        "reason": row.reason,
        "comment": (row.comment or "")[:500],
        "created_at": row.created_at.isoformat(),
    }
