# =============================================================================
# Signals — señales deterministas del Answerability Gate
# =============================================================================
# El LLM puede actuar como crítico adicional, pero la decisión NUNCA depende
# exclusivamente de él: se combinan señales objetivas del sistema.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.entities import RetrievalContext
from src.core.domain.intelligence import (
    EvidenceObject,
    QueryPlan,
    QueryUnderstanding,
)
from src.core.ports.sql_expert import SqlQueryResult

# Pesos por estrategia del plan: las señales que no aplican a la ruta
# ejecutada no deben inflar el score (p. ej. schema en una ruta solo-RAG).
_SQL_WEIGHTS: dict[str, float] = {
    "intent_resolution": 0.10,
    "concept_resolution": 0.15,
    "schema_link_quality": 0.10,
    "sql_validation": 0.10,
    "sql_execution_success": 0.10,
    "result_presence": 0.15,
    "result_relevance": 0.05,
    "source_freshness": 0.05,
    "source_authority": 0.05,
    "source_agreement": 0.05,
    "business_definition_status": 0.05,
    "permission_check": 0.05,
    "ambiguity": 0.05,
}

_RAG_WEIGHTS: dict[str, float] = {
    "intent_resolution": 0.08,
    "concept_resolution": 0.12,
    "retrieval_relevance": 0.20,
    "retrieval_coverage": 0.20,
    "result_presence": 0.15,
    "result_relevance": 0.05,
    "source_freshness": 0.05,
    "source_authority": 0.05,
    "source_agreement": 0.05,
    "data_quality": 0.05,
    "permission_check": 0.05,
    "ambiguity": 0.05,
}

_FULL_WEIGHTS: dict[str, float] = {
    "intent_resolution": 0.10,
    "concept_resolution": 0.12,
    "schema_link_quality": 0.05,
    "retrieval_relevance": 0.08,
    "retrieval_coverage": 0.08,
    "sql_validation": 0.05,
    "sql_execution_success": 0.05,
    "result_presence": 0.15,
    "result_relevance": 0.05,
    "source_freshness": 0.05,
    "source_authority": 0.05,
    "source_agreement": 0.05,
    "business_definition_status": 0.10,
    "permission_check": 0.05,
    "data_quality": 0.05,
    "ambiguity": 0.05,
}


def weights_for_plan(plan) -> dict[str, float]:
    """Pesos activos según la estrategia del plan (SQL, RAG o mixta)."""
    if getattr(plan, "needs_sql", False) and not getattr(
        plan, "needs_retrieval", False
    ):
        return _SQL_WEIGHTS
    if getattr(plan, "needs_retrieval", False) and not getattr(
        plan, "needs_sql", False
    ):
        return _RAG_WEIGHTS
    return _FULL_WEIGHTS


@dataclass
class SignalSet:
    """Señales objetivas del sistema para decidir answerability (0..1)."""

    intent_resolution: float = 0.0
    concept_resolution: float = 0.0
    schema_link_quality: float = 0.0
    retrieval_relevance: float = 0.0
    retrieval_coverage: float = 0.0
    sql_validation: float = 0.0
    sql_execution_success: float = 0.0
    result_presence: float = 0.0
    result_relevance: float = 0.0
    source_freshness: float = 0.0
    source_authority: float = 0.0
    source_agreement: float = 1.0
    business_definition_status: float = 0.0
    permission_check: float = 1.0
    data_quality: float = 0.0
    ambiguity: float = 0.0
    weights: dict = field(default_factory=dict)

    def score(self, weights: dict | None = None) -> float:
        """Score compuesto ponderado (0..1). Determinista, sin falsa precisión.

        Los pesos explícitos (plan-aware) tienen precedencia; luego los pesos
        calculados por el collector; finalmente los pesos full.
        """
        active = weights or self.weights or _FULL_WEIGHTS
        total_weight = sum(active.values())
        if total_weight <= 0:
            return 0.0
        weighted = sum(
            getattr(self, name) * weight for name, weight in active.items()
        )
        return round(weighted / total_weight, 4)


class SignalCollector:
    """Calcula las señales a partir de las salidas del pipeline."""

    def __init__(
        self,
        *,
        min_meaningful_score: float = 0.1,
        freshness_max_days: int = 30,
        retrieval_coverage_min: float = 0.2,
    ) -> None:
        self._min_meaningful = min_meaningful_score
        self._freshness_max_days = freshness_max_days
        self._coverage_min = retrieval_coverage_min

    def collect(
        self,
        understanding: QueryUnderstanding,
        plan: QueryPlan,
        retrieval_context: RetrievalContext | None,
        sql_result: SqlQueryResult | None,
        evidences: list[EvidenceObject],
        *,
        permission_ok: bool = True,
    ) -> SignalSet:
        signals = SignalSet()

        # --- Intención resuelta? ---
        signals.intent_resolution = 1.0 if understanding.intent != "general" else 0.3

        # --- Conceptos empresariales (definiciones aprobadas) ---
        resolved = understanding.resolved_concepts or {}
        if not resolved:
            signals.concept_resolution = 1.0
            signals.business_definition_status = 1.0
        else:
            defined = sum(1 for v in resolved.values() if v)
            ratio = defined / len(resolved)
            signals.concept_resolution = ratio
            signals.business_definition_status = ratio

        # --- Retrieval ---
        chunks = (retrieval_context.chunks or []) if retrieval_context else []
        meaningful = [c for c in chunks if c.score >= self._min_meaningful]
        if chunks:
            signals.retrieval_relevance = min(
                max(c.score for c in chunks) / 1.0, 1.0
            )
            signals.retrieval_coverage = min(len(meaningful) / len(chunks), 1.0)
        else:
            signals.retrieval_relevance = 0.0
            signals.retrieval_coverage = 0.0

        # --- SQL ---
        sql_ran = sql_result is not None and not sql_result.error
        if sql_result is not None and sql_result.sql:
            signals.schema_link_quality = 1.0 if sql_ran else 0.5
        signals.sql_validation = 1.0 if sql_ran else 0.0
        signals.sql_execution_success = 1.0 if sql_ran else 0.0

        # --- Resultado presente ---
        # SQL ejecutado con 0 filas ES una respuesta válida ("resultado = 0");
        # se distingue de "no existe data suficiente" (nada ejecutado).
        if sql_ran:
            signals.result_presence = 1.0
            signals.result_relevance = 1.0
        elif meaningful:
            signals.result_presence = 1.0
            signals.result_relevance = signals.retrieval_relevance
        else:
            signals.result_presence = 0.0
            signals.result_relevance = 0.0

        # --- Frescura / autoridad / acuerdo (desde evidencias) ---
        signals.source_freshness = self._freshness_signal(evidences, sql_ran)
        signals.source_authority = self._authority_signal(evidences)
        invalid = [e for e in evidences if e.validation_status == "invalid"]
        signals.source_agreement = 0.0 if invalid else 1.0
        signals.data_quality = round(
            (
                signals.source_freshness
                + signals.source_authority
                + signals.sql_validation
            )
            / 3.0,
            4,
        )

        # --- Permisos ---
        signals.permission_check = 1.0 if permission_ok else 0.0

        # --- Ambigüedad ---
        signals.ambiguity = 1.0 if understanding.ambiguity else 0.0

        signals.weights = weights_for_plan(plan)

        return signals

    def _freshness_signal(
        self, evidences: list[EvidenceObject], sql_live: bool
    ) -> float:
        if sql_live:
            return 1.0
        if not evidences:
            return 0.0
        scores: list[float] = []
        for e in evidences:
            if e.type.value in ("sql_result", "api_response", "tool_result"):
                scores.append(1.0)
            elif e.freshness == "approved":
                scores.append(1.0)
            elif e.freshness and e.freshness.isdigit():
                days = int(e.freshness)
                if days <= self._freshness_max_days:
                    scores.append(1.0)
                else:
                    scores.append(
                        max(0.0, 1.0 - (days - self._freshness_max_days) / 30.0)
                    )
            else:
                scores.append(0.5)
        return round(sum(scores) / len(scores), 4) if scores else 0.0

    @staticmethod
    def _authority_signal(evidences: list[EvidenceObject]) -> float:
        if not evidences:
            return 0.0
        ranking = {
            "authoritative": 1.0,
            "approved": 0.9,
            "informational": 0.6,
            "external": 0.4,
        }
        return max(ranking.get(e.authority_level, 0.4) for e in evidences)
