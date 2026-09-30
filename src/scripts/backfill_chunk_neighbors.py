#!/usr/bin/env python
# =============================================================================
# Backfill de vecindad estructural de chunks (prev/next/chunk_index)
# =============================================================================
# La ingesta V2 nueva guarda `metadata.chunk_index`, `prev_chunk_id` y
# `next_chunk_id` para que la expansión llegue a los hermanos exactos sin
# adivinar. Los puntos indexados antes de ese cambio no tienen esos campos y
# NO se pueden reconstruir desde Qdrant (el orden no está en el payload): hay
# que reprocesar la fuente.
#
# Este script re-encola la ingesta de fuentes con documento estructurado para
# que el chunker regenere los puntos con vecindad.
#
# Uso:
#   python -m src.scripts.backfill_chunk_neighbors --dry-run
#   python -m src.scripts.backfill_chunk_neighbors --org <uuid> --limit 20
#   python -m src.scripts.backfill_chunk_neighbors --name-contains Cat31
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from src.infrastructure.postgres.knowledge_repos import (
    PostgresIngestionJobRepository,
)
from src.knowledge.queue import enqueue_knowledge_job
from src.scripts.knowledge_v2_backfill import _JOB_TYPES, find_candidates


def _print(line: str) -> None:
    print(line)  # noqa: T201 (CLI)


async def backfill(
    organization_id: UUID | None,
    limit: int,
    dry_run: bool,
    name_contains: str | None,
) -> int:
    candidates = await find_candidates(
        organization_id,
        limit,
        force=True,
        name_contains=name_contains,
        only_with_document=True,
    )
    if not candidates:
        _print("No hay fuentes con documento estructurado para reprocesar.")
        return 0
    job_repo = PostgresIngestionJobRepository()
    enqueued = 0
    for source in candidates:
        job_type = _JOB_TYPES.get(source["type"])
        if job_type is None:
            continue
        _print(
            f"[{'DRY' if dry_run else 'ENQ'}] org={source['organization_id']} "
            f"source={source['id']} name={source['name']!r}"
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
    _print(
        f"Candidatos: {len(candidates)} · Encolados: {enqueued} (dry_run={dry_run})"
    )
    return enqueued


async def _main(args: argparse.Namespace) -> None:
    organization_id = UUID(args.org) if args.org else None
    await backfill(organization_id, args.limit, args.dry_run, args.name_contains)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill de vecindad de chunks V2")
    parser.add_argument("--org", help="Organization UUID (default: todas)")
    parser.add_argument("--limit", type=int, default=50, help="Máx. fuentes a encolar")
    parser.add_argument("--dry-run", action="store_true", help="Solo lista candidatas")
    parser.add_argument(
        "--name-contains",
        help="Filtra por nombre de fuente (ej: Cat31) para reprocesar por tandas",
    )
    args = parser.parse_args()
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
