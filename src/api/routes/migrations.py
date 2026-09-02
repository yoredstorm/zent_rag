# =============================================================================
# Tenant Data Migration Tools — import/export de KBs y agentes.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/migrations", tags=["Migrations"])


@router.post("/import/preview", summary="Dry-run: validar y previsualizar import")
async def tenant_migration_preview(body: ImportPreviewIn, request: Request):
    from src.platform.migrate.migrations import preview_import, stage_content
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        result = await preview_import(
            ctx.organization_id, body.kind, body.content, body.filename, ctx.user_id
        )
        await stage_content(UUID(result["migration_id"]), body.content)
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/import/apply", summary="Aplicar import (dry-run → applied)")
async def tenant_migration_apply(body: MigrationApplyIn, request: Request):
    from src.platform.migrate.migrations import apply_import
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await apply_import(ctx.organization_id, UUID(body.migration_id))
    if result is None:
        raise HTTPException(404, "Migration not found or not in dry_run")
    return result


@router.post("/export", summary="Exportar KBs/agentes con manifest")
async def tenant_migration_export(body: MigrationExportIn, request: Request):
    from src.platform.migrate.migrations import export_migration
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    try:
        return await export_migration(ctx.organization_id, body.kind, ctx.user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("", summary="Historial de migraciones")
async def tenant_migrations_list(request: Request):
    from src.platform.migrate.migrations import list_migrations
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_migrations(ctx.organization_id)


@router.get("/export/{migration_id}/download", summary="Descargar export")
async def tenant_migration_export_download(migration_id: str, request: Request):
    from src.platform.migrate.migrations import get_export_file
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    result = await get_export_file(UUID(migration_id))
    if result is None:
        raise HTTPException(404, "Export not found")
    content, filename = result
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/agents/{agent_id}/reversion", summary="Re-versión del agente")
async def tenant_migration_reversion(agent_id: str, request: Request):
    from src.platform.migrate.migrations import reversion_agent
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await reversion_agent(ctx.organization_id, UUID(agent_id))
    if result is None:
        raise HTTPException(404, "Agent not found")
    return result


class ImportPreviewIn(BaseModel):
    kind: str = Field(..., pattern="^(kb|agents|full)$")
    content: str
    filename: str = Field(default="import.json", max_length=300)


class MigrationApplyIn(BaseModel):
    migration_id: str


class MigrationExportIn(BaseModel):
    kind: str = Field(..., pattern="^(kb|agents|full)$")
