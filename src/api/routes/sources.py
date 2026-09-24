# =============================================================================
# Sources Routes — CRUD, discover, sync y upload de fuentes (Knowledge Platform)
# =============================================================================
# Toda operación deriva la organización del TenantContext. Acceso por ID a
# una fuente de otra organización -> 404 (no revela existencia).
# Las credenciales NO viajan en config_json (Vault es el path productivo).
# =============================================================================
from __future__ import annotations

import json
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.api.deps import (
    get_job_repo,
    get_source_repo,
)
from src.core.config import get_settings
from src.core.ports import IngestionJobRepository, SourceRepository
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.workspaces.context import resolve_workspace

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Knowledge Sources"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _normalize_filename(name: str) -> str:
    """Normaliza nombre+extensión para detectar duplicados.

    Colapsa espacios, minúsculas y el sufijo de copia del navegador:
    "ATPCO (1).xlsx" ≡ "atpco.xlsx".
    """
    value = re.sub(r"\s+", " ", (name or "").strip().lower())
    stem, dot, extension = value.rpartition(".")
    if not dot:
        stem, extension = value, ""
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem).strip()
    return f"{stem}.{extension}" if extension else stem


async def _find_duplicate_source(repo: SourceRepository, organization_id, filename: str):
    """Fuente existente con el mismo nombre+extensión (ignora borradas)."""
    normalized = _normalize_filename(filename)
    if not normalized:
        return None
    try:
        sources = await repo.list_sources(organization_id)
    except Exception as exc:  # noqa: BLE001 - el aviso nunca bloquea la ingesta
        logger.warning("Duplicate source check failed", error=str(exc)[:200])
        return None
    for source in sources:
        status = str(getattr(source, "status", "") or "")
        if status in ("deleted", "archived"):
            continue
        if _normalize_filename(getattr(source, "name", "") or "") == normalized:
            return source
    return None


async def _next_copy_name(repo: SourceRepository, organization_id, base_name: str) -> str:
    """Nombre libre para una copia forzada (kb_sources tiene UNIQUE org+name)."""
    try:
        sources = await repo.list_sources(organization_id)
        existing = {getattr(s, "name", "") or "" for s in sources}
    except Exception:  # noqa: BLE001
        existing = set()
    if base_name not in existing:
        return base_name
    stem, dot, extension = base_name.rpartition(".")
    if not dot:
        stem, extension = base_name, ""
    for index in range(2, 100):
        candidate = f"{stem} ({index})" + (f".{extension}" if extension else "")
        if candidate not in existing:
            return candidate
    return f"{base_name} copia {uuid4().hex[:6]}"


class CreateSourceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(
        ..., pattern=r"^(sql|file|csv|excel|web|s3|api|gdrive)$",
        description="Tipo de fuente: sql, file, csv, excel, web, s3, api, gdrive",
    )
    knowledge_base_id: UUID | None = None
    config: dict = Field(default_factory=dict)


class UpdateSourceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    knowledge_base_id: UUID | None = None
    config: dict | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(created|connected|discovering|profiled|ready|ingesting|indexed|error)$",
    )
    # Ciclo de vida: created|connected|discovering|profiled|ready|ingesting|indexed|error


def _source_response(source, extra: dict | None = None) -> dict:
    payload = {
        "id": str(source.id),
        "name": source.name,
        "type": source.type,
        "knowledge_base_id": str(source.knowledge_base_id) if source.knowledge_base_id else None,
        "workspace_id": str(source.workspace_id) if getattr(source, "workspace_id", None) else None,
        "config": source.config_json,
        "status": source.status,
        "created_at": source.created_at.isoformat(),
        "last_sync": None,
        "last_error": None,
        "document_count": 0,
        "error_count": 0,
        "last_processed_count": 0,
    }
    if extra:
        payload.update(extra)
    return payload


async def _enqueue_source_sync(ctx, jobs: IngestionJobRepository, source):
    job = await jobs.create_job(
        ctx.organization_id,
        job_type=f"sync_source:{source.type}",
        source_id=source.id,
        knowledge_base_id=source.knowledge_base_id,
    )
    from src.knowledge.queue import enqueue_knowledge_job

    await enqueue_knowledge_job(str(job.id))
    await _audit().write(
        ctx, "source.sync_enqueued", "source", source.id,
        metadata={"job_id": str(job.id), "name": source.name},
    )
    return job


async def _source_stats(organization_id: UUID, source_ids: list[UUID]) -> dict[UUID, dict]:
    if not source_ids:
        return {}
    from sqlalchemy import bindparam
    from sqlalchemy import text as sql_text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        stmt = sql_text(
            """
            SELECT s.id AS source_id,
                   st.last_success_at,
                   st.last_error,
                   COALESCE(st.last_processed_count, 0)::int AS last_processed_count,
                   COALESCE(docs.document_count, 0)::int AS document_count,
                   COALESCE(jobs.error_count, 0)::int AS error_count
            FROM kb_sources s
            LEFT JOIN source_sync_state st ON st.source_id = s.id
            LEFT JOIN (
                SELECT source_id, COUNT(*)::int AS document_count
                FROM source_documents
                WHERE organization_id = :oid AND status = 'active'
                GROUP BY source_id
            ) docs ON docs.source_id = s.id
            LEFT JOIN (
                SELECT source_id, COUNT(*)::int AS error_count
                FROM ingestion_jobs
                WHERE organization_id = :oid2 AND status IN ('failed', 'dead')
                GROUP BY source_id
            ) jobs ON jobs.source_id = s.id
            WHERE s.organization_id = :oid3 AND s.id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True))
        rows = (
            await session.execute(
                stmt,
                {
                    "oid": organization_id,
                    "oid2": organization_id,
                    "oid3": organization_id,
                    "ids": source_ids,
                },
            )
        ).fetchall()
        stats: dict[UUID, dict] = {}
        for row in rows:
            stats[row.source_id] = {
                "last_sync": row.last_success_at.isoformat() if row.last_success_at else None,
                "last_error": row.last_error,
                "last_processed_count": row.last_processed_count,
                "document_count": row.document_count,
                "error_count": row.error_count,
            }
        return stats
    finally:
        await session.close()


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
    ws = await resolve_workspace(request)
    sources = await repo.list_sources(
        ctx.organization_id, knowledge_base_id, workspace_id=ws.id
    )
    stats = await _source_stats(ctx.organization_id, [s.id for s in sources])
    return {
        "sources": [_source_response(s, stats.get(s.id)) for s in sources],
        "count": len(sources),
    }


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
    stats = await _source_stats(ctx.organization_id, [s.id for s in sources])
    return {
        "sources": [_source_response(s, stats.get(s.id)) for s in sources],
        "count": len(sources),
    }


@router.post("/sources", status_code=201, summary="Crear fuente de datos")
async def create_source(
    body: CreateSourceRequest,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    await _assert_own_kb(ctx, body.knowledge_base_id)
    ws = await resolve_workspace(request)
    source = await repo.create_source(
        ctx.organization_id,
        body.name,
        body.type,
        knowledge_base_id=body.knowledge_base_id,
        config_json=body.config,
        workspace_id=ws.id,
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
    ws = await resolve_workspace(request)
    source = await repo.create_source(
        ctx.organization_id,
        body.name,
        body.type,
        knowledge_base_id=kid,
        config_json=body.config,
        workspace_id=ws.id,
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


@router.get(
    "/sources/{source_id}/usage",
    summary="Agentes que usan la fuente (advertencia antes de eliminarla)",
)
async def source_usage(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Agentes que dejarían de usar la fuente: directa (`source_ids`) o por
    su colección (`knowledge_base_ids`)."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    ctx, sid, source = await _own_source(request, source_id, repo)
    params: dict = {"oid": ctx.organization_id, "sid": str(sid)}
    select = (
        "SELECT id, name, is_active, "
        "CASE WHEN config_json->'source_ids' @> to_jsonb(ARRAY[:sid]::text[]) "
        "THEN 'source' ELSE 'knowledge_base' END AS via "
        "FROM agents WHERE organization_id = :oid AND ("
        "config_json->'source_ids' @> to_jsonb(ARRAY[:sid]::text[])"
    )
    if source.knowledge_base_id is not None:
        params["kid"] = str(source.knowledge_base_id)
        query = (
            select
            + " OR config_json->'knowledge_base_ids' @> "
            "to_jsonb(ARRAY[:kid]::text[])"
        )
    else:
        query = select
    query += ") ORDER BY is_active DESC, name"
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(query),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    agents = [
        {
            "id": str(row.id),
            "name": row.name,
            "is_active": bool(row.is_active),
            "via": row.via,
        }
        for row in rows
    ]
    return {"source_id": str(sid), "agents": agents, "count": len(agents)}


@router.get("/sources/{source_id}", summary="Obtener fuente")
async def get_source(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    ctx, sid, source = await _own_source(request, source_id, repo)
    stats = await _source_stats(ctx.organization_id, [sid])
    return _source_response(source, stats.get(sid))


@router.get("/sources/{source_id}/documents", summary="Documentos indexados de una fuente")
async def list_source_documents(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
    limit: int = Query(default=100, ge=1, le=200),
):
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    ctx, sid, _source = await _own_source(request, source_id, repo)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, external_id, document_id, status, last_seen_at "
                    "FROM source_documents "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "ORDER BY last_seen_at DESC "
                    "LIMIT :lim"
                ),
                {"oid": ctx.organization_id, "sid": sid, "lim": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "source_id": str(sid),
        "documents": [
            {
                "id": r.id,
                "external_id": r.external_id,
                "document_id": str(r.document_id),
                "status": r.status,
                "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


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

    # 1) Vectores y registry primero: si esto falla, la fuente sigue entera y se
    #    puede reintentar la eliminación sin quedar a medias.
    from src.api.deps import get_doc_registry_repo, get_vector_store

    registry = get_doc_registry_repo()
    stale_ids = await registry.mark_missing_deleted(sid, set())
    if stale_ids:
        try:
            await get_vector_store().delete_points(ctx.organization_id, [str(i) for i in stale_ids])
        except Exception:
            raise HTTPException(500, "Failed to purge source vectors")
    # 2) La fuente y sus documentos.
    await repo.delete_source(ctx.organization_id, sid)
    await registry.delete_source_documents(sid)
    # 3) Referencias: los agentes que la usaban dejan de apuntarle (es lo que
    #    promete la advertencia del portal). Sin esto quedan ids colgados.
    detached = await _detach_source_from_agents(ctx, sid)

    await _audit().write(
        ctx,
        "source.deleted",
        "source",
        sid,
        metadata={"name": source.name, "agents_updated": len(detached)},
    )
    return {
        "status": "deleted",
        "source_id": str(sid),
        "agents_updated": len(detached),
        "agents": detached[:20],
    }


async def _detach_source_from_agents(ctx, source_id: UUID) -> list[str]:
    """Quita la fuente de `config_json.source_ids` en todos los agentes de la org.

    `knowledge_base_ids` no se toca: la colección sigue existiendo aunque se borre
    una de sus fuentes. Devuelve los nombres de los agentes actualizados.
    """
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "UPDATE agents SET "
                    "config_json = jsonb_set("
                    "  config_json, '{source_ids}', coalesce(("
                    "    SELECT jsonb_agg(value) FROM jsonb_array_elements_text("
                    "      config_json->'source_ids') AS value WHERE value <> :sid"
                    "  ), '[]'::jsonb)), updated_at = now() "
                    "WHERE organization_id = :oid "
                    "AND config_json->'source_ids' @> to_jsonb(ARRAY[:sid]::text[]) "
                    "RETURNING name"
                ),
                {"oid": ctx.organization_id, "sid": str(source_id)},
            )
        ).fetchall()
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    names = [str(row[0]) for row in rows]
    if names:
        logger.warning(
            "source deleted; agents detached",
            organization_id=str(ctx.organization_id),
            source_id=str(source_id),
            agents=names[:10],
            agents_count=len(names),
        )
    return names


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

    job = await _enqueue_source_sync(ctx, jobs, source)
    return {"job_id": str(job.id), "status": job.status.value, "source_id": str(sid)}


# ---------------------------------------------------------------------------
# Upload de archivos (crea fuentes file/csv/excel con el objeto almacenado)
# ---------------------------------------------------------------------------

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_MAX_BATCH_FILES = 20


async def _store_uploaded_file(
    ctx,
    repo: SourceRepository,
    jobs: IngestionJobRepository,
    *,
    filename: str,
    data: bytes,
    knowledge_base_id: UUID | None,
    source_type: str | None,
    name: str | None,
    force: bool,
    workspace_id: UUID | None = None,
):
    """Crea fuente + job para un archivo. Lanza HTTPException 413/415/409."""
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 25 MB)")

    from src.platform.data_onboarding.mime import MimeRejected, detect_source_type

    try:
        detected = detect_source_type(filename, data)
    except MimeRejected as exc:
        raise HTTPException(415, str(exc)) from None

    if source_type is None:
        source_type = detected

    # Duplicados por nombre+extensión (cualquier documento): avisa y reusa la
    # fuente existente salvo force=true. Detecta el sufijo "(1)" del navegador.
    duplicate = await _find_duplicate_source(
        repo, ctx.organization_id, name or filename
    )
    if duplicate is not None and not force:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "duplicate_name",
                "message": (
                    f"Ya existe una fuente con el mismo nombre: {duplicate.name}"
                ),
                "existing_source_id": str(duplicate.id),
                "existing_name": duplicate.name,
                "hint": "Abre la fuente existente o repite con force=true para copia.",
            },
        )

    from src.knowledge.storage import store_upload

    source_name = name or filename
    if force and duplicate is not None:
        source_name = await _next_copy_name(repo, ctx.organization_id, source_name)

    object_key = store_upload(ctx.organization_id, filename, data)
    config: dict = {"object_key": object_key, "filename": filename}
    if source_type == "csv":
        config["delimiter"] = ","

    source = await repo.create_source(
        ctx.organization_id,
        source_name,
        source_type,
        knowledge_base_id=knowledge_base_id,
        config_json=config,
        workspace_id=workspace_id,
    )
    await _audit().write(
        ctx, "source.created", "source", source.id,
        metadata={"name": source.name, "type": source.type, "object_key": object_key},
    )
    job = await _enqueue_source_sync(ctx, jobs, source)
    return source, job


@router.post("/sources/files/upload", status_code=201, summary="Subir archivo como fuente")
async def upload_file_source(
    request: Request,
    file: UploadFile = File(...),
    knowledge_base_id: UUID | None = None,
    source_type: str | None = Query(default=None, pattern=r"^(file|csv|excel)$"),
    name: str | None = Query(default=None, max_length=255),
    force: bool = Query(
        default=False,
        description="Crear copia aunque exista otra fuente con el mismo nombre.",
    ),
    repo: SourceRepository = Depends(get_source_repo),
    jobs: IngestionJobRepository = Depends(get_job_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    if knowledge_base_id is not None:
        await _assert_own_kb(ctx, knowledge_base_id)
    ws = await resolve_workspace(request)
    source, job = await _store_uploaded_file(
        ctx,
        repo,
        jobs,
        filename=file.filename or "upload.bin",
        data=await file.read(),
        knowledge_base_id=knowledge_base_id,
        source_type=source_type,
        name=name,
        force=force,
        workspace_id=ws.id,
    )
    return _source_response(source, extra={"job_id": str(job.id)})


@router.post(
    "/sources/files/upload-batch",
    status_code=200,
    summary="Subir varios archivos como fuentes (resultado por archivo)",
)
async def upload_files_batch(
    request: Request,
    files: list[UploadFile] = File(...),
    knowledge_base_id: UUID | None = None,
    force: bool = Query(
        default=False,
        description="Crear copia aunque exista otra fuente con el mismo nombre.",
    ),
    repo: SourceRepository = Depends(get_source_repo),
    jobs: IngestionJobRepository = Depends(get_job_repo),
) -> dict:
    """Sube N archivos sin pedir nombre: cada fuente hereda el nombre del archivo.

    Nunca corta el lote: devuelve el resultado por archivo (created, duplicate,
    rejected, error). Cada fuente creada encola su job de indexado.
    """
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    if len(files) > _MAX_BATCH_FILES:
        raise HTTPException(
            422, f"Too many files per request (max {_MAX_BATCH_FILES})"
        )
    if knowledge_base_id is not None:
        await _assert_own_kb(ctx, knowledge_base_id)
    ws = await resolve_workspace(request)

    items: list[dict] = []
    created = duplicates = rejected = failed = 0
    for upload in files:
        filename = upload.filename or "upload.bin"
        data = await upload.read()
        try:
            source, job = await _store_uploaded_file(
                ctx,
                repo,
                jobs,
                filename=filename,
                data=data,
                knowledge_base_id=knowledge_base_id,
                source_type=None,
                name=None,
                force=force,
                workspace_id=ws.id,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            if exc.status_code == 409:
                status, duplicates = "duplicate", duplicates + 1
            elif exc.status_code in (413, 415):
                status, rejected = "rejected", rejected + 1
            else:
                status, failed = "error", failed + 1
            items.append(
                {
                    "filename": filename,
                    "status": status,
                    "error": detail.get("message") or str(exc.detail),
                    "existing_source_id": detail.get("existing_source_id"),
                    "existing_name": detail.get("existing_name"),
                    "http_status": exc.status_code,
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 — el lote no se corta
            logger.warning(
                "Batch upload failed", filename=filename, error=str(exc)[:200]
            )
            items.append(
                {
                    "filename": filename,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                }
            )
            failed += 1
            continue
        items.append(
            {
                "filename": filename,
                "status": "created",
                "source_id": str(source.id),
                "name": source.name,
                "job_id": str(job.id),
            }
        )
        created += 1
    return {
        "items": items,
        "created": created,
        "duplicates": duplicates,
        "rejected": rejected,
        "failed": failed,
    }

@router.post("/sources/{source_id}/profile", summary="Perfilizar fuente (SQL: null rates, cardinalidad, PII)")
async def profile_source(
    source_id: str,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    from sqlalchemy import text as _text

    from src.connectors.sql.profiling import profile_table
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:write")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")
    if source.type not in ("sql", "postgres"):
        raise HTTPException(400, "Profiling solo disponible para fuentes SQL")

    config = source.config_json or {}
    default_schema = config.get("schema") or "public"
    tables = config.get("tables") or [config.get("table")]
    table_refs: list[tuple[str, str]] = []
    for entry in tables:
        if not entry or not isinstance(entry, str):
            continue
        schema, _, table = str(entry).partition(".")
        if not table:
            schema, table = default_schema, schema
        table_refs.append((schema, table))

    session = await get_async_session()
    try:
        await session.execute(
            _text(
                "UPDATE kb_sources SET status = 'discovering', updated_at = NOW() "
                "WHERE id = :sid AND organization_id = :oid"
            ),
            {"sid": sid, "oid": ctx.organization_id},
        )
        await session.commit()
        profiled_tables = []
        profiled_columns = []
        for schema_name, table_name in table_refs:
            if not table_name or not isinstance(table_name, str):
                continue
            try:
                profile = await profile_table(session, schema_name, table_name)
            except Exception as exc:
                logger.warning(
                    "Profile failed for table", table=table_name, error=str(exc)
                )
                continue
            profiled_tables.append({"name": profile["name"], "columns": profile["columns"]})
            profiled_columns.extend(profile["columns"])
        await session.execute(
            _text(
                "INSERT INTO source_profiles (id, organization_id, source_id, columns, tables) "
                "VALUES (uuid_generate_v4(), :oid, :sid, CAST(:cols AS jsonb), CAST(:tabs AS jsonb))"
            ),
            {
                "oid": ctx.organization_id,
                "sid": sid,
                "cols": json.dumps(profiled_columns),
                "tabs": json.dumps(profiled_tables),
            },
        )
        await session.execute(
            _text(
                "UPDATE kb_sources SET status = 'profiled', updated_at = NOW() "
                "WHERE id = :sid AND organization_id = :oid"
            ),
            {"sid": sid, "oid": ctx.organization_id},
        )
        await session.commit()
    finally:
        await session.close()
    await _audit().write(
        ctx, "source.profiled", "source", sid,
        metadata={"tables": len(profiled_tables), "columns": len(profiled_columns)},
    )
    return {"source_id": str(sid), "status": "profiled", "tables": profiled_tables}


@router.get(
    "/sources/{source_id}/tabular",
    summary="Representación tabular estructurada (Excel/CSV)",
)
async def get_source_tabular(source_id: str, request: Request):
    """Workbooks + tablas detectadas + estado de representaciones (§35).

    Solo lectura; datos scoped por organización (nunca cross-tenant)."""
    from src.infrastructure.postgres.tabular import PostgresTabularRepository
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")

    from sqlalchemy import text as _text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        exists = (
            await session.execute(
                _text(
                    "SELECT 1 FROM kb_sources WHERE id = :sid AND organization_id = :oid"
                ),
                {"sid": sid, "oid": ctx.organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if exists is None:
        raise HTTPException(404, "Source not found")

    repository = PostgresTabularRepository()
    workbooks = await repository.list_workbooks(ctx.organization_id, sid)
    tables = await repository.list_tables(ctx.organization_id, sid)
    filename_by_workbook = {
        workbook["id"]: workbook.get("filename") for workbook in workbooks
    }
    from src.knowledge.tabular.map import build_tabular_map, render_tabular_map_text

    tabular_map = await build_tabular_map(
        repository, ctx.organization_id, source_ids=[sid]
    )
    return {
        "source_id": str(sid),
        "workbooks": workbooks,
        "map": render_tabular_map_text(tabular_map),
        "tables": [
            {
                "id": table["id"],
                "workbook_id": table["workbook_id"],
                "workbook": filename_by_workbook.get(table["workbook_id"]),
                "name": table["name"],
                "title": table["title"],
                "row_count": table["row_count"],
                "column_count": table["column_count"],
                "detection_method": table["detection_method"],
                "detection_confidence": table["detection_confidence"],
                "header_rows": table["header_rows"],
                "range": table["range"],
            }
            for table in tables
        ],
    }


class SourceTestQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


class SourceSqlRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)


async def _materialized_table_names(
    organization_id: UUID, source_id: UUID
) -> set[str]:
    """Tablas materializadas (`zent_*`) de una fuente, en minúsculas."""
    from src.infrastructure.postgres.tabular import PostgresTabularRepository

    names: set[str] = set()
    try:
        workbooks = await PostgresTabularRepository().list_workbooks(
            organization_id, source_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Materialized table lookup failed", error=str(exc)[:200])
        return names
    for workbook in workbooks:
        materialization = workbook.get("materialization") or {}
        for table in materialization.get("tables") or []:
            if table.get("name"):
                names.add(str(table["name"]).lower())
    return names


async def _org_materialized_table_names(organization_id: UUID) -> set[str]:
    """Todas las tablas materializadas de la organización (para joins)."""
    from src.infrastructure.postgres.tabular import PostgresTabularRepository

    names: set[str] = set()
    try:
        workbooks = await PostgresTabularRepository().list_workbooks(organization_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Org materialized table lookup failed", error=str(exc)[:200])
        return names
    for workbook in workbooks:
        materialization = workbook.get("materialization") or {}
        for table in materialization.get("tables") or []:
            if table.get("name"):
                names.add(str(table["name"]).lower())
    return names


def _jsonable_row(row) -> list:
    return [
        value
        if isinstance(value, (int, float, str, bool, type(None)))
        else str(value)
        for value in row
    ]


@router.get(
    "/sources/{source_id}/table-preview",
    summary="Vista previa de la tabla materializada (solo lectura)",
)
async def source_table_preview(
    source_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    repo: SourceRepository = Depends(get_source_repo),
):
    """Columnas + primeras filas de la tabla SQL de la fuente.

    Usa la Managed DB (reader) si la tabla está materializada; si no, cae a la
    representación estructurada canónica (`tabular_rows`)."""
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")

    table_names = await _materialized_table_names(ctx.organization_id, sid)
    if table_names:
        from src.platform.managed_db.service import open_managed_query_session

        session = await open_managed_query_session(
            ctx.organization_id, source.workspace_id
        )
        if session is not None:
            table_name = sorted(table_names)[0]
            try:
                result = await session.execute(
                    text(f'SELECT * FROM "{table_name}" LIMIT {int(limit)}')  # noqa: S608 (tabla de la whitelist, limit acotado)
                )
                rows = result.fetchall()
                columns = list(result.keys()) if rows else []
                return {
                    "source_id": str(sid),
                    "origin": "managed_db",
                    "table": table_name,
                    "columns": columns,
                    "rows": [_jsonable_row(row) for row in rows],
                    "count": len(rows),
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("Table preview failed", error=str(exc)[:200])
            finally:
                await session.close()

    # Fallback: representación estructurada canónica.
    from src.infrastructure.postgres.tabular import PostgresTabularRepository

    repository = PostgresTabularRepository()
    tables = await repository.list_tables(ctx.organization_id, sid)
    if not tables:
        return {
            "source_id": str(sid),
            "origin": "none",
            "table": None,
            "columns": [],
            "rows": [],
            "count": 0,
        }
    table = tables[0]
    schema = await repository.get_table(ctx.organization_id, UUID(table["id"]))
    rows = await repository.fetch_rows(
        ctx.organization_id, UUID(table["id"]), limit=int(limit)
    )
    columns = [
        column.get("original_name") or column.get("normalized_name")
        for column in (schema or {}).get("columns", [])
    ]
    normalized = [column.get("normalized_name") for column in (schema or {}).get("columns", [])]
    return {
        "source_id": str(sid),
        "origin": "tabular",
        "table": table["name"],
        "columns": columns,
        "rows": [
            [row.get("values", {}).get(name, "") for name in normalized] for row in rows
        ],
        "count": len(rows),
    }


@router.post(
    "/sources/{source_id}/sql",
    summary="SQL read-only sobre las tablas materializadas de la fuente",
)
async def source_sql(
    source_id: str,
    payload: SourceSqlRequest,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    """SELECT-only contra la Managed DB, acotado a las tablas de esta fuente."""
    import asyncio
    import re as _re

    from sqlalchemy import text as _text

    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:sql")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")

    table_names = await _materialized_table_names(ctx.organization_id, sid)
    if not table_names:
        raise HTTPException(
            400,
            "La fuente no tiene tabla materializada (requiere Managed DB y un sync)",
        )
    # Whitelist: cualquier tabla materializada de la organización (permite
    # joins entre fuentes); el resto del esquema queda fuera.
    allowed_tables = await _org_materialized_table_names(ctx.organization_id) or table_names

    sql = payload.query.strip().rstrip(";").strip()
    from src.agents.tools.sql_expert_postgres import (
        _FORBIDDEN_KEYWORDS,
        SqlValidationError,
        _validate_sql_ast,
    )

    if _FORBIDDEN_KEYWORDS.search(sql):
        raise HTTPException(400, "Solo se permiten consultas SELECT de lectura")
    try:
        _validate_sql_ast(sql)
    except SqlValidationError as exc:
        raise HTTPException(400, str(exc)[:300]) from None

    import sqlglot

    try:
        referenced = {
            table.name.lower()
            for table in sqlglot.parse_one(sql).find_all(sqlglot.exp.Table)
        }
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "SQL inválido") from None
    if not referenced:
        raise HTTPException(400, "La consulta no referencia ninguna tabla")
    unknown = sorted(referenced - allowed_tables)
    if unknown:
        raise HTTPException(
            403,
            "Solo podés consultar tablas materializadas de la organización: "
            + ", ".join(sorted(allowed_tables)),
        )

    from src.infrastructure.postgres.readonly_session import apply_readonly_transaction
    from src.platform.managed_db.service import open_managed_query_session

    settings = get_settings()
    timeout_seconds = float(settings.RAG_SQL_TIMEOUT_SECONDS)
    max_rows = int(settings.RAG_SQL_MAX_ROWS)
    session = await open_managed_query_session(ctx.organization_id, source.workspace_id)
    if session is None:
        raise HTTPException(400, "Managed DB no disponible para esta organización")
    try:
        await apply_readonly_transaction(session, timeout_seconds)
        if not _re.search(r"\bLIMIT\s+\d+\s*$", sql, _re.IGNORECASE):
            sql = f"{sql} LIMIT {max_rows}"
        result = await asyncio.wait_for(
            session.execute(_text(sql)), timeout=timeout_seconds
        )
        rows = result.fetchall()
        columns = list(result.keys()) if rows else []
    except TimeoutError:
        raise HTTPException(504, "La consulta excedió el timeout") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)[:300]) from None
    finally:
        await session.close()
    return {
        "source_id": str(sid),
        "sql": sql,
        "columns": columns,
        "rows": [_jsonable_row(row) for row in rows],
        "count": len(rows),
        "truncated": len(rows) >= max_rows,
        "tables": sorted(allowed_tables),
    }


@router.post(
    "/sources/{source_id}/test-query",
    summary="Probar una consulta exacta contra la fuente (SQL-first, sin LLM)",
)
async def test_source_query(
    source_id: str,
    payload: SourceTestQueryRequest,
    request: Request,
    repo: SourceRepository = Depends(get_source_repo),
):
    """Ejecuta el resolutor estructurado (Excel/CSV) y devuelve valor + procedencia.

    Es el mismo camino que usa el agente para datos exactos; sirve para validar
    la confiabilidad de la fuente desde el portal sin gastar embeddings.
    """
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    source = await repo.get_source(ctx.organization_id, sid)
    if source is None:
        raise HTTPException(404, "Source not found")

    from src.api.deps import get_tabular_query_service

    service = get_tabular_query_service()
    role = next(
        (candidate for candidate in ("owner", "admin", "member") if candidate in ctx.roles),
        "member",
    )
    try:
        result = await service.try_answer(
            ctx.organization_id,
            payload.query,
            source_ids=[sid],
            role=role,
            user_id=ctx.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Source test query failed", error=str(exc)[:200])
        raise HTTPException(500, "Test query failed") from None
    if result is None:
        return {"matched": False, "source_id": str(sid)}
    metadata = result.metadata or {}
    return {
        "matched": True,
        "source_id": str(sid),
        "strategy": metadata.get("strategy"),
        "confidence": metadata.get("confidence"),
        "columns": list(result.columns),
        "rows": [list(row) for row in result.rows[:20]],
        "row_count": result.row_count,
        "total": metadata.get("total"),
        "tables": metadata.get("tables"),
        "provenance": (metadata.get("provenance") or [])[:5],
        "sql": result.sql,
    }


@router.get("/sources/{source_id}/profile", summary="Perfil de la fuente (último profiling)")
async def get_source_profile(source_id: str, request: Request):
    from sqlalchemy import text as _text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(source_id)
    except ValueError:
        raise HTTPException(400, "source_id must be a valid UUID")
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                _text(
                    "SELECT id, columns, tables, detected_at FROM source_profiles "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "ORDER BY detected_at DESC LIMIT 1"
                ),
                {"oid": ctx.organization_id, "sid": sid},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "No profile yet. Ejecuta POST /profile primero.")
    return {
        "profile_id": str(row.id),
        "detected_at": row.detected_at.isoformat(),
        "columns": row.columns if isinstance(row.columns, list) else [],
        "tables": row.tables if isinstance(row.tables, list) else [],
    }
