# =============================================================================
# Connectors Routes — CRUD de conectores (organization-scoped)
# =============================================================================
# Las credenciales de conectores NUNCA viajan en config_json; se guardan en
# HashiCorp Vault (secret/<type>/<connector_id>). El API solo acepta
# parámetros no sensibles (host, schema allowlist, nombre de collección...).
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_connector_repo
from src.core.config import get_settings
from src.core.ports import ConnectorRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/connectors", tags=["Connectors"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class CreateConnectorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern=r"^[a-zA-Z0-9_\-]{1,30}$")
    project_id: UUID | None = None
    config: dict = Field(default_factory=dict)
    # Credenciales cifradas: van al SecretStore, NUNCA a config_json.
    secrets: dict | None = None


class UpdateConnectorRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    project_id: UUID | None = None
    config: dict | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled|error)$")
    # Merge sobre secretos existentes; null = borrar todos.
    secrets: dict | None = None


def _connector_response(connector, has_secrets: bool | None = None) -> dict:
    payload = {
        "id": str(connector.id),
        "name": connector.name,
        "type": connector.type,
        "project_id": str(connector.project_id) if connector.project_id else None,
        "config": connector.config_json,
        "status": connector.status,
        "created_at": connector.created_at.isoformat(),
    }
    if has_secrets is not None:
        payload["has_secrets"] = has_secrets
    return payload


async def _load_plugin(request: Request, connector_id: str):
    """Plugin del conector con config + secrets del SecretStore."""
    from src.api.deps import get_connector_repo as _repo
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:read")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID") from None
    connector = await _repo().get_connector(ctx.organization_id, cid)
    if connector is None:
        raise HTTPException(404, "Connector not found")
    secrets = await get_secret_store().get(ctx.organization_id, cid)
    return connector, secrets


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
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.platform.billing.plan_limits import (
        PlanLimitError,
        check_resource_limit,
    )
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:write")
    try:
        await check_resource_limit(ctx.organization_id, "connectors")
    except PlanLimitError as exc:
        raise HTTPException(409, str(exc)) from None
    _require_known_type(body.type)
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    connector = await repo.create_connector(
        ctx.organization_id,
        body.name,
        body.type,
        project_id=body.project_id,
        config_json=body.config,
    )
    if body.secrets:
        await get_secret_store().put(
            ctx.organization_id, connector.id, body.secrets
        )
    await _audit().write(
        ctx, "connector.created", "connector", connector.id,
        metadata={"name": connector.name, "type": connector.type},
    )
    return _connector_response(
        connector, has_secrets=bool(body.secrets)
    )


@router.get("/types", summary="Tipos de conectores registrados")
async def connector_types(request: Request):
    from src.connectors.plugin import plugin_types
    from src.platform.rbac.policy import require_permission

    require_permission(request, "connectors:read")
    types = plugin_types()
    return {
        "types": [
            {
                "type": name,
                "capabilities": sorted(info.capabilities),
                "required_secret_keys": info.required_secret_keys,
            }
            for name, info in types.items()
        ],
        "count": len(types),
    }


@router.get("/{connector_id}", summary="Obtener conector")
async def get_connector(
    connector_id: str,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:read")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID")
    connector = await repo.get_connector(ctx.organization_id, cid)
    if connector is None:
        raise HTTPException(404, "Connector not found")
    secrets = await get_secret_store().get(ctx.organization_id, cid)
    return _connector_response(connector, has_secrets=bool(secrets))


@router.put("/{connector_id}", summary="Actualizar conector")
async def update_connector(
    connector_id: str,
    body: UpdateConnectorRequest,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:write")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID")
    if body.project_id is not None:
        await _require_own_project(ctx, body.project_id)
    fields = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    secrets_payload = fields.pop("secrets", None)
    try:
        connector = await repo.update_connector(ctx.organization_id, cid, **fields)
    except ValueError:
        raise HTTPException(404, "Connector not found")
    if secrets_payload:
        # Merge: nuevos valores sobre los existentes (nunca reemplazo ciego).
        current = await get_secret_store().get(ctx.organization_id, cid)
        merged = {**current, **secrets_payload}
        await get_secret_store().put(ctx.organization_id, cid, merged)
    elif secrets_payload is None and "secrets" in body.model_fields_set:
        await get_secret_store().delete(ctx.organization_id, cid)
    await _audit().write(
        ctx, "connector.updated", "connector", cid, metadata={"name": connector.name}
    )
    has = bool(await get_secret_store().get(ctx.organization_id, cid))
    return _connector_response(connector, has_secrets=has)


@router.delete("/{connector_id}", summary="Eliminar conector")
async def delete_connector(
    connector_id: str,
    request: Request,
    repo: ConnectorRepository = Depends(get_connector_repo),
):
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "connectors:write")
    try:
        cid = UUID(connector_id)
    except ValueError:
        raise HTTPException(400, "connector_id must be a valid UUID")
    if await repo.get_connector(ctx.organization_id, cid) is None:
        raise HTTPException(404, "Connector not found")
    await repo.delete_connector(ctx.organization_id, cid)
    await get_secret_store().delete(ctx.organization_id, cid)
    await _audit().write(ctx, "connector.deleted", "connector", cid)
    return {"status": "deleted", "connector_id": str(cid)}


@router.post("/{connector_id}/test", summary="Probar conexión del conector")
async def test_connector(connector_id: str, request: Request):
    from src.connectors.plugin import get_plugin, redact
    from src.platform.rbac.policy import require_permission

    connector, secrets = await _load_plugin(request, connector_id)
    try:
        plugin = get_plugin(connector.type, connector.config_json, secrets)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    timeout = get_settings().CONNECTOR_TEST_TIMEOUT_SECONDS + 2
    try:
        result = await asyncio.wait_for(
            plugin.test_connection(), timeout=float(timeout)
        )
    except asyncio.TimeoutError:
        raise HTTPException(422, "Connection test timed out") from None
    finally:
        try:
            await plugin.close()
        except Exception:
            pass
    ctx = require_permission(request, "connectors:read")
    await _audit().write(
        ctx, "connector.test", "connector", connector.id,
        metadata={"ok": result.ok},
    )
    payload = {
        "ok": result.ok,
        "latency_ms": round(result.latency_ms, 2),
        "message": redact(result.message),
        "server_version": result.server_version,
    }
    return payload


@router.post("/{connector_id}/discover", summary="Descubrir schema del conector")
async def discover_connector(connector_id: str, request: Request):
    from src.connectors.plugin import ConnectorError, get_plugin, redact
    from src.platform.rbac.policy import require_permission

    connector, secrets = await _load_plugin(request, connector_id)
    try:
        plugin = get_plugin(connector.type, connector.config_json, secrets)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    try:
        discovery = await asyncio.wait_for(
            plugin.discover(),
            timeout=float(get_settings().CONNECTOR_TEST_TIMEOUT_SECONDS + 20),
        )
    except asyncio.TimeoutError:
        raise HTTPException(422, "Discovery timed out") from None
    except ConnectorError as exc:
        raise HTTPException(422, redact(str(exc))) from None
    finally:
        try:
            await plugin.close()
        except Exception:
            pass
    ctx = require_permission(request, "connectors:read")
    await _audit().write(
        ctx, "connector.discover", "connector", connector.id,
        metadata={"tables": len(discovery.tables)},
    )
    return discovery.to_dict()


@router.get("/{connector_id}/capabilities", summary="Capacidades del conector")
async def connector_capabilities(connector_id: str, request: Request):
    from src.connectors.plugin import get_plugin_class

    connector, _secrets = await _load_plugin(request, connector_id)
    cls = get_plugin_class(connector.type)
    if cls is None:
        raise HTTPException(400, f"Unknown connector type: {connector.type}")
    return {
        "connector_id": str(connector.id),
        "type": connector.type,
        "capabilities": sorted(cls.capabilities),
        "required_secret_keys": list(cls.required_secret_keys),
    }


def _require_known_type(connector_type: str) -> None:
    from src.connectors.plugin import get_plugin_class

    if get_plugin_class(connector_type) is None:
        raise HTTPException(400, f"Unknown connector type: {connector_type}")


async def _require_own_project(ctx, project_id: UUID) -> None:
    from src.api.deps import get_project_repo

    project = await get_project_repo().get_project(ctx.organization_id, project_id)
    if project is None:
        raise HTTPException(404, "Project not found in this organization")
