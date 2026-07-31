# =============================================================================
# Health Check Route — Endpoint de salud para Kubernetes/Docker
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, status as http_status

from sqlalchemy import text

from src.config import get_settings
from src.domain.models import HealthResponse
from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import get_async_session
from src.infrastructure.vector_store import _get_client as _get_qdrant_client
from src.infrastructure.cache import _get_redis

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=http_status.HTTP_200_OK,
    summary="Health check del servicio — verifica PostgreSQL, Qdrant y Redis",
)
async def health_check() -> HealthResponse:
    settings = get_settings()
    checks: dict[str, str] = {}
    degraded = False

    # --- PostgreSQL ---
    try:
        session = await get_async_session()
        try:
            await session.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        finally:
            await session.close()
    except Exception as exc:
        logger.warning("Health check: PostgreSQL failed", error=str(exc))
        checks["postgres"] = f"error: {exc}"
        degraded = True

    # --- Qdrant ---
    try:
        client = await _get_qdrant_client()
        await client.get_collections()
        checks["qdrant"] = "ok"
    except Exception as exc:
        logger.warning("Health check: Qdrant failed", error=str(exc))
        checks["qdrant"] = f"error: {exc}"
        degraded = True

    # --- Redis ---
    try:
        redis = await _get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("Health check: Redis failed", error=str(exc))
        checks["redis"] = f"error: {exc}"
        degraded = True

    return HealthResponse(
        status="degraded" if degraded else "healthy",
        environment=settings.ENVIRONMENT,
        checks=checks,
    )
