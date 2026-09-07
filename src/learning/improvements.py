# =============================================================================
# Improvement Queue — backlog centralizado de mejoras de inteligencia
# =============================================================================
# Priorización DETERMINISTA con señales reales (no LLM judgment):
# query_frequency, users, agents, business_criticality, failure_rate,
# source_authority, evaluation_failures, recent_growth.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.learning import ImprovementItem, ImprovementStatus, PriorityLevel
from src.infrastructure.observability.logging_config import get_logger
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

# Pesos de señales (configurables por código; documentados).
_WEIGHTS = {
    "query_frequency": 0.30,
    "users": 0.15,
    "agents": 0.20,
    "business_criticality": 0.15,
    "failure_rate": 0.10,
    "source_authority": 0.05,
    "evaluation_failures": 0.05,
}

_CRITICAL_TERMS = {"margin", "margen", "revenue", "ingresos", "churn", "profit", "ganancia", "rentab"}
_HIGH_TERMS = {"customer", "cliente", "order", "pedido", "sales", "venta", "inventory", "stock", "costo"}


class ImprovementQueue:
    """Genera y prioriza items de mejora a partir de gaps y señales."""

    def __init__(self, store: PostgresLearningStore) -> None:
        self._store = store

    @staticmethod
    def priority_for(
        *,
        query_frequency: int,
        users: int,
        agents: int,
        concept: str,
        source_authoritative: bool = False,
        failure_rate: float = 0.0,
        eval_failures: int = 0,
    ) -> PriorityLevel:
        """Score determinista 0..1 + umbrales a nivel de prioridad."""
        concept_l = (concept or "").lower()
        criticality = 1.0 if any(t in concept_l for t in _CRITICAL_TERMS) else (
            0.6 if any(t in concept_l for t in _HIGH_TERMS) else 0.3
        )
        freq = min(query_frequency / 200.0, 1.0)
        user_s = min(users / 20.0, 1.0)
        agent_s = min(agents / 5.0, 1.0)
        fail_s = min(failure_rate, 1.0)
        auth_s = 0.8 if source_authoritative else 0.3
        eval_s = min(eval_failures / 20.0, 1.0)

        score = (
            freq * _WEIGHTS["query_frequency"]
            + user_s * _WEIGHTS["users"]
            + agent_s * _WEIGHTS["agents"]
            + criticality * _WEIGHTS["business_criticality"]
            + fail_s * _WEIGHTS["failure_rate"]
            + auth_s * _WEIGHTS["source_authority"]
            + eval_s * _WEIGHTS["evaluation_failures"]
        )
        if score >= 0.75:
            return PriorityLevel.CRITICAL
        if score >= 0.55:
            return PriorityLevel.HIGH
        if score >= 0.35:
            return PriorityLevel.MEDIUM
        return PriorityLevel.LOW

    async def sync_from_gap(
        self,
        *,
        organization_id: UUID,
        gap_type: str,
        concept: str,
        question: str | None,
        evidence: list[str],
        impact: dict,
        recommended_action: str,
    ) -> UUID | None:
        """Crea/actualiza un improvement item desde un gap (dedupe por concept)."""
        queries = int(impact.get("query_count_30d") or 1)
        users = int(impact.get("users") or 0)
        agents = int(impact.get("agents") or 0)
        priority = self.priority_for(
            query_frequency=queries,
            users=users,
            agents=agents,
            concept=concept,
            source_authoritative=False,
        )
        item = ImprovementItem(
            organization_id=organization_id,
            priority=priority,
            gap_type=gap_type,
            title=f"{concept} ({gap_type})",
            description=(
                f"Preguntas no contestables relacionadas: {question or concept}."
            ),
            evidence=list(evidence or [])[:10],
            affected_queries=queries,
            affected_users=users,
            affected_agents=agents,
            recommended_action=recommended_action,
            estimated_impact={"answerability_impact": "high" if priority in (
                PriorityLevel.CRITICAL, PriorityLevel.HIGH
            ) else "medium"},
            status=ImprovementStatus.OPEN,
            suggested_concept=concept,
            cluster_key=concept[:64],
        )
        return await self._store.upsert_improvement(item, dedupe_key=concept)

    async def sync_from_cluster(
        self,
        *,
        organization_id: UUID,
        cluster_key: str,
        title: str,
        questions: list[str],
        concept_hint: str | None = None,
    ) -> UUID | None:
        """Item de mejora desde un cluster de preguntas no contestadas."""
        priority = self.priority_for(
            query_frequency=len(questions),
            users=0,
            agents=0,
            concept=concept_hint or title,
        )
        item = ImprovementItem(
            organization_id=organization_id,
            priority=priority,
            gap_type="UNSUPPORTED_OPERATION",
            title=title,
            description=(
                f"{len(questions)} preguntas similares sin respuesta."
            ),
            evidence=list(questions)[:10],
            affected_queries=len(questions),
            recommended_action="Revisar el concepto sugerido y definirlo en el glosario",
            estimated_impact={"cluster_size": len(questions)},
            status=ImprovementStatus.IN_REVIEW,
            suggested_concept=concept_hint,
            cluster_key=cluster_key,
        )
        return await self._store.upsert_improvement(item, dedupe_key=cluster_key)

    async def sync_from_metric_pattern(
        self,
        *,
        organization_id: UUID,
        sql: str,
        question_sample: str,
        query_count: int,
    ) -> UUID | None:
        """Sugerencia 'métrica reusable' desde SQL exitoso repetido (nunca aprobado)."""
        item = ImprovementItem(
            organization_id=organization_id,
            priority=PriorityLevel.MEDIUM,
            gap_type="MISSING_METRIC",
            title=f"Crear métrica reusable para: {question_sample[:120]}",
            description=(
                f"{query_count} consultas exitosas usaron exactamente la misma "
                f"lógica SQL. Sugerencia: crear una business metric (no se "
                f"convierte SQL en definición aprobada automáticamente)."
            ),
            evidence=[sql[:500]],
            affected_queries=query_count,
            recommended_action="Crear la métrica en /catalog/metrics y aprobarla",
            estimated_impact={"repeated_sql": True},
            status=ImprovementStatus.IN_REVIEW,
            cluster_key=None,
        )
        # Sin cluster_key -> no dedupe por SQL; usa el título como clave.
        item.cluster_key = f"metric:{abs(hash(sql)) % (10 ** 12):012x}"
        return await self._store.upsert_improvement(item, dedupe_key=item.cluster_key)
