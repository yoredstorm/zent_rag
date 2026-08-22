# =============================================================================
# Sources Routes — CRUD, discover, sync y upload de fuentes (Knowledge Platform)
# =============================================================================
# Toda operación deriva la organización del TenantContext. Acceso por ID a
# una fuente de otra organización -> 404 (no revela existencia).
# Las credenciales NO viajan en config_json (Vault es el path productivo).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from src.api.deps import (
    get_job_repo,
    get_source_repo,
)
from src.core.ports import IngestionJobRepository, SourceRepository
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Knowledge Sources"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class CreateSourceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(
        ..., pattern=r"^(sql|file|csv|excel|web|s3|api)$",
        description="Tipo de fuente: sql, file, csv, excel, web, s3, api",
    )
    knowledge_base_id: UUID | None = None
    config: dict = Field(default_factory=dict)


class UpdateSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    knowledge_base_id: UUID | None = None
    config: dict | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled|error)$")


def _source_response(source) -> dict:
    return {
        "id": str(source.id),
        "name": source.name,
        "type": source.type,
        "knowledge_base_id": str(source.knowledge_base_id) if source.knowledge_base_id else None,
        "config": source.config_json,
        "status": source.status,
        "created_at": source.created_at.isoformat(),
    }


async def _assert_own_kb(ctx, kb_id: UUID | None) -> None:
    if kb_id is None:
        return
    from src.api.deps import get_kb_repo

    kb = await get_kb_repo().get_kb(ctx.organization_id, kb_id)
    if kb is None:
        raise HTTPException(404, "Knowledge base not found in this organization")


# ---------------------------------------------------------------------------
# Listado y creación
# ---------------------------------------------------------------------------


@router.get("/sources", summary="Listar fuentes de la organización")
async def list_sources(
    request: Request,
    knowledge_base_id: UUID | None = Query(default=None),
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    sources = await repo.list_sources(ctx.organization_id, knowledge_base_id)
    return {"sources": [_source_response(s) for s in sources], "count": len(sources)}


@router.get("/knowledge-bases/{kb_id}/sources", summary="Fuentes de una KB")
async def list_kb_sources(
    kb_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        kid = UUID(kb_id)
    except ValueError:
        raise HTTPException(400, "kb_id must be a valid UUID")
    await _assert_own_kb(ctx, kid)
    sources = await repo.list_sources(ctx.organization_id, kid)
    return {"sources": [_source_response(s) for s in sources], "count": len(sources)}


@router.post("/sources", status_code=201, summary="Crear fuente de datos")
async def create_source(
    body: CreateSourceRequest,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    await _assert_own_kb(ctx, body.knowledge_base_id)
    source = await repo.create_source(
        ctx.organization_id,
        body.name,
        body.type,
        knowledge_base_id=body.knowledge_base_id,
        config_json=body.config,
    )
    await _audit().write(
        ctx, "source.created", "source", source.id,
        metadata={"name": source.name, "type": source.type},
    )
    return _source_response(source)


@router.post("/knowledge-bases/{kb_id}/sources", status_code=201, summary="Crear fuente en una KB")
async def create_kb_source(
    kb_id: str,
    body: CreateSourceRequest,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        kid = UUID(kb_id)
    except ValueError:
        raise HTTPException(400, "kb_id must be a valid UUID")
    await _assert_own_kb(ctx, kid)
    source = await repo.create_source(
        ctx.organization_id,
        body.name,
        body.type,
        knowledge_base_id=kid,
        config_json=body.config,
    )
    await _audit().write(
        ctx, "source.created", "source", source.id,
        metadata={"name": source.name, "type": source.type, "kb_id": kb_id},
    )
    return _source_response(source)


# ---------------------------------------------------------------------------
# Detalle / update / delete / discover / sync
# ---------------------------------------------------------------------------


async def _own_source(request: Request, source_id: str, repo: SourceRepository):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")
    return ctx, sid, source


@router.get("/sources/{source_id}", summary="Obtener fuente")
async def get_source(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    _ctx, _sid, source = await _own_source(request, source_id, repo)
    return _source_response(source)


@router.put("/sources/{source_id}", summary="Actualizar fuente")
async def update_source(
    source_id: str,
    body: UpdateSourceRequest,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    if await repo.get_source(ctx.organization_id, sid) is None:
        raise HTTPException(404, "Source not found")
    if body.knowledge_base_id is not None:
        await _assert_own_kb(ctx, body.knowledge_base_id)
    try:
        source = await repo.update_source(
            ctx.organization_id, sid, **body.model_dump(exclude_none=True)
        )
    except ValueError:
        raise HTTPException(404, "Source not found")
    await _audit().write(ctx, "source.updated", "source", sid, metadata={"name": source.name})
    return _source_response(source)


@router.delete("/sources/{source_id}", summary="Eliminar fuente")
async def delete_source(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")

    await repo.delete_source(ctx.organization_id, sid)
    # Limpiar vectores y registry de la fuente (nunca org-cruzado)
    from src.api.deps import get_doc_registry_repo, get_vector_store

    registry = get_doc_registry_repo()
    stale_ids = await registry.mark_missing_deleted(sid, set())
    if stale_ids:
        try:
            await get_vector_store().delete_points(ctx.organization_id, [str(i) for i in stale_ids])
        except Exception:
            raise HTTPException(500, "Failed to purge source vectors")
    await registry.delete_source_documents(sid)

    await _audit().write(ctx, "source.deleted", "source", sid, metadata={"name": source.name})
    return {"status": "deleted", "source_id": str(sid)}


@router.post("/sources/{source_id}/discover", summary="Descubrir elementos de la fuente")
async def discover_source(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")

    from src.knowledge.connectors.base import ConnectorError
    from src.knowledge.connectors.registry import build_connector

    connector = build_connector(source)
    try:
        await connector.connect()
        await connector.validate()
        items = await connector.discover()
    except ConnectorError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        logger.error("Source discover failed", error=str(exc), exc_info=True)
        raise HTTPException(500, f"Discovery failed: {exc}")
    return {
        "source_id": str(sid),
        "type": source.type,
        "items": [
            {"external_id": i.external_id, "label": i.label, **i.extra}
            for i in items[:200]
        ],
        "count": len(items),
    }


@router.post("/sources/{source_id}/sync", summary="Sincronizar fuente (background)")
async def sync_source(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
    jobs: IngestionJobRepository = Depends(get_job_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")

    job = await jobs.create_job(
        ctx.organization_id,
        job_type=f"sync_source:{source.type}",
        source_id=sid,
        knowledge_base_id=source.knowledge_base_id,
    )
    from src.knowledge.queue import enqueue_knowledge_job

    await enqueue_knowledge_job(str(job.id))
    await _audit().write(
        ctx, "source.sync_enqueued", "source", sid,
        metadata={"job_id": str(job.id), "name": source.name},
    )
    return {"job_id": str(job.id), "status": job.status.value, "source_id": str(sid)}


# ---------------------------------------------------------------------------
# Upload de archivos (crea fuente file/csv/excel con el objeto almacenado)
# ---------------------------------------------------------------------------


@router.post("/sources/files/upload", status_code=201, summary="Subir archivo como fuente")
async def upload_file_source(
    request: Request,
    file: UploadFile = File(...),
    knowledge_base_id: UUID | None = None,
    source_type: str | None = Query(default=None, pattern=r"^(file|csv|excel)$"),
    name: str | None = Query(default=None, max_length=255),
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    if knowledge_base_id is not None:
        await _assert_own_kb(ctx, knowledge_base_id)

    data = await file.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 25 MB)")

    filename = file.filename or "upload.bin"
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if source_type is None:
        if extension in ("csv",):
            source_type = "csv"
        elif extension in ("xlsx", "xls"):
            source_type = "excel"
        else:
            source_type = "file"

    from src.knowledge.storage import store_upload

    object_key = store_upload(ctx.organization_id, filename, data)
    config: dict = {"object_key": object_key, "filename": filename}
    if source_type == "csv":
        config["delimiter"] = ","

    source = await repo.create_source(
        ctx.organization_id,
        name or filename,
        source_type,
        knowledge_base_id=knowledge_base_id,
        config_json=config,
    )
    await _audit().write(
        ctx, "source.created", "source", source.id,
        metadata={"name": source.name, "type": source.type, "object_key": object_key},
    )
    return _source_response(source)
