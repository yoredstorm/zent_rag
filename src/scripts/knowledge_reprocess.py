#!/usr/bin/env python
# =============================================================================
# Knowledge OS — reproceso limpio (purga + reingesta)
# =============================================================================
# Cuando el parser o el compilador cambian de semántica, el conocimiento viejo
# no se debe conservar "por compatibilidad": se elimina lo producido por el
# compilador defectuoso y se reingieren las fuentes con el pipeline corregido.
#
# Uso:
#   python -m src.scripts.knowledge_reprocess --org <uuid> --dry-run
#   python -m src.scripts.knowledge_reprocess --org <uuid> --source <uuid> --purge
#   python -m src.scripts.knowledge_reprocess --org <uuid> --requeue --limit 100
#   python -m src.scripts.knowledge_reprocess --org <uuid> --purge --requeue
#
# La purga respeta la provenance: solo elimina filas creadas por el Knowledge
# Compiler (`metadata->>'compiled_by' = 'knowledge_compiler'`), salvo
# `knowledge_conflicts` y `knowledge_ingestion_quality`, que son íntegramente
# de esta pipeline.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.knowledge_repos import PostgresIngestionJobRepository
from src.infrastructure.postgres.session import get_async_session
from src.knowledge.queue import enqueue_knowledge_job

_COMPILER = "knowledge_compiler"

_PURGE_STATEMENTS: list[str] = [
    # Evidencia del compilador (primero: apunta a objetos/assertions).
    "DELETE FROM evidence_ledger e WHERE e.organization_id = :org "
    "AND e.metadata->>'compiled_by' = :compiler {source_clause}",
    # Conflictos: los escribe el compilador y el materializador; el contrato
    # nuevo no conserva conflicto sin provenance, así que se purgan por org.
    "DELETE FROM knowledge_conflicts WHERE organization_id = :org",
    "DELETE FROM knowledge_ingestion_quality WHERE organization_id = :org "
    "{source_clause}",
    "DELETE FROM knowledge_entity_aliases WHERE organization_id = :org "
    "{source_clause}",
    "DELETE FROM knowledge_assertions WHERE organization_id = :org "
    "AND metadata->>'compiled_by' = :compiler {source_clause}",
    "DELETE FROM knowledge_edges WHERE organization_id = :org "
    "AND metadata->>'compiled_by' = :compiler {source_clause}",
    "DELETE FROM knowledge_canonical_objects WHERE organization_id = :org "
    "AND metadata->>'compiled_by' = :compiler {source_clause}",
    "DELETE FROM knowledge_compilations WHERE organization_id = :org "
    "{source_clause}",
]


_LEGACY_CONFLICT_FILTER = """
(
    source_a IS NULL
 OR source_b IS NULL
 OR conflict_type IS NULL
 OR conflict_type NOT IN ('TRUE_CONFLICT', 'SOURCE_CONFLICT')
)
"""


async def purge_legacy_conflicts(
    organization_id: UUID | None, *, all_orgs: bool, dry_run: bool
) -> int:
    """Elimina conflictos que no pasan el gate nuevo (sin sources o sin tipo real).

    Es la limpieza de la implementación defectuosa: se conserva únicamente un
    conflicto con fuentes en ambos lados y clasificación de conflicto real.
    """
    session = await get_async_session()
    try:
        where = _LEGACY_CONFLICT_FILTER
        params: dict = {}
        if not all_orgs:
            if organization_id is None:
                return 0
            where = "organization_id = :org AND " + where
            params["org"] = organization_id
        if dry_run:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM knowledge_conflicts "  # noqa: S608
                        "WHERE " + where  # where es constante del módulo
                    ),
                    params,
                )
            ).first()
            return int(row.total or 0)
        result = await session.execute(
            text(
                "DELETE FROM knowledge_conflicts WHERE "  # noqa: S608
                + where  # where es constante del módulo
            ),
            params,
        )
        await session.commit()
        return int(result.rowcount or 0)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def _print(line: str) -> None:
    print(line)  # noqa: T201 (CLI)


async def purge(
    organization_id: UUID,
    source_id: UUID | None,
    *,
    dry_run: bool,
) -> dict:
    session = await get_async_session()
    counts: dict[str, int] = {}
    try:
        for index, template in enumerate(_PURGE_STATEMENTS):
            sql = template.format(
                source_clause="AND source_id = :source" if source_id else "",
            )
            params = {"org": organization_id}
            if source_id:
                params["source"] = source_id
            if ":compiler" in template:
                params["compiler"] = _COMPILER
            if dry_run:
                _print(f"[DRY] {sql.strip()}")
                continue
            result = await session.execute(text(sql), params)
            counts[f"stmt_{index}"] = int(result.rowcount or 0)
        if not dry_run:
            await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return counts


async def requeue(organization_id: UUID, limit: int, dry_run: bool) -> int:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                """
                SELECT s.id, s.organization_id, s.knowledge_base_id, s.name, s.type
                FROM kb_sources s
                WHERE s.organization_id = :org
                  AND s.type IN ('file','csv','excel')
                ORDER BY s.created_at ASC
                LIMIT :limit
                """
            ),
            {"org": organization_id, "limit": limit},
        )
        sources = result.fetchall()
    finally:
        await session.close()

    job_repo = PostgresIngestionJobRepository()
    job_types = {"file": "sync_source:file", "csv": "sync_source:csv", "excel": "sync_source:excel"}
    enqueued = 0
    for source in sources:
        job_type = job_types.get(source.type)
        if job_type is None:
            continue
        _print(f"[{'DRY' if dry_run else 'ENQ'}] source={source.id} name={source.name!r}")
        if dry_run:
            continue
        job = await job_repo.create_job(
            source.organization_id,
            job_type=job_type,
            source_id=source.id,
            knowledge_base_id=source.knowledge_base_id,
            max_attempts=3,
        )
        await enqueue_knowledge_job(str(job.id))
        enqueued += 1
    return enqueued


async def _main(args: argparse.Namespace) -> None:
    organization_id = UUID(args.org) if args.org else None
    source_id = UUID(args.source) if args.source else None
    if args.legacy_conflicts:
        removed = await purge_legacy_conflicts(
            organization_id, all_orgs=args.all_orgs, dry_run=args.dry_run
        )
        scope = "todas las orgs" if args.all_orgs else str(organization_id)
        _print(
            f"Conflictos legacy {'contados' if args.dry_run else 'eliminados'}: "
            f"{removed} ({scope})"
        )
    if args.purge:
        if organization_id is None:
            raise SystemExit("--purge requiere --org")
        counts = await purge(
            organization_id, source_id, dry_run=args.dry_run
        )
        _print(f"Purga {'(dry-run)' if args.dry_run else ''}: {counts}")
    if args.requeue:
        if organization_id is None:
            raise SystemExit("--requeue requiere --org")
        enqueued = await requeue(organization_id, args.limit, args.dry_run)
        _print(f"Fuentes encoladas: {enqueued} (dry_run={args.dry_run})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproceso limpio del Knowledge OS (purga + reingesta)"
    )
    parser.add_argument("--org", help="Organization UUID (requerido salvo --all-orgs)")
    parser.add_argument("--source", help="Fuente UUID (purga scoped a esa fuente)")
    parser.add_argument("--purge", action="store_true", help="Elimina conocimiento del compilador")
    parser.add_argument("--requeue", action="store_true", help="Reencola fuentes para reingesta")
    parser.add_argument(
        "--legacy-conflicts",
        action="store_true",
        help=(
            "Elimina conflictos que no pasan el gate nuevo (sin fuentes o sin "
            "clasificación de conflicto real)"
        ),
    )
    parser.add_argument(
        "--all-orgs",
        action="store_true",
        help="Con --legacy-conflicts: limpia todas las organizaciones",
    )
    parser.add_argument("--limit", type=int, default=50, help="Máx. fuentes a reencolar")
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada")
    args = parser.parse_args()
    if not args.org and not args.all_orgs:
        parser.error("--org es obligatorio (o usa --all-orgs con --legacy-conflicts)")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
