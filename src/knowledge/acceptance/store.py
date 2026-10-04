# =============================================================================
# Acceptance — store Postgres (probes + evaluaciones, scoped por tenant)
# =============================================================================
# Los probes son objetos versionados y re-ejecutables. La evaluación es un
# snapshot inmutable (métricas + probes fallidos) para auditoría y tendencia.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

from .contracts import AcceptanceReport, RetrievalProbe

logger = get_logger(__name__)


class PostgresAcceptanceStore:
    """Persistencia de probes/aceptación. Nunca cruza organization_id."""

    async def save_probes(self, probes: tuple[RetrievalProbe, ...]) -> int:
        if not probes:
            return 0
        session = await get_async_session()
        try:
            for probe in probes:
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_retrieval_probes (
                            probe_id, organization_id, workspace_id, source_id,
                            document_id, semantic_unit_id, query, query_type,
                            expected_document_id, expected_section_id,
                            expected_unit_id, expected_entity_ids, generated_by,
                            generator_version, policy_version, active, metadata,
                            created_at, updated_at
                        ) VALUES (
                            :probe_id, :organization_id, :workspace_id, :source_id,
                            :document_id, :semantic_unit_id, :query, :query_type,
                            :expected_document_id, :expected_section_id,
                            :expected_unit_id, CAST(:expected_entity_ids AS jsonb),
                            :generated_by, :generator_version, :policy_version,
                            :active, CAST(:metadata AS jsonb), now(), now()
                        )
                        ON CONFLICT (probe_id) DO UPDATE SET
                            query = EXCLUDED.query,
                            query_type = EXCLUDED.query_type,
                            expected_document_id = EXCLUDED.expected_document_id,
                            expected_section_id = EXCLUDED.expected_section_id,
                            expected_unit_id = EXCLUDED.expected_unit_id,
                            expected_entity_ids = EXCLUDED.expected_entity_ids,
                            generator_version = EXCLUDED.generator_version,
                            policy_version = EXCLUDED.policy_version,
                            metadata = EXCLUDED.metadata,
                            updated_at = now()
                        """
                    ),
                    {
                        "probe_id": probe.probe_id,
                        "organization_id": str(probe.organization_id),
                        "workspace_id": str(probe.workspace_id) if probe.workspace_id else None,
                        "source_id": str(probe.source_id) if probe.source_id else None,
                        "document_id": str(probe.document_id),
                        "semantic_unit_id": probe.semantic_unit_id,
                        "query": probe.query,
                        "query_type": probe.query_type,
                        "expected_document_id": probe.expected_document_id,
                        "expected_section_id": probe.expected_section_id,
                        "expected_unit_id": probe.expected_unit_id,
                        "expected_entity_ids": json.dumps(list(probe.expected_entity_ids)),
                        "generated_by": probe.generated_by,
                        "generator_version": probe.generator_version,
                        "policy_version": probe.policy_version,
                        "active": bool(probe.active),
                        "metadata": json.dumps(probe.metadata or {}, default=str),
                    },
                )
            await session.commit()
            return len(probes)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_probes(
        self,
        organization_id: UUID,
        *,
        document_id: UUID | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {"oid": str(organization_id), "limit": max(1, min(limit, 1000))}
            if document_id is not None:
                where.append("document_id = :did")
                params["did"] = str(document_id)
            if active_only:
                where.append("active = true")
            rows = (
                await session.execute(
                    text(
                        "SELECT probe_id, organization_id, workspace_id, source_id, "  # noqa: S608
                        "document_id, semantic_unit_id, query, "
                        "query_type, expected_document_id, expected_section_id, "
                        "expected_unit_id, expected_entity_ids, generator_version, "
                        "policy_version, active, last_result, last_evaluated_at, "
                        "metadata FROM knowledge_retrieval_probes WHERE "
                        + " AND ".join(where)  # where: fragmentos constantes
                        + " ORDER BY query_type, query LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [_probe_row(row) for row in rows]
        finally:
            await session.close()

    async def set_probe_active(
        self, organization_id: UUID, probe_id: str, active: bool
    ) -> None:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "UPDATE knowledge_retrieval_probes SET active = :active, "
                    "updated_at = now() WHERE organization_id = :oid "
                    "AND probe_id = :pid"
                ),
                {"active": bool(active), "oid": str(organization_id), "pid": str(probe_id)},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def update_probe_results(self, report: AcceptanceReport) -> None:
        """Guarda el último resultado por probe (re-ejecutable sin re-ingesta)."""
        if not report.outcomes:
            return
        session = await get_async_session()
        try:
            for outcome in report.outcomes:
                await session.execute(
                    text(
                        "UPDATE knowledge_retrieval_probes SET last_result = "
                        "CAST(:result AS jsonb), last_evaluated_at = now(), "
                        "updated_at = now() WHERE organization_id = :oid "
                        "AND probe_id = :pid"
                    ),
                    {
                        "result": json.dumps(outcome.to_dict(), default=str),
                        "oid": str(report.organization_id),
                        "pid": outcome.probe_id,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def save_evaluation(self, report: AcceptanceReport) -> str | None:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        """
                        INSERT INTO knowledge_retrieval_evaluations (
                            organization_id, workspace_id, source_id, document_id,
                            mode, accepted, retrievable, probes_total, probes_passed,
                            probes_failed, recall_at_1, recall_at_3, recall_at_5, mrr,
                            metrics, failed_probes, generator_version, policy_version,
                            duration_ms, created_at
                        ) VALUES (
                            :organization_id, :workspace_id, :source_id, :document_id,
                            :mode, :accepted, :retrievable, :probes_total, :probes_passed,
                            :probes_failed, :recall_at_1, :recall_at_3, :recall_at_5, :mrr,
                            CAST(:metrics AS jsonb), CAST(:failed_probes AS jsonb),
                            :generator_version, :policy_version, :duration_ms, now()
                        ) RETURNING id
                        """
                    ),
                    {
                        "organization_id": str(report.organization_id),
                        "workspace_id": str(report.workspace_id) if report.workspace_id else None,
                        "source_id": str(report.source_id) if report.source_id else None,
                        "document_id": str(report.document_id) if report.document_id else None,
                        "mode": report.mode,
                        "accepted": bool(report.accepted),
                        "retrievable": bool(report.retrievable),
                        "probes_total": int(report.probes_total),
                        "probes_passed": int(report.probes_passed),
                        "probes_failed": int(report.probes_failed),
                        "recall_at_1": report.recall_at_1,
                        "recall_at_3": report.recall_at_3,
                        "recall_at_5": report.recall_at_5,
                        "mrr": report.mrr,
                        "metrics": json.dumps(
                            {
                                "state": report.gate_state,
                                "correct_document_rate": report.correct_document_rate,
                                "correct_section_rate": report.correct_section_rate,
                                "evidence_hit_rate": report.evidence_hit_rate,
                                "semantic_hit_rate": report.semantic_hit_rate,
                                "lexical_hit_rate": report.lexical_hit_rate,
                                "top_score": report.top_score,
                                "min_recall_at_5": report.min_recall_at_5,
                                **dict(report.details or {}),
                            },
                            default=str,
                        ),
                        "failed_probes": json.dumps(
                            [outcome.to_dict() for outcome in report.failed_probes],
                            default=str,
                        ),
                        "generator_version": report.generator_version,
                        "policy_version": report.policy_version,
                        "duration_ms": float(report.duration_ms),
                    },
                )
            ).fetchone()
            await session.commit()
            return str(row.id) if row else None
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_evaluations(
        self,
        organization_id: UUID,
        *,
        document_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            where = ["organization_id = :oid"]
            params: dict = {"oid": str(organization_id), "limit": max(1, min(limit, 500))}
            if document_id is not None:
                where.append("document_id = :did")
                params["did"] = str(document_id)
            rows = (
                await session.execute(
                    text(
                        "SELECT id, organization_id, workspace_id, source_id, "
                        "document_id, mode, accepted, retrievable, probes_total, "
                        "probes_passed, probes_failed, recall_at_1, recall_at_3, "
                        "recall_at_5, mrr, metrics, failed_probes, generator_version, "
                        "policy_version, duration_ms, created_at "
                        "FROM knowledge_retrieval_evaluations WHERE "
                        + " AND ".join(where)
                        + " ORDER BY created_at DESC LIMIT :limit"
                    ),
                    params,
                )
            ).fetchall()
            return [_evaluation_row(row) for row in rows]
        finally:
            await session.close()

    async def last_evaluation(
        self, organization_id: UUID, document_id: UUID
    ) -> dict | None:
        rows = await self.list_evaluations(
            organization_id, document_id=document_id, limit=1
        )
        return rows[0] if rows else None


def probe_from_row(row: dict) -> RetrievalProbe:
    """Fila persistida -> objeto de probe (re-ejecutable sin re-ingesta)."""
    return RetrievalProbe(
        probe_id=row["probe_id"],
        organization_id=UUID(row["organization_id"]) if row.get("organization_id") else UUID(int=0),
        document_id=UUID(row["document_id"]) if row.get("document_id") else UUID(int=0),
        workspace_id=UUID(row["workspace_id"]) if row.get("workspace_id") else None,
        source_id=UUID(row["source_id"]) if row.get("source_id") else None,
        query=row["query"],
        query_type=row["query_type"],
        expected_document_id=row.get("expected_document_id") or "",
        expected_section_id=row.get("expected_section_id"),
        expected_unit_id=row.get("expected_unit_id"),
        expected_entity_ids=tuple(row.get("expected_entity_ids") or ()),
        generator_version=row.get("generator_version") or "",
        policy_version=row.get("policy_version") or "",
        active=bool(row.get("active", True)),
        metadata=row.get("metadata") or {},
    )


def _probe_row(row) -> dict:
    return {
        "probe_id": str(row.probe_id),
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "source_id": str(row.source_id) if row.source_id else None,
        "document_id": str(row.document_id) if row.document_id else None,
        "semantic_unit_id": row.semantic_unit_id,
        "query": row.query,
        "query_type": row.query_type,
        "expected_document_id": row.expected_document_id,
        "expected_section_id": row.expected_section_id,
        "expected_unit_id": row.expected_unit_id,
        "expected_entity_ids": list(row.expected_entity_ids or []),
        "generator_version": row.generator_version,
        "policy_version": row.policy_version,
        "active": bool(row.active),
        "last_result": row.last_result or None,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
        "metadata": row.metadata or {},
    }


def _evaluation_row(row) -> dict:
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "workspace_id": str(row.workspace_id) if row.workspace_id else None,
        "source_id": str(row.source_id) if row.source_id else None,
        "document_id": str(row.document_id) if row.document_id else None,
        "mode": row.mode,
        "accepted": bool(row.accepted),
        "retrievable": bool(row.retrievable),
        "probes_total": int(row.probes_total or 0),
        "probes_passed": int(row.probes_passed or 0),
        "probes_failed": int(row.probes_failed or 0),
        "recall_at_1": row.recall_at_1,
        "recall_at_3": row.recall_at_3,
        "recall_at_5": row.recall_at_5,
        "mrr": row.mrr,
        "metrics": row.metrics or {},
        "failed_probes": row.failed_probes or [],
        "generator_version": row.generator_version,
        "policy_version": row.policy_version,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
