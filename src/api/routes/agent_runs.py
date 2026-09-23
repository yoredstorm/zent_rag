# =============================================================================
# Agent Run Route — ejecución del Agent Runtime
# =============================================================================
# POST /api/v1/agents/{agent_id}/run        (sync)
# POST /api/v1/agents/{agent_id}/run/stream (SSE)
# GET  /api/v1/agents/{agent_id}/runs       (traces del agente)
# GET  /api/v1/agents/runs/{run_id}         (trace individual)
# =============================================================================
from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agents.runtime.agent_runtime import AgentRunRequest
from src.agents.runtime.trace_store import (
    ensure_agent_runs_table,
    get_flow,
    get_run,
    list_runs,
    save_run,
)
from src.api.deps import get_agent_repo, get_agent_runtime
from src.core.ports import AgentRepository
from src.infrastructure.observability.logging_config import get_logger
from src.runtime.agent_flow import build_agent_flow

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/agents", tags=["Agent Runs"])


class AgentRunBody(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}

    message: str = Field(..., min_length=1, max_length=32000)
    conversation_id: UUID | None = None
    role: str = Field(default="admin", pattern="^(admin|customer)$")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _runtime_context(agent) -> dict:
    """Contexto real del run para no inventar procedencia (§9, §12)."""
    config = agent.config_json if isinstance(agent.config_json, dict) else {}
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    reasoning_mode = str(runtime.get("evidence_reasoning_mode") or "")
    jev_configured: bool | None = None
    try:
        from src.decision.service import get_decision_engine

        jev_configured = bool(get_decision_engine().settings.jev_configured)
    except Exception:  # noqa: BLE001 — sin engine no se afirma nada
        jev_configured = None
    if not reasoning_mode:
        try:
            from src.core.config import get_settings
            from src.intelligence.reasoning import wiring

            reasoning_mode = wiring.reasoning_mode(get_settings()).value
        except Exception:  # noqa: BLE001
            reasoning_mode = ""
    return {"reasoning_mode": reasoning_mode, "jev_configured": jev_configured}


def build_agent_run_flow(*, result, agent, question: str = "") -> dict:
    """Flow canónico v2 del run: el backend es la autoridad, el portal renderiza."""
    context = _runtime_context(agent)
    tools = tuple(str(name) for name in (getattr(agent, "tools", None) or []))
    try:
        return build_agent_flow(
            result=result,
            question=question,
            agent_tools=tools,
            reasoning_mode=context["reasoning_mode"],
            jev_configured=context["jev_configured"],
        )
    except Exception as exc:  # noqa: BLE001 — el flow nunca rompe el run
        logger.warning("Agent flow build failed", error=str(exc)[:200])
        return {}


def _run_payload(result, flow: dict) -> dict:
    """Contrato del run para el portal: flow + métricas reales (§3, §13)."""
    payload: dict = {
        "run_id": str(result.run_id),
        "status": result.status,
        "answer": result.answer,
        "steps": result.steps,
        "flow": flow,
        "total_latency_ms": result.total_latency_ms,
        "total_tokens": result.total_tokens,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "cost": result.cost,
        "model": result.model,
        "provider": result.provider,
        "injection_detected": result.injection_detected,
    }
    return payload


async def _load_agent(
    request: Request,
    agent_repo: AgentRepository,
    agent_id: UUID,
):
    from src.api.security import resolve_organization

    organization_id = resolve_organization(request)
    agent = await agent_repo.get_agent(organization_id, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.is_active:
        raise HTTPException(status_code=409, detail="Agent is inactive")
    return agent, organization_id


def _tenant_context(request: Request):
    return request.state.tenant_context


@router.post("/{agent_id}/run", summary="Ejecutar agente (Agent Runtime)")
async def run_agent(
    agent_id: UUID,
    body: AgentRunBody,
    request: Request,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    x_user_id: str = Header(default="", alias="X-User-Id"),
    runtime=Depends(get_agent_runtime),
):
    from src.api.security import resolve_user_id
    from src.platform.rbac.policy import require_permission

    require_permission(request, "agents:execute")
    agent, organization_id = await _load_agent(request, agent_repo, agent_id)
    user_id = await resolve_user_id(request, x_user_id)
    ctx = _tenant_context(request)
    org_config = await _org_config(request, organization_id)

    result = await runtime.run(
        AgentRunRequest(
            agent=agent,
            message=body.message,
            user_id=user_id,
            role=body.role,
            conversation_id=body.conversation_id,
            permissions=ctx.permissions,
            org_config=org_config,
            trace_id=request.headers.get("X-Trace-Id"),
        )
    )
    flow = build_agent_run_flow(result=result, agent=agent, question=body.message)
    try:
        await ensure_agent_runs_table()
    except Exception:
        pass
    await save_run(result, flow=flow or None)
    try:
        from src.platform.onboardingv2.onboarding import sync_progress

        await sync_progress(request.agent.organization_id)
    except Exception:  # noqa: BLE001
        pass

    return _run_payload(result, flow)


@router.post("/{agent_id}/run/stream", summary="Ejecutar agente (SSE)")
async def run_agent_stream(
    agent_id: UUID,
    body: AgentRunBody,
    request: Request,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    x_user_id: str = Header(default="", alias="X-User-Id"),
    runtime=Depends(get_agent_runtime),
):
    from src.api.security import resolve_user_id
    from src.platform.rbac.policy import require_permission

    require_permission(request, "agents:execute")
    agent, organization_id = await _load_agent(request, agent_repo, agent_id)
    user_id = await resolve_user_id(request, x_user_id)
    ctx = _tenant_context(request)
    org_config = await _org_config(request, organization_id)

    queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()

    async def run_pipeline() -> None:
        result = await runtime.run(
            AgentRunRequest(
                agent=agent,
                message=body.message,
                user_id=user_id,
                role=body.role,
                conversation_id=body.conversation_id,
                permissions=ctx.permissions,
                org_config=org_config,
            )
        )
        # El flow canónico se construye SERVER-SIDE y viaja en el `done`:
        # el portal no reconstruye la verdad del run (docs/architecture/execution-story.md).
        flow = build_agent_run_flow(result=result, agent=agent, question=body.message)
        try:
            await ensure_agent_runs_table()
        except Exception:
            pass
        await save_run(result, flow=flow or None)
        await queue.put(("done", _run_payload(result, flow)))

    async def event_stream():
        await queue.put(("status", {"phase": "running"}))
        task = asyncio.ensure_future(run_pipeline())
        try:
            while True:
                event, data = await asyncio.wait_for(queue.get(), timeout=290)
                yield _sse(event, data)
                if event in ("done", "error"):
                    break
        except asyncio.TimeoutError:
            yield _sse("error", {"message": "stream timeout"})
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}", summary="Trace de un run (admin org)")
async def get_agent_run(
    run_id: UUID,
    request: Request,
):
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    await ensure_agent_runs_table()
    run = await get_run(organization_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/runs/{run_id}/flow", summary="Flow canónico v2 de un run (tenant)")
async def get_agent_run_flow(run_id: UUID, request: Request) -> dict:
    """Flow canónico del run. Para runs viejos sin flow persistido: None."""
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "rag:read")
    await ensure_agent_runs_table()
    flow = await get_flow(ctx.organization_id, run_id)
    return {"flow": flow}


@router.post(
    "/runs/{run_id}/analysis",
    summary="Root cause de una respuesta (FASE 03) — admin org",
)
async def analyze_agent_run(run_id: UUID, request: Request):
    """Clasifica posibles causas usando señales reales del run + feedback.

    Language honesto: 'Probable cause' / 'Possible contributing factor'.
    """
    from src.api.security import resolve_organization
    from src.platform.quality.analysis import analyze_run
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    return await analyze_run(organization_id, run_id)


@router.get("/{agent_id}/runs", summary="Traces de un agente (admin org)")
async def list_agent_runs(
    agent_id: UUID,
    request: Request,
    limit: int = 20,
    offset: int = 0,
):
    from src.api.security import resolve_organization
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    await ensure_agent_runs_table()
    runs = await list_runs(
        organization_id, agent_id=agent_id, limit=min(limit, 100), offset=offset
    )
    return {"runs": runs, "total": len(runs)}


async def _org_config(request: Request, organization_id: UUID) -> dict:
    from src.api.deps import get_organization_repo

    repo = get_organization_repo()
    organization = await repo.get_by_id(organization_id)
    return organization.config_json if organization else {}

