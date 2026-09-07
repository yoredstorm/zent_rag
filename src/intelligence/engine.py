# =============================================================================
# Intelligence Engine — fachada del pipeline de answerability
# =============================================================================
# Compone: understand -> plan -> evidencia -> señales -> gate -> answer/abstain.
# Se inyecta en el RAGOrchestrator; el LLM nunca es la única señal.
# =============================================================================
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from src.core.domain.entities import RetrievalContext
from src.core.domain.intelligence import (
    AnswerabilityDecision,
    AnswerabilityStatus,
    BusinessDefinition,
    ConfidenceLevel,
    EvidenceObject,
    IntelligenceTrace,
    QueryPlan,
    QueryUnderstanding,
)
from src.core.domain.semantic import SemanticCompileResult
from src.core.ports.sql_expert import SqlQueryResult
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.abstention import AbstentionBuilder, AbstentionMessage
from src.intelligence.answerability import AnswerabilityGate
from src.intelligence.definitions import BusinessDefinitionRegistry
from src.intelligence.evidence import EvidenceCollector
from src.intelligence.planner import QueryPlanner
from src.intelligence.semantic_compiler import SemanticCompiler
from src.intelligence.signals import SignalCollector, SignalSet
from src.intelligence.store import PostgresIntelligenceStore
from src.intelligence.trace import TraceRecorder
from src.intelligence.understanding import QueryUnderstandingService

logger = get_logger(__name__)

FreshnessResolver = Callable[
    [UUID, list[str]], Awaitable[dict[str, str]]
]

AuthorityResolver = Callable[
    [UUID, list[str]], Awaitable[str | None]
]


class IntelligenceEngine:
    """Pipeline de answerability usado por el orchestrator (no reescribe RAG)."""

    def __init__(
        self,
        *,
        llm_provider: Any | None = None,
        definition_registry: BusinessDefinitionRegistry | None = None,
        store: PostgresIntelligenceStore | None = None,
        cache: Any | None = None,
        min_meaningful_score: float = 0.1,
        min_score: float = 0.6,
        coverage_min: float = 0.2,
        conflict_tolerance_pct: float = 5.0,
        freshness_max_days: int = 30,
        llm_critic_enabled: bool = False,
        concept_llm_enabled: bool = True,
        sql_router_threshold: float = 0.5,
        freshness_resolver: FreshnessResolver | None = None,
        authority_resolver: AuthorityResolver | None = None,
    ) -> None:
        self._store = store or PostgresIntelligenceStore()
        self._definitions = definition_registry or BusinessDefinitionRegistry(
            store=self._store, cache=cache
        )
        self._understanding_service = QueryUnderstandingService(
            llm_provider=llm_provider,
            concept_llm_enabled=concept_llm_enabled,
        )
        self._compiler = SemanticCompiler()
        self._planner = QueryPlanner()
        self._collector = EvidenceCollector()
        self._signals = SignalCollector(
            min_meaningful_score=min_meaningful_score,
            freshness_max_days=freshness_max_days,
            retrieval_coverage_min=coverage_min,
        )
        self._gate = AnswerabilityGate(
            min_score=min_score,
            coverage_min=coverage_min,
            conflict_tolerance_pct=conflict_tolerance_pct,
            llm_critic_enabled=llm_critic_enabled,
            llm_provider=llm_provider,
        )
        self._abstention = AbstentionBuilder()
        self._sql_router_threshold = sql_router_threshold
        self._freshness_resolver = freshness_resolver
        self._authority_resolver = authority_resolver
        self.tracer = TraceRecorder(self._store)

    async def get_definitions(
        self, organization_id: UUID
    ) -> list[BusinessDefinition]:
        return await self._definitions.get_all(organization_id)

    async def resolve_authoritative_source(
        self, organization_id: UUID, concepts: list[str]
    ) -> str | None:
        """Fuente autoritativa para los conceptos (FASE 24 — catalog_authority).

        Alimenta al Answerability Gate para resolver SOURCE_CONFLICT sin
        elegir fuentes arbitrariamente. Fail-soft: None sin catálogo.
        """
        if self._authority_resolver is None or not concepts:
            return None
        try:
            return await self._authority_resolver(organization_id, concepts)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------- pipeline
    async def understand(
        self,
        organization_id: UUID,
        query: str,
        use_llm: bool = True,
    ) -> QueryUnderstanding:
        return await self._understanding_service.understand(
            query,
            resolve_concepts=lambda concepts: self._definitions.resolve_concepts(
                organization_id, concepts
            ),
            use_llm=use_llm,
        )

    async def compile(
        self,
        organization_id: UUID,
        understanding: QueryUnderstanding,
        *,
        query: str = "",
    ) -> SemanticCompileResult:
        """Build Business Semantic AST and resolve against approved definitions.

        Runs after understand, before plan. Never invents physical SQL joins.
        """
        definitions = await self._definitions.get_all(organization_id)
        return self._compiler.compile(
            understanding,
            query=query,
            definitions=definitions,
        )

    def plan(
        self,
        understanding: QueryUnderstanding,
        *,
        query: str,
        sql_available: bool,
        router_score: float | None = None,
        kb_available: bool = True,
        tools_available: bool = False,
        compile_result: SemanticCompileResult | None = None,
    ) -> QueryPlan:
        return self._planner.plan(
            understanding,
            query=query,
            sql_available=sql_available,
            router_score=router_score,
            sql_router_threshold=self._sql_router_threshold,
            kb_available=kb_available,
            tools_available=tools_available,
            compile_result=compile_result,
        )

    async def collect_evidence(
        self,
        *,
        organization_id: UUID,
        query: str,
        understanding: QueryUnderstanding,
        retrieval_context: RetrievalContext | None,
        sql_result: SqlQueryResult | None,
        definitions: list[BusinessDefinition],
        min_meaningful_score: float = 0.1,
    ) -> list[EvidenceObject]:
        evidences: list[EvidenceObject] = []

        if sql_result is not None and sql_result.sql:
            evidence = EvidenceCollector.from_sql_result(sql_result)
            evidence.value = self._first_numeric_value(sql_result)
            if evidence.value is not None:
                evidence.metadata["metric"] = query[:200]
            evidences.append(evidence)

        if retrieval_context and retrieval_context.chunks:
            freshness_map: dict[str, str] = {}
            if self._freshness_resolver is not None:
                try:
                    source_ids = {
                        str(c.metadata.get("source_id") or "")
                        for c in retrieval_context.chunks
                        if c.metadata.get("source_id")
                    }
                    if source_ids:
                        freshness_map = await self._freshness_resolver(
                            organization_id, sorted(source_ids)
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Freshness resolution failed", error=str(exc)
                    )
            evidences.extend(
                EvidenceCollector.from_retrieval_chunks(
                    retrieval_context,
                    min_score=min_meaningful_score,
                    freshness=freshness_map.get(
                        str(
                            (
                                retrieval_context.chunks[0].metadata or {}
                            ).get("source_id", "")
                        )
                    ),
                )
            )

        for definition in definitions:
            if definition.concept in (understanding.concepts or []):
                evidences.append(EvidenceCollector.from_definition(definition))

        return evidences

    @staticmethod
    def _first_numeric_value(sql_result: SqlQueryResult) -> float | None:
        if not sql_result.rows or not sql_result.columns:
            return None
        for row in sql_result.rows:
            for cell in row:
                try:
                    return float(cell)
                except (TypeError, ValueError):
                    continue
        return None

    def collect_signals(
        self,
        understanding: QueryUnderstanding,
        plan: QueryPlan,
        retrieval_context: RetrievalContext | None,
        sql_result: SqlQueryResult | None,
        evidences: list[EvidenceObject],
        *,
        permission_ok: bool = True,
    ) -> SignalSet:
        return self._signals.collect(
            understanding,
            plan,
            retrieval_context,
            sql_result,
            evidences,
            permission_ok=permission_ok,
        )

    def evaluate(
        self,
        signals: SignalSet,
        understanding: QueryUnderstanding,
        plan: QueryPlan,
        evidences: list[EvidenceObject],
        *,
        execution_error: str | None = None,
        missing_data_hints: list[str] | None = None,
        authoritative_source: str | None = None,
    ) -> AnswerabilityDecision:
        return self._gate.evaluate(
            signals,
            understanding,
            plan,
            evidences,
            execution_error=execution_error,
            missing_data_hints=missing_data_hints,
            authoritative_source=authoritative_source,
        )

    async def run_critic(
        self,
        *,
        question: str,
        answer: str,
        evidences: list[EvidenceObject],
        decision: AnswerabilityDecision,
    ) -> AnswerabilityDecision:
        if not self._gate.critic_enabled:
            return decision
        evidence_text = "\n---\n".join(
            (e.content or "")[:800]
            for e in evidences
            if e.content
        ) or "Sin evidencia textual"
        critic_result = await self._gate.critic(
            question=question,
            answer=answer,
            evidence_text=evidence_text,
        )
        return self._gate.apply_critic(decision, critic_result)

    def build_abstention(self, decision: AnswerabilityDecision) -> AbstentionMessage:
        return self._abstention.build(decision)

    def confidence_level(self, decision: AnswerabilityDecision) -> ConfidenceLevel:
        return decision.confidence_level

    # ------------------------------------------------------------- side effects
    async def record_outcome(
        self,
        *,
        organization_id: UUID,
        decision: AnswerabilityDecision,
    ) -> None:
        """Registra gaps de contexto/datos para hacerlos accionables."""
        if decision.status == AnswerabilityStatus.CONTEXT_MISSING:
            for concept in decision.missing_context:
                await self._store.record_gap(
                    organization_id=organization_id,
                    gap_type="CONTEXT_MISSING",
                    concept=concept.replace("Definition of ", ""),
                    hints=decision.found,
                )
        elif decision.status == AnswerabilityStatus.DATA_MISSING:
            for hint in decision.missing_data:
                await self._store.record_gap(
                    organization_id=organization_id,
                    gap_type="DATA_MISSING",
                    concept=hint[:160],
                    hints=[],
                )

    async def save_trace(self, trace: IntelligenceTrace) -> None:
        await self._store.save_trace(trace)
