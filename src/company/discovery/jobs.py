# =============================================================================
# Company Discovery — jobs (§23)
# =============================================================================
# Tres disparadores, un mismo camino:
#   - event-driven: la ingesta (o un evento de negocio) encola una corrida
#   - background: un worker toma corridas pendientes (FOR UPDATE SKIP LOCKED)
#   - scheduled: un loop encola para las organizaciones con actividad
#
# El descubrimiento pesado NUNCA corre dentro del request: se encola y el
# worker lo ejecuta. La ingesta no se bloquea ni falla si el job no se puede
# encolar (fail-soft).
# =============================================================================
from __future__ import annotations

import asyncio
from uuid import UUID

from src.company.discovery.engine import CompanyDiscoveryEngine
from src.company.discovery.source_loaders import organizations_due_for_discovery
from src.core.domain.company_discovery import DiscoverySourceKind, DiscoveryTrigger
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

#: Canal Redis de despertar (mismo patrón que la cola de ingesta).
DISCOVERY_QUEUE_KEY = "rag:company:discovery:queue"
DEFAULT_INTERVAL_SECONDS = 900


async def enqueue_discovery(
    organization_id: UUID,
    *,
    trigger: DiscoveryTrigger = DiscoveryTrigger.MANUAL,
    source_kinds: tuple[DiscoverySourceKind, ...] = (),
    notify: bool = True,
) -> str:
    """Encola una corrida y despierta al worker. Devuelve el run id."""
    from src.company.wiring import company_discovery_repository

    run = await company_discovery_repository().enqueue_run(
        organization_id, trigger=trigger.value, source_kinds=source_kinds
    )
    if notify:
        await _notify()
    return str(run.id)


async def _notify() -> None:
    """Despierta al worker vía Redis. Si Redis no está, el loop lo recoge."""
    try:
        from src.infrastructure.redis.cache import get_redis

        client = await get_redis()
        if client is None:
            return
        await client.lpush(DISCOVERY_QUEUE_KEY, "1")
    except Exception as exc:  # noqa: BLE001 - el job durable ya existe
        logger.debug("company discovery notify failed", error=str(exc)[:150])


async def on_document_ingested(
    organization_id: UUID,
    *,
    document_id: UUID | None = None,
    source_id: UUID | None = None,
) -> None:
    """Hook de ingesta: encola descubrimiento documental (§3).

    Se llama después de persistir el documento estructurado y NUNCA propaga
    excepciones: si el descubrimiento falla, la ingesta ya terminó bien.
    """
    try:
        await enqueue_discovery(
            organization_id,
            trigger=DiscoveryTrigger.INGESTION,
            source_kinds=(DiscoverySourceKind.DOCUMENT,),
        )
    except Exception as exc:  # noqa: BLE001 - ingesta no se rompe
        logger.warning(
            "company discovery hook failed",
            error=str(exc)[:200],
            document_id=str(document_id) if document_id else None,
        )


async def run_next_discovery_job(engine: CompanyDiscoveryEngine | None = None) -> bool:
    """Ejecuta una corrida pendiente. True si había trabajo."""
    engine = engine or _engine()
    if engine is None:
        return False
    result = await engine.run_pending()
    return result is not None


async def run_due_discovery(
    engine: CompanyDiscoveryEngine | None = None, *, limit: int = 20
) -> int:
    """Encola corridas para organizaciones con actividad (§23 scheduled)."""
    engine = engine or _engine()
    if engine is None:
        return 0
    try:
        organizations = await organizations_due_for_discovery(limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("company discovery schedule failed", error=str(exc)[:200])
        return 0
    from src.company.wiring import company_discovery_repository

    store = company_discovery_repository()
    enqueued = 0
    for organization_id in organizations:
        try:
            await store.enqueue_run(
                organization_id, trigger=DiscoveryTrigger.SCHEDULED.value
            )
            enqueued += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "company discovery enqueue failed", error=str(exc)[:150]
            )
    return enqueued


async def company_discovery_worker_loop(interval_seconds: int | None = None) -> None:
    """Worker: drena corridas pendientes; en ausencia de trabajo, planifica."""
    from src.company.wiring import company_discovery_enabled

    if not company_discovery_enabled():
        logger.info("Company discovery disabled (RAG_COMPANY_DISCOVERY_ENABLED)")
        return
    interval = interval_seconds or DEFAULT_INTERVAL_SECONDS
    engine = _engine()
    if engine is None:
        return
    logger.info("Company discovery worker started", interval_seconds=interval)
    while True:
        try:
            worked = await run_next_discovery_job(engine)
            if not worked:
                await run_due_discovery(engine)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - el loop nunca muere
            logger.warning("company discovery worker error", error=str(exc)[:200])
            await asyncio.sleep(interval)


def _engine() -> CompanyDiscoveryEngine | None:
    try:
        from src.company.wiring import company_discovery_engine

        return company_discovery_engine()
    except Exception as exc:  # noqa: BLE001
        logger.warning("company discovery engine unavailable", error=str(exc)[:200])
        return None


__all__ = [
    "DISCOVERY_QUEUE_KEY",
    "company_discovery_worker_loop",
    "enqueue_discovery",
    "on_document_ingested",
    "run_due_discovery",
    "run_next_discovery_job",
]
