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
        await _check_promotion_gate(ctx.organization_id, aid, vid)

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
async def _check_promotion_gate(
    organization_id: UUID, agent_id: UUID, version_id: UUID
) -> None:
    """FASE 03 (S4/S5): bloquea promotion a production si la evaluación de la
    versión candidata no pasa el quality gate configurado, o si hay una
    regresión vs la versión actualmente desplegada."""
    from sqlalchemy import text

    from src.api.deps import get_agent_repo
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.quality.gates import (
        gate_blocked,
        get_gate,
        regression_blocked,
    )

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
    candidate_quality = summary.get("quality") or {}

    # Gate configurado por org (y por workspace del agente si existe).
    workspace_id = None
    try:
        agent = await get_agent_repo().get_agent(organization_id, agent_id)
        workspace_id = getattr(agent, "workspace_id", None)
    except Exception:  # noqa: BLE001
        pass
    gate = await get_gate(organization_id, workspace_id)

    reasons = await gate_blocked(candidate_quality, gate)

    # Regresión vs la versión desplegada (S5): comparar candidata contra la
    # eval de la versión production actual del agente.
    baseline_quality = None
    if not reasons:
        base = (
            await session.execute(
                text(
                    "SELECT v.id FROM agent_versions v "
                    "WHERE v.agent_id = :aid AND v.status = 'production' "
                    "ORDER BY v.version_number DESC LIMIT 1"
                ),
                {"aid": str(agent_id)},
            )
        ).fetchone()
        if base is not None:
            baseline = (
                await session.execute(
                    text(
                        "SELECT summary FROM eval_runs "
                        "WHERE organization_id = :oid AND version_id = :vid "
                        "AND target_type = 'agent' AND status = 'completed' "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"oid": organization_id, "vid": str(base["id"])},
                )
            ).fetchone()
            if baseline is not None and isinstance(baseline.summary, dict):
                baseline_quality = baseline.summary.get("quality") or {}
        reasons = await regression_blocked(candidate_quality, baseline_quality, gate)

    if reasons:
        raise HTTPException(
            409,
            "Promotion blocked: " + "; ".join(reasons[:6]),
        )
