# =============================================================================
# Deployments Routes — entornos y despliegues de agentes
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import (
    get_agent_repo,
    get_agent_version_repo,
    get_deployment_repo,
)
from src.core.ports import (
    AgentRepository,
    AgentVersionRepository,
    DeploymentRepository,
)
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.deployments.deployments import (
    deploy_to_environment,
    ensure_default_environments,
    rollback_deployment,
)

router = APIRouter(prefix="/api/v1", tags=["Deployments"])

_ENV_NAMES = {"development", "staging", "production"}


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _environment_response(env) -> dict:
    return {
        "id": str(env.id),
        "name": env.name,
        "slug": env.slug,
        "is_default": env.is_default,
        "created_at": env.created_at.isoformat(),
    }


def _deployment_response(dep) -> dict:
    return {
        "id": str(dep.id),
        "environment_id": str(dep.environment_id),
        "agent_id": str(dep.agent_id),
        "agent_version_id": str(dep.agent_version_id),
        "slug": dep.slug,
        "status": dep.status.value,
        "endpoint": dep.endpoint,
        "deployed_by": str(dep.deployed_by) if dep.deployed_by else None,
        "deployed_at": dep.deployed_at.isoformat() if dep.deployed_at else None,
        "rollback_from_id": str(dep.rollback_from_id) if dep.rollback_from_id else None,
        "created_at": dep.created_at.isoformat(),
    }


class CreateEnvironmentRequest(BaseModel):
    name: str = Field(..., pattern="^(development|staging|production)$")
    slug: str = Field(..., min_length=2, max_length=30, pattern="^[a-z0-9-]+$")
    is_default: bool = False


class CreateDeploymentRequest(BaseModel):
    agent_id: UUID
    agent_version_id: UUID
    environment_id: UUID | None = None
    environment_slug: str | None = Field(default=None, max_length=30)
    slug: str | None = Field(default=None, max_length=255, pattern="^[a-z0-9-]+$")


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


@router.get("/environments", summary="Listar entornos (dev/staging/prod)")
async def list_environments(
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    envs = await ensure_default_environments(repo, ctx.organization_id)
    return {"environments": [_environment_response(e) for e in envs]}


@router.post("/environments", status_code=201, summary="Crear entorno")
async def create_environment(
    body: CreateEnvironmentRequest,
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:write")
    if body.name not in _ENV_NAMES:
        raise HTTPException(400, "name must be development|staging|production")
    existing = await repo.get_environment_by_slug(ctx.organization_id, body.slug)
    if existing is not None:
        raise HTTPException(409, "Environment slug already exists")
    env = await repo.create_environment(
        ctx.organization_id, body.name, body.slug, body.is_default
    )
    await _audit().write(
        ctx, "environment.created", "environment", env.id, metadata={"name": env.name}
    )
    return _environment_response(env)


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------


@router.get("/deployments", summary="Listar deployments")
async def list_deployments(
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    deployments = await repo.list_deployments(ctx.organization_id)
    return {
        "deployments": [_deployment_response(d) for d in deployments],
        "count": len(deployments),
    }


@router.post("/deployments", status_code=201, summary="Desplegar versión en entorno")
async def create_deployment(
    body: CreateDeploymentRequest,
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
    agent_repo: AgentRepository = Depends(get_agent_repo),
    version_repo: AgentVersionRepository = Depends(get_agent_version_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:deploy")

    agent = await agent_repo.get_agent(ctx.organization_id, body.agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found in this organization")

    version = await version_repo.get_version(
        ctx.organization_id, body.agent_id, body.agent_version_id
    )
    if version is None:
        raise HTTPException(404, "Version not found for this agent")

    environment = None
    if body.environment_id is not None:
        environment = await repo.get_environment(ctx.organization_id, body.environment_id)
    elif body.environment_slug is not None:
        environment = await repo.get_environment_by_slug(
            ctx.organization_id, body.environment_slug
        )
    if environment is None:
        raise HTTPException(404, "Environment not found")

    try:
        deployment = await deploy_to_environment(
            repo,
            ctx.organization_id,
            agent=agent,
            version=version,
            environment_id=environment.id,
            environment=environment,
            slug=body.slug,
            deployed_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None

    await _audit().write(
        ctx,
        "agent.deployed",
        "deployment",
        deployment.id,
        metadata={
            "agent_id": str(agent.id),
            "agent_version_id": str(version.id),
            "environment": environment.slug,
            "slug": deployment.slug,
        },
    )
    try:
        from src.platform.onboardingv2.onboarding import sync_progress

        await sync_progress(ctx.organization_id)
    except Exception:  # noqa: BLE001
        pass
    return _deployment_response(deployment)


@router.get("/deployments/{deployment_id}", summary="Obtener deployment")
async def get_deployment(
    deployment_id: str,
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    try:
        did = UUID(deployment_id)
    except ValueError:
        raise HTTPException(400, "deployment_id must be a valid UUID")
    deployment = await repo.get_deployment(ctx.organization_id, did)
    if deployment is None:
        raise HTTPException(404, "Deployment not found")
    return _deployment_response(deployment)


@router.post(
    "/deployments/{deployment_id}/rollback",
    summary="Rollback al último deployment bueno",
)
async def rollback_deployment_route(
    deployment_id: str,
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:rollback")
    try:
        did = UUID(deployment_id)
    except ValueError:
        raise HTTPException(400, "deployment_id must be a valid UUID")
    existing = await repo.get_deployment(ctx.organization_id, did)
    if existing is None:
        raise HTTPException(404, "Deployment not found")
    try:
        deployment = await rollback_deployment(
            repo, ctx.organization_id, did, deployed_by=ctx.user_id
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    await _audit().write(
        ctx,
        "agent.rolled_back",
        "deployment",
        deployment.id,
        metadata={
            "agent_id": str(deployment.agent_id),
            "agent_version_id": str(deployment.agent_version_id),
            "rollback_from_id": str(did),
        },
    )
    return _deployment_response(deployment)
@router.get("/deployments/{deployment_id}/events", summary="Historial de eventos del deployment")
async def get_deployment_events(
    deployment_id: str,
    request: Request,
    repo: DeploymentRepository = Depends(get_deployment_repo),
):
    from src.platform.deployments.events import list_events
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    try:
        did = UUID(deployment_id)
    except ValueError:
        raise HTTPException(400, "deployment_id must be a valid UUID")
    if await repo.get_deployment(ctx.organization_id, did) is None:
        raise HTTPException(404, "Deployment not found")
    events = await list_events(ctx.organization_id, did)
    return {"events": events, "count": len(events)}


@router.get("/deployments/{deployment_id}/slos", summary="SLIs/SLOs del deployment (tenant)")
async def tenant_deployment_slos(deployment_id: str, request: Request):
    from src.platform.observability.slos import deployment_slos
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    try:
        did = UUID(deployment_id)
    except ValueError:
        raise HTTPException(400, "deployment_id must be a valid UUID")
    if await get_deployment_repo().get_deployment(ctx.organization_id, did) is None:
        raise HTTPException(404, "Deployment not found")
    slos = await deployment_slos(ctx.organization_id, did)
    if slos is None:
        raise HTTPException(404, "Deployment not found")
    return slos


@router.get("/deployments/{deployment_id}/incidents", summary="Alertas de incidentes del deployment (tenant)")
async def tenant_deployment_incidents(deployment_id: str, request: Request):
    from src.platform.observability.alerts import list_alerts
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "deployments:read")
    try:
        did = UUID(deployment_id)
    except ValueError:
        raise HTTPException(400, "deployment_id must be a valid UUID")
    if await get_deployment_repo().get_deployment(ctx.organization_id, did) is None:
        raise HTTPException(404, "Deployment not found")
    alerts = await list_alerts(ctx.organization_id, status=None, limit=50)
    return {
        "alerts": [a for a in alerts if a["deployment_id"] == str(did)],
        "count": sum(1 for a in alerts if a["deployment_id"] == str(did)),
    }
