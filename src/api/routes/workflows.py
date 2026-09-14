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

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
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


@router.post("/copilot/intent", summary="Copiloto: describir qué automatizar → Intent + Plan")
async def tenant_workflow_copilot_intent(body: CopilotIntentIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.copilot_v2 import propose_workflow

    ctx = require_permission(request, "workflows:create")
    try:
        return await propose_workflow(
            ctx.organization_id,
            body.prompt.strip(),
            workspace_id=await _workspace_id(request),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/copilot/compile", summary="Copiloto: WorkflowPlan → WorkflowGraph validado")
async def tenant_workflow_copilot_compile(body: CopilotCompileIn, request: Request):
    from pydantic import ValidationError as PydanticValidationError

    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.copilot_v2 import compile_proposal

    ctx = require_permission(request, "workflows:create")
    try:
        return await compile_proposal(
            ctx.organization_id,
            body.plan,
            workspace_id=await _workspace_id(request),
        )
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
    return await list_approvals(ctx.organization_id, UUID(run_id))


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
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Approval not found")
    return result


# ---------------------------------------------------------------------------
# Rutas con parámetro workflow_id
# ---------------------------------------------------------------------------
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
    from src.platform.workflows.engine import set_workflow_status

    ctx = require_permission(request, "workflows:activate")
    result = await set_workflow_status(ctx.organization_id, UUID(workflow_id), "active")
    if result is None:
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
    from src.platform.workflows.engine import WorkflowAccessError, run_workflow

    ctx = require_permission(request, "workflows:run")
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
            simulate=bool(body.simulate),
            run_mode=body.run_mode,
            target_node_id=body.target_node_id,
            source_run_id=UUID(body.source_run_id) if body.source_run_id else None,
        )
    except WorkflowAccessError as exc:
        raise HTTPException(403, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/{workflow_id}/runs", summary="Runs del workflow")
async def tenant_workflow_runs(workflow_id: str, request: Request, limit: int = 50):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_runs

    ctx = require_permission(request, "workflow_runs:read")
    return await list_runs(ctx.organization_id, UUID(workflow_id), limit)


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
    from src.platform.workflows.versions import promote_version

    ctx = require_permission(request, "workflows:activate")
    try:
        result = await promote_version(
            ctx.organization_id, UUID(workflow_id), UUID(version_id), body.status
        )
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
    from src.platform.workflows.versions import restore_version

    ctx = require_permission(request, "workflows:update")
    try:
        result = await restore_version(
            ctx.organization_id, UUID(workflow_id), UUID(version_id)
        )
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
    from src.platform.workflows.versions import publish_workflow

    ctx = require_permission(request, "workflows:activate")
    try:
        result = await publish_workflow(
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


@router.post("/marketplace/install", summary="Instalar integración inline desde el canvas")
async def tenant_workflow_marketplace_install(body: InlineInstallIn, request: Request):
    from src.platform.marketplace.runtime import (
        MarketplaceError,
        PurposeRequiredError,
    )
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.capabilities import install_inline

    ctx = require_permission(request, "workflows:update")
    try:
        return await install_inline(
            ctx.organization_id,
            body.integration_slug,
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
    integration_slug: str = Field(min_length=1, max_length=100)
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
    try:
        result = await run_workflow_from_hook(UUID(workflow_id), secret, payload)
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
