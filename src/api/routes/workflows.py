# =============================================================================
# AI Workflow Automation Studio v2 — CRUD, ejecución, trazabilidad.
#
# Phase 32A: RBAC dedicado (workflows:*, workflow_runs:read, integrations:*,
# external_actions:execute, workflow_secrets:manage, workflow_approvals:approve),
# aislamiento por workspace, graph IR, dry-run y trigger de eventos.
#
# ORDEN IMPORTANTE: rutas estáticas (/triggers, /runs/...) ANTES de
# /{workflow_id} para evitar captura de path.
# =============================================================================
from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])


async def _workspace_id(request: Request) -> UUID | None:
    """Workspace del request (header > activo). None = tenant legacy sin
    workspace (aislamiento se aplica cuando existe workspace)."""
    from src.platform.workspaces.context import (
        get_active_workspace_id,
        workspace_header_or_none,
    )

    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        return None
    header = workspace_header_or_none(request)
    if header is not None:
        return header
    try:
        active = await get_active_workspace_id(ctx.organization_id, ctx.user_id)
        if active is not None:
            return active
    except Exception:  # noqa: BLE001
        pass
    return None


#: Fecha de retirada anunciada del camino Copilot legacy.
_LEGACY_SUNSET = "Wed, 31 Dec 2026 23:59:59 GMT"


def _mark_legacy(response: Response) -> None:
    """Marca los endpoints Copilot como legacy sin romper a sus consumidores."""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = _LEGACY_SUNSET
    response.headers["Link"] = '</api/v1/workflows/architect/plan>; rel="successor-version"'
    response.headers["Warning"] = (
        '299 - "Copilot legacy: usa /api/v1/workflows/architect/plan"'
    )


# ---------------------------------------------------------------------------
# Rutas estáticas (antes de /{workflow_id})
# ---------------------------------------------------------------------------
@router.get("", summary="Workflows del tenant")
async def tenant_workflows_list(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_workflows

    ctx = require_permission(request, "workflows:read")
    return await list_workflows(ctx.organization_id, await _workspace_id(request))


@router.post("", summary="Crear workflow")
async def tenant_workflows_create(body: WorkflowIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import create_workflow

    ctx = require_permission(request, "workflows:create")
    ws_id = await _workspace_id(request) if not body.workspace_id else UUID(body.workspace_id)
    if ws_id is not None:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            owned = (
                await session.execute(
                    text(
                        "SELECT 1 FROM workspaces WHERE id = :ws AND organization_id = :oid"
                    ),
                    {"ws": str(ws_id), "oid": str(ctx.organization_id)},
                )
            ).fetchone()
        finally:
            await session.close()
        if owned is None:
            raise HTTPException(403, "workspace no pertenece a la organización")
    try:
        return await create_workflow(
            ctx.organization_id,
            body.name,
            body.trigger_type,
            body.trigger_config,
            body.steps,
            body.description,
            ctx.user_id,
            body.editor_state,
            workspace_id=ws_id,
            graph=body.graph,
            workflow_version=body.workflow_version,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/validate", summary="Validar grafo o steps sin persistir")
async def tenant_workflow_validate(body: ValidateIn, request: Request):
    from src.platform.rbac.policy import require_permission

    require_permission(request, "workflows:update")
    from src.platform.workflows.ir import (
        LegacyWorkflowAdapter,
        WorkflowGraph,
        WorkflowGraphError,
        validate_graph,
    )

    try:
        graph = (
            WorkflowGraph.from_dict(dict(body.graph))
            if body.graph is not None
            else LegacyWorkflowAdapter.steps_to_graph(
                body.steps or [], body.trigger_type or "webhook", body.trigger_config or {}
            )
        )
        validate_graph(graph)
        return {"valid": True, "graph": graph.to_dict()}
    except (WorkflowGraphError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"grafo inválido: {exc}") from exc


@router.get("/node-schemas", summary="Schemas de negocio por nodo (Simple/Guided/Advanced)")
async def tenant_workflow_node_schemas(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.parameters import all_node_schemas, output_contracts

    require_permission(request, "workflows:read")
    return {
        "schemas": [schema.model_dump(mode="json") for schema in all_node_schemas()],
        "output_contracts": output_contracts(),
    }


@router.get("/node-catalog", summary="Catálogo semántico de nodos (tenant-aware)")
async def tenant_workflow_node_catalog(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.node_catalog import build_node_catalog

    ctx = require_permission(request, "workflows:read")
    scopes = getattr(ctx, "scopes", frozenset()) or frozenset()
    permissions = None if "admin:*" in scopes else ctx.permissions
    return await build_node_catalog(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        permissions=permissions,
    )


@router.get("/notification-targets", summary="Canales y destinatarios disponibles para Avisar")
async def tenant_workflow_notification_targets(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.notifications import notification_targets

    ctx = require_permission(request, "workflows:read")
    return await notification_targets(ctx.organization_id, await _workspace_id(request))


@router.post("/copilot/intent", summary="Copiloto legacy: describir qué automatizar → Intent + Plan")
async def tenant_workflow_copilot_intent(
    body: CopilotIntentIn, request: Request, response: Response
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.copilot_v2 import propose_workflow

    _mark_legacy(response)
    ctx = require_permission(request, "workflows:create")
    try:
        return await propose_workflow(
            ctx.organization_id,
            body.prompt.strip(),
            workspace_id=await _workspace_id(request),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/copilot/compile", summary="Copiloto legacy: WorkflowPlan → WorkflowGraph validado")
async def tenant_workflow_copilot_compile(
    body: CopilotCompileIn, request: Request, response: Response
):
    from pydantic import ValidationError as PydanticValidationError

    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.copilot_v2 import compile_proposal

    _mark_legacy(response)
    ctx = require_permission(request, "workflows:create")
    try:
        return await compile_proposal(
            ctx.organization_id,
            body.plan,
            workspace_id=await _workspace_id(request),
        )
    except (PydanticValidationError, ValueError) as exc:
        raise HTTPException(400, f"plan inválido: {exc}") from exc


@router.get(
    "/architect/config",
    summary="Workflow Architect: feature flag y contrato de estados",
)
async def tenant_workflow_architect_config(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect_observability import (
        DESIGN_STATES,
        PLANNER_VERSION,
        architect_ui_enabled,
    )

    require_permission(request, "workflows:read")
    return {
        "enabled": architect_ui_enabled(),
        "planner_version": PLANNER_VERSION,
        "states": list(DESIGN_STATES),
    }


@router.post(
    "/architect/plan",
    summary="Workflow Architect: lenguaje natural → plan semántico → grafo draft",
)
async def tenant_workflow_architect_plan(body: ArchitectPlanIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import plan_workflow

    ctx = require_permission(request, "workflows:create")
    return await plan_workflow(
        ctx.organization_id,
        body.prompt.strip(),
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
        model=body.model,
        session_id=body.session_id,
        actor_id=ctx.user_id,
        preferred_agent_id=body.agent_id,
    )


@router.post(
    "/architect/agentic-plan",
    summary="Workflow Architect: planner agéntico con tool calling read-only",
)
async def tenant_workflow_architect_agentic_plan(
    body: ArchitectAgenticPlanIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.planner_session import (
        PlannerBudget,
        PlannerBudgetExceeded,
        PlanningCancelled,
        WorkflowPlanningSession,
    )

    ctx = require_permission(request, "workflows:create")
    session = WorkflowPlanningSession(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
        model=body.model,
        budget=PlannerBudget.from_settings(),
        session_id=body.session_id,
        clarification_history=body.clarification_history,
    )
    task = asyncio.create_task(session.run(body.prompt.strip()))
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.5)
            if await request.is_disconnected() and not task.done():
                session.cancel_event.set()
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001 — el cliente ya se fue
                    pass
                return JSONResponse(
                    status_code=409,
                    content={
                        "error_code": "PLANNER_CANCELLED",
                        "message": "La planificación se canceló porque el cliente cerró la conexión.",
                    },
                )
        result = task.result()
    except PlannerBudgetExceeded as exc:
        from src.platform.workflows.planner_diagnostics import budget_diagnostic

        diagnostic = budget_diagnostic(exc.reason)
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "PLANNER_BUDGET_EXCEEDED",
                "reason": exc.reason,
                "message": diagnostic["message"],
                "action": diagnostic["action"],
                "diagnostic": diagnostic,
                "usage": exc.usage.as_dict(),
            },
        )
    except PlanningCancelled as exc:
        return JSONResponse(
            status_code=409,
            content={"error_code": "PLANNER_CANCELLED", "message": str(exc)},
        )
    response = JSONResponse(status_code=200, content=result)
    response.headers["X-Zent-Planner"] = "agentic"
    return response


@router.post(
    "/architect/resources/resolve",
    summary="Workflow Architect: resuelve recursos, autoridad, campos y bindings del tenant",
)
async def tenant_workflow_architect_resources_resolve(
    body: ArchitectResourceResolveIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.business_resources import BusinessResourceResolver

    ctx = require_permission(request, "workflows:read")
    resolver = BusinessResourceResolver(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
    )
    report = await resolver.resolve_need(
        body.need.strip(),
        required_fields=body.required_fields,
        concepts=body.concepts,
        domain=body.domain,
        kinds=body.kinds,
        capability_refs=body.capability_refs,
        limit=body.limit,
    )
    return report.model_dump(mode="json")


@router.post(
    "/architect/simulate",
    summary="Workflow Architect: validación estática y simulación ejecutable de escenarios",
)
async def tenant_workflow_architect_simulate(
    body: ArchitectSimulateIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect_discovery import discover_capabilities
    from src.platform.workflows.workflow_simulation import (
        SimulationScenario,
        simulate_semantic_plan,
    )

    ctx = require_permission(request, "workflows:create")
    capabilities = await discover_capabilities(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
    )
    try:
        scenarios = [
            SimulationScenario.model_validate(item) for item in body.scenarios
        ]
        report = await simulate_semantic_plan(
            body.plan,
            capabilities,
            scenarios,
            organization_id=ctx.organization_id,
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
        )
    except ValueError as exc:
        raise HTTPException(400, f"simulación inválida: {exc}") from exc
    return report.model_dump(mode="json")


@router.post(
    "/architect/simulate/repair",
    summary="Workflow Architect: reparación semántica acotada tras simulación",
)
async def tenant_workflow_architect_simulate_repair(
    body: ArchitectSimulateRepairIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect_discovery import discover_capabilities
    from src.platform.workflows.workflow_simulation import (
        SimulationScenario,
        simulate_with_repair,
    )

    ctx = require_permission(request, "workflows:create")
    capabilities = await discover_capabilities(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
    )
    try:
        scenarios = [
            SimulationScenario.model_validate(item) for item in body.scenarios
        ]
        result = await simulate_with_repair(
            body.plan,
            capabilities,
            scenarios,
            organization_id=ctx.organization_id,
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
            model=body.model,
            max_repairs=body.max_repairs,
            session_id=body.session_id,
        )
    except ValueError as exc:
        raise HTTPException(400, f"reparación inválida: {exc}") from exc
    return result


@router.post(
    "/architect/sessions",
    summary="Workflow Architect: abre una sesión persistente de diseño",
)
async def tenant_workflow_architect_session_create(
    body: DesignSessionCreateIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.design_sessions import (
        append_design_message,
        create_design_session,
        get_design_session,
        save_design_result,
    )
    from src.platform.workflows.planner_session import (
        PlannerBudget,
        PlannerBudgetExceeded,
        PlanningCancelled,
        WorkflowPlanningSession,
    )

    ctx = require_permission(request, "workflows:create")
    ws_id = await _workspace_id(request)
    design = await create_design_session(
        ctx.organization_id,
        user_id=ctx.user_id,
        workspace_id=ws_id,
        prompt=body.prompt.strip(),
        title=body.title,
    )
    planner = WorkflowPlanningSession(
        ctx.organization_id,
        workspace_id=ws_id,
        permissions=ctx.permissions,
        model=body.model,
        budget=PlannerBudget.from_settings(),
        session_id=design["id"],
    )
    try:
        proposal = await planner.run(body.prompt.strip())
    except PlannerBudgetExceeded as exc:
        from src.platform.workflows.planner_diagnostics import budget_diagnostic

        diagnostic = budget_diagnostic(exc.reason)
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "PLANNER_BUDGET_EXCEEDED",
                "reason": exc.reason,
                "message": diagnostic["message"],
                "action": diagnostic["action"],
                "diagnostic": diagnostic,
                "design_session_id": design["id"],
                "usage": exc.usage.as_dict(),
            },
        )
    except PlanningCancelled as exc:
        return JSONResponse(
            status_code=409,
            content={"error_code": "PLANNER_CANCELLED", "message": str(exc)},
        )
    saved = await save_design_result(
        ctx.organization_id,
        UUID(design["id"]),
        proposal,
        expected_revision=0,
        user_id=ctx.user_id,
        kind="initial",
        instruction=body.prompt.strip(),
        diff={"summary": "Plan inicial"},
    )
    await append_design_message(
        ctx.organization_id,
        UUID(design["id"]),
        role="assistant",
        content=_design_assistant_summary(proposal),
        user_id=None,
        revision=saved["revision"],
        metadata={"state": proposal.get("state")},
    )
    saved = await get_design_session(
        ctx.organization_id,
        UUID(design["id"]),
        user_id=ctx.user_id,
        include_revisions=True,
    ) or saved
    response_proposal = (saved.get("state") or {}).get("proposal") or proposal
    return {"design_session": saved, "proposal": response_proposal}


@router.get(
    "/architect/sessions",
    summary="Workflow Architect: sesiones de diseño del usuario",
)
async def tenant_workflow_architect_sessions_list(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.design_sessions import list_design_sessions

    ctx = require_permission(request, "workflows:read")
    return await list_design_sessions(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        user_id=ctx.user_id,
    )


@router.get(
    "/architect/sessions/{design_session_id}",
    summary="Workflow Architect: detalle y revisiones de una sesión de diseño",
)
async def tenant_workflow_architect_session_get(
    design_session_id: str, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.design_sessions import get_design_session

    ctx = require_permission(request, "workflows:read")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    design = await get_design_session(
        ctx.organization_id,
        session_id,
        user_id=ctx.user_id,
        include_revisions=True,
    )
    if design is None:
        raise HTTPException(404, "Sesión de diseño no encontrada")
    return design


@router.post(
    "/architect/sessions/{design_session_id}/messages",
    summary="Workflow Architect: conversación y patch semántico persistente",
)
async def tenant_workflow_architect_session_message(
    design_session_id: str, body: DesignSessionMessageIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import patch_workflow_plan
    from src.platform.workflows.design_sessions import (
        append_design_message,
        get_design_session,
        save_design_result,
    )
    from src.platform.workflows.planner_session import (
        PlannerBudget,
        PlannerBudgetExceeded,
        PlanningCancelled,
        WorkflowPlanningSession,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    current = await get_design_session(
        ctx.organization_id, session_id, user_id=ctx.user_id, include_revisions=False
    )
    if current is None:
        raise HTTPException(404, "Sesión de diseño no encontrada")
    if current.get("status") == "closed":
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CLOSED",
                "message": "La sesión está cerrada; reábrela antes de continuar.",
            },
        )
    if current["revision"] != body.expected_revision:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CONFLICT",
                "message": "La sesión cambió desde que la cargaste.",
                "current_revision": current["revision"],
                "expected_revision": body.expected_revision,
            },
        )
    await append_design_message(
        ctx.organization_id,
        session_id,
        role="user",
        content=body.message.strip(),
        user_id=ctx.user_id,
        revision=current["revision"],
    )
    ws_id = await _workspace_id(request)
    current_state = str((current.get("state") or {}).get("state") or "")
    # Un plan sin grafo (BLOCKED/NEEDS_CLARIFICATION/NEEDS_CONFIGURATION) no es
    # una base segura para un patch: se vuelve a planificar con la aclaración
    # del usuario. El patch solo aplica sobre un diseño ya compilado.
    can_patch = bool(current.get("plan") and current.get("graph")) and current_state in (
        "DRAFT_READY",
        "NEEDS_CONFIGURATION",
    )
    try:
        if can_patch:
            proposal = await patch_workflow_plan(
                ctx.organization_id,
                current["plan"],
                body.message.strip(),
                workspace_id=ws_id,
                permissions=ctx.permissions,
                model=body.model,
                session_id=design_session_id,
                plan_hash_value=current.get("plan_hash"),
                actor_id=ctx.user_id,
            )
            kind = "patch"
            diff = proposal.get("diff") or proposal.get("patch") or {
                "summary": body.message.strip()[:400]
            }
            if isinstance(diff, dict):
                diff = {
                    **diff,
                    "summary": (proposal.get("patch") or {}).get("summary")
                    or diff.get("summary")
                    or body.message.strip()[:400],
                }
        else:
            history = [
                item["content"]
                for item in current.get("messages") or []
                if item.get("role") == "user"
            ]
            planner = WorkflowPlanningSession(
                ctx.organization_id,
                workspace_id=ws_id,
                permissions=ctx.permissions,
                model=body.model,
                budget=PlannerBudget.from_settings(),
                session_id=design_session_id,
                clarification_history=history,
            )
            proposal = await planner.run(body.message.strip())
            kind = "plan"
            diff = {"summary": "Nuevo plan desde conversación"}
    except PlannerBudgetExceeded as exc:
        from src.platform.workflows.planner_diagnostics import budget_diagnostic

        diagnostic = budget_diagnostic(exc.reason)
        return JSONResponse(
            status_code=429,
            content={
                "error_code": "PLANNER_BUDGET_EXCEEDED",
                "reason": exc.reason,
                "message": diagnostic["message"],
                "action": diagnostic["action"],
                "diagnostic": diagnostic,
                "design_session_id": design_session_id,
                "usage": exc.usage.as_dict(),
            },
        )
    except PlanningCancelled as exc:
        return JSONResponse(
            status_code=409,
            content={"error_code": "PLANNER_CANCELLED", "message": str(exc)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error_code": "DESIGN_PATCH_INVALID", "message": str(exc)[:400]},
        )
    saved = await save_design_result(
        ctx.organization_id,
        session_id,
        proposal,
        expected_revision=current["revision"],
        user_id=ctx.user_id,
        kind=kind,
        instruction=body.message.strip(),
        diff=diff,
    )
    await append_design_message(
        ctx.organization_id,
        session_id,
        role="assistant",
        content=_design_assistant_summary(proposal),
        user_id=None,
        revision=saved["revision"],
        metadata={"state": proposal.get("state"), "kind": kind},
    )
    saved = await get_design_session(
        ctx.organization_id, session_id, user_id=ctx.user_id, include_revisions=True
    ) or saved
    response_proposal = (saved.get("state") or {}).get("proposal") or proposal
    return {"design_session": saved, "proposal": response_proposal}


@router.post(
    "/architect/sessions/{design_session_id}/patch-preview",
    summary="Workflow Architect: diff semántico antes de aplicar",
)
async def tenant_workflow_architect_session_patch_preview(
    design_session_id: str, body: DesignSessionPatchPreviewIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import patch_workflow_plan
    from src.platform.workflows.design_sessions import get_design_session

    ctx = require_permission(request, "workflows:create")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    current = await get_design_session(
        ctx.organization_id, session_id, user_id=ctx.user_id, include_revisions=False
    )
    if current is None:
        raise HTTPException(404, "Sesión de diseño no encontrada")
    if current.get("status") == "closed":
        return JSONResponse(
            status_code=409,
            content={"error_code": "DESIGN_SESSION_CLOSED", "message": "La sesión está cerrada."},
        )
    if current["revision"] != body.expected_revision:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CONFLICT",
                "current_revision": current["revision"],
                "expected_revision": body.expected_revision,
            },
        )
    if not current.get("plan"):
        raise HTTPException(422, "La sesión no tiene un plan para modificar")
    try:
        proposal = await patch_workflow_plan(
            ctx.organization_id,
            current["plan"],
            body.message.strip(),
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
            model=body.model,
            session_id=design_session_id,
            plan_hash_value=current.get("plan_hash"),
            actor_id=ctx.user_id,
            preview_only=True,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error_code": "DESIGN_PATCH_INVALID", "message": str(exc)[:400]},
        )
    return {
        "confirmation_required": True,
        "revision": current["revision"],
        "proposal": proposal,
        "patch": proposal.get("patch"),
        "diff": proposal.get("diff"),
    }


@router.post(
    "/architect/sessions/{design_session_id}/patch-apply",
    summary="Workflow Architect: aplica un diff semántico confirmado",
)
async def tenant_workflow_architect_session_patch_apply(
    design_session_id: str, body: DesignSessionPatchApplyIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import patch_workflow_plan
    from src.platform.workflows.design_sessions import (
        append_design_message,
        get_design_session,
        save_design_result,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    current = await get_design_session(
        ctx.organization_id, session_id, user_id=ctx.user_id, include_revisions=False
    )
    if current is None:
        raise HTTPException(404, "Sesión de diseño no encontrada")
    if current.get("status") == "closed":
        return JSONResponse(
            status_code=409,
            content={"error_code": "DESIGN_SESSION_CLOSED", "message": "La sesión está cerrada."},
        )
    if current["revision"] != body.expected_revision:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CONFLICT",
                "current_revision": current["revision"],
                "expected_revision": body.expected_revision,
            },
        )
    if not current.get("plan"):
        raise HTTPException(422, "La sesión no tiene un plan para modificar")
    await append_design_message(
        ctx.organization_id,
        session_id,
        role="user",
        content=body.message.strip(),
        user_id=ctx.user_id,
        revision=current["revision"],
    )
    try:
        proposal = await patch_workflow_plan(
            ctx.organization_id,
            current["plan"],
            body.message.strip(),
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
            session_id=design_session_id,
            plan_hash_value=current.get("plan_hash"),
            actor_id=ctx.user_id,
            proposed_patch=body.patch,
            proposed_source=body.source,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error_code": "DESIGN_PATCH_INVALID", "message": str(exc)[:400]},
        )
    diff = proposal.get("diff") or proposal.get("patch") or {}
    if isinstance(diff, dict):
        diff = {
            **diff,
            "summary": (proposal.get("patch") or {}).get("summary")
            or diff.get("summary")
            or body.message.strip()[:400],
        }
    saved = await save_design_result(
        ctx.organization_id,
        session_id,
        proposal,
        expected_revision=current["revision"],
        user_id=ctx.user_id,
        kind="patch",
        instruction=body.message.strip(),
        diff=diff,
    )
    await append_design_message(
        ctx.organization_id,
        session_id,
        role="assistant",
        content=_design_assistant_summary(proposal),
        user_id=None,
        revision=saved["revision"],
        metadata={"state": proposal.get("state"), "kind": "patch"},
    )
    saved = await get_design_session(
        ctx.organization_id, session_id, user_id=ctx.user_id, include_revisions=True
    ) or saved
    response_proposal = (saved.get("state") or {}).get("proposal") or proposal
    return {"design_session": saved, "proposal": response_proposal}


@router.post(
    "/architect/sessions/{design_session_id}/restore",
    summary="Workflow Architect: restaura una revisión anterior",
)
async def tenant_workflow_architect_session_restore(
    design_session_id: str, body: DesignSessionRevisionIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.design_sessions import (
        DesignSessionConflict,
        DesignSessionNotFound,
        restore_design_revision,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    try:
        design = await restore_design_revision(
            ctx.organization_id,
            session_id,
            body.revision,
            expected_revision=body.expected_revision,
            user_id=ctx.user_id,
            instruction=body.instruction,
        )
    except DesignSessionConflict as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CONFLICT",
                "message": str(exc),
                "current_revision": exc.current_revision,
            },
        )
    except DesignSessionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return design


@router.post(
    "/architect/sessions/{design_session_id}/close",
    summary="Workflow Architect: cierra una sesión de diseño",
)
async def tenant_workflow_architect_session_close(
    design_session_id: str, body: DesignSessionCloseIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.design_sessions import (
        DesignSessionConflict,
        close_design_session,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        design = await close_design_session(
            ctx.organization_id,
            UUID(design_session_id),
            expected_revision=body.expected_revision,
            user_id=ctx.user_id,
        )
    except DesignSessionConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"error_code": "DESIGN_SESSION_CONFLICT", "current_revision": exc.current_revision},
        )
    return design


@router.post(
    "/architect/sessions/{design_session_id}/reopen",
    summary="Workflow Architect: reabre una sesión de diseño",
)
async def tenant_workflow_architect_session_reopen(
    design_session_id: str, body: DesignSessionCloseIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.design_sessions import (
        DesignSessionConflict,
        reopen_design_session,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        design = await reopen_design_session(
            ctx.organization_id,
            UUID(design_session_id),
            expected_revision=body.expected_revision,
            user_id=ctx.user_id,
        )
    except DesignSessionConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"error_code": "DESIGN_SESSION_CONFLICT", "current_revision": exc.current_revision},
        )
    return design


@router.post(
    "/architect/sessions/{design_session_id}/simulate",
    summary="Workflow Architect: certifica la sesión con escenarios",
)
async def tenant_workflow_architect_session_simulate(
    design_session_id: str, body: DesignSessionSimulateIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect_discovery import discover_capabilities
    from src.platform.workflows.design_sessions import (
        DesignSessionConflict,
        DesignSessionNotFound,
        get_design_session,
        save_design_simulation,
    )
    from src.platform.workflows.workflow_simulation import (
        SimulationScenario,
        simulate_semantic_plan,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    current = await get_design_session(ctx.organization_id, session_id, user_id=ctx.user_id)
    if current is None:
        raise HTTPException(404, "Sesión de diseño no encontrada")
    if current.get("status") == "closed":
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CLOSED",
                "message": "La sesión está cerrada; reábrela antes de simular.",
            },
        )
    if current["revision"] != body.expected_revision:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CONFLICT",
                "current_revision": current["revision"],
                "expected_revision": body.expected_revision,
            },
        )
    if not current.get("plan"):
        raise HTTPException(422, "La sesión no tiene un plan para simular")
    try:
        scenarios = [
            SimulationScenario.model_validate(item) for item in body.scenarios
        ]
        capabilities = await discover_capabilities(
            ctx.organization_id,
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
        )
        certification = await simulate_semantic_plan(
            current["plan"],
            capabilities,
            scenarios,
            organization_id=ctx.organization_id,
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
        )
        saved = await save_design_simulation(
            ctx.organization_id,
            session_id,
            certification.model_dump(mode="json"),
            expected_revision=current["revision"],
            user_id=ctx.user_id,
            instruction="Certificación de simulación",
        )
    except (DesignSessionConflict, DesignSessionNotFound) as exc:
        return JSONResponse(
            status_code=409,
            content={"error_code": "DESIGN_SESSION_CONFLICT", "message": str(exc)},
        )
    except ValueError as exc:
        raise HTTPException(422, f"simulación inválida: {exc}") from exc
    return {"design_session": saved, "certification": certification}


@router.post(
    "/architect/sessions/{design_session_id}/draft",
    summary="Workflow Architect: guarda un borrador desde la sesión",
)
async def tenant_workflow_architect_session_draft(
    design_session_id: str, body: DesignSessionDraftIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import save_architect_draft
    from src.platform.workflows.design_sessions import (
        attach_workflow,
        get_design_session,
    )

    ctx = require_permission(request, "workflows:create")
    try:
        session_id = UUID(design_session_id)
    except ValueError as exc:
        raise HTTPException(400, "sesión inválida") from exc
    current = await get_design_session(ctx.organization_id, session_id, user_id=ctx.user_id)
    if current is None:
        raise HTTPException(404, "Sesión de diseño no encontrada")
    if current.get("status") == "closed":
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CLOSED",
                "message": "La sesión está cerrada; reábrela antes de guardar.",
            },
        )
    if current["revision"] != body.expected_revision:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "DESIGN_SESSION_CONFLICT",
                "current_revision": current["revision"],
                "expected_revision": body.expected_revision,
            },
        )
    if not current.get("plan"):
        raise HTTPException(422, "La sesión no tiene un plan para guardar")
    source = str((current.get("state") or {}).get("proposal", {}).get("planner", {}).get("source") or "llm")
    result = await save_architect_draft(
        ctx.organization_id,
        current["plan"],
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
        name=body.name,
        description=body.description,
        editor_state={"mode": "canvas", "config_level": body.config_level},
        session_id=design_session_id,
        plan_hash_value=current.get("plan_hash"),
        capability_snapshot_hash=current.get("capability_snapshot_hash"),
        source=source,
        actor_id=ctx.user_id,
    )
    await attach_workflow(
        ctx.organization_id, session_id, UUID(result["workflow_id"]), user_id=ctx.user_id
    )
    return {"design_session": await get_design_session(
        ctx.organization_id, session_id, user_id=ctx.user_id, include_revisions=True
    ), "workflow": result}


def _design_assistant_summary(proposal: dict[str, Any]) -> str:
    state = str(proposal.get("state") or "BLOCKED")
    if state == "DRAFT_READY":
        return "Entendí el proceso y el plan está listo para revisar."
    clarifications = proposal.get("clarifications") or []
    if clarifications:
        return "Necesito confirmar: " + "; ".join(
            str(item.get("question") or "")[:200]
            for item in clarifications[:3]
        )
    requirements = proposal.get("requirements") or []
    if requirements:
        return "Faltan dependencias: " + "; ".join(
            str(item.get("message") or item.get("requirement") or "")[:200]
            for item in requirements[:3]
        )
    return f"El diseño quedó en estado {state}. Revisa los detalles antes de continuar."


@router.post(
    "/architect/patch",
    summary="Workflow Architect: cambio conversacional sobre el plan",
)
async def tenant_workflow_architect_patch(body: ArchitectPatchIn, request: Request):
    from pydantic import ValidationError as PydanticValidationError

    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import patch_workflow_plan
    from src.platform.workflows.architect_observability import PlanHashMismatch

    ctx = require_permission(request, "workflows:create")
    try:
        return await patch_workflow_plan(
            ctx.organization_id,
            body.plan,
            body.instruction.strip(),
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
            model=body.model,
            session_id=body.session_id,
            plan_hash_value=body.plan_hash,
            actor_id=ctx.user_id,
        )
    except PlanHashMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except (PydanticValidationError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post(
    "/architect/draft",
    summary="Workflow Architect: guardar borrador (re-valida plan y grafo en el servidor)",
)
async def tenant_workflow_architect_draft(body: ArchitectDraftIn, request: Request):
    from pydantic import ValidationError as PydanticValidationError

    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.architect import save_architect_draft
    from src.platform.workflows.architect_observability import (
        ArchitectBlocked,
        PlanHashMismatch,
    )
    from src.platform.workflows.capability_registry import CapabilitySnapshotStale

    ctx = require_permission(request, "workflows:create")
    ws_id = await _workspace_id(request)
    if body.workspace_id:
        try:
            ws_id = UUID(body.workspace_id)
        except ValueError as exc:
            raise HTTPException(400, "workspace_id inválido") from exc
    try:
        return await save_architect_draft(
            ctx.organization_id,
            body.plan,
            workspace_id=ws_id,
            permissions=ctx.permissions,
            name=body.name,
            description=body.description,
            editor_state=body.editor_state,
            session_id=body.session_id,
            plan_hash_value=body.plan_hash,
            capability_snapshot_hash=body.capability_snapshot_hash,
            source=body.source,
            actor_id=ctx.user_id,
        )
    except PlanHashMismatch as exc:
        raise HTTPException(409, str(exc)) from exc
    except CapabilitySnapshotStale as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error_code": "CAPABILITY_SNAPSHOT_STALE",
                "message": str(exc),
                "changed_refs": exc.changed_refs,
                "reason": exc.reason,
            },
        )
    except ArchitectBlocked as exc:
        return JSONResponse(status_code=422, content=exc.payload())
    except (PydanticValidationError, ValueError) as exc:
        raise HTTPException(400, f"plan inválido: {exc}") from exc


@router.post("/{workflow_id}/patch/preview", summary="Editar con IA: propuesta de diff")
async def tenant_workflow_patch_preview(workflow_id: str, body: PatchPreviewIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.patches import propose_patch

    ctx = require_permission(request, "workflows:update")
    try:
        result = await propose_patch(ctx.organization_id, UUID(workflow_id), body.prompt.strip())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post("/{workflow_id}/patch/apply", summary="Editar con IA: aplicar diff confirmado")
async def tenant_workflow_patch_apply(workflow_id: str, body: PatchApplyIn, request: Request):
    from pydantic import ValidationError as PydanticValidationError

    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.patches import apply_workflow_patch

    ctx = require_permission(request, "workflows:update")
    try:
        result = await apply_workflow_patch(
            ctx.organization_id,
            UUID(workflow_id),
            body.patch,
            base_graph_hash=body.base_graph_hash,
        )
    except (PydanticValidationError, ValueError) as exc:
        raise HTTPException(400, f"patch inválido: {exc}") from exc
    if result is None:
        raise HTTPException(404, "Workflow not found")
    if result.get("status") == "conflict":
        raise HTTPException(409, result.get("message") or "El flujo cambió")
    if result.get("status") == "invalid":
        raise HTTPException(422, result.get("issues") or "El cambio no es válido")
    return result


@router.get("/event-catalog", summary="Catálogo de eventos en lenguaje de negocio")
async def tenant_workflow_event_catalog(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.event_registry import catalog_payload

    require_permission(request, "workflows:read")
    return catalog_payload()


@router.get("/watchers", summary="Data watchers del tenant")
async def tenant_workflow_watchers(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import list_watchers

    ctx = require_permission(request, "workflows:read")
    return {"watchers": await list_watchers(ctx.organization_id, await _workspace_id(request))}


@router.post("/watchers", summary="Crear data watcher")
async def tenant_workflow_watcher_create(body: WatcherIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import WatcherDefinition, WatcherError, create_watcher

    ctx = require_permission(request, "workflows:create")
    try:
        payload = body.model_dump(mode="json")
        if not payload.get("source_id"):
            payload.pop("source_id", None)
        definition = WatcherDefinition.model_validate(payload)
        return await create_watcher(
            ctx.organization_id,
            definition,
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
        )
    except WatcherError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/watchers/{watcher_id}", summary="Detalle del watcher")
async def tenant_workflow_watcher_detail(watcher_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import get_watcher

    ctx = require_permission(request, "workflows:read")
    watcher = await get_watcher(ctx.organization_id, UUID(watcher_id))
    if watcher is None:
        raise HTTPException(404, "Watcher not found")
    return watcher


@router.patch("/watchers/{watcher_id}", summary="Actualizar watcher (pausa, intervalo, condición)")
async def tenant_workflow_watcher_update(watcher_id: str, body: WatcherPatchIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import WatcherError, update_watcher

    ctx = require_permission(request, "workflows:update")
    try:
        result = await update_watcher(
            ctx.organization_id, UUID(watcher_id), body.model_dump(exclude_unset=True)
        )
    except WatcherError as exc:
        raise HTTPException(422, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Watcher not found")
    return result


@router.delete("/watchers/{watcher_id}", summary="Eliminar watcher")
async def tenant_workflow_watcher_delete(watcher_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import delete_watcher

    ctx = require_permission(request, "workflows:delete")
    if not await delete_watcher(ctx.organization_id, UUID(watcher_id)):
        raise HTTPException(404, "Watcher not found")
    return {"deleted": True}


@router.post("/watchers/{watcher_id}/check", summary="Check manual del watcher")
async def tenant_workflow_watcher_check(watcher_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import check_watcher

    ctx = require_permission(request, "workflows:run")
    outcome = await check_watcher(ctx.organization_id, UUID(watcher_id), force=True)
    if outcome is None:
        raise HTTPException(404, "Watcher not found")
    return outcome.to_dict()


@router.get("/watchers/{watcher_id}/state", summary="Estado incremental del watcher")
async def tenant_workflow_watcher_state(watcher_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.watchers import get_watcher_state

    ctx = require_permission(request, "workflows:read")
    state = await get_watcher_state(ctx.organization_id, UUID(watcher_id))
    if state is None:
        raise HTTPException(404, "Watcher not found")
    return state


@router.get("/templates", summary="Plantillas de workflows")
async def tenant_workflow_templates(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_templates

    ctx = require_permission(request, "workflows:read")
    return await list_templates()


@router.post("/templates/{slug}/install", summary="Crear desde plantilla")
async def tenant_workflow_template_install(slug: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import create_from_template

    ctx = require_permission(request, "workflows:create")
    try:
        return await create_from_template(
            ctx.organization_id, slug, workspace_id=await _workspace_id(request)
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/triggers", summary="Triggers de eventos del workspace")
async def tenant_workflow_event_triggers(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.events import list_event_triggers

    ctx = require_permission(request, "workflow_events:subscribe")
    return await list_event_triggers(ctx.organization_id, await _workspace_id(request))


@router.post("/triggers", summary="Suscribir workflow a un evento")
async def tenant_workflow_event_trigger_create(body: TriggerIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.events import create_event_trigger

    ctx = require_permission(request, "workflow_events:subscribe")
    ws_id = await _workspace_id(request) if not body.workspace_id else UUID(body.workspace_id)
    try:
        return await create_event_trigger(
            ctx.organization_id,
            UUID(body.workflow_id),
            ws_id,
            body.event_type,
            body.filters,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/triggers/{trigger_id}", summary="Eliminar trigger de evento")
async def tenant_workflow_event_trigger_delete(trigger_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.events import delete_event_trigger

    ctx = require_permission(request, "workflow_events:subscribe")
    if not await delete_event_trigger(ctx.organization_id, UUID(trigger_id)):
        raise HTTPException(404, "Trigger not found")
    return {"deleted": True}


@router.get("/runs/{run_id}", summary="Detalle del run con pasos")
async def tenant_workflow_run_detail(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import run_detail

    ctx = require_permission(request, "workflow_runs:read")
    result = await run_detail(ctx.organization_id, UUID(run_id))
    if result is None:
        raise HTTPException(404, "Run not found")
    return result


@router.get("/runs/{run_id}/approvals", summary="Aprobaciones del run")
async def tenant_workflow_run_approvals(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_approvals

    ctx = require_permission(request, "workflow_runs:read")
    return await list_approvals(
        ctx.organization_id,
        UUID(run_id),
        workspace_id=await _workspace_id(request),
    )


@router.post(
    "/runs/{run_id}/approvals/{approval_id}/decide", summary="Decidir aprobación humana"
)
async def tenant_workflow_approval_decide(
    run_id: str, approval_id: str, body: ApprovalIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import decide_approval

    ctx = require_permission(request, "workflow_approvals:approve")
    try:
        result = await decide_approval(
            ctx.organization_id,
            UUID(approval_id),
            body.decision,
            ctx.user_id,
            body.comment,
            workspace_id=await _workspace_id(request),
            allow_owner_self_approval=ctx.is_organization_admin(),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Approval not found")
    if result.get("status") == "forbidden" and result.get("error") == "self_approval":
        raise HTTPException(
            403,
            detail={
                "error_code": "self_approval_forbidden",
                "message": "Quien solicitó la aprobación no puede aprobarla.",
            },
        )
    return result


# ---------------------------------------------------------------------------
# Workflows durables: instancias (procesos de negocio vivos)
# ---------------------------------------------------------------------------
class InstanceStartIn(BaseModel):
    payload: dict = Field(default_factory=dict)
    conversation_id: UUID | None = None
    participant_id: str | None = Field(default=None, max_length=160)
    business_key: str | None = Field(default=None, max_length=200)
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class InstanceSignalIn(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=120)
    correlation: dict = Field(default_factory=dict)
    payload: dict = Field(default_factory=dict)
    external_event_id: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=200)


@router.get("/instances", summary="Instancias durables del tenant")
async def tenant_workflow_instances_list(
    request: Request,
    workflow_id: str | None = None,
    conversation_id: str | None = None,
    business_key: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import list_instances

    ctx = require_permission(request, "workflow_runs:read")
    from src.platform.workflows.operations import operational_status

    result = await list_instances(
        ctx.organization_id,
        workflow_id=UUID(workflow_id) if workflow_id else None,
        conversation_id=UUID(conversation_id) if conversation_id else None,
        business_key=business_key,
        status=status,
        workspace_id=await _workspace_id(request),
        limit=limit,
        offset=offset,
    )
    for item in result.get("instances") or []:
        item["view_status"] = operational_status(item)
    return result


@router.get("/instances/{instance_id}", summary="Detalle de la instancia durable")
async def tenant_workflow_instance_detail(instance_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import get_instance

    ctx = require_permission(request, "workflow_runs:read")
    result = await get_instance(
        ctx.organization_id,
        UUID(instance_id),
        workspace_id=await _workspace_id(request),
    )
    if result is None:
        raise HTTPException(404, "Instance not found")
    # El estado durable es visible (sin secretos: nunca se guardan aquí).
    return result


@router.get("/instances/{instance_id}/timeline", summary="Timeline: runs, señales y eventos")
async def tenant_workflow_instance_timeline(instance_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import get_instance, instance_timeline

    ctx = require_permission(request, "workflow_runs:read")
    instance = await get_instance(
        ctx.organization_id,
        UUID(instance_id),
        workspace_id=await _workspace_id(request),
    )
    if instance is None:
        raise HTTPException(404, "Instance not found")
    timeline = await instance_timeline(ctx.organization_id, UUID(instance_id))
    from src.platform.workflows.operations import operational_status, project_business_timeline

    instance["view_status"] = operational_status(instance)
    return {
        "instance": instance,
        **timeline,
        "business_timeline": project_business_timeline(timeline),
    }


@router.post("/instances/{instance_id}/signal", summary="Enviar señal a la instancia")
async def tenant_workflow_instance_signal(
    instance_id: str, body: InstanceSignalIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import signal_workflow_instance

    ctx = require_permission(request, "workflows:run")
    from src.platform.workflows.instances import get_instance

    workspace_id = await _workspace_id(request)
    if (
        await get_instance(
            ctx.organization_id, UUID(instance_id), workspace_id=workspace_id
        )
        is None
    ):
        # Una instancia de otro tenant/workspace no existe para este caller:
        # la señal no se acepta (nunca se encola para un proceso ajeno).
        raise HTTPException(404, "instancia no encontrada")
    result = await signal_workflow_instance(
        organization_id=ctx.organization_id,
        event_type=body.event_type,
        correlation=body.correlation,
        payload=body.payload,
        external_event_id=body.external_event_id,
        idempotency_key=body.idempotency_key,
        source="api",
        instance_id=UUID(instance_id),
        workspace_id=workspace_id,
    )
    if result.get("status") == "not_found":
        raise HTTPException(404, "instancia no encontrada")
    return result


@router.post("/instances/{instance_id}/cancel", summary="Cancelar la instancia")
async def tenant_workflow_instance_cancel(instance_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import cancel_instance

    ctx = require_permission(request, "workflows:run")
    from src.platform.workflows.instances import get_instance

    if (
        await get_instance(
            ctx.organization_id,
            UUID(instance_id),
            workspace_id=await _workspace_id(request),
        )
        is None
    ):
        raise HTTPException(404, "instancia no encontrada")
    return await cancel_instance(ctx.organization_id, UUID(instance_id), reason="api")


@router.post("/instances/{instance_id}/suspend", summary="Suspender la instancia")
async def tenant_workflow_instance_suspend(instance_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import suspend_instance

    ctx = require_permission(request, "workflows:run")
    from src.platform.workflows.instances import get_instance

    if (
        await get_instance(
            ctx.organization_id,
            UUID(instance_id),
            workspace_id=await _workspace_id(request),
        )
        is None
    ):
        raise HTTPException(404, "instancia no encontrada")
    return await suspend_instance(ctx.organization_id, UUID(instance_id))


@router.post("/instances/{instance_id}/resume", summary="Reanudar instancia suspendida")
async def tenant_workflow_instance_resume(instance_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.instances import resume_suspended_instance

    ctx = require_permission(request, "workflows:run")
    from src.platform.workflows.instances import get_instance

    if (
        await get_instance(
            ctx.organization_id,
            UUID(instance_id),
            workspace_id=await _workspace_id(request),
        )
        is None
    ):
        raise HTTPException(404, "instancia no encontrada")
    return await resume_suspended_instance(ctx.organization_id, UUID(instance_id))


# ---------------------------------------------------------------------------
# Capability bindings + paquetes portables (import/export)
# ---------------------------------------------------------------------------
class BindingIn(BaseModel):
    #: Provider kinds del binder (fuente única: `bindings.PROVIDER_KINDS`).
    provider_kind: str = Field(
        ...,
        pattern="^(managed_db|connected_db|marketplace_action|semantic_query|rest_api|erp|custom|commerce|payment_provider|conversation)$",
    )
    config: dict = Field(default_factory=dict)
    contract_input_schema: dict = Field(default_factory=dict)
    contract_output_schema: dict = Field(default_factory=dict)
    credential_ref: str | None = Field(default=None, max_length=160)
    workspace_id: str | None = None


class PackageIn(BaseModel):
    package: dict = Field(...)


@router.get("/capability-bindings", summary="Bindings de capacidades del tenant")
async def tenant_capability_bindings(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.bindings import list_bindings

    ctx = require_permission(request, "workflows:read")
    return await list_bindings(ctx.organization_id, await _workspace_id(request))


@router.put("/capability-bindings/{capability_ref}", summary="Crear/actualizar binding")
async def tenant_capability_binding_upsert(
    capability_ref: str, body: BindingIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.bindings import upsert_binding

    ctx = require_permission(request, "workflows:update")
    try:
        result = await upsert_binding(
            ctx.organization_id,
            capability_ref,
            body.provider_kind,
            config=body.config,
            workspace_id=UUID(body.workspace_id) if body.workspace_id else None,
            credential_ref=body.credential_ref,
            contract_input_schema=body.contract_input_schema,
            contract_output_schema=body.contract_output_schema,
            created_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@router.delete("/capability-bindings/{binding_id}", summary="Desactivar binding")
async def tenant_capability_binding_delete(binding_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.bindings import delete_binding

    ctx = require_permission(request, "workflows:update")
    if not await delete_binding(ctx.organization_id, UUID(binding_id)):
        raise HTTPException(404, "Binding not found")
    return {"deleted": True}


@router.post("/import/inspect", summary="Inspeccionar paquete (sin persistir)")
async def tenant_workflow_import_inspect(body: PackageIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.packages import inspect_package

    ctx = require_permission(request, "workflows:create")
    return await inspect_package(
        ctx.organization_id,
        body.package,
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
    )


@router.post("/import", summary="Importar paquete (solo draft)")
async def tenant_workflow_import(body: PackageIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.packages import import_workflow_package

    ctx = require_permission(request, "workflows:create")
    try:
        return await import_workflow_package(
            ctx.organization_id,
            body.package,
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
            permissions=ctx.permissions,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


# ---------------------------------------------------------------------------
# Rutas con parámetro workflow_id
# ---------------------------------------------------------------------------
class WorkflowTestIn(BaseModel):
    requested_level: str = Field(default="simulation", max_length=20)
    scenario: dict = Field(default_factory=dict)


@router.post(
    "/{workflow_id}/test",
    summary="Workflow Test Studio: nivel decidido por el servidor y reporte persistido",
)
async def tenant_workflow_test(
    workflow_id: str, body: WorkflowTestIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.test_studio import execute_workflow_test

    ctx = require_permission(request, "workflows:run")
    workflow = await get_workflow(ctx.organization_id, UUID(workflow_id))
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    request_ws = await _workspace_id(request)
    workflow_ws = workflow.get("workspace_id")
    if request_ws is not None and workflow_ws and str(workflow_ws) != str(request_ws):
        raise HTTPException(404, "Workflow not found")
    try:
        return await execute_workflow_test(
            organization_id=ctx.organization_id,
            workspace_id=request_ws,
            workflow=workflow,
            workflow_id=UUID(workflow_id),
            requested_level=body.requested_level,
            scenario_draft=body.scenario,
            permissions=ctx.permissions,
            created_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get(
    "/{workflow_id}/test-reports",
    summary="Reportes del Workflow Test Studio",
)
async def tenant_workflow_test_reports(
    workflow_id: str, request: Request, limit: int = 50
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.test_studio import list_test_reports

    ctx = require_permission(request, "workflow_runs:read")
    return await list_test_reports(
        ctx.organization_id,
        UUID(workflow_id),
        workspace_id=await _workspace_id(request),
        limit=limit,
    )


@router.get(
    "/operations/queue",
    summary="Cola de operación: fallos, expirados y esperas humanas",
)
async def tenant_workflow_operations_queue(request: Request, limit: int = 100):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.operations import list_operations_queue

    ctx = require_permission(request, "workflow_runs:read")
    return await list_operations_queue(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        limit=limit,
    )


@router.get(
    "/capabilities/discover",
    summary="Descubrir capacidades disponibles e instaladas (catálogo único)",
)
async def tenant_workflow_capabilities_discover(
    request: Request,
    q: str | None = None,
    limit: int = 50,
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import discover_capabilities

    ctx = require_permission(request, "workflows:read")
    return await discover_capabilities(
        ctx.organization_id,
        await _workspace_id(request),
        query=q or "",
        limit=limit,
    )


@router.get(
    "/subflows/library",
    summary="Biblioteca de subflujos publicados (definición versionada)",
)
async def tenant_subflow_library(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.composition import subflow_library

    require_permission(request, "workflows:read")
    return {"subflows": subflow_library(), "executor": "execute_graph"}


@router.get(
    "/{workflow_id}/data-mapping",
    summary="Plano de datos y mapeo declarativo del workflow",
)
async def tenant_workflow_data_mapping(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.data_mapper import (
        data_plane_inventory,
        mapping_errors,
    )
    from src.platform.workflows.engine import get_workflow

    ctx = require_permission(request, "workflows:read")
    result = await get_workflow(ctx.organization_id, UUID(workflow_id))
    if result is None:
        raise HTTPException(404, "Workflow not found")
    request_ws = await _workspace_id(request)
    if request_ws is not None and result.get("workspace_id") not in (None, str(request_ws)):
        raise HTTPException(404, "Workflow not found")
    graph = result.get("graph") if isinstance(result.get("graph"), dict) else {}
    mapping = ((graph.get("metadata") or {}).get("data_mapping")) or {}
    return {
        "workflow_id": str(workflow_id),
        "inventory": data_plane_inventory(),
        "mapping": mapping,
        "errors": mapping_errors(mapping) if mapping else [],
    }


@router.get("/{workflow_id}", summary="Detalle del workflow")
async def tenant_workflow_detail(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import get_workflow

    ctx = require_permission(request, "workflows:read")
    result = await get_workflow(ctx.organization_id, UUID(workflow_id))
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.patch("/{workflow_id}", summary="Actualizar workflow")
async def tenant_workflow_update(workflow_id: str, body: WorkflowUpdateIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import update_workflow

    ctx = require_permission(request, "workflows:update")
    try:
        result = await update_workflow(
            ctx.organization_id,
            UUID(workflow_id),
            body.name,
            body.description,
            body.trigger_config,
            body.steps,
            body.editor_state,
            graph=body.graph,
            workflow_version=body.workflow_version,
            trigger_type=body.trigger_type,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.delete("/{workflow_id}", summary="Eliminar workflow")
async def tenant_workflow_delete(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import delete_workflow

    ctx = require_permission(request, "workflows:delete")
    if not await delete_workflow(ctx.organization_id, UUID(workflow_id)):
        raise HTTPException(404, "Workflow not found")
    return {"deleted": True}


@router.post("/{workflow_id}/activate", summary="Activar workflow")
async def tenant_workflow_activate(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import ReleaseDenied, activate_workflow

    ctx = require_permission(request, "workflows:activate")
    try:
        result = await activate_workflow(
            ctx.organization_id,
            UUID(workflow_id),
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
        )
    except ReleaseDenied as exc:
        raise HTTPException(
            409,
            {"code": "release_blocked", "message": str(exc), **exc.decision},
        ) from exc
    if not result:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post("/{workflow_id}/pause", summary="Pausar workflow")
async def tenant_workflow_pause(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import set_workflow_status

    ctx = require_permission(request, "workflows:activate")
    result = await set_workflow_status(ctx.organization_id, UUID(workflow_id), "paused")
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post("/{workflow_id}/run", summary="Ejecutar workflow (también dry-run y parcial)")
async def tenant_workflow_run(workflow_id: str, body: RunIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.ingress import route_ingress

    ctx = require_permission(request, "workflows:run")
    if body.simulate or body.run_mode != "full":
        from src.platform.workflows.engine import WorkflowAccessError, run_workflow

        try:
            result = await run_workflow(
                UUID(workflow_id),
                body.payload,
                trigger="manual",
                organization_id=ctx.organization_id,
                workspace_id=await _workspace_id(request),
                actor_type="user",
                actor_id=ctx.user_id,
                permissions=ctx.permissions,
                simulate=True,
                run_mode=body.run_mode,
                target_node_id=body.target_node_id,
                source_run_id=UUID(body.source_run_id) if body.source_run_id else None,
            )
        except WorkflowAccessError as exc:
            raise HTTPException(403, str(exc)) from exc
    else:
        result = await route_ingress(
            workflow_id=UUID(workflow_id),
            organization_id=ctx.organization_id,
            trigger="manual",
            payload=body.payload or {},
            workspace_id=await _workspace_id(request),
            actor_type="user",
            actor_id=ctx.user_id,
            permissions=ctx.permissions,
            require_active=False,
        )
        if result.get("error") == "not_found":
            raise HTTPException(404, "Workflow not found")
        if result.get("status_code") == 403:
            raise HTTPException(403, result.get("error") or "forbidden")
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post(
    "/{workflow_id}/instances",
    summary="Iniciar proceso durable (WorkflowInstance)",
)
async def tenant_workflow_instance_start(workflow_id: str, body: InstanceStartIn, request: Request):
    """Arranca un proceso de negocio de larga duración: la definición queda
    congelada y la instancia sobrevive reinicios, waits y días de espera."""
    from datetime import datetime, timedelta, timezone

    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import WorkflowAccessError
    from src.platform.workflows.instances import start_workflow_instance

    ctx = require_permission(request, "workflows:run")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(hours=int(body.expires_in_hours))
        if body.expires_in_hours
        else None
    )
    try:
        result = await start_workflow_instance(
            workflow_id=UUID(workflow_id),
            organization_id=ctx.organization_id,
            workspace_id=await _workspace_id(request),
            trigger="manual",
            payload=body.payload,
            conversation_id=body.conversation_id,
            participant_id=body.participant_id,
            business_key=body.business_key,
            ingress_key=request.headers.get("idempotency-key"),
            actor_type="user",
            actor_id=ctx.user_id,
            permissions=ctx.permissions,
            expires_at=expires_at,
        )
    except WorkflowAccessError as exc:
        raise HTTPException(403, str(exc)) from exc
    if result is None or result.get("status") == "failed":
        raise HTTPException(404, (result or {}).get("error") or "Workflow not found")
    return result


@router.get("/{workflow_id}/runs", summary="Runs del workflow")
async def tenant_workflow_runs(workflow_id: str, request: Request, limit: int = 50):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_runs

    ctx = require_permission(request, "workflow_runs:read")
    return await list_runs(ctx.organization_id, UUID(workflow_id), limit)


@router.get("/{workflow_id}/export", summary="Exportar workflow (zent.workflow.package/v1)")
async def tenant_workflow_export(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.packages import export_workflow_package

    ctx = require_permission(request, "workflows:read")
    package = await export_workflow_package(ctx.organization_id, UUID(workflow_id))
    if package is None:
        raise HTTPException(404, "Workflow not found")
    return package


@router.get(
    "/{workflow_id}/sample-outputs",
    summary="Últimos outputs reales por nodo (Data Picker / Live Preview)",
)
async def tenant_workflow_sample_outputs(workflow_id: str, request: Request, run_id: str | None = None):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.samples import latest_node_outputs

    ctx = require_permission(request, "workflow_runs:read")
    result = await latest_node_outputs(
        ctx.organization_id,
        UUID(workflow_id),
        run_id=UUID(run_id) if run_id else None,
    )
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get(
    "/{workflow_id}/data-catalog",
    summary="Datos disponibles del grafo para el Data Picker",
)
async def tenant_workflow_data_catalog(workflow_id: str, request: Request, run_id: str | None = None):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.data_catalog import workflow_data_catalog

    ctx = require_permission(request, "workflows:read")
    result = await workflow_data_catalog(
        ctx.organization_id,
        UUID(workflow_id),
        workspace_id=await _workspace_id(request),
        run_id=UUID(run_id) if run_id else None,
    )
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/{workflow_id}/readiness", summary="Checklist de negocio antes de publicar")
async def tenant_workflow_readiness(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.readiness import workflow_readiness

    ctx = require_permission(request, "workflows:read")
    result = await workflow_readiness(
        ctx.organization_id, UUID(workflow_id), workspace_id=await _workspace_id(request)
    )
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/{workflow_id}/summary", summary="Resumen legible del workflow")
async def tenant_workflow_summary(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.readiness import workflow_summary

    ctx = require_permission(request, "workflows:read")
    result = await workflow_summary(ctx.organization_id, UUID(workflow_id))
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/{workflow_id}/pinned-data", summary="Datos fijados para pruebas")
async def tenant_workflow_pinned_list(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.pinned import list_pinned

    ctx = require_permission(request, "workflows:read")
    result = await list_pinned(ctx.organization_id, UUID(workflow_id))
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.put("/{workflow_id}/pinned-data/{node_id}", summary="Fijar datos de un nodo para pruebas")
async def tenant_workflow_pinned_upsert(workflow_id: str, node_id: str, body: PinnedDataIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import get_workflow
    from src.platform.workflows.pinned import upsert_pinned

    ctx = require_permission(request, "workflows:update")
    workflow = await get_workflow(ctx.organization_id, UUID(workflow_id))
    if workflow is None:
        raise HTTPException(404, "Workflow not found")
    graph = workflow.get("graph") or {}
    node_ids = {str(node.get("id")) for node in graph.get("nodes") or [] if isinstance(node, dict)}
    if node_ids and node_id not in node_ids:
        raise HTTPException(422, f"nodo no existe en el flujo: {node_id}")
    result = await upsert_pinned(
        ctx.organization_id, UUID(workflow_id), node_id, body.output, created_by=ctx.user_id
    )
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.delete("/{workflow_id}/pinned-data/{node_id}", summary="Quitar datos fijados")
async def tenant_workflow_pinned_delete(workflow_id: str, node_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.pinned import delete_pinned

    ctx = require_permission(request, "workflows:update")
    if not await delete_pinned(ctx.organization_id, UUID(workflow_id), node_id):
        raise HTTPException(404, "Pinned data not found")
    return {"deleted": True}


@router.post("/{workflow_id}/hook-secret/rotate", summary="Rotar secret inbound")
async def tenant_workflow_rotate_hook_secret(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import rotate_hook_secret

    ctx = require_permission(request, "workflow_secrets:manage")
    result = await rotate_hook_secret(ctx.organization_id, UUID(workflow_id))
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


# ---------------------------------------------------------------------------
# Versiones publicables (snapshot / promote / rollback)
# ---------------------------------------------------------------------------
@router.get("/{workflow_id}/versions", summary="Versiones del workflow")
async def tenant_workflow_versions(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.versions import list_versions

    ctx = require_permission(request, "workflows:read")
    return await list_versions(ctx.organization_id, UUID(workflow_id))


@router.post("/{workflow_id}/versions", summary="Crear snapshot del workflow")
async def tenant_workflow_version_create(
    workflow_id: str, request: Request, body: VersionIn | None = None
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.versions import create_version

    ctx = require_permission(request, "workflows:update")
    try:
        result = await create_version(
            ctx.organization_id,
            UUID(workflow_id),
            notes=body.notes if body else None,
            created_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post("/{workflow_id}/versions/{version_id}/promote", summary="Promover versión")
async def tenant_workflow_version_promote(
    workflow_id: str, version_id: str, body: PromoteIn, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import ReleaseDenied
    from src.platform.workflows.versions import promote_version

    ctx = require_permission(request, "workflows:activate")
    try:
        result = await promote_version(
            ctx.organization_id,
            UUID(workflow_id),
            UUID(version_id),
            body.status,
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
        )
    except ReleaseDenied as exc:
        raise HTTPException(
            409,
            {"code": "release_blocked", "message": str(exc), **exc.decision},
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Version not found")
    return result


@router.post(
    "/{workflow_id}/versions/{version_id}/restore", summary="Restaurar versión (rollback)"
)
async def tenant_workflow_version_restore(
    workflow_id: str, version_id: str, request: Request
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import ReleaseDenied
    from src.platform.workflows.versions import restore_version

    ctx = require_permission(request, "workflows:update")
    try:
        result = await restore_version(
            ctx.organization_id,
            UUID(workflow_id),
            UUID(version_id),
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
        )
    except ReleaseDenied as exc:
        raise HTTPException(
            409,
            {"code": "release_blocked", "message": str(exc), **exc.decision},
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Version not found")
    return result


@router.post("/{workflow_id}/publish", summary="Publicar workflow (snapshot + activar)")
async def tenant_workflow_publish(
    workflow_id: str, request: Request, body: VersionIn | None = None
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import ReleaseDenied
    from src.platform.workflows.versions import publish_workflow

    ctx = require_permission(request, "workflows:activate")
    try:
        result = await publish_workflow(
            ctx.organization_id,
            UUID(workflow_id),
            notes=body.notes if body else None,
            created_by=ctx.user_id,
            confirm_architect_draft=bool(body.confirm_architect_draft) if body else False,
            permissions=ctx.permissions,
            workspace_id=await _workspace_id(request),
        )
    except ReleaseDenied as exc:
        raise HTTPException(
            409,
            {"code": "release_blocked", "message": str(exc), **exc.decision},
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/{workflow_id}/release-gate", summary="Estado del gate de release")
async def tenant_workflow_release_gate(
    workflow_id: str, request: Request, action: str = "publish"
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import evaluate_release

    ctx = require_permission(request, "workflows:read")
    if action not in ("publish", "activate", "promote", "restore"):
        raise HTTPException(400, "acción inválida")
    decision = await evaluate_release(
        ctx.organization_id,
        UUID(workflow_id),
        action=action,
        workspace_id=await _workspace_id(request),
        permissions=ctx.permissions,
    )
    return decision.to_dict()


@router.post("/{workflow_id}/certifications", summary="Emitir certificado de release")
async def tenant_workflow_certify(
    workflow_id: str, request: Request, body: CertificationIn | None = None
):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import (
        CertificateError,
        issue_certificate,
    )

    ctx = require_permission(request, "workflows:activate")
    payload = body or CertificationIn()
    try:
        certificate = await issue_certificate(
            ctx.organization_id,
            UUID(workflow_id),
            level=payload.level,
            workspace_id=await _workspace_id(request),
            permissions=ctx.permissions,
            scenarios=payload.scenarios,
            issued_by=ctx.user_id,
            expires_in_days=payload.expires_in_days,
        )
    except CertificateError as exc:
        raise HTTPException(409, str(exc)) from exc
    return certificate


@router.get("/{workflow_id}/certifications", summary="Certificados del workflow")
async def tenant_workflow_certificates(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.release_policy import list_certificates

    ctx = require_permission(request, "workflows:read")
    return await list_certificates(ctx.organization_id, UUID(workflow_id))


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    trigger_type: str = Field(default="webhook", pattern="^(webhook|schedule|event)$")
    trigger_config: dict | None = None
    steps: list[dict] = Field(default_factory=list)
    editor_state: dict | None = None
    graph: dict | None = None
    workspace_id: str | None = None
    workflow_version: int | None = None


class WorkflowUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = None
    trigger_type: str | None = Field(default=None, pattern="^(webhook|schedule|event)$")
    trigger_config: dict | None = None
    steps: list[dict] | None = None
    editor_state: dict | None = None
    graph: dict | None = None
    workflow_version: int | None = None


class RunIn(BaseModel):
    payload: dict | None = None
    simulate: bool = False
    run_mode: str = Field(default="full", pattern="^(full|node|until_node|from_node)$")
    target_node_id: str | None = Field(default=None, max_length=80)
    source_run_id: str | None = None


class PinnedDataIn(BaseModel):
    output: dict


class VersionIn(BaseModel):
    notes: str | None = Field(default=None, max_length=500)
    confirm_architect_draft: bool = False


class CertificationIn(BaseModel):
    level: str = Field(default="design", pattern="^(design|simulation)$")
    scenarios: list[dict] = Field(default_factory=list, max_length=20)
    expires_in_days: int = Field(default=7, ge=1, le=90)


class PromoteIn(BaseModel):
    status: str = Field(pattern="^(draft|ready|production|archived)$")


class ApprovalIn(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str | None = None


class TriggerIn(BaseModel):
    workflow_id: str
    event_type: str = Field(min_length=3, max_length=120)
    filters: dict | None = None
    workspace_id: str | None = None


class ValidateIn(BaseModel):
    steps: list[dict] | None = None
    graph: dict | None = None
    trigger_type: str | None = None
    trigger_config: dict | None = None


class CopilotIntentIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)


class CopilotCompileIn(BaseModel):
    plan: dict


class ArchitectPlanIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)
    model: str | None = Field(default=None, max_length=120)
    session_id: str | None = Field(default=None, max_length=80)
    agent_id: str | None = Field(default=None, max_length=64)


class ArchitectAgenticPlanIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=4000)
    model: str | None = Field(default=None, max_length=120)
    session_id: str | None = Field(default=None, max_length=80)
    clarification_history: list[Annotated[str, Field(max_length=2000)]] = Field(
        default_factory=list, max_length=8
    )


class ArchitectResourceResolveIn(BaseModel):
    need: str = Field(min_length=3, max_length=500)
    required_fields: list[str | dict] = Field(default_factory=list, max_length=30)
    concepts: list[str] = Field(default_factory=list, max_length=10)
    domain: str = Field(default="general", max_length=80)
    kinds: list[str] = Field(default_factory=list, max_length=10)
    capability_refs: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=10, ge=1, le=20)


class ArchitectSimulateIn(BaseModel):
    plan: dict
    scenarios: list[Any] = Field(min_length=1, max_length=20)


class ArchitectSimulateRepairIn(ArchitectSimulateIn):
    model: str | None = Field(default=None, max_length=120)
    session_id: str | None = Field(default=None, max_length=80)
    max_repairs: int = Field(default=2, ge=0, le=3)


class DesignSessionCreateIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=12000)
    title: str | None = Field(default=None, max_length=200)
    model: str | None = Field(default=None, max_length=120)
    agent_id: str | None = Field(default=None, max_length=64)


class DesignSessionMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=0)
    model: str | None = Field(default=None, max_length=120)
    agent_id: str | None = Field(default=None, max_length=64)


class DesignSessionPatchPreviewIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=0)
    model: str | None = Field(default=None, max_length=120)


class DesignSessionPatchApplyIn(DesignSessionPatchPreviewIn):
    patch: dict[str, Any]
    source: str = Field(default="llm", pattern="^(llm|heuristics)$")


class DesignSessionRevisionIn(BaseModel):
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=0)
    instruction: str | None = Field(default=None, max_length=500)


class DesignSessionCloseIn(BaseModel):
    expected_revision: int = Field(ge=0)


class DesignSessionSimulateIn(BaseModel):
    scenarios: list[Any] = Field(min_length=1, max_length=20)
    expected_revision: int = Field(ge=0)


class DesignSessionDraftIn(BaseModel):
    expected_revision: int = Field(ge=0)
    name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    config_level: str = Field(default="simple", pattern="^(simple|guided|advanced)$")


class ArchitectPatchIn(BaseModel):
    plan: dict
    instruction: str = Field(min_length=3, max_length=1000)
    model: str | None = Field(default=None, max_length=120)
    session_id: str | None = Field(default=None, max_length=80)
    plan_hash: str | None = Field(default=None, max_length=64)


class ArchitectDraftIn(BaseModel):
    plan: dict
    plan_hash: str | None = Field(default=None, max_length=64)
    capability_snapshot_hash: str | None = Field(default=None, max_length=64)
    session_id: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    editor_state: dict | None = None
    source: str = Field(default="llm", pattern="^(llm|heuristics)$")
    workspace_id: str | None = None


class PatchPreviewIn(BaseModel):
    prompt: str = Field(min_length=4, max_length=2000)


class PatchApplyIn(BaseModel):
    patch: dict
    base_graph_hash: str | None = Field(default=None, max_length=80)


class WatcherIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    source_id: str | None = None
    strategy: str = Field(
        default="watermark_polling",
        pattern="^(watermark_polling|timestamp_polling|query_watch|application_event|webhook)$",
    )
    entity: str = Field(default="registro", max_length=80)
    schema_name: str | None = Field(default=None, max_length=63)
    table_name: str = Field(min_length=1, max_length=63)
    primary_key: str | None = Field(default=None, max_length=63)
    timestamp_field: str | None = Field(default=None, max_length=63)
    selected_fields: list[str] = Field(default_factory=list, max_length=50)
    condition: dict
    transition_mode: str = Field(default="on_enter", pattern="^(on_change|on_enter|on_exit|while_true)$")
    interval_seconds: int = Field(default=300, ge=60, le=86_400)
    cooldown_seconds: int = Field(default=0, ge=0, le=604_800)
    debounce_seconds: int = Field(default=0, ge=0, le=86_400)
    event_type: str = Field(default="", max_length=160)
    entity_field: str | None = Field(default=None, max_length=63)
    workflow_id: str | None = None
    status: str = Field(default="listening", pattern="^(listening|checking|error|paused)$")


class WatcherPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=600)
    strategy: str | None = Field(
        default=None,
        pattern="^(watermark_polling|timestamp_polling|query_watch|application_event|webhook)$",
    )
    entity: str | None = Field(default=None, max_length=80)
    schema_name: str | None = Field(default=None, max_length=63)
    table_name: str | None = Field(default=None, min_length=1, max_length=63)
    primary_key: str | None = Field(default=None, max_length=63)
    timestamp_field: str | None = Field(default=None, max_length=63)
    selected_fields: list[str] | None = None
    condition: dict | None = None
    transition_mode: str | None = Field(default=None, pattern="^(on_change|on_enter|on_exit|while_true)$")
    interval_seconds: int | None = Field(default=None, ge=60, le=86_400)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=604_800)
    debounce_seconds: int | None = Field(default=None, ge=0, le=86_400)
    event_type: str | None = Field(default=None, max_length=160)
    entity_field: str | None = Field(default=None, max_length=63)
    workflow_id: str | None = None
    status: str | None = Field(default=None, pattern="^(listening|checking|error|paused)$")


# ---------------------------------------------------------------------------
# Phase 33B — Marketplace-native workflow UX (canvas context, costos,
# install inline, recomendaciones, puertos tipados).
# ---------------------------------------------------------------------------
@router.get("/marketplace/context", summary="Contexto de marketplace para el canvas")
async def tenant_workflow_marketplace_context(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import canvas_context

    ctx = require_permission(request, "workflows:read")
    return await canvas_context(ctx.organization_id, await _workspace_id(request))


@router.post("/marketplace/install", summary="Instalar desde el Marketplace global (canvas)")
async def tenant_workflow_marketplace_install(body: InlineInstallIn, request: Request):
    from src.platform.marketplace.runtime import (
        MarketplaceError,
        PurposeRequiredError,
    )
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import install_inline

    ctx = require_permission(request, "workflows:update")
    if not body.product_slug and not body.integration_slug:
        raise HTTPException(422, "product_slug o integration_slug requerido")
    try:
        return await install_inline(
            ctx.organization_id,
            body.integration_slug,
            product_slug=body.product_slug,
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
            purpose=body.purpose,
        )
    except PurposeRequiredError as exc:
        raise HTTPException(
            422,
            "La integración requiere un propósito de uso (datos personales). "
            "Configúralo en Integraciones antes de usarla en workflows.",
        ) from exc
    except MarketplaceError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/marketplace/ports/{action_id}", summary="Puertos tipados de una acción")
async def tenant_workflow_marketplace_ports(action_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import ports_for_action

    require_permission(request, "workflows:read")
    result = await ports_for_action(action_id)
    if result is None:
        raise HTTPException(404, "Acción no encontrada")
    return result


@router.post("/marketplace/recommend", summary="Recomendaciones para el grafo actual")
async def tenant_workflow_marketplace_recommend(body: RecommendIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import recommend_for_graph

    ctx = require_permission(request, "workflows:read")
    return await recommend_for_graph(
        ctx.organization_id, body.graph or {}, await _workspace_id(request)
    )


@router.post("/cost-estimate", summary="Costo estimado por run y mensual")
async def tenant_workflow_cost_estimate(body: EstimateIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import cost_estimate

    ctx = require_permission(request, "workflows:read")
    return await cost_estimate(ctx.organization_id, body.graph or {}, body.trigger_config)


class InlineInstallIn(BaseModel):
    # Compat: integración directa (canvas existente) o producto del catálogo.
    integration_slug: str | None = Field(default=None, min_length=1, max_length=100)
    product_slug: str | None = Field(default=None, min_length=1, max_length=100)
    purpose: str | None = Field(default=None, max_length=80)


class RecommendIn(BaseModel):
    graph: dict | None = None


class EstimateIn(BaseModel):
    graph: dict | None = None
    trigger_config: dict | None = None


public_router = APIRouter(prefix="/api/v1/public/workflows", tags=["Workflows"])


@public_router.post("/{workflow_id}/hook", summary="Disparar workflow por webhook inbound")
async def public_workflow_hook(workflow_id: str, request: Request):
    from src.platform.workflows.engine import run_workflow_from_hook

    secret = request.headers.get("x-zent-workflow-secret") or ""
    secret_in_query = any(k.lower() == "x-zent-workflow-secret" for k in request.query_params)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else body
    idempotency_key = (
        request.headers.get("idempotency-key")
        or request.headers.get("x-zent-event-id")
        or (str(body.get("event_id")) if body.get("event_id") else None)
    )
    external_event_id = (
        request.headers.get("x-zent-event-id")
        or (str(body.get("event_id")) if body.get("event_id") else None)
    )
    try:
        result = await run_workflow_from_hook(
            UUID(workflow_id),
            secret,
            payload,
            idempotency_key=idempotency_key,
            external_event_id=external_event_id,
        )
    except ValueError:
        raise HTTPException(404, "Workflow not found") from None
    if result.get("error") == "not_found":
        raise HTTPException(404, "Workflow not found")
    if result.get("error") == "unauthorized":
        if secret_in_query and not secret:
            raise HTTPException(
                401,
                "Invalid workflow secret. Send it as HTTP header X-Zent-Workflow-Secret, "
                "not as a query parameter.",
            )
        if not secret:
            raise HTTPException(
                401,
                "Invalid workflow secret. Send header X-Zent-Workflow-Secret.",
            )
        raise HTTPException(401, "Invalid workflow secret")
    if result.get("error") == "inactive":
        raise HTTPException(409, "Workflow is not active")
    return result


@public_router.post(
    "/{workflow_id}/instances/signal",
    summary="Señal externa para instancias durables (webhook)",
)
async def public_workflow_instance_signal(workflow_id: str, request: Request):
    """Proveedores externos (pagos, canales) empujan eventos sin sesión: el
    secret del workflow autentica el inbound; el inbox durable deduplica."""
    from src.platform.workflows.instances import signal_instance_from_hook

    secret = request.headers.get("x-zent-workflow-secret") or ""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        result = await signal_instance_from_hook(UUID(workflow_id), secret, body)
    except ValueError:
        raise HTTPException(404, "Workflow not found") from None
    if result.get("error") == "not_found":
        raise HTTPException(404, "Workflow or instance not found")
    if result.get("error") == "unauthorized":
        raise HTTPException(
            401,
            "Invalid workflow secret. Send header X-Zent-Workflow-Secret.",
        )
    if result.get("error") == "inactive":
        raise HTTPException(409, "Workflow is not active")
    if result.get("error") == "missing_event_type":
        raise HTTPException(400, "event_type is required")
    return result
