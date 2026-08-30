# =============================================================================
# Agents Routes — CRUD de agentes (organization-scoped, project opcional)
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from src.api.deps import get_agent_repo
from src.core.ports import AgentRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class AgentLimits(BaseModel):
    max_steps: int | None = Field(default=None, ge=1, le=100)
    max_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    max_cost_usd: float | None = Field(default=None, ge=0, le=1000)


class AgentSecurity(BaseModel):
    sql_enabled: bool = False
    api_calls_enabled: bool = False


class AgentConfig(BaseModel):
    purpose: str | None = Field(default=None, max_length=2000)
    temperature: float = Field(default=0.2, ge=0, le=1)
    tone: str = Field(default="professional", pattern="^(professional|friendly|concise)$")
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=50)
    limits: AgentLimits | None = None
    security: AgentSecurity | None = None


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_id: UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=16000)
    tools: list[str] = Field(default_factory=list, max_length=20)
    model: str | None = Field(default=None, max_length=100)
    config: AgentConfig | None = None


class UpdateAgentRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    project_id: UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=16000)
    tools: list[str] | None = Field(default=None, max_length=20)
    model: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    config: AgentConfig | None = None


def parse_agent_config(raw: dict | None) -> dict:
    try:
        return AgentConfig.model_validate(raw or {}).model_dump(mode="json")
    except ValidationError:
        return AgentConfig().model_dump(mode="json")


def _agent_response(agent) -> dict:
    return {
        "id": str(agent.id),
        "name": agent.name,
        "description": agent.description,
        "project_id": str(agent.project_id) if agent.project_id else None,
        "system_prompt": agent.system_prompt,
        "tools": agent.tools,
        "model": agent.model,
        "is_active": agent.is_active,
        "created_at": agent.created_at.isoformat(),
        "config": parse_agent_config(agent.config_json),
    }


@router.get("", summary="Listar agentes")
async def list_agents(
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    agents = await repo.list_agents(ctx.organization_id)
    return {"agents": [_agent_response(a) for a in agents], "count": len(agents)}


@router.post("", status_code=201, summary="Crear agente")
async def create_agent(
    body: CreateAgentRequest,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.billing.plan_limits import (
        PlanLimitError,
        check_resource_limit,
        plan_limit_detail,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        await check_resource_limit(ctx.organization_id, "agents")
    except PlanLimitError as exc:
        raise HTTPException(status_code=409, detail=plan_limit_detail(exc)) from None
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    config_payload = None
    if body.config is not None:
        await _require_own_kbs(ctx, body.config.knowledge_base_ids)
        config_payload = body.config.model_dump(mode="json")
    agent = await repo.create_agent(
        ctx.organization_id,
        body.name,
        description=body.description,
        project_id=body.project_id,
        system_prompt=body.system_prompt,
        tools=body.tools,
        model=body.model,
        config_json=config_payload,
    )
    await _audit().write(ctx, "agent.created", "agent", agent.id, metadata={"name": agent.name})
    return _agent_response(agent)


@router.get("/{agent_id}", summary="Obtener agente")
async def get_agent(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await repo.get_agent(ctx.organization_id, aid)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return _agent_response(agent)


@router.put("/{agent_id}", summary="Actualizar agente")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    fields = body.model_dump(exclude_none=True)
    if "config" in fields:
        if body.config is not None:
            await _require_own_kbs(ctx, body.config.knowledge_base_ids)
        fields["config_json"] = (
            body.config.model_dump(mode="json") if body.config is not None else {}
        )
        del fields["config"]
    try:
        agent = await repo.update_agent(ctx.organization_id, aid, **fields)
    except ValueError:
        raise HTTPException(404, "Agent not found")
    await _audit().write(ctx, "agent.updated", "agent", aid, metadata={"name": agent.name})
    return _agent_response(agent)


@router.delete("/{agent_id}", summary="Eliminar agente")
async def delete_agent(
    agent_id: str,
    request: Request,
    repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:write")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    if await repo.get_agent(ctx.organization_id, aid) is None:
        raise HTTPException(404, "Agent not found")
    await repo.delete_agent(ctx.organization_id, aid)
    await _audit().write(ctx, "agent.deleted", "agent", aid)
    return {"status": "deleted", "agent_id": str(aid)}


async def _require_own_project(ctx, project_id: UUID) -> None:
    from src.api.deps import get_project_repo

    project = await get_project_repo().get_project(ctx.organization_id, project_id)
    if project is None:
        raise HTTPException(404, "Project not found in this organization")


async def _require_own_kbs(ctx, knowledge_base_ids: list[UUID]) -> None:
    from src.api.deps import get_kb_repo

    repo = get_kb_repo()
    for kb_id in knowledge_base_ids:
        kb = await repo.get_kb(ctx.organization_id, kb_id)
        if kb is None:
            raise HTTPException(
                404, "Knowledge base not found in this organization"
            )
