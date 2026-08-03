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
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.api.deps import get_cache_provider, get_embedding_provider, get_vector_store
from src.domain.ports import CacheProvider, EmbeddingProvider, VectorStore
from src.domain.services import IngestionResult
from src.infrastructure.data_ingestion import PostgresIngestionService
from src.infrastructure.ingestion_queue import enqueue_sync, get_job_status, list_recent_jobs
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
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    ingestion: PostgresIngestionService = Depends(get_ingestion_service),
):
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id debe ser un UUID válido")

    sources = await ingestion.discover_sources(tenant_id)
    synced_count = 0
    source_list = []
    for s in sources:
        is_synced = await ingestion.is_synced(tenant_id, s.schema_name, s.table_name)
        if is_synced:
            synced_count += 1
        source_list.append({
            "schema": s.schema_name,
            "table": s.table_name,
            "columns": len(s.columns),
            "row_count": s.row_count,
            "synced": is_synced,
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
    full_refresh: bool = False,
    background: bool = Query(default=True, description="Siempre en background para streaming de progreso"),
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    ingestion: PostgresIngestionService = Depends(get_ingestion_service),
):
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id debe ser un UUID válido")

    from uuid import uuid4

    from src.infrastructure.ingestion_queue import update_job_status

    job_id = uuid4().hex
    await update_job_status(job_id, "running", progress=0)

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
                await update_job_status(job_id, "failed", progress=100,
                    result_summary={"errors": result.errors},
                    error="; ".join(result.errors[:5]))
            else:
                await update_job_status(
                    job_id, "completed", progress=100,
                    result_summary={
                        "tables_processed": result.tables_processed,
                        "rows_indexed": result.rows_indexed,
                        "vectors_upserted": result.vectors_upserted,
                        "duration_ms": result.duration_ms,
                    },
                )
        except Exception as exc:
            await update_job_status(job_id, "failed", progress=100, error=str(exc))

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
    schema_name: str,
    table_name: str,
    full_refresh: bool = False,
    background: bool = Query(default=False, description="Ejecutar en background (cola Redis)"),
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    ingestion: PostgresIngestionService = Depends(get_ingestion_service),
):
    try:
        tenant_id = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id debe ser un UUID válido")

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
async def get_job(job_id: str):
    job = await get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.get(
    "/jobs",
    summary="Listar jobs recientes de ingesta",
    description="Lista los jobs más recientes en la cola de ingesta (máximo 100).",
)
async def list_jobs(limit: int = Query(default=50, ge=1, le=100)):
    jobs = await list_recent_jobs(limit)
    return {"jobs": jobs, "count": len(jobs)}


@router.get(
    "/jobs/{job_id}/stream",
    summary="Stream del progreso de ingesta (SSE)",
    description="Server-Sent Events que emite el progreso en tiempo real de un job de ingesta.",
)
async def stream_job_progress(
    job_id: str,
    interval_ms: int = Query(default=1000, ge=500, le=5000, description="Intervalo entre actualizaciones"),
):
    async def event_stream():
        last_progress = -1
        consecutive_same = 0
        while True:
            job = await get_job_status(job_id)
            if job is None:
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
