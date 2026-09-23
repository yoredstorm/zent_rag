# =============================================================================
# Unified Execution Flow — un contrato, tres orígenes (§32).
# =============================================================================
# GET /api/v1/executions/{kind}/{id}/flow
#
#   query/{query_id}       → rag_flows (Flow v2 cuando el camino lo emite)
#   agent/{run_id}         → agent_runs.flow (Flow v2; steps crudos si es viejo)
#   workflow/{run_id}      → workflow run (etapas; v1 honesto, sin inventar)
#
# El portal consume SIEMPRE la misma forma: `{"flow": {...}}`. El backend es la
# autoridad: acá no se reconstruye nada, sólo se normaliza lo que ya existe.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from src.infrastructure.observability.logging_config import get_logger
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/executions", tags=["Executions"])

KINDS = ("query", "agent", "workflow")


@router.get("/{kind}/{execution_id}/flow", summary="Flow canónico de una ejecución")
async def execution_flow(kind: str, execution_id: str, request: Request) -> dict:
    ctx = require_permission(request, "rag:read")
    resolved = str(kind or "").strip().lower()
    if resolved not in KINDS:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_kind",
                "message": f"kind debe ser uno de {', '.join(KINDS)}",
            },
        )
    try:
        target = UUID(execution_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_id", "message": "id debe ser UUID"},
        ) from exc

    if resolved == "query":
        from src.rag.flow_store import get_flow

        flow = await get_flow(ctx.organization_id, target)
        return {"flow": flow, "kind": resolved, "id": str(target)}

    if resolved == "agent":
        from src.agents.runtime.trace_store import ensure_agent_runs_table, get_flow, get_run

        await ensure_agent_runs_table()
        flow = await get_flow(ctx.organization_id, target)
        if flow is None:
            # Run viejo sin flow persistido: se normaliza lo que existe, sin
            # inventar telemetría (v1 explícito, el portal lo marca histórico).
            run = await get_run(ctx.organization_id, target)
            if run is None:
                return {"flow": None, "kind": resolved, "id": str(target)}
            from src.rag.flow_story import with_story
            from src.runtime.agent_flow import steps_to_flow

            mapped = steps_to_flow(run.get("steps"))
            flow = with_story(
                {
                    "execution": {"kind": "agent_run", "id": str(target)},
                    "method": "agent",
                    "status": run.get("status"),
                    "steps": mapped["steps"],
                    "jev": mapped["jev"],
                    "sources": [],
                    "fallbacks": [],
                }
            )
            flow["flow_version"] = 1
            flow.pop("events", None)
        return {"flow": flow, "kind": resolved, "id": str(target)}

    from src.platform.workflows.engine import run_detail
    from src.rag.flow_story import with_story
    from src.runtime.agent_flow import steps_to_flow

    run = await run_detail(ctx.organization_id, target)
    if run is None:
        return {"flow": None, "kind": resolved, "id": str(target)}
    steps = run.get("steps") if isinstance(run.get("steps"), list) else []
    mapped = steps_to_flow(
        [
            {"type": "workflow_step", **step}
            for step in steps
            if isinstance(step, dict)
        ]
    )
    flow = with_story(
        {
            "execution": {"kind": "workflow_run", "id": str(target)},
            "method": "workflow",
            "status": run.get("status"),
            "steps": mapped["steps"],
            "timings": {"total_ms": run.get("duration_ms") or 0.0},
            "sources": [],
            "fallbacks": [],
        }
    )
    # El run de workflow todavía no emite Flow v2: se declara v1 en vez de
    # fabricar eventos que no existen.
    flow["flow_version"] = 1
    flow.pop("events", None)
    return {"flow": flow, "kind": resolved, "id": str(target)}
