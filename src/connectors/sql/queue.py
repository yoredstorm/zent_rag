# =============================================================================
# Ingestion Job Queue — Redis-backed background ingestion
# =============================================================================
# Pushes ingestion tasks to a Redis list for async processing by workers.
# Job metadata is stored in Redis hashes for status polling and progress.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import redis.asyncio as aioredis

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

QUEUE_KEY = "rag:ingestion:queue"
JOB_KEY_PREFIX = "rag:ingestion:job"
JOBS_LIST_KEY = "rag:ingestion:jobs"

MAX_RECENT_JOBS = 100
JOB_TTL_SECONDS = 86400 * 7  # 7 days


async def enqueue_sync(
    organization_id: UUID,
    schema_name: str | None = None,
    table_name: str | None = None,
    full_refresh: bool = False,
) -> str:
    job_id = uuid4().hex

    job_data = {
        "job_id": job_id,
        "job_type": "sync",
        "organization_id": str(organization_id),
        "schema_name": schema_name or "",
        "table_name": table_name or "",
        "full_refresh": "1" if full_refresh else "0",
        "status": "pending",
        "progress": "0",
        "message": "En cola",
        "current_table": "",
        "tables_done": "0",
        "tables_total": "0",
        "result_summary": "",
        "error": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    client: aioredis.Redis = await _get_redis()
    try:
        async with client.pipeline() as pipe:
            pipe.hset(f"{JOB_KEY_PREFIX}:{job_id}", mapping=job_data)
            pipe.expire(f"{JOB_KEY_PREFIX}:{job_id}", JOB_TTL_SECONDS)
            pipe.rpush(QUEUE_KEY, job_id)
            pipe.lpush(JOBS_LIST_KEY, job_id)
            pipe.ltrim(JOBS_LIST_KEY, 0, MAX_RECENT_JOBS - 1)
            await pipe.execute()
    except Exception as exc:
        logger.error("Failed to enqueue ingestion job", job_id=job_id, error=str(exc))
        raise

    logger.info(
        "Ingestion job enqueued",
        job_id=job_id,
        job_type="sync",
        organization_id=str(organization_id),
        schema_name=schema_name,
        table_name=table_name,
        full_refresh=full_refresh,
    )
    return job_id


async def enqueue_trigram_index(
    organization_id: UUID,
    schema_name: str,
    table_name: str,
    columns: list[str],
) -> str:
    """Encola la creación de índices GIN trigram para columnas de texto.

    Job procesado por el ingestion worker en background; la request del
    usuario nunca espera a que se cree el índice.
    """
    job_id = uuid4().hex

    job_data = {
        "job_id": job_id,
        "job_type": "create_trigram_index",
        "organization_id": str(organization_id),
        "schema_name": schema_name,
        "table_name": table_name,
        "columns": json.dumps(columns),
        "status": "pending",
        "progress": "0",
        "message": "En cola",
        "current_table": "",
        "result_summary": "",
        "error": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    client: aioredis.Redis = await _get_redis()
    try:
        async with client.pipeline() as pipe:
            pipe.hset(f"{JOB_KEY_PREFIX}:{job_id}", mapping=job_data)
            pipe.expire(f"{JOB_KEY_PREFIX}:{job_id}", JOB_TTL_SECONDS)
            pipe.rpush(QUEUE_KEY, job_id)
            pipe.lpush(JOBS_LIST_KEY, job_id)
            pipe.ltrim(JOBS_LIST_KEY, 0, MAX_RECENT_JOBS - 1)
            await pipe.execute()
    except Exception as exc:
        logger.error("Failed to enqueue trigram index job", job_id=job_id, error=str(exc))
        raise

    logger.info(
        "Trigram index job enqueued",
        job_id=job_id,
        organization_id=str(organization_id),
        schema_name=schema_name,
        table_name=table_name,
        columns=columns,
    )
    return job_id


async def get_job_status(job_id: str) -> dict | None:
    client: aioredis.Redis = await _get_redis()
    try:
        data = await client.hgetall(f"{JOB_KEY_PREFIX}:{job_id}")
    except Exception as exc:
        logger.warning("Failed to read job status", job_id=job_id, error=str(exc))
        return None

    if not data:
        return None

    result = dict(data)
    result["full_refresh"] = result.get("full_refresh", "0") == "1"
    progress_val = result.get("progress", "0")
    result["progress"] = int(progress_val) if str(progress_val).isdigit() else 0

    for int_key in ("tables_done", "tables_total"):
        raw = result.get(int_key, "0")
        result[int_key] = int(raw) if str(raw).isdigit() else 0

    result.setdefault("message", "")
    result.setdefault("current_table", "")
    result.setdefault("updated_at", result.get("created_at", ""))

    summary_raw = result.get("result_summary", "")
    if summary_raw:
        try:
            result["result_summary"] = json.loads(summary_raw)
        except json.JSONDecodeError:
            result["result_summary"] = None
    else:
        result["result_summary"] = None

    return result


async def list_recent_jobs(limit: int = 50) -> list[dict]:
    client: aioredis.Redis = await _get_redis()
    try:
        job_ids = await client.lrange(JOBS_LIST_KEY, 0, limit - 1)
    except Exception as exc:
        logger.warning("Failed to list recent jobs", error=str(exc))
        return []

    jobs: list[dict] = []
    for jid in job_ids:
        job = await get_job_status(jid)
        if job:
            jobs.append(job)
    return jobs


async def update_job_status(
    job_id: str,
    status: str,
    progress: int | None = None,
    result_summary: dict | None = None,
    error: str | None = None,
    message: str | None = None,
    current_table: str | None = None,
    tables_done: int | None = None,
    tables_total: int | None = None,
) -> None:
    client: aioredis.Redis = await _get_redis()
    key = f"{JOB_KEY_PREFIX}:{job_id}"
    mapping: dict[str, str] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if progress is not None:
        mapping["progress"] = str(progress)
    if result_summary is not None:
        mapping["result_summary"] = json.dumps(result_summary, default=str)
    if error is not None:
        mapping["error"] = error
    if message is not None:
        mapping["message"] = message
    if current_table is not None:
        mapping["current_table"] = current_table
    if tables_done is not None:
        mapping["tables_done"] = str(tables_done)
    if tables_total is not None:
        mapping["tables_total"] = str(tables_total)

    try:
        await client.hset(key, mapping=mapping)
        await client.expire(key, JOB_TTL_SECONDS)
    except Exception as exc:
        logger.warning(
            "Failed to update job status",
            job_id=job_id,
            status=status,
            error=str(exc),
        )
