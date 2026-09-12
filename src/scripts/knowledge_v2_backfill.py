#!/usr/bin/env python
# =============================================================================
# Knowledge V2 backfill — re-procesa fuentes de archivo para generar
# documentos estructurados + chunks V2 (tras activar RAG_KNOWLEDGE_V2_ENABLED).
#
# Uso:
#   python -m src.scripts.knowledge_v2_backfill --dry-run
#   python -m src.scripts.knowledge_v2_backfill --org <uuid> --limit 5
#
# Solo encola jobs (estado en Postgres + wakeup Redis); el worker existente
# los procesa. Se salta fuentes que ya tienen structured_documents.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.postgres.knowledge_repos import (
    PostgresIngestionJobRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.knowledge.queue import enqueue_knowledge_job

# Tipos de fuente que producen bytes crudos para el pipeline V2 (file connector).
V2_CAPABLE_TYPES = ("file",)

_JOB_TYPES = {
    "file": "sync_source:file",
}


def _print(line: str) -> None:
    print(line)  # noqa: T201 (CLI)


async def find_candidates(
    organization_id: UUID | None,
    limit: int,
) -> list[dict]:
    session = await get_async_session()
    try:
        query = (
            "SELECT s.id, s.organization_id, s.knowledge_base_id, s.name, s.type "
            "FROM kb_sources s "
            "WHERE s.type = :source_type "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM structured_documents sd "
            "  WHERE sd.source_id = s.id AND sd.organization_id = s.organization_id"
            ") "
        )
        params: dict = {"source_type": V2_CAPABLE_TYPES[0], "limit": limit}
        if organization_id is not None:
            query += "AND s.organization_id = :oid "
            params["oid"] = organization_id
        query += "ORDER BY s.created_at ASC LIMIT :limit"
        result = await session.execute(text(query), params)
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "organization_id": row.organization_id,
                "knowledge_base_id": row.knowledge_base_id,
                "name": row.name,
                "type": row.type,
            }
            for row in rows
        ]
    finally:
        await session.close()


async def backfill(
    organization_id: UUID | None,
    limit: int,
    dry_run: bool,
) -> int:
    candidates = await find_candidates(organization_id, limit)
    if not candidates:
        _print("No hay fuentes pendientes de reproceso V2 (tipo=file sin structured_documents).")
        return 0

    job_repo = PostgresIngestionJobRepository()
    enqueued = 0
    for source in candidates:
        job_type = _JOB_TYPES.get(source["type"])
        if job_type is None:
            continue
        _print(
            f"[{'DRY' if dry_run else 'ENQ'}] org={source['organization_id']} "
            f"source={source['id']} kb={source['knowledge_base_id']} name={source['name']!r}"
        )
        if dry_run:
            continue
        job = await job_repo.create_job(
            source["organization_id"],
            job_type=job_type,
            source_id=source["id"],
            knowledge_base_id=source["knowledge_base_id"],
            max_attempts=3,
        )
        await enqueue_knowledge_job(str(job.id))
        enqueued += 1
    _print(f"Candidatos: {len(candidates)} · Encolados: {enqueued} (dry_run={dry_run})")
    return enqueued


async def _main(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.KNOWLEDGE_V2_ENABLED:
        _print(
            "ATENCIÓN: RAG_KNOWLEDGE_V2_ENABLED está off. Los jobs correrán "
            "solo el pipeline V1 (sin documentos estructurados ni chunks V2)."
        )
    organization_id: UUID | None = None
    if args.org:
        organization_id = UUID(args.org)
    await backfill(organization_id, args.limit, args.dry_run)


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge V2 backfill")
    parser.add_argument("--org", help="Organization UUID (default: todas)")
    parser.add_argument("--limit", type=int, default=50, help="Máx. fuentes a encolar")
    parser.add_argument("--dry-run", action="store_true", help="Solo lista candidatas")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
