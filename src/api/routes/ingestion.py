# =============================================================================
# Ingestion API Route — Sincronización Database → Vector Store
# =============================================================================
# POST /api/v1/ingestion/sync            — Sincroniza TODAS las tablas descubiertas
# POST /api/v1/ingestion/sync/{schema}/{table} — Sincroniza una tabla específica
# GET  /api/v1/ingestion/sources         — Lista las fuentes de datos descubiertas
# GET  /api/v1/ingestion/jobs/{job_id}   — Consulta el estado de un job en cola
# GET  /api/v1/ingestion/jobs            — Lista los jobs recientes
# =============================================================================
from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from src.api.deps import get_cache_provider, get_embedding_provider, get_vector_store
from src.domain.ports import CacheProvider, EmbeddingProvider, VectorStore
from src.domain.services import IngestionResult
from src.infrastructure.data_ingestion import PostgresIngestionService
from src.infrastructure.ingestion_queue import enqueue_sync, get_job_status, list_recent_jobs
from src.infrastructure.lazy_activity import (
    lazy_log_cache_key,
    parse_lazy_activity,
)
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/ingestion", tags=["Ingestion"])


# Singleton del ingestion service
_ingestion_service: PostgresIngestionService | None = None


def get_ingestion_service(
    vs: VectorStore = Depends(get_vector_store),
    emb: EmbeddingProvider = Depends(get_embedding_provider),
    cache: CacheProvider = Depends(get_cache_provider),
) -> PostgresIngestionService:
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = PostgresIngestionService(vs, emb, cache)
    return _ingestion_service


@router.get(
    "/sources",
    summary="Listar fuentes de datos descubiertas",
    description=(
        "Descubre automáticamente todas las tablas disponibles en PostgreSQL "
        "para el tenant. Retorna esquema, nombre, columnas y conteo de filas."
    ),
)
async def list_sources(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    ingestion: PostgresIngestionService = Depends(get_ingestion_service),
):
    from src.api.security import resolve_tenant

    tenant_id = resolve_tenant(request, x_tenant_id)

    sources = await ingestion.discover_sources(tenant_id)
    skip_set = ingestion._skip_tables
    synced_count = 0
    source_list = []
    for s in sources:
        is_synced = await ingestion.is_synced(tenant_id, s.schema_name, s.table_name)
        progress = await ingestion.get_table_progress(tenant_id, s.schema_name, s.table_name)
        is_skipped = s.table_name.lower() in skip_set
        if is_synced:
            synced_count += 1
        source_list.append({
            "schema": s.schema_name,
            "table": s.table_name,
            "columns": len(s.columns),
            "row_count": s.row_count,
            "synced": is_synced,
            "skipped": is_skipped,
            "progress": progress,
            "lazy_rows_indexed": await ingestion.get_lazy_rows_indexed(
                tenant_id, s.schema_name, s.table_name
            ),
            "columns_detail": [
                {"name": c.name, "type": c.data_type, "nullable": c.is_nullable, "is_pk": c.is_primary_key}
                for c in s.columns[:10]
            ],
        })
    return {
        "tenant_id": str(tenant_id),
        "total_sources": len(sources),
        "synced_sources": synced_count,
        "sources": source_list,
    }


@router.get(
    "/lazy-activity",
    summary="Actividad de indexado por demanda",
    description="Eventos recientes de ingesta perezosa para el tenant autenticado.",
)
async def lazy_activity(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    cache: CacheProvider = Depends(get_cache_provider),
):
    from src.api.security import resolve_tenant

    tenant_id = resolve_tenant(request, x_tenant_id)

    entries = await cache.get_list(lazy_log_cache_key(tenant_id))
    trigger_count, recent = parse_lazy_activity(entries, days=days, limit=limit)

    # Estado del rate limit por tenant (transparencia para el admin)
    rate_limited = False
    total_rows_indexed = 0
    try:
        from src.infrastructure.lazy_rate_limit import lazy_trigger_limited

        rate_limited = await lazy_trigger_limited(tenant_id)
        raw_total = await cache.get(f"rag:lazy_rows_total:{tenant_id.hex}")
        try:
            total_rows_indexed = int(raw_total) if raw_total else 0
        except (TypeError, ValueError):
            total_rows_indexed = 0
    except Exception:
        rate_limited = False

    return {
        "tenant_id": str(tenant_id),
        "days": days,
        "trigger_count": trigger_count,
        "total_rows_indexed": total_rows_indexed,
        "rate_limited": rate_limited,
        "recent": recent,
    }


@router.post(
    "/sync",
    response_model=dict,
    summary="Sincronizar todas las tablas con la BD vectorial",
    description=(
        "Descubre e indexa automáticamente todas las tablas del tenant en Qdrant. "
        "Cada fila se convierte en texto enriquecido, se genera su embedding y se "
        "almacena con metadatos completos para búsqueda semántica."
    ),
)
async def sync_all(
    request: Request,
    full_refresh: bool = False,
    background: bool = Query(default=True, description="Siempre en background para streaming de progreso"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    ingestion: PostgresIngestionService = Depends(get_ingestion_service),
):
    from src.api.security import require_scope, resolve_tenant

    require_scope(request, "rag:ingest")
    tenant_id = resolve_tenant(request, x_tenant_id)

    from src.infrastructure.cache import _get_redis
    from src.infrastructure.ingestion_queue import (
        JOB_KEY_PREFIX,
        JOB_TTL_SECONDS,
        JOBS_LIST_KEY,
        update_job_status,
    )

    # Lock por tenant: un solo sync activo a la vez (evita tareas duplicadas).
    lock_key = f"rag:ingest_lock:{tenant_id.hex}"
    client = await _get_redis()
    try:
        acquired = await client.set(lock_key, "1", nx=True, ex=3600)
    except Exception:
        acquired = None
    if not acquired:
        raise HTTPException(
            409,
            "A sync is already running for this tenant. Wait for it to finish.",
        )

    async def _release_lock():
        try:
            await client.delete(lock_key)
        except Exception:
            pass

    job_id = uuid4().hex
    init = {
        "job_id": job_id,
        "tenant_id": str(tenant_id),
        "status": "running",
        "progress": "0",
        "message": "Iniciando sincronización…",
        "current_table": "",
        "tables_done": "0",
        "tables_total": "0",
        "result_summary": "",
        "error": "",
        "full_refresh": "1" if full_refresh else "0",
    }
    await client.hset(f"{JOB_KEY_PREFIX}:{job_id}", mapping=init)
    await client.expire(f"{JOB_KEY_PREFIX}:{job_id}", JOB_TTL_SECONDS)
    await client.lpush(JOBS_LIST_KEY, job_id)
    await update_job_status(
        job_id,
        "running",
        progress=0,
        message="Iniciando sincronización…",
        tables_done=0,
        tables_total=0,
    )

    logger.info(
        "Starting ingestion sync",
        tenant_id=str(tenant_id),
        full_refresh=full_refresh,
        job_id=job_id,
    )

    # Ejecutar en background task para no bloquear la respuesta HTTP
    async def _run_sync():
        try:
            result: IngestionResult = await ingestion.sync_all(tenant_id, full_refresh, job_id=job_id)
            if not result.success:
                await update_job_status(
                    job_id,
                    "failed",
                    progress=100,
                    result_summary={"errors": result.errors},
                    error="; ".join(result.errors[:5]),
                    message=f"Falló con {len(result.errors)} error(es)",
                    current_table="",
                )
            else:
                await update_job_status(
                    job_id,
                    "completed",
                    progress=100,
                    result_summary={
                        "tables_processed": result.tables_processed,
                        "rows_indexed": result.rows_indexed,
                        "vectors_upserted": result.vectors_upserted,
                        "duration_ms": result.duration_ms,
                    },
                    message=(
                        f"Listo: {result.tables_processed} tablas, "
                        f"{result.rows_indexed} filas, {result.vectors_upserted} vectores"
                    ),
                    current_table="",
                    tables_done=result.tables_processed,
                )
        except Exception as exc:
            await update_job_status(
                job_id,
                "failed",
                progress=100,
                error=str(exc),
                message=f"Error: {exc}",
            )
        finally:
            await _release_lock()

    asyncio.create_task(_run_sync())

    return {
        "job_id": job_id,
        "status": "running",
        "message": "Ingestion started. Stream progress at GET /jobs/{job_id}/stream",
    }


@router.post(
    "/sync/{schema_name}/{table_name}",
    summary="Sincronizar una tabla específica",
)
async def sync_table(
    request: Request,
    schema_name: str,
    table_name: str,
    full_refresh: bool = False,
    background: bool = Query(default=False, description="Ejecutar en background (cola Redis)"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    ingestion: PostgresIngestionService = Depends(get_ingestion_service),
):
    from src.api.security import require_scope, resolve_tenant
    from src.infrastructure.schema_discovery import quote_ident

    require_scope(request, "rag:ingest")
    tenant_id = resolve_tenant(request, x_tenant_id)

    # Validar identificadores ANTES de cualquier ejecución SQL (anti inyección).
    try:
        quote_ident(schema_name)
        quote_ident(table_name)
    except ValueError:
        raise HTTPException(400, "Schema o tabla inválidos (solo letras, números y _)")

    if background:
        job_id = await enqueue_sync(tenant_id, schema_name, table_name, full_refresh)
        return {
            "job_id": job_id,
            "status": "pending",
            "message": "Ingestion job enqueued for background processing",
        }

    result = await ingestion.sync_table(tenant_id, schema_name, table_name, full_refresh)

    return {
        "status": "completed" if result.success else "partial",
        "tenant_id": str(result.tenant_id),
        "schema": schema_name,
        "table": table_name,
        "rows_indexed": result.rows_indexed,
        "vectors_upserted": result.vectors_upserted,
        "duration_ms": result.duration_ms,
        "errors": result.errors,
    }


@router.get(
    "/jobs/{job_id}",
    summary="Consultar estado de un job de ingesta",
    description="Retorna el estado, progreso y resultado de un job en la cola de ingesta.",
)
async def get_job(
    request: Request,
    job_id: str,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
):
    from src.api.security import resolve_tenant

    tenant_id = resolve_tenant(request, x_tenant_id)
    job = await get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    if job.get("tenant_id") != str(tenant_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.get(
    "/jobs",
    summary="Listar jobs recientes de ingesta",
    description="Lista los jobs más recientes del tenant autenticado (máximo 100).",
)
async def list_jobs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
):
    from src.api.security import resolve_tenant

    tenant_id = resolve_tenant(request, x_tenant_id)
    jobs = await list_recent_jobs(100)
    own_jobs = [j for j in jobs if j.get("tenant_id") == str(tenant_id)][:limit]
    return {"jobs": own_jobs, "count": len(own_jobs)}


@router.get(
    "/jobs/{job_id}/stream",
    summary="Stream del progreso de ingesta (SSE)",
    description="Server-Sent Events que emite el progreso en tiempo real de un job de ingesta.",
)
async def stream_job_progress(
    request: Request,
    job_id: str,
    interval_ms: int = Query(default=1000, ge=500, le=5000, description="Intervalo entre actualizaciones"),
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
):
    from src.api.security import resolve_tenant

    tenant_id = resolve_tenant(request, x_tenant_id)

    async def event_stream():
        last_progress = -1
        consecutive_same = 0
        start = asyncio.get_running_loop().time()
        while True:
            # Cap de duración total del stream (anti resource exhaustion)
            if asyncio.get_running_loop().time() - start > 600:
                yield f"event: error\ndata: {json.dumps({'error': 'Stream timeout'})}\n\n"
                return

            job = await get_job_status(job_id)
            if job is None or job.get("tenant_id") != str(tenant_id):
                yield f"event: error\ndata: {json.dumps({'error': 'Job not found'})}\n\n"
                return

            current_progress = job.get("progress", 0)
            job_status = job.get("status", "unknown")

            yield f"data: {json.dumps({'progress': current_progress, 'status': job_status})}\n\n"

            if job_status in ("completed", "failed"):
                return

            if current_progress == last_progress:
                consecutive_same += 1
            else:
                consecutive_same = 0
                last_progress = current_progress

            # Job estancado (mismo progreso durante > 2 min): cerrar stream.
            if consecutive_same * (interval_ms / 1000.0) > 120:
                yield f"event: error\ndata: {json.dumps({'error': 'No progress detected'})}\n\n"
                return

            await asyncio.sleep(interval_ms / 1000.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
