# =============================================================================
# Deployments — máquina de estados de despliegues de agentes
# =============================================================================
# Un deployment enlaza una versión concreta (agent_versions) con un entorno
# (development|staging|production). F1: creación síncrona con estados
# pending → deploying → healthy; rollback a la última versión buena.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.core.domain.entities import (
    Agent,
    AgentVersion,
    Deployment,
    DeploymentStatus,
    Environment,
)
from src.core.ports import DeploymentRepository
from src.platform.deployments import events as deployment_events
from src.platform.deployments.versions import slugify

_DEFAULT_ENVIRONMENTS = (
    ("development", "development"),
    ("staging", "staging"),
    ("production", "production"),
)

# Estados desde los que se permite rollback.
_ROLLBACKABLE = {DeploymentStatus.HEALTHY, DeploymentStatus.DEGRADED}


async def ensure_default_environments(
    repo: DeploymentRepository, organization_id: UUID
) -> list[Environment]:
    """Crea los entornos DEV/STAGING/PROD si no existen (idempotente)."""
    existing = {env.slug for env in await repo.list_environments(organization_id)}
    for name, slug in _DEFAULT_ENVIRONMENTS:
        if slug not in existing:
            await repo.create_environment(organization_id, name, slug)
    return await repo.list_environments(organization_id)


async def _unique_slug(
    repo: DeploymentRepository,
    organization_id: UUID,
    base: str,
) -> str:
    """Slug único por organización (apende -N en colisiones)."""
    slug = base
    counter = 2
    while True:
        existing = await repo.get_deployment_by_slug(organization_id, slug)
        if existing is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


async def deploy_to_environment(
    repo: DeploymentRepository,
    organization_id: UUID,
    *,
    agent: Agent,
    version: AgentVersion,
    environment_id: UUID,
    environment: Environment | None = None,
    slug: str | None = None,
    deployed_by: UUID | None = None,
    endpoint: str | None = None,
) -> Deployment:
    """Despliega una versión de agente en un entorno.

    Valida pertenencia (mismo org) y crea el deployment con la transición
    pending → deploying → healthy.
    """
    if version.organization_id != organization_id or version.agent_id != agent.id:
        raise ValueError("Version does not belong to this agent/organization")

    if environment is None:
        environment = await repo.get_environment(organization_id, environment_id)
    if environment is None or environment.organization_id != organization_id:
        raise ValueError("Environment does not belong to this organization")

    if version.status.value not in ("ready", "staging", "production"):
        raise ValueError(
            f"Version must be ready/staging/production to deploy (got '{version.status.value}')"
        )

    base = slug or f"{slugify(agent.name)}-{environment.slug}"
    final_slug = await _unique_slug(repo, organization_id, base)
    endpoint = endpoint or f"/api/v1/deployments/{final_slug}/query"

    deployment = await repo.create_deployment(
        organization_id=organization_id,
        environment_id=environment.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        slug=final_slug,
        endpoint=endpoint,
        deployed_by=deployed_by,
    )
    await deployment_events.record_event(
        organization_id, deployment.id, deployment_events.CREATED,
        actor_user_id=deployed_by,
        metadata={"agent_id": str(agent.id), "environment": environment.slug,
                  "version": str(version.id)},
    )
    await repo.update_deployment_status(
        organization_id, deployment.id, DeploymentStatus.DEPLOYING.value
    )
    await deployment_events.record_event(
        organization_id, deployment.id, deployment_events.DEPLOYING,
        actor_user_id=deployed_by,
    )
    healthy = await repo.update_deployment_status(
        organization_id,
        deployment.id,
        DeploymentStatus.HEALTHY.value,
        deployed_at=datetime.now(timezone.utc),
    )
    if healthy is None:
        raise RuntimeError(f"Deployment {deployment.id} disappeared during deploy")
    await deployment_events.record_event(
        organization_id, deployment.id, deployment_events.HEALTHY,
        actor_user_id=deployed_by,
    )
    return healthy


async def rollback_deployment(
    repo: DeploymentRepository,
    organization_id: UUID,
    deployment_id: UUID,
    deployed_by: UUID | None = None,
) -> Deployment:
    """Revierte al último deployment bueno del mismo agente+entorno.

    Crea un NUEVO deployment apuntando a la versión anterior (historia
    preservada, rollback_from_id referencia al deployment actual).
    """
    current = await repo.get_deployment(organization_id, deployment_id)
    if current is None:
        raise ValueError(f"Deployment {deployment_id} not found")
    if current.status not in _ROLLBACKABLE:
        raise ValueError(
            f"Only healthy/degraded deployments can be rolled back (got '{current.status.value}')"
        )

    previous = await repo.get_last_deployment(
        organization_id,
        environment_id=current.environment_id,
        agent_id=current.agent_id,
        exclude_version_id=current.agent_version_id,
    )
    if previous is None:
        raise ValueError("No previous version available to roll back to")

    base = f"{current.slug}-rb"
    final_slug = await _unique_slug(repo, organization_id, base)

    await deployment_events.record_event(
        organization_id, current.id, deployment_events.ROLLED_BACK,
        actor_user_id=deployed_by,
        metadata={"new_deployment": str(current.id)},
    )
    new_deployment = await repo.create_deployment(
        organization_id=organization_id,
        environment_id=current.environment_id,
        agent_id=current.agent_id,
        agent_version_id=previous.agent_version_id,
        slug=final_slug,
        endpoint=current.endpoint,
        deployed_by=deployed_by,
        rollback_from_id=current.id,
    )
    await deployment_events.record_event(
        organization_id, new_deployment.id, deployment_events.CREATED,
        actor_user_id=deployed_by,
        metadata={"rollback_from": str(current.id)},
    )
    await repo.update_deployment_status(
        organization_id, new_deployment.id, DeploymentStatus.DEPLOYING.value
    )
    await deployment_events.record_event(
        organization_id, new_deployment.id, deployment_events.DEPLOYING,
        actor_user_id=deployed_by,
    )
    healthy = await repo.update_deployment_status(
        organization_id,
        new_deployment.id,
        DeploymentStatus.HEALTHY.value,
        deployed_at=datetime.now(timezone.utc),
    )
    if healthy is None:
        raise RuntimeError(
            f"Deployment {new_deployment.id} disappeared during rollback"
        )
    await deployment_events.record_event(
        organization_id, new_deployment.id, deployment_events.HEALTHY,
        actor_user_id=deployed_by,
    )
    await deployment_events.record_event(
        organization_id, new_deployment.id, deployment_events.ROLLED_BACK_TO,
        actor_user_id=deployed_by,
        metadata={"from_deployment": str(current.id)},
    )
    return healthy
