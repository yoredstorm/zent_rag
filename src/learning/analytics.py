# =============================================================================
# Learning Analytics — tendencias y Continuous Improvement (solo datos reales)
# =============================================================================
# answerability/abstention trends, gap trends + resolution rate, semantic
# coverage, patrones de éxito, clusters de fallos, conceptos faltantes más
# impactantes, cambios de conocimiento, impacto de evaluación. Nada inventado.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.core.domain.intelligence import AnswerabilityStatus
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.intelligence.store import PostgresIntelligenceStore
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)


class LearningAnalytics:
    """Agregados de aprendizaje del ciclo gobernado."""

    def __init__(
        self,
        learning_store: PostgresLearningStore,
        catalog_store: PostgresCatalogStore | None = None,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._learning = learning_store
        self._catalog = catalog_store
        self._intel = intelligence_store or PostgresIntelligenceStore()

    async def trends(self, organization_id: UUID, days: int = 30) -> dict:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT status, COUNT(*) AS n FROM intelligence_traces "
                        "WHERE organization_id = :oid AND created_at >= :since "
                        "GROUP BY status"
                    ),
                    {"oid": organization_id, "since": since},
                )
            ).fetchall()
            by_status = {r.status: int(r.n) for r in rows}
        finally:
            await session.close()

        total = sum(by_status.values())
        answerable = by_status.get(AnswerabilityStatus.ANSWERABLE.value, 0)
        abstained = total - answerable

        gaps = await self._intel.list_gaps(organization_id, limit=500)
        open_gaps = sum(1 for g in gaps if g["status"] == "open")
        resolved = sum(1 for g in gaps if g["status"] == "resolved")

        improvements = await self._learning.list_improvements(
            organization_id, limit=500
        )
        unresolved_improvements = sum(
            1 for i in improvements if i["status"] in ("OPEN", "IN_REVIEW")
        )
        most_impactful = sorted(
            improvements, key=lambda i: i["affected_queries"], reverse=True
        )[:5]

        replays = await self._learning.list_replays(organization_id, limit=100)
        replay_verdicts = {
            v: sum(1 for r in replays if r["verdict"] == v)
            for v in ("pass", "warn", "fail", "unknown")
        }

        return {
            "days": days,
            "total_queries": total,
            "answerable_queries": answerable,
            "abstained_queries": abstained,
            "answerability_rate": round(answerable / max(total, 1) * 100, 2),
            "unsupported_question_rate": round(abstained / max(total, 1) * 100, 2),
            "context_gaps_open": open_gaps,
            "context_gaps_resolved": resolved,
            "gap_resolution_rate": round(resolved / max(open_gaps + resolved, 1) * 100, 2),
            "improvements_open": unresolved_improvements,
            "most_impactful_missing_concepts": [
                {
                    "title": i["title"],
                    "gap_type": i["gap_type"],
                    "affected_queries": i["affected_queries"],
                }
                for i in most_impactful
            ],
            "knowledge_approvals_30d": len(
                await self._learning.list_approval_records(organization_id, limit=500)
            ),
            "evaluation_replays": {
                "total": len(replays),
                **replay_verdicts,
            },
        }

    async def monthly_summary(self, organization_id: UUID) -> dict:
        """Continuous Improvement del mes (solo métricas de datos reales)."""
        since = datetime.now(timezone.utc) - timedelta(days=30)
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT "
                        "(SELECT COUNT(*) FROM business_definitions WHERE "
                        " organization_id = :oid AND updated_at >= :since "
                        " AND status = 'approved') AS approved_definitions, "
                        "(SELECT COUNT(*) FROM catalog_relationships WHERE "
                        " organization_id = :oid AND reviewed_at >= :since "
                        " AND status = 'confirmed') AS validated_relationships, "
                        "(SELECT COUNT(*) FROM catalog_authority WHERE "
                        " organization_id = :oid AND created_at >= :since) "
                        " AS new_authorities, "
                        "(SELECT COUNT(*) FROM context_gaps WHERE "
                        " organization_id = :oid AND resolved_at >= :since) "
                        " AS resolved_gaps"
                    ),
                    {"oid": organization_id, "since": since},
                )
            ).fetchone()
            approved_definitions = int(rows.approved_definitions or 0)
            validated_relationships = int(rows.validated_relationships or 0)
            new_authorities = int(rows.new_authorities or 0)
            resolved_gaps = int(rows.resolved_gaps or 0)
        finally:
            await session.close()

        # Deltas de answerability: mes actual vs mes anterior (traces).
        month_start = datetime.now(timezone.utc) - timedelta(days=30)
        prev_start = month_start - timedelta(days=30)
        current = await self._rates(organization_id, month_start)
        previous = await self._rates(organization_id, prev_start, month_start)

        return {
            "period": "month",
            "approved_definitions": approved_definitions,
            "validated_relationships": validated_relationships,
            "new_authoritative_sources": new_authorities,
            "resolved_context_gaps": resolved_gaps,
            "answerability_delta_pct": round(
                current["rate"] - previous["rate"], 2
            ),
            "unsupported_delta_pct": round(
                current["unsupported"] - previous["unsupported"], 2
            ),
            "current_answerability_rate": round(current["rate"], 2),
        }

    async def _rates(
        self, organization_id: UUID, since: datetime, before: datetime | None = None
    ) -> dict:
        session = await get_async_session()
        try:
            query = (
                "SELECT status, COUNT(*) AS n FROM intelligence_traces "
                "WHERE organization_id = :oid AND created_at >= :since "
            )
            params: dict = {"oid": organization_id, "since": since}
            if before is not None:
                query += "AND created_at < :before "
                params["before"] = before
            query += "GROUP BY status"
            rows = (await session.execute(text(query), params)).fetchall()
        finally:
            await session.close()
        total = sum(int(r.n) for r in rows)
        answerable = sum(
            int(r.n) for r in rows if r.status == AnswerabilityStatus.ANSWERABLE.value
        )
        return {
            "rate": answerable / max(total, 1) * 100,
            "unsupported": (total - answerable) / max(total, 1) * 100,
        }
