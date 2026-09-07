# =============================================================================
# Agent Intelligence Readiness — readiness explicable por agente
# =============================================================================
# 9 dimensiones operativas (no gamificación): knowledge_coverage,
# semantic_coverage, source_health, data_freshness, evaluation_pass_rate,
# answerability_rate, unsupported_question_rate, context_gap_count,
# deployment_health. Caché en agent_readiness.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

_WEIGHTS = {
    "knowledge_coverage": 0.15,
    "semantic_coverage": 0.15,
    "source_health": 0.10,
    "data_freshness": 0.10,
    "evaluation_pass_rate": 0.15,
    "answerability_rate": 0.20,
    "deployment_health": 0.15,
}


class AgentReadinessService:
    """Calcula readiness de inteligencia por agente (operativa)."""

    def __init__(
        self,
        learning_store: PostgresLearningStore,
        catalog_store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._learning = learning_store
        self._catalog = catalog_store
        self._intel = intelligence_store or PostgresIntelligenceStore()

    async def compute(
        self, organization_id: UUID, agent_id: UUID, agent_config: dict | None = None
    ) -> dict:
        dimensions: dict[str, float] = {}

        # Knowledge coverage: tablas con columnas / tablas totales.
        tables = 0
        tables_with_columns = 0
        for source in await self._catalog.list_sources(organization_id):
            for t in await self._catalog.list_tables(
                organization_id, UUID(source["id"]), limit=1000
            ):
                tables += 1
                if await self._catalog.list_columns(
                    organization_id, UUID(t["id"])
                ):
                    tables_with_columns += 1
        dimensions["knowledge_coverage"] = round(
            tables_with_columns / max(tables, 1) * 100, 2
        )

        # Semantic coverage: entidades aprobadas / tablas.
        entities = await self._catalog.list_entities(organization_id, limit=1000)
        approved_entities = sum(1 for e in entities if e["status"] == "approved")
        dimensions["semantic_coverage"] = round(
            approved_entities / max(tables, 1) * 100, 2
        )

        # Source health: fuentes en estado productivo.
        sources = await self._catalog.list_sources(organization_id)
        healthy = sum(
            1
            for s in sources
            if s["phase"] in ("COMPLETED", "WAITING_REVIEW")
        )
        dimensions["source_health"] = round(
            healthy / max(len(sources), 1) * 100, 2
        )

        # Data freshness: readiness.freshness promedio.
        freshness_values: list[float] = []
        for s in sources:
            from src.catalog.readiness import ReadinessService

            report = await ReadinessService(
                self._catalog, intelligence_store=self._intel
            ).for_source(organization_id, UUID(s["id"]))
            freshness_values.append(report.freshness)
        dimensions["data_freshness"] = round(
            sum(freshness_values) / max(len(freshness_values), 1), 2
        )

        # Evaluation pass rate: último run de evaluación del agente (o de la org).
        try:
            from src.rag.evaluation.store import list_eval_runs

            runs = await list_eval_runs(organization_id, limit=50)
            agent_runs = [
                r
                for r in runs
                if str(r.get("target_id") or "") == str(agent_id)
            ] or runs
            best_composite = max(
                (float((r.get("quality") or {}).get("composite_score") or 0))
                for r in agent_runs
            ) if agent_runs else 0.0
            dimensions["evaluation_pass_rate"] = round(best_composite * 100, 2)
        except Exception:  # noqa: BLE001
            dimensions["evaluation_pass_rate"] = 0.0

        # Answerability / unsupported rate: traces del org (últimos 30 días).
        from src.core.domain.intelligence import AnswerabilityStatus

        answerable = 0
        total = 0
        try:
            answerable = await self._intel.count_traces_by_status(
                organization_id, AnswerabilityStatus.ANSWERABLE, days=30
            )
        except Exception:  # noqa: BLE001
            pass
        total = answerable
        for status in AnswerabilityStatus:
            if status == AnswerabilityStatus.ANSWERABLE:
                continue
            try:
                total += await self._intel.count_traces_by_status(
                    organization_id, status, days=30
                )
            except Exception:  # noqa: BLE001
                pass
        dimensions["answerability_rate"] = round(
            answerable / max(total, 1) * 100, 2
        )
        dimensions["unsupported_question_rate"] = round(
            100 - dimensions["answerability_rate"], 2
        )

        # Context gaps abiertos.
        gaps = await self._intel.list_gaps(organization_id, status="open", limit=500)
        dimensions["context_gap_count"] = float(len(gaps))

        # Deployment health.
        try:
            from sqlalchemy import text

            from src.infrastructure.postgres.session import get_async_session

            session = await get_async_session()
            try:
                row = (
                    await session.execute(
                        text(
                            "SELECT COUNT(*) FROM deployments WHERE agent_id = :agent "
                            "AND status = 'healthy'"
                        ),
                        {"agent": agent_id},
                    )
                ).fetchone()
                dimensions["deployment_health"] = round(
                    float(int(row[0] or 0) >= 1) * 100, 2
                )
            finally:
                await session.close()
        except Exception:  # noqa: BLE001
            dimensions["deployment_health"] = 0.0

        score = sum(
            dimensions.get(k, 0.0) * w for k, w in _WEIGHTS.items()
        )
        overall = "HIGH" if score >= 75 else ("MEDIUM" if score >= 50 else "LOW")
        result = {
            "overall": overall,
            "score": round(score, 2),
            "dimensions": dimensions,
        }
        await self._learning.save_agent_readiness(
            organization_id=organization_id,
            agent_id=agent_id,
            overall=overall,
            score=round(score, 2),
            dimensions=dimensions,
        )
        return result
