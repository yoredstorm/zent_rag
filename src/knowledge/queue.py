# =============================================================================
# Knowledge Queue — wakeup de jobs de la Knowledge Platform (Redis)
# =============================================================================
# El estado del job vive en Postgres (ingestion_jobs); Redis solo despierta
# al worker. El payload es únicamente el job_id.
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)


def knowledge_queue_key() -> str:
    return get_settings().KNOWLEDGE_QUEUE_KEY


async def enqueue_knowledge_job(job_id: str) -> None:
    """Encola el job_id para que el worker lo procese (wakeup).

    El job ya vive en Postgres; Redis solo despierta al worker. Si Redis no
    está (CI/tests/outage) no fallamos el HTTP salvo en production.
    """
    try:
        client = await _get_redis()
        await client.lpush(knowledge_queue_key(), job_id)
    except Exception as exc:
        logger.warning("Failed to enqueue knowledge job", job_id=job_id, error=str(exc))
        if get_settings().ENVIRONMENT == "production":
            raise
        return
    logger.info("Knowledge job enqueued", job_id=job_id)
