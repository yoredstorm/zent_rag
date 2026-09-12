# =============================================================================
# Cognitive Inspector — Phase 9 (backend)
# =============================================================================
# Vista de alto nivel de un run para el Agent Inspector / Evidence View:
# especialistas, tareas, evidencia, claims, conflictos, verificación y costo.
# NUNCA expone chain-of-thought (solo conclusiones/evidencia/estados).
# =============================================================================
from __future__ import annotations


def build_inspector(
    *,
    run: dict,
    tasks: list[dict],
    executions: list[dict],
    messages: list[dict],
) -> dict:
    plan = run.get("plan") or {}
    specialists = [
        {
            "agent_id": execution.get("agent_id"),
            "status": execution.get("status"),
            "latency_ms": round(float(execution.get("latency_ms") or 0.0), 2),
            "tokens": int(execution.get("tokens") or 0),
            "cost_usd": float(execution.get("cost_usd") or 0.0),
            "error": execution.get("error"),
            "result": execution.get("result") or {},
        }
        for execution in executions
    ]
    evidence_ids = sorted(
        {
            str(evidence_id)
            for message in messages
            for evidence_id in (message.get("evidence_ids") or [])
        }
    )
    claim_ids = sorted(
        {
            str(claim_id)
            for message in messages
            for claim_id in (message.get("claim_ids") or [])
        }
    )
    totals = {
        "executions": len(executions),
        "llm_calls": sum(int(e.get("llm_calls") or 0) for e in executions),
        "tokens": sum(int(e.get("tokens") or 0) for e in executions),
        "cost_usd": round(
            sum(float(e.get("cost_usd") or 0.0) for e in executions), 6
        ),
        "latency_ms": round(
            sum(float(e.get("latency_ms") or 0.0) for e in executions), 2
        ),
    }
    return {
        "run": {
            "id": str(run.get("id")),
            "status": run.get("status"),
            "complexity": run.get("complexity"),
            "query": run.get("query"),
        },
        "specialists": specialists,
        "tasks": [
            {
                "key": task.get("task_key"),
                "agent_id": task.get("agent_id"),
                "status": task.get("status"),
                "depends_on": task.get("depends_on") or [],
            }
            for task in tasks
        ],
        "evidence": {"count": len(evidence_ids), "ids": evidence_ids},
        "claims": {"count": len(claim_ids), "ids": claim_ids},
        "conflicts": plan.get("conflicts") or [],
        "critique": plan.get("critique"),
        "debate": plan.get("debate") or [],
        "final_answer": plan.get("final_answer"),
        "totals": totals,
        "chain_of_thought_exposed": False,
    }
