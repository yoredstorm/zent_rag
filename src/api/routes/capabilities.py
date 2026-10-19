# =============================================================================
# Capability Registry API — descubrimiento/inspección read-only para el planner.
#
# No ejecuta capacidades. Toda consulta se limita por organización, workspace y
# permisos del actor; el binding se devuelve con la config redactada.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from src.infrastructure.observability.logging_config import get_logger
from src.platform.workflows.capability_registry import build_capability_snapshot, search_capabilities
from src.platform.workflows.capability_services import (
    capability_dependencies,
    check_availability,
    compose_capabilities,
    discover_resources,
    inspect_capability,
    inspect_event,
    inspect_resource,
    inspect_template,
    resolve_binding_for_tenant,
    search_templates,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/capabilities", tags=["Capabilities"])


async def _workspace_id(request: Request) -> UUID | None:
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
        return await get_active_workspace_id(ctx.organization_id, ctx.user_id)
    except Exception:  # noqa: BLE001
        return None


def _ctx(request: Request):
    from src.platform.rbac.policy import require_permission

    return require_permission(request, "workflows:read")


async def _snapshot(request: Request):
    ctx = _ctx(request)
    workspace_id = await _workspace_id(request)
    snapshot = await build_capability_snapshot(
        ctx.organization_id, workspace_id, permissions=ctx.permissions
    )
    return ctx, workspace_id, snapshot


def _log(action: str, ctx, workspace_id: UUID | None, **fields) -> None:
    try:
        logger.info(
            "capability.api",
            action=action,
            organization_id=str(ctx.organization_id),
            workspace_id=str(workspace_id) if workspace_id else None,
            actor_id=str(ctx.user_id) if getattr(ctx, "user_id", None) else None,
            **fields,
        )
    except Exception:  # noqa: BLE001 — observabilidad no rompe la consulta
        pass


@router.get("", summary="Buscar capacidades reales del tenant")
async def capability_search_endpoint(
    request: Request,
    q: str = Query(default="", max_length=300),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=500),
    category: str | None = Query(default=None, max_length=60),
    source: str | None = Query(default=None, max_length=40),
    status: str | None = Query(default=None, max_length=40),
    executable: bool | None = Query(default=None),
    risk_level: str | None = Query(default=None, max_length=20),
    side_effect: str | None = Query(default=None, max_length=20),
    provider_kind: str | None = Query(default=None, max_length=60),
    semantic: bool = Query(default=False),
):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = await search_capabilities(
        snapshot,
        q,
        limit=limit,
        offset=offset,
        semantic=semantic,
        category=category,
        source=source,
        status=status,
        executable=executable,
        risk_level=risk_level,
        side_effect=side_effect,
        provider_kind=provider_kind,
    )
    _log(
        "search",
        ctx,
        workspace_id,
        query=q[:120],
        returned=result["returned"],
        total=result["total_matches"],
        semantic=result["semantic_used"],
    )
    return result


@router.get("/metrics", summary="Cobertura del catálogo de capacidades")
async def capability_metrics(request: Request):
    ctx, workspace_id, snapshot = await _snapshot(request)
    _log("metrics", ctx, workspace_id, snapshot_hash=snapshot.snapshot_hash)
    return {
        "schema": "zent.capability.metrics/v1",
        "snapshot_hash": snapshot.snapshot_hash,
        "generated_at": snapshot.generated_at.isoformat(),
        "coverage": snapshot.coverage,
    }


@router.get("/events", summary="Eventos disponibles para el planner")
async def capability_events(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
):
    _, _, snapshot = await _snapshot(request)
    tokens = {token for token in q.lower().split() if token}
    items = [
        event
        for event in snapshot.events
        if not q
        or any(
            token in f"{event.event_type} {event.business_name} {event.description}".lower()
            for token in tokens
        )
    ][:limit]
    return {
        "schema": "zent.event.catalog/v1",
        "snapshot_hash": snapshot.snapshot_hash,
        "total": len(snapshot.events),
        "returned": len(items),
        "events": [item.compact() for item in items],
    }


@router.get("/events/{event_type:path}", summary="Inspeccionar un evento")
async def capability_event_inspect(event_type: str, request: Request):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = inspect_event(snapshot, event_type)
    if result is None:
        raise HTTPException(404, "evento no encontrado")
    _log("event.inspect", ctx, workspace_id, event_type=event_type)
    return result


@router.get("/resources", summary="Descubrir recursos del tenant")
async def capability_resources(
    request: Request,
    kind: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = discover_resources(snapshot, kind=kind, limit=limit)
    _log("resource.discover", ctx, workspace_id, kind=kind, returned=result["returned"])
    return result


@router.get("/resources/{resource_ref:path}", summary="Inspeccionar un recurso")
async def capability_resource_inspect(resource_ref: str, request: Request):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = inspect_resource(snapshot, resource_ref)
    if result is None:
        raise HTTPException(404, "recurso no encontrado")
    _log("resource.inspect", ctx, workspace_id, resource_ref=resource_ref)
    return result


@router.get("/templates", summary="Buscar plantillas de workflow")
async def capability_templates(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
):
    ctx, workspace_id, _ = await _snapshot(request)
    result = await search_templates(q, limit=limit)
    _log("template.search", ctx, workspace_id, query=q[:120], returned=result["returned"])
    return result


@router.get("/templates/{slug}", summary="Inspeccionar una plantilla")
async def capability_template_inspect(slug: str, request: Request):
    ctx, workspace_id, _ = await _snapshot(request)
    result = await inspect_template(slug)
    if result is None:
        raise HTTPException(404, "plantilla no encontrada")
    _log("template.inspect", ctx, workspace_id, slug=slug)
    return result


@router.get("/{capability_ref:path}/dependencies", summary="Dependencias de una capacidad")
async def capability_dependencies_endpoint(capability_ref: str, request: Request):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = await capability_dependencies(snapshot, capability_ref)
    if result is None:
        raise HTTPException(404, "capacidad no encontrada")
    _log("capability.dependencies", ctx, workspace_id, capability_ref=capability_ref)
    return result


@router.get("/{capability_ref:path}/availability", summary="Disponibilidad real de una capacidad")
async def capability_availability_endpoint(capability_ref: str, request: Request):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = check_availability(snapshot, capability_ref)
    if result is None:
        raise HTTPException(404, "capacidad no encontrada")
    _log("capability.availability", ctx, workspace_id, capability_ref=capability_ref)
    return result


@router.get("/{capability_ref:path}/binding", summary="Binding resuelto (sin secretos)")
async def capability_binding_endpoint(capability_ref: str, request: Request):
    ctx, workspace_id, _ = await _snapshot(request)
    result = await resolve_binding_for_tenant(
        ctx.organization_id, capability_ref, workspace_id=workspace_id
    )
    _log("capability.binding", ctx, workspace_id, capability_ref=capability_ref)
    return result


@router.get("/{capability_ref:path}/compose", summary="¿La salida alimenta la entrada?")
async def capability_compose_endpoint(
    capability_ref: str,
    request: Request,
    to: str = Query(min_length=1, max_length=200),
):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = compose_capabilities(snapshot, capability_ref, to)
    if result is None:
        raise HTTPException(404, "capacidad no encontrada")
    _log("capability.compose", ctx, workspace_id, from_ref=capability_ref, to_ref=to)
    return result


@router.get("/{capability_ref:path}", summary="Inspeccionar una capacidad (contrato completo)")
async def capability_inspect_endpoint(capability_ref: str, request: Request):
    ctx, workspace_id, snapshot = await _snapshot(request)
    result = await inspect_capability(snapshot, capability_ref)
    if result is None:
        raise HTTPException(404, "capacidad no encontrada")
    _log("capability.inspect", ctx, workspace_id, capability_ref=capability_ref)
    return result
