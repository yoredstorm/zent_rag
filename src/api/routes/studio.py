# =============================================================================
# Universal Studio API — RoleProfiles and Solution blueprints.
#
# These endpoints create design artifacts. Execution remains in Agents and
# Workflows. No endpoint copies an Agent or a Workflow.
# =============================================================================
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.platform.studio.contracts import RoleProfileV1, SolutionV1
from src.platform.studio.roles import (
    RoleConflict,
    RoleError,
    RoleNotFound,
    archive_role,
    clone_role,
    create_role,
    export_role,
    get_agent_role,
    get_role,
    get_role_version,
    import_role,
    link_agent_role,
    list_role_versions,
    list_roles,
    mission_sheet,
    propose_role,
    update_role,
)
from src.platform.studio.sessions import resolve_session
from src.platform.studio.solutions import (
    SolutionConflict,
    SolutionError,
    clone_solution,
    create_solution,
    export_solution,
    get_solution,
    get_solution_version,
    import_solution,
    list_solution_versions,
    list_solutions,
    update_solution,
    validate_solution,
)
from src.platform.studio.templates import list_role_templates
from src.platform.workspaces.context import resolve_workspace

router = APIRouter(prefix="/api/v1/studio", tags=["Universal Studio"])


class RoleEnvelope(BaseModel):
    """Accept both {"role": {...}} and a raw portable role payload."""

    model_config = ConfigDict(extra="allow")

    role: dict[str, Any] | None = None


class SolutionEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    solution: dict[str, Any] | None = None


class ProposeRoleIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    template_id: str | None = Field(default=None, max_length=80)


class CloneIn(BaseModel):
    new_id: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=400)


class AgentRoleIn(BaseModel):
    role_profile_id: UUID | None = None


class SessionResolveIn(BaseModel):
    session_id: UUID
    kind: Literal["conversation", "design", "workflow_instance"]


def _permission(request: Request, permission: str):
    from src.platform.rbac.policy import require_permission

    return require_permission(request, permission)


async def _workspace(request: Request):
    return await resolve_workspace(request)


def _role_body(body: RoleEnvelope) -> dict[str, Any]:
    if body.role is not None:
        return body.role
    return {key: value for key, value in body.model_dump().items() if key != "role"}


def _solution_body(body: SolutionEnvelope) -> dict[str, Any]:
    if body.solution is not None:
        return body.solution
    return {key: value for key, value in body.model_dump().items() if key != "solution"}


def _raise_role(exc: Exception) -> None:
    if isinstance(exc, RoleConflict):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, RoleNotFound):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, RoleError):
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(400, str(exc)[:500]) from exc


def _raise_solution(exc: Exception) -> None:
    if isinstance(exc, SolutionConflict):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, SolutionError):
        raise HTTPException(400, str(exc)) from exc
    raise HTTPException(400, str(exc)[:500]) from exc


@router.post("/sessions/resolve", summary="Distinguir sesión de usuario, diseño e instancia")
async def post_session_resolve(request: Request, body: SessionResolveIn):
    ctx = _permission(request, "rag:read")
    return await resolve_session(ctx.organization_id, body.session_id, body.kind)


@router.get("/templates", summary="Plantillas mínimas de rol")
async def get_templates(request: Request):
    _permission(request, "agents:read")
    templates = list_role_templates()
    return {"templates": templates, "count": len(templates)}


@router.post("/roles/propose", summary="Proponer un rol editable desde una función")
async def propose(request: Request, body: ProposeRoleIn):
    ctx = _permission(request, "agents:read")
    try:
        result = await propose_role(body.prompt, template_id=body.template_id)
    except RoleError as exc:
        _raise_role(exc)
    return {**result, "organization_id": str(ctx.organization_id)}


@router.get("/roles", summary="Listar perfiles de rol")
async def get_roles(request: Request):
    ctx = _permission(request, "agents:read")
    workspace = await _workspace(request)
    roles = await list_roles(ctx.organization_id, workspace_id=workspace.id)
    return {"roles": roles, "count": len(roles), "workspace_id": str(workspace.id)}


@router.post("/roles", status_code=201, summary="Crear perfil de rol")
async def post_role(request: Request, body: RoleEnvelope):
    ctx = _permission(request, "agents:write")
    workspace = await _workspace(request)
    payload = _role_body(body)
    try:
        role = await create_role(
            ctx.organization_id,
            workspace_id=workspace.id,
            user_id=ctx.user_id,
            payload=payload,
        )
    except RoleError as exc:
        _raise_role(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_role(exc)
    return {"role": role, "mission_sheet": mission_sheet(RoleProfileV1.model_validate(role))}


@router.post("/roles/import", status_code=201, summary="Importar rol portable")
async def post_import_role(request: Request, body: dict[str, Any]):
    ctx = _permission(request, "agents:write")
    workspace = await _workspace(request)
    try:
        role = await import_role(
            ctx.organization_id,
            body,
            workspace_id=workspace.id,
            user_id=ctx.user_id,
        )
    except RoleError as exc:
        _raise_role(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_role(exc)
    return {"role": role}


@router.get("/roles/{role_id}", summary="Obtener perfil de rol")
async def get_one_role(request: Request, role_id: UUID):
    ctx = _permission(request, "agents:read")
    workspace = await _workspace(request)
    role = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if role is None:
        raise HTTPException(404, "rol inexistente")
    return {
        "role": role,
        "mission_sheet": mission_sheet(RoleProfileV1.model_validate(role)),
    }


@router.put("/roles/{role_id}", summary="Editar perfil de rol (nueva versión)")
async def put_role(request: Request, role_id: UUID, body: RoleEnvelope):
    ctx = _permission(request, "agents:write")
    workspace = await _workspace(request)
    current = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "rol inexistente")
    payload = _role_body(body)
    try:
        role = await update_role(
            ctx.organization_id,
            role_id,
            payload,
            user_id=ctx.user_id,
            notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
        )
    except RoleError as exc:
        _raise_role(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_role(exc)
    if role is None:
        raise HTTPException(404, "rol inexistente")
    return {"role": role, "mission_sheet": mission_sheet(RoleProfileV1.model_validate(role))}


@router.delete("/roles/{role_id}", summary="Archivar perfil de rol")
async def delete_role(request: Request, role_id: UUID):
    ctx = _permission(request, "agents:write")
    workspace = await _workspace(request)
    current = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "rol inexistente")
    role = await archive_role(ctx.organization_id, role_id, user_id=ctx.user_id)
    return {"role": role}


@router.post("/roles/{role_id}/clone", status_code=201, summary="Clonar perfil de rol")
async def post_clone_role(request: Request, role_id: UUID, body: CloneIn | None = None):
    ctx = _permission(request, "agents:write")
    workspace = await _workspace(request)
    current = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "rol inexistente")
    try:
        role = await clone_role(
            ctx.organization_id,
            role_id,
            user_id=ctx.user_id,
            new_role_id=(body.new_id if body else None),
        )
    except RoleError as exc:
        _raise_role(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_role(exc)
    return {"role": role}


@router.get("/roles/{role_id}/versions", summary="Historial de versiones del rol")
async def get_role_versions(request: Request, role_id: UUID):
    ctx = _permission(request, "agents:read")
    workspace = await _workspace(request)
    current = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "rol inexistente")
    return {"versions": await list_role_versions(ctx.organization_id, role_id)}


@router.get("/roles/{role_id}/versions/{revision}", summary="Snapshot de una versión del rol")
async def get_one_role_version(request: Request, role_id: UUID, revision: int):
    ctx = _permission(request, "agents:read")
    workspace = await _workspace(request)
    current = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "rol inexistente")
    snapshot = await get_role_version(ctx.organization_id, role_id, revision)
    if snapshot is None:
        raise HTTPException(404, "versión inexistente")
    return {"role": snapshot}


@router.get("/roles/{role_id}/export", summary="Exportar rol portable")
async def get_role_export(request: Request, role_id: UUID):
    ctx = _permission(request, "agents:read")
    workspace = await _workspace(request)
    current = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "rol inexistente")
    role = await export_role(ctx.organization_id, role_id)
    return {"role": role, "schema": "zent.role/v1"}


@router.get("/roles/{role_id}/mission-sheet", summary="Hoja de misión legible")
async def get_mission_sheet(request: Request, role_id: UUID):
    ctx = _permission(request, "agents:read")
    workspace = await _workspace(request)
    role = await get_role(ctx.organization_id, role_id, workspace_id=workspace.id)
    if role is None:
        raise HTTPException(404, "rol inexistente")
    return mission_sheet(RoleProfileV1.model_validate(role))


@router.get("/agents/{agent_id}/role", summary="Rol efectivo de un agente")
async def get_role_for_agent(request: Request, agent_id: UUID):
    ctx = _permission(request, "agents:read")
    role = await get_agent_role(ctx.organization_id, agent_id)
    return {"agent_id": str(agent_id), "role": role}


@router.post("/agents/{agent_id}/role", summary="Vincular rol a un agente existente")
async def post_role_for_agent(request: Request, agent_id: UUID, body: AgentRoleIn):
    ctx = _permission(request, "agents:write")
    try:
        return await link_agent_role(ctx.organization_id, agent_id, body.role_profile_id)
    except RoleNotFound as exc:
        _raise_role(exc)
    except RoleError as exc:
        _raise_role(exc)


@router.get("/solutions", summary="Listar soluciones")
async def get_solutions(request: Request):
    ctx = _permission(request, "workflows:read")
    workspace = await _workspace(request)
    solutions = await list_solutions(ctx.organization_id, workspace_id=workspace.id)
    return {"solutions": solutions, "count": len(solutions), "workspace_id": str(workspace.id)}


@router.post("/solutions", status_code=201, summary="Crear solución/blueprint")
async def post_solution(request: Request, body: SolutionEnvelope):
    ctx = _permission(request, "workflows:create")
    workspace = await _workspace(request)
    payload = _solution_body(body)
    try:
        solution = await create_solution(
            ctx.organization_id,
            workspace_id=workspace.id,
            user_id=ctx.user_id,
            payload=payload,
        )
    except SolutionError as exc:
        _raise_solution(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_solution(exc)
    return {"solution": solution}


@router.post("/solutions/validate", summary="Validar solución sin guardar")
async def post_validate_solution(request: Request, body: dict[str, Any]):
    _permission(request, "workflows:read")
    return validate_solution(body)


@router.post("/solutions/import", status_code=201, summary="Importar solución portable")
async def post_import_solution(request: Request, body: dict[str, Any]):
    ctx = _permission(request, "workflows:create")
    workspace = await _workspace(request)
    try:
        solution = await import_solution(
            ctx.organization_id,
            body,
            workspace_id=workspace.id,
            user_id=ctx.user_id,
        )
    except SolutionError as exc:
        _raise_solution(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_solution(exc)
    return {"solution": solution}


@router.get("/solutions/{solution_id}", summary="Obtener solución")
async def get_one_solution(request: Request, solution_id: UUID):
    ctx = _permission(request, "workflows:read")
    workspace = await _workspace(request)
    solution = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if solution is None:
        raise HTTPException(404, "solución inexistente")
    return {
        "solution": solution,
        "validation": validate_solution(solution),
    }


@router.put("/solutions/{solution_id}", summary="Editar solución (nueva versión)")
async def put_solution(request: Request, solution_id: UUID, body: SolutionEnvelope):
    ctx = _permission(request, "workflows:create")
    workspace = await _workspace(request)
    current = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "solución inexistente")
    payload = _solution_body(body)
    try:
        solution = await update_solution(
            ctx.organization_id,
            solution_id,
            payload,
            user_id=ctx.user_id,
            notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
        )
    except SolutionError as exc:
        _raise_solution(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_solution(exc)
    if solution is None:
        raise HTTPException(404, "solución inexistente")
    return {"solution": solution, "validation": validate_solution(solution)}


@router.post("/solutions/{solution_id}/clone", status_code=201, summary="Clonar solución")
async def post_clone_solution(
    request: Request, solution_id: UUID, body: CloneIn | None = None
):
    ctx = _permission(request, "workflows:create")
    workspace = await _workspace(request)
    current = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "solución inexistente")
    try:
        solution = await clone_solution(
            ctx.organization_id,
            solution_id,
            user_id=ctx.user_id,
            new_solution_id=(body.new_id if body else None),
        )
    except SolutionError as exc:
        _raise_solution(exc)
    except Exception as exc:  # noqa: BLE001
        _raise_solution(exc)
    return {"solution": solution}


@router.get("/solutions/{solution_id}/versions", summary="Historial de versiones")
async def get_solution_versions(request: Request, solution_id: UUID):
    ctx = _permission(request, "workflows:read")
    workspace = await _workspace(request)
    current = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "solución inexistente")
    return {"versions": await list_solution_versions(ctx.organization_id, solution_id)}


@router.get(
    "/solutions/{solution_id}/versions/{revision}",
    summary="Snapshot de una versión de la solución",
)
async def get_one_solution_version(request: Request, solution_id: UUID, revision: int):
    ctx = _permission(request, "workflows:read")
    workspace = await _workspace(request)
    current = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "solución inexistente")
    snapshot = await get_solution_version(ctx.organization_id, solution_id, revision)
    if snapshot is None:
        raise HTTPException(404, "versión inexistente")
    return {"solution": snapshot}


@router.get("/solutions/{solution_id}/export", summary="Exportar solución portable")
async def get_solution_export(request: Request, solution_id: UUID):
    ctx = _permission(request, "workflows:read")
    workspace = await _workspace(request)
    current = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if current is None:
        raise HTTPException(404, "solución inexistente")
    solution = await export_solution(ctx.organization_id, solution_id)
    return {"solution": solution, "schema": "zent.solution/v1"}


@router.get("/solutions/{solution_id}/install-plan", summary="Requisitos e instalación")
async def get_install_plan(request: Request, solution_id: UUID):
    ctx = _permission(request, "workflows:read")
    workspace = await _workspace(request)
    solution = await get_solution(ctx.organization_id, solution_id, workspace_id=workspace.id)
    if solution is None:
        raise HTTPException(404, "solución inexistente")
    profile = SolutionV1.model_validate(solution)
    return {
        "solution_id": profile.solution_id,
        "requirements": profile.requirements,
        "capabilities": [item.model_dump(mode="json") for item in profile.capabilities],
        "knowledge": [item.model_dump(mode="json") for item in profile.knowledge],
        "installation": [item.model_dump(mode="json") for item in profile.installation],
        "roles": [item.model_dump(mode="json") for item in profile.roles],
        "workflows": [item.model_dump(mode="json") for item in profile.workflows],
        "agents": [item.model_dump(mode="json") for item in profile.agents],
    }
