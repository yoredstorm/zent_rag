# =============================================================================
# Connectors Routes — CRUD de conectores (organization-scoped)
# =============================================================================
# Las credenciales de conectores NUNCA viajan en config_json; se guardan en
# HashiCorp Vault (secret/<type>/<connector_id>). El API solo acepta
# parámetros no sensibles (host, schema allowlist, nombre de collección...).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_connector_repo
from src.core.ports import ConnectorRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/connectors", tags=["Connectors"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class CreateConnectorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern=r"^(sql|api|files)$")
    project_id: UUID | None = None
    config: dict = Field(default_factory=dict)


class UpdateConnectorRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    project_id: UUID | None = None
    config: dict | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled|error)$")


def _connector_response(connector) -> dict:
    return {
        "id": str(connector.id),
        "name": connector.name,
        "type": connector.type,
        "project_id": str(connector.project_id) if connector.project_id else None,
        "config": connector.config_json,
        "status": connector.status,
        "created_at": connector.created_at.isoformat(),
    }


@router.get("", summary="Listar conectores")
async def list_connectors(
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:read")
    connectors = await repo.list_connectors(ctx.organization_id)
    return {"connectors": [_connector_response(c) for c in connectors], "count": len(connectors)}


@router.post("", status_code=201, summary="Crear conector")
async def create_connector(
    body: CreateConnectorRequest,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:write")
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    connector = await repo.create_connector(
        ctx.organization_id,
        body.name,
        body.type,
        project_id=body.project_id,
        config_json=body.config,
    )
    await _audit().write(
        ctx, "connector.created", "connector", connector.id,
        metadata={"name": connector.name, "type": connector.type},
    )
    return _connector_response(connector)


@router.get("/{connector_id}", summary="Obtener conector")
async def get_connector(
    connector_id: str,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:read")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID")
    connector = await repo.get_connector(ctx.organization_id, cid)
    if connector is None:
        raise HTTPException(404, "Connector not found")
    return _connector_response(connector)


@router.put("/{connector_id}", summary="Actualizar conector")
async def update_connector(
    connector_id: str,
    body: UpdateConnectorRequest,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:write")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID")
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    fields = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    try:
        connector = await repo.update_connector(ctx.organization_id, cid, **fields)
    except ValueError:
        raise HTTPException(404, "Connector not found")
    await _audit().write(
        ctx, "connector.updated", "connector", cid, metadata={"name": connector.name}
    )
    return _connector_response(connector)


@router.delete("/{connector_id}", summary="Eliminar conector")
async def delete_connector(
    connector_id: str,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:write")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID")
    if await repo.get_connector(ctx.organization_id, cid) is None:
        raise HTTPException(404, "Connector not found")
    await repo.delete_connector(ctx.organization_id, cid)
    await _audit().write(ctx, "connector.deleted", "connector", cid)
    return {"status": "deleted", "connector_id": str(cid)}


async def _require_own_project(ctx, project_id: UUID) -> None:
    from src.api.deps import get_project_repo

    project = await get_project_repo().get_project(ctx.organization_id, project_id)
    if project is None:
        raise HTTPException(404, "Project not found in this organization")
