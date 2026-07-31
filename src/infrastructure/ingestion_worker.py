# =============================================================================
# Ingestion Worker — Background process for async ingestion jobs
# =============================================================================
# Polls the Redis ingestion queue and executes ingestion tasks asynchronously.
# Designed to run as a long-lived asyncio task alongside the FastAPI app or as
# a standalone process.
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import UUID

import redis.asyncio as aioredis

from src.api.deps import get_cache_provider, get_embedding_provider, get_vector_store
from src.infrastructure.cache import _get_redis
from src.infrastructure.data_ingestion import PostgresIngestionService
from src.infrastructure.ingestion_queue import QUEUE_KEY, update_job_status
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

_shutdown_flag: bool = False


def request_shutdown() -> None:
    global _shutdown_flag
    _shutdown_flag = True
    logger.info("Ingestion worker shutdown requested")


async def _build_ingestion_service() -> PostgresIngestionService:
    vs = get_vector_store()
    emb = get_embedding_provider()
    cache = get_cache_provider()
    return PostgresIngestionService(vs, emb, cache)


async def process_job(job_data: dict) -> None:
    job_id: str = job_data["job_id"]
    tenant_id = UUID(job_data["tenant_id"])
    schema_name_raw: str = job_data.get("schema_name", "")
    table_name_raw: str = job_data.get("table_name", "")
    full_refresh = job_data.get("full_refresh", "0") == "1"

    schema_name: str | None = schema_name_raw if schema_name_raw else None
    table_name: str | None = table_name_raw if table_name_raw else None

    logger.info(
        "Worker processing job",
        job_id=job_id,
        tenant_id=str(tenant_id),
        schema_name=schema_name,
        table_name=table_name,
        full_refresh=full_refresh,
    )

    await update_job_status(job_id, "running", progress=0)

    try:
        service = await _build_ingestion_service()

        if schema_name and table_name:
            result = await service.sync_table(tenant_id, schema_name, table_name, full_refresh)
        else:
            result = await service.sync_all(tenant_id, full_refresh)

        summary = {
            "tables_processed": result.tables_processed,
            "rows_indexed": result.rows_indexed,
            "vectors_upserted": result.vectors_upserted,
            "duration_ms": result.duration_ms,
            "errors": result.errors,
        }

        if result.success:
            await update_job_status(
                job_id, "completed", progress=100, result_summary=summary
            )
            logger.info("Job completed successfully", job_id=job_id, **summary)
        else:
            await update_job_status(
                job_id, "completed", progress=100, result_summary=summary
            )
            logger.warning("Job completed with errors", job_id=job_id, errors=result.errors)

    except Exception as exc:
        logger.error("Job failed", job_id=job_id, error=str(exc), exc_info=True)
        await update_job_status(
            job_id,
            "failed",
            progress=0,
            error=str(exc),
        )


async def run_worker(poll_timeout: int = 5) -> None:
    global _shutdown_flag
    _shutdown_flag = False

    logger.info("Ingestion worker started", poll_timeout=poll_timeout)
    client: aioredis.Redis = await _get_redis()

    while not _shutdown_flag:
        try:
            result = await client.blpop(QUEUE_KEY, timeout=poll_timeout)
        except Exception as exc:
            logger.warning("Worker BLPOP error, retrying", error=str(exc))
            await asyncio.sleep(1)
            continue

        if result is None:
            continue

        _, job_id_raw = result
        job_id = job_id_raw if isinstance(job_id_raw, str) else job_id_raw.decode("utf-8")
        job_key = f"rag:ingestion:job:{job_id}"

        try:
            raw_data = await client.hgetall(job_key)
        except Exception as exc:
            logger.warning("Failed to read job data, skipping", job_id=job_id, error=str(exc))
            continue

        if not raw_data:
            logger.warning("Job data missing, skipping", job_id=job_id)
            continue

        job_data = dict(raw_data)
        await process_job(job_data)

    logger.info("Ingestion worker stopped")
