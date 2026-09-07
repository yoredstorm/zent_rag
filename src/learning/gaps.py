# =============================================================================
# Context Gap Engine — ContextGapAnalyzer (FASE 25)
# =============================================================================
# Cada consulta no contestable se convierte en un gap estructurado con
# evidencia e impacto. Mapeo determinista decision.status -> gap_type (el LLM
# nunca es la fuente del gap). Los conflictos se registran SIEMPRE, aun si la
# autoridad los resolvió.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
)
from src.core.domain.learning import ContextGapType, SourceConflictRecord
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

# Mapeo determinista estado -> gap (el analizador no "opina").
_STATUS_TO_GAP: dict[AnswerabilityStatus, ContextGapType] = {
    AnswerabilityStatus.CONTEXT_MISSING: ContextGapType.MISSING_BUSINESS_TERM,
    AnswerabilityStatus.DATA_MISSING: ContextGapType.MISSING_TABLE,
    AnswerabilityStatus.SOURCE_CONFLICT: ContextGapType.SOURCE_CONFLICT,
    AnswerabilityStatus.DATA_QUALITY_LOW: ContextGapType.LOW_DATA_QUALITY,
    AnswerabilityStatus.ACCESS_BLOCKED: ContextGapType.PERMISSION_LIMITATION,
    AnswerabilityStatus.AMBIGUOUS: ContextGapType.AMBIGUOUS_TERM,
    AnswerabilityStatus.CLARIFICATION_REQUIRED: ContextGapType.AMBIGUOUS_TERM,
    AnswerabilityStatus.EXECUTION_FAILED: ContextGapType.UNSUPPORTED_OPERATION,
    AnswerabilityStatus.HUMAN_REVIEW_REQUIRED: ContextGapType.LOW_DATA_QUALITY,
}

# reason_codes que refinan el gap.
_REASON_REFINEMENT = {
    "UNDEFINED_BUSINESS_TERM": ContextGapType.MISSING_BUSINESS_TERM,
    "NO_SOURCE_AVAILABLE": ContextGapType.MISSING_SOURCE,
    "NO_SQL_RESULT": ContextGapType.MISSING_TABLE,
    "NO_RETRIEVAL": ContextGapType.MISSING_TABLE,
    "AMBIGUOUS_QUERY": ContextGapType.AMBIGUOUS_TERM,
    "SOURCE_DISAGREEMENT": ContextGapType.SOURCE_CONFLICT,
    "PERMISSION_DENIED": ContextGapType.PERMISSION_LIMITATION,
    "LOW_DATA_QUALITY": ContextGapType.LOW_DATA_QUALITY,
    "BUDGET_EXCEEDED": ContextGapType.UNSUPPORTED_OPERATION,
    "CRITIC_UNSUPPORTED": ContextGapType.LOW_DATA_QUALITY,
}


class ContextGapAnalyzer:
    """Convierte abstenciones en gaps estructurados con impacto."""

    def __init__(
        self,
        learning_store: PostgresLearningStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = learning_store
        self._intel = intelligence_store or PostgresIntelligenceStore()

    def map_gap_type(
        self, decision: AnswerabilityDecision
    ) -> ContextGapType | None:
        """Mapeo determinista decision -> gap_type (None si answerable)."""
        if decision.answerable:
            return None
        for code in decision.reason_codes:
            if code in _REASON_REFINEMENT:
                return _REASON_REFINEMENT[code]
        return _STATUS_TO_GAP.get(decision.status)

    @staticmethod
    def _extract_concept(decision: AnswerabilityDecision, question: str) -> str:
        if decision.missing_context:
            return decision.missing_context[0].replace("Definition of ", "")
        if decision.missing_data:
            return decision.missing_data[0][:160]
        for c in decision.conflicting_sources:
            concept = c.get("metric")
            if concept and concept != "__generic__":
                return str(concept)[:160]
        return (question or "unknown")[:160]

    async def analyze_and_record(
        self,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        question: str,
        decision: AnswerabilityDecision,
    ) -> ContextGapType | None:
        """Analiza una abstención y registra el gap + impacto (fail-soft).

        Los conflictos se registran SIEMPRE, incluso si la autoridad los
        resolvió (decisión answerable con conflicting_sources).
        """
        try:
            # Conflictos: registrar SIEMPRE (incluso si la autoridad resolvió).
            if decision.conflicting_sources:
                concept_hint = (
                    decision.missing_context[0].replace("Definition of ", "")
                    if decision.missing_context
                    else ""
                )
                for conflict in decision.conflicting_sources:
                    await self._store.record_source_conflict(
                        SourceConflictRecord(
                            organization_id=organization_id,
                            concept=str(conflict.get("metric") or concept_hint or "conflict")[:160],
                            question=question,
                            source_a=str(conflict.get("source_a") or ""),
                            value_a=conflict.get("value_a"),
                            source_b=str(conflict.get("source_b") or ""),
                            value_b=conflict.get("value_b"),
                            resolved_by_authority=(
                                decision.status != AnswerabilityStatus.SOURCE_CONFLICT
                            ),
                            authority_source=(
                                None
                                if decision.status == AnswerabilityStatus.SOURCE_CONFLICT
                                else "authority"
                            ),
                        )
                    )

            gap_type = self.map_gap_type(decision)
            if gap_type is None:
                return None
            concept = self._extract_concept(decision, question)

            hints: list[str] = []
            hints.extend(decision.found)
            hints.extend(decision.missing_context)
            hints.extend(decision.missing_data)
            hints = list(dict.fromkeys(h for h in hints if h))[:20]

            impact = await self._impact(organization_id, decision.status, user_id)

            await self._intel.record_gap(
                organization_id=organization_id,
                gap_type=gap_type.value,
                concept=concept,
                hints=hints,
                question=question,
                impact=impact,
            )
            return gap_type
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gap analysis failed", error=str(exc)[:200])
            return None

    async def _impact(
        self,
        organization_id: UUID,
        status: AnswerabilityStatus,
        user_id: UUID | None,
    ) -> dict:
        """Impacto real: queries 30d, usuarios distintos, agentes de la org."""
        impact: dict = {"query_count_30d": 0, "users": 0, "agents": 0}
        try:
            impact["query_count_30d"] = await self._intel.count_traces_by_status(
                organization_id, status
            )
            impact["users"] = await self._intel.count_trace_users(
                organization_id, status
            )
            impact["agents"] = await self._count_agents(organization_id)
        except Exception:  # noqa: BLE001
            pass
        return impact

    @staticmethod
    async def _count_agents(organization_id: UUID) -> int:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM agents WHERE organization_id = :oid "
                        "AND status <> 'archived'"
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:  # noqa: BLE001
            return 0
        finally:
            await session.close()
