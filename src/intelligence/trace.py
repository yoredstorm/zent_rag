# =============================================================================
# Traceability — cada respuesta se puede reconstruir desde su trace
# =============================================================================
# Relaciona: user_query, understanding, query_plan, evidencia, decisión,
# presupuesto, respuesta final y feedback (persistido org-scoped).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.intelligence import (
    AnswerabilityDecision,
    IntelligenceTrace,
)
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)


class TraceRecorder:
    """Construye y persiste trazas de ejecución del Intelligence Layer."""

    def __init__(self, store: PostgresIntelligenceStore | None = None) -> None:
        self._store = store or PostgresIntelligenceStore()

    def build(
        self,
        *,
        organization_id: UUID,
        query_id: UUID | None,
        user_id: UUID | None,
        user_query: str,
        role: str,
        understanding: dict,
        query_plan: dict,
        evidence: list[dict],
        decision: dict,
        status: str,
        answer: str | None,
        method: str,
        model: str | None,
        budget: dict,
        latency_ms: float,
    ) -> IntelligenceTrace:
        return IntelligenceTrace(
            organization_id=organization_id,
            query_id=query_id,
            user_id=user_id,
            user_query=user_query,
            role=role,
            understanding=understanding,
            query_plan=query_plan,
            evidence=evidence,
            decision=decision,
            status=status,
            answer=answer,
            method=method,
            model=model,
            budget=budget,
            latency_ms=latency_ms,
        )

    async def persist(self, trace: IntelligenceTrace) -> None:
        """Fail-soft: un fallo de persistencia nunca rompe la respuesta."""
        await self._store.save_trace(trace)

    async def persist_decision(
        self,
        *,
        organization_id: UUID,
        query_id: UUID | None,
        user_query: str,
        role: str,
        decision: AnswerabilityDecision,
        trace_id: str | None = None,
    ) -> IntelligenceTrace | None:
        trace = self.build(
            organization_id=organization_id,
            query_id=query_id,
            user_query=user_query,
            role=role,
            understanding={},
            query_plan={},
            evidence=[],
            decision=decision.to_dict(),
            status=decision.status.value,
            answer=None,
            method="rag",
            model=None,
            budget={},
            latency_ms=0.0,
        )
        if trace_id:
            trace.trace_id = trace_id
        await self.persist(trace)
        return trace
