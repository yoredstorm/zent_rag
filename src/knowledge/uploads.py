# =============================================================================
# Uploads de archivos como fuentes — helpers compartidos
# =============================================================================
# Usado por las rutas de sources y por el asistente de data-onboarding: mismo
# criterio de duplicados, nombres de copia y encolado de indexado.
# =============================================================================
from __future__ import annotations

import re
from uuid import uuid4

from src.core.ports import IngestionJobRepository, SourceRepository
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

logger = get_logger(__name__)


def audit_service() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def normalize_filename(name: str) -> str:
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


async def find_duplicate_source(repo: SourceRepository, organization_id, filename: str):
    """Fuente existente con el mismo nombre+extensión (ignora borradas)."""
    normalized = normalize_filename(filename)
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
        if normalize_filename(getattr(source, "name", "") or "") == normalized:
            return source
    return None


async def next_copy_name(repo: SourceRepository, organization_id, base_name: str) -> str:
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


async def enqueue_source_sync(
    ctx,
    jobs: IngestionJobRepository,
    source,
    *,
    on_created=None,
):
    """Crea el job de sync y lo encola.

    ``on_created(job)`` corre ANTES de encolar: permite registrar el job en su
    sesión de aprendizaje antes de que el worker pueda tomarlo (sin carrera).
    """
    job = await jobs.create_job(
        ctx.organization_id,
        job_type=f"sync_source:{source.type}",
        source_id=source.id,
        knowledge_base_id=source.knowledge_base_id,
    )
    if on_created is not None:
        try:
            await on_created(job)
        except Exception as exc:  # noqa: BLE001 — la observabilidad no bloquea
            logger.warning(
                "Source sync on_created hook failed", error=str(exc)[:200]
            )
    from src.knowledge.queue import enqueue_knowledge_job

    await enqueue_knowledge_job(str(job.id))
    await audit_service().write(
        ctx, "source.sync_enqueued", "source", source.id,
        metadata={"job_id": str(job.id), "name": source.name},
    )
    return job
