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
#   python -m src.scripts.knowledge_reprocess --org <uuid> --invalidate-representation
#   python -m src.scripts.knowledge_reprocess --org <uuid> --reevaluate [--document <uuid>]
#
# La purga respeta la provenance: solo elimina filas creadas por el Knowledge
# Compiler (`metadata->>'compiled_by' = 'knowledge_compiler'`), salvo
# `knowledge_conflicts` y `knowledge_ingestion_quality`, que son íntegramente
# de esta pipeline.
#
# La reingesta corre el pipeline corregido con la Semantic Reconstruction Layer
# obligatoria (source -> adapter -> IR -> gate -> compiler): el conocimiento
# viejo con artifacts nunca se conserva "por compatibilidad".
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


async def invalidate_representation(
    organization_id: UUID, source_id: UUID | None, *, dry_run: bool
) -> int:
    """Limpia el fingerprint indexado para forzar re-materialización selectiva.

    No purga evidencia ni conocimiento: el próximo sync ve representación stale
    (content igual + fingerprint ausente → CREATE/REINDEX) y re-indexa solo lo
    necesario.
    """
    session = await get_async_session()
    where = (
        "organization_id = :org "
        "AND (metadata ? 'indexed_representation_fingerprint' "
        "OR metadata ? 'indexed_representation_descriptor')"
    )
    params: dict = {"org": organization_id}
    if source_id is not None:
        where += " AND source_id = :source"
        params["source"] = source_id
    try:
        if dry_run:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) AS total FROM structured_documents WHERE "  # noqa: S608
                        + where  # where: fragmentos constantes
                    ),
                    params,
                )
            ).first()
            return int(row.total or 0)
        result = await session.execute(
            text(
                "UPDATE structured_documents SET metadata = (metadata - "  # noqa: S608
                "'indexed_representation_fingerprint' - "
                "'indexed_representation_descriptor') || "
                "jsonb_build_object('representation_invalidated_by', 'manual'), "
                "updated_at = now() WHERE " + where  # where: fragmentos constantes
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


async def reevaluate(
    organization_id: UUID,
    document_id: UUID | None,
    *,
    limit: int,
    dry_run: bool,
) -> dict:
    """Re-ejecuta acceptance con los probes persistidos (sin re-ingerir)."""
    from src.api.deps import get_embedding_provider, get_vector_store
    from src.knowledge.acceptance import (
        PostgresAcceptanceStore,
        evaluate_probes,
        probe_from_row,
    )

    session = await get_async_session()
    try:
        where = ["organization_id = :org", "active = true"]
        params: dict = {"org": organization_id, "limit": limit}
        if document_id is not None:
            where.append("document_id = :doc")
            params["doc"] = document_id
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT document_id FROM knowledge_retrieval_probes "  # noqa: S608
                    "WHERE " + " AND ".join(where) + " LIMIT :limit"  # fragmentos constantes
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()

    store = PostgresAcceptanceStore()
    summary: dict = {"documents": len(rows), "evaluated": 0, "accepted": 0, "failed": 0}
    for row in rows:
        doc_uuid = row.document_id
        probe_rows = await store.list_probes(
            organization_id, document_id=doc_uuid, active_only=True, limit=500
        )
        if not probe_rows:
            continue
        if dry_run:
            _print(f"[DRY] reevaluate document={doc_uuid} probes={len(probe_rows)}")
            continue
        report = await evaluate_probes(
            tuple(probe_from_row(item) for item in probe_rows),
            embedder=get_embedding_provider(),
            vector_store=get_vector_store(),
            role="admin",
        )
        await store.save_evaluation(report)
        await store.update_probe_results(report)
        summary["evaluated"] += 1
        if report.accepted:
            summary["accepted"] += 1
        else:
            summary["failed"] += 1
        _print(
            f"[EVAL] document={doc_uuid} recall@5={report.recall_at_5} "
            f"mrr={report.mrr} accepted={report.accepted}"
        )
    return summary


#: Heurística declarada para estimaciones de backfill (tokens por chunk).
ESTIMATED_TOKENS_PER_CHUNK = 180


def estimate_reembedding(vectors: int, *, tokens_per_chunk: int = ESTIMATED_TOKENS_PER_CHUNK) -> dict:
    """Estimación explícita (no promesa): vectores -> embeddings/tokens/costo.

    El costo se completa en `_main` con el pricing real si está disponible.
    """
    vectors = max(0, int(vectors))
    tokens = vectors * max(1, int(tokens_per_chunk))
    return {
        "vectors_affected": vectors,
        "estimated_embeddings": vectors,
        "estimated_tokens": tokens,
        "tokens_per_chunk_assumption": int(tokens_per_chunk),
    }


async def _count_vectors(
    organization_id: UUID, source_id: UUID | None
) -> int | None:
    """Cuenta vectores V2 reales (Qdrant) para estimar; None si no disponible."""
    try:
        from src.api.deps import get_vector_store

        return await get_vector_store().count_document_points(
            organization_id, source_id=source_id
        )
    except Exception as exc:  # noqa: BLE001 — la estimación nunca frena el CLI
        _print(f"[WARN] no se pudo contar vectores: {str(exc)[:160]}")
        return None


async def _estimate_cost_usd(tokens: int) -> float | None:
    try:
        from src.core.config import get_settings
        from src.platform.billing.pricing import estimate_cost

        model = str(getattr(get_settings(), "EMBEDDING_MODEL", "") or "")
        return float(await estimate_cost(model, 0, 0, embedding_tokens=tokens))
    except Exception:  # noqa: BLE001 — sin pricing, estimación parcial
        return None


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
    if args.invalidate_representation:
        if organization_id is None:
            raise SystemExit("--invalidate-representation requiere --org")
        touched = await invalidate_representation(
            organization_id, source_id, dry_run=args.dry_run
        )
        _print(
            f"Fingerprints de representación "
            f"{'contados' if args.dry_run else 'invalidados'}: {touched} "
            f"(dry_run={args.dry_run})"
        )
        from src.knowledge.representation import invalidation_plan

        plan = invalidation_plan("manual")
        _print(
            "Plan de invalidación (manual): "
            f"stale={[kind.value for kind in plan.stale]} "
            f"acciones={list(plan.actions)} "
            f"reembed={plan.requires_reembedding}"
        )
        if args.dry_run:
            vectors = await _count_vectors(organization_id, source_id)
            if vectors is not None:
                estimates = estimate_reembedding(vectors)
                cost = await _estimate_cost_usd(estimates["estimated_tokens"])
                if cost is not None:
                    estimates["estimated_cost_usd"] = round(cost, 6)
                _print(f"Estimación: {estimates}")
    if args.reevaluate:
        if organization_id is None:
            raise SystemExit("--reevaluate requiere --org")
        document_id = UUID(args.document) if args.document else None
        summary = await reevaluate(
            organization_id, document_id, limit=args.limit, dry_run=args.dry_run
        )
        _print(f"Re-evaluación: {summary}")


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
    parser.add_argument("--document", help="Document UUID (para --reevaluate)")
    parser.add_argument(
        "--invalidate-representation",
        action="store_true",
        help=(
            "Limpia el fingerprint de representación indexado (el próximo sync "
            "re-materializa e indexa sin purgar evidencia)"
        ),
    )
    parser.add_argument(
        "--reevaluate",
        action="store_true",
        help="Re-ejecuta acceptance con los probes persistidos (sin re-ingerir)",
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribe nada")
    args = parser.parse_args()
    if not args.org and not args.all_orgs:
        parser.error("--org es obligatorio (o usa --all-orgs con --legacy-conflicts)")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
