# =============================================================================
# Thin hook so RAGOrchestrator does not import JEV.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.core.domain.adaptive import (
    AdaptivePlan,
    AdaptiveTrace,
    EvidenceQuality,
    EvidenceSet,
    GroundingResult,
    RetrievalAttempt,
)
from src.core.domain.decision import RoutingDecision
from src.core.domain.entities import RetrievalContext
from src.decision.judgment import PHASE_GROUNDING, JudgmentContext
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.tracing import trace_span
from src.rag.adaptive.evidence import EvidenceEvaluator, build_evidence_set
from src.rag.adaptive.fast_path import extract_answer, should_fast_path
from src.rag.adaptive.grounding import evaluate_grounding, maybe_jev_grounding
from src.rag.adaptive.metrics import (
    record_attempts,
    record_grounding,
    record_llm_skipped,
    record_plan,
    record_quality,
    record_tokens,
)
from src.rag.adaptive.planner import AdaptivePlanner
from src.rag.adaptive.retry import next_plan
from src.rag.adaptive.rewrite import maybe_rewrite
from src.rag.adaptive.settings import AdaptiveRagSettings, settings_from_app

logger = get_logger(__name__)

_INSUFFICIENT_ES = (
    "No existe suficiente evidencia en las fuentes disponibles."
)


class OrchestratorAdaptiveHook:
    def __init__(
        self,
        settings: AdaptiveRagSettings | None = None,
        *,
        judge=None,
        cache=None,
        llm=None,
        high_confidence: float = 0.90,
        rewrite_model: str | None = None,
        claims_ledger=None,
    ) -> None:
        self._settings = settings or settings_from_app()
        self._judge = judge
        self._llm = llm
        self._rewrite_model = rewrite_model
        self._claims_ledger = claims_ledger
        self._planner = AdaptivePlanner(
            self._settings,
            judge=judge,
            cache=cache,
            high_confidence=high_confidence,
        )
        self._evaluator = EvidenceEvaluator(self._settings, judge=judge)

    @property
    def settings(self) -> AdaptiveRagSettings:
        return self._settings

    def enabled(self) -> bool:
        return self._settings.enabled()

    async def plan(
        self,
        *,
        organization_id: UUID,
        request_id: UUID,
        query: str,
        sql_enabled: bool,
        routing: RoutingDecision | None = None,
        knowledge_base_id: UUID | None = None,
        tenant_top_k_max: int | None = None,
    ) -> AdaptivePlan:
        async with trace_span("adaptive.plan"):
            plan = await self._planner.plan(
                organization_id=organization_id,
                request_id=request_id,
                query=query,
                sql_enabled=sql_enabled,
                routing=routing,
                knowledge_base_id=knowledge_base_id,
                tenant_top_k_max=tenant_top_k_max,
            )
        record_plan(plan)
        return plan

    async def maybe_rewrite_query(self, plan: AdaptivePlan, query: str) -> str | None:
        if not plan.apply or not plan.rewrite_needed:
            return None
        rewritten = await maybe_rewrite(
            query,
            needed=True,
            llm=self._llm,
            model=self._rewrite_model,
        )
        if rewritten:
            plan.rewritten_query = rewritten
        return rewritten

    def build_evidence(
        self,
        *,
        query: str,
        retrieval: RetrievalContext | None,
        sql_result: Any | None,
    ) -> EvidenceSet:
        return build_evidence_set(query=query, retrieval=retrieval, sql_result=sql_result)

    def deterministic_quality(self, evidence: EvidenceSet) -> EvidenceQuality:
        """Reglas determinísticas sin JEV (zona fuerte / débil / incierta)."""
        from src.rag.adaptive.evidence import evaluate_deterministic

        return evaluate_deterministic(evidence, self._settings)

    def select_passages(
        self,
        evidence: EvidenceSet,
        *,
        quality: EvidenceQuality | None = None,
        max_candidates: int | None = None,
    ):
        """Preselección determinística de passages para el judge."""
        from src.rag.adaptive.passages import select_passages

        return select_passages(
            evidence,
            quality=quality or self.deterministic_quality(evidence),
            settings=self._settings,
            max_candidates=max_candidates,
        )

    async def judge_passages(
        self,
        evidence: EvidenceSet,
        *,
        quality: EvidenceQuality | None = None,
        selection=None,
        organization_id: UUID | None = None,
        request_id: UUID | None = None,
    ):
        """JEV sobre passages dudosos (sin evidence gate; ver evaluate_evidence)."""
        from src.rag.adaptive.passages import judge_passages

        return await judge_passages(
            evidence,
            judge=self._judge,
            settings=self._settings,
            quality=quality,
            selection=selection,
            organization_id=organization_id,
            request_id=request_id,
        )

    def apply_passages(self, evidence: EvidenceSet, selection, *, retrieval=None):
        """Drops fuera del contexto; flags etiquetados. Nunca ejecuta acciones."""
        from src.rag.adaptive.passages import apply_passages

        return apply_passages(evidence, selection, retrieval=retrieval)

    async def evaluate_evidence(
        self,
        evidence: EvidenceSet,
        *,
        organization_id: UUID,
        request_id: UUID | None = None,
        passages=None,
    ) -> EvidenceQuality:
        async with trace_span("adaptive.evidence"):
            # JEV mira la misma evidencia (fragmentos completos elegidos por
            # relevancia) dentro del presupuesto configurado del run.
            try:
                from src.core.config import get_settings

                budget = int(
                    getattr(get_settings(), "RUNTIME_EVIDENCE_BUDGET_CHARS", 0) or 0
                )
            except Exception:  # noqa: BLE001
                budget = 0
            quality = await self._evaluator.evaluate(
                evidence,
                organization_id=organization_id,
                request_id=request_id,
                passages=passages,
                state_char_budget=budget or 12_000,
            )
        record_quality(quality)
        return quality

    def retry_plan(
        self,
        plan: AdaptivePlan,
        quality: EvidenceQuality,
        attempt: int,
    ) -> AdaptivePlan | None:
        return next_plan(plan, quality, attempt, self._settings)

    def pack_chunks(self, retrieval: RetrievalContext | None, plan: AdaptivePlan) -> int:
        """Trim context to dynamic top_k. Returns tokens after packing (approx)."""
        if retrieval is None or not plan.apply:
            return _approx_tokens(retrieval)
        before = _approx_tokens(retrieval)
        retrieval.chunks = list(retrieval.chunks[: max(1, plan.top_k)])
        after = _approx_tokens(retrieval)
        record_tokens(before, after)
        return after

    def try_fast_path(
        self,
        plan: AdaptivePlan,
        quality: EvidenceQuality,
        evidence: EvidenceSet,
        query: str,
    ) -> str | None:
        if not plan.apply or not self._settings.fast_path_enabled:
            return None
        if plan.path == "complex":
            return None
        if not should_fast_path(plan, quality):
            return None
        answer = extract_answer(query, evidence)
        if answer:
            record_llm_skipped()
        return answer

    async def ground(
        self,
        *,
        answer: str,
        evidence: EvidenceSet,
        plan: AdaptivePlan,
        organization_id: UUID | None = None,
        request_id: UUID | None = None,
        agent_id: UUID | None = None,
        regeneration_used: bool = False,
        retrieval_budget_left: int = 0,
        evidence_contradictions: int = 0,
    ) -> GroundingResult:
        result = evaluate_grounding(
            answer=answer, evidence=evidence, settings=self._settings
        )
        if plan.apply:
            result = await maybe_jev_grounding(
                result,
                answer=answer,
                evidence=evidence,
                settings=self._settings,
                judge=self._judge,
                context=JudgmentContext(
                    phase=PHASE_GROUNDING,
                    organization_id=organization_id,
                    request_id=request_id,
                )
                if (organization_id is not None or request_id is not None)
                else None,
                claims_enabled=self._settings.claims_enabled,
                organization_id=organization_id,
                request_id=request_id,
                agent_id=agent_id,
                claims_ledger=self._claims_ledger,
                regeneration_used=regeneration_used,
                retrieval_budget_left=retrieval_budget_left,
                evidence_contradictions=evidence_contradictions,
            )
        record_grounding(result.score)
        return result

    def insufficient_message(self) -> str:
        return _INSUFFICIENT_ES

    async def build_trace(
        self,
        *,
        organization_id: UUID,
        request_id: UUID,
        plan: AdaptivePlan,
        routing: RoutingDecision | None,
        evidence: EvidenceSet | None,
        quality: EvidenceQuality | None,
        attempts: list[RetrievalAttempt],
        grounding: GroundingResult | None,
        generator_model: str | None,
        llm_skipped: bool,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        context_tokens_before: int,
        context_tokens_after: int,
        fallbacks: list[str],
        passages: dict | None = None,
    ) -> dict:
        record_attempts(len(attempts) or 1)
        # Pricing Registry primero; estimated_cost_per_1k solo si el registry cae.
        from src.decision.costs import resolve_cost

        cost = await resolve_cost(
            provider="default",
            model=generator_model or "",
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            legacy_per_1k=self._settings.estimated_cost_per_1k,
        )
        trace = AdaptiveTrace(
            organization_id=organization_id,
            request_id=request_id,
            intent=plan.intent,
            decision_capability=routing.capability if routing is not None else None,
            plan=plan.to_public_dict(),
            source_route=plan.source_route,
            retrieval_strategy=plan.retrieval_strategy,
            retrieved=[item.to_public_dict() for item in (evidence.items if evidence else [])[:12]],
            evidence_evaluation=quality.to_public_dict() if quality else {},
            attempts=[a.to_public_dict() for a in attempts],
            rewrite=plan.rewritten_query,
            generator_model=generator_model,
            llm_skipped=llm_skipped,
            grounding=grounding.to_public_dict() if grounding else None,
            passages=dict(passages or {}),
            jev_decisions=dict(plan.jev_answers),
            confidence=plan.confidence,
            top_k=plan.top_k,
            context_tokens_before=context_tokens_before,
            context_tokens_after=context_tokens_after,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost=cost.amount,
            latency_ms=latency_ms,
            fallbacks=fallbacks,
        )
        if quality and quality.jev_answers:
            trace.jev_decisions = {**trace.jev_decisions, **quality.jev_answers}
        return trace.to_public_dict()


def _approx_tokens(retrieval: RetrievalContext | None) -> int:
    if retrieval is None:
        return 0
    chars = sum(len(c.content or "") for c in retrieval.chunks)
    return max(0, chars // 4)
