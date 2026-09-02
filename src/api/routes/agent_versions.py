# =============================================================================
# Agent Versions Routes — snapshot inmutable de configuración de agentes
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_agent_repo, get_agent_version_repo
from src.core.domain.entities import AgentVersionStatus
from src.core.ports import AgentRepository, AgentVersionRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.deployments.versions import create_version, promote_version

router = APIRouter(prefix="/api/v1/agents", tags=["Agent Versions"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _version_response(version) -> dict:
    return {
        "id": str(version.id),
        "agent_id": str(version.agent_id),
        "version_number": version.version_number,
        "status": version.status.value,
        "config_snapshot": version.config_snapshot,
        "notes": version.notes,
        "created_by": str(version.created_by) if version.created_by else None,
        "created_at": version.created_at.isoformat(),
    }


class PromoteVersionRequest(BaseModel):
    status: AgentVersionStatus = Field(
        ..., description="Estado destino (ready | staging | production | archived)"
    )


class CreateVersionRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


async def _require_own_agent(
    request: Request,
    repo: AgentRepository,
    organization_id: UUID,
    agent_id: UUID,
):
    agent = await repo.get_agent(organization_id, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found in this organization")
    return agent


@router.get("/{agent_id}/versions", summary="Listar versiones de un agente")
async def list_versions(
    agent_id: str,
    request: Request,
    repo: AgentVersionRepository = Depends(get_agent_version_repo),
    agent_repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    await _require_own_agent(request, agent_repo, ctx.organization_id, aid)
    versions = await repo.list_versions(ctx.organization_id, aid)
    return {"versions": [_version_response(v) for v in versions], "count": len(versions)}


@router.post("/{agent_id}/versions", status_code=201, summary="Crear snapshot del agente")
async def create_agent_version(
    agent_id: str,
    body: CreateVersionRequest,
    request: Request,
    repo: AgentVersionRepository = Depends(get_agent_version_repo),
    agent_repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:version")
    try:
        aid = UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "agent_id must be a valid UUID")
    agent = await _require_own_agent(request, agent_repo, ctx.organization_id, aid)
    version = await create_version(
        repo, ctx.organization_id, agent, notes=body.notes, created_by=ctx.user_id
    )
    await _audit().write(
        ctx,
        "agent.version.created",
        "agent_version",
        version.id,
        metadata={"agent_id": str(aid), "version_number": version.version_number},
    )
    return _version_response(version)


@router.get("/{agent_id}/versions/{version_id}", summary="Obtener versión")
async def get_agent_version(
    agent_id: str,
    version_id: str,
    request: Request,
    repo: AgentVersionRepository = Depends(get_agent_version_repo),
    agent_repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "agents:read")
    try:
        aid, vid = UUID(agent_id), UUID(version_id)
    except ValueError:
        raise HTTPException(400, "agent_id and version_id must be valid UUIDs")
    await _require_own_agent(request, agent_repo, ctx.organization_id, aid)
    version = await repo.get_version(ctx.organization_id, aid, vid)
    if version is None:
        raise HTTPException(404, "Version not found")
    return _version_response(version)


@router.post("/{agent_id}/versions/{version_id}/promote", summary="Promover versión")
async def promote_agent_version(
    agent_id: str,
    version_id: str,
    body: PromoteVersionRequest,
    request: Request,
    repo: AgentVersionRepository = Depends(get_agent_version_repo),
    agent_repo: AgentRepository = Depends(get_agent_repo),
):
    from src.platform.rbac.policy import require_permission

    required = (
        "deployments:promote"
        if body.status == AgentVersionStatus.PRODUCTION
        else "agents:version"
    )
    ctx = require_permission(request, required)
    try:
        aid, vid = UUID(agent_id), UUID(version_id)
    except ValueError:
        raise HTTPException(400, "agent_id and version_id must be valid UUIDs")
    await _require_own_agent(request, agent_repo, ctx.organization_id, aid)
    if body.status == AgentVersionStatus.PRODUCTION:
        await _check_promotion_gate(ctx.organization_id, vid)

    try:
        version = await promote_version(
            repo, ctx.organization_id, aid, vid, body.status
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    await _audit().write(
        ctx,
        "agent.version.promoted",
        "agent_version",
        vid,
        metadata={"status": body.status.value, "version_number": version.version_number},
    )
    return _version_response(version)
async def _check_promotion_gate(organization_id: UUID, version_id: UUID) -> None:
    """Bloquea promotion a production si el último run de evaluación de la
    versión no alcanza los thresholds configurados (gate opcional)."""
    from sqlalchemy import text

    from src.core.config import get_settings
    from src.infrastructure.postgres.session import get_async_session

    settings = get_settings()
    min_score = settings.EVAL_PROMOTION_MIN_SCORE
    max_hallucination = settings.EVAL_PROMOTION_MAX_HALLUCINATION
    if min_score <= 0 and max_hallucination >= 1.0:
        return

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT summary FROM eval_runs "
                    "WHERE organization_id = :oid AND version_id = :vid "
                    "AND target_type = 'agent' AND status = 'completed' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": organization_id, "vid": str(version_id)},
            )
        ).fetchone()
    finally:
        await session.close()

    if row is None:
        raise HTTPException(
            409,
            "Promotion blocked: no hay evaluación completada para esta versión "
            "(el promotion gate está activo).",
        )
    summary = row.summary if isinstance(row.summary, dict) else {}
    quality = summary.get("quality") or {}
    score = quality.get("composite_score")
    hallucination = quality.get("hallucination_rate")

    reasons = []
    if score is not None and min_score > 0 and score < min_score:
        reasons.append(f"score {score:.1f} < {min_score}")
    if hallucination is not None and max_hallucination < 1.0 and hallucination > max_hallucination:
        reasons.append(f"hallucination {hallucination:.2f} > {max_hallucination}")
    if reasons:
        raise HTTPException(
            409,
            "Promotion blocked por thresholds de evaluación: " + "; ".join(reasons),
        )
