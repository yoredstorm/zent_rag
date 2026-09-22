# =============================================================================
# Adaptive planner — Rules + optional JEV. DecisionEngine owns JEV access.
# =============================================================================
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from src.agents.tools.sql_router import SqlIntentRouter
from src.core.domain.adaptive import (
    AdaptivePath,
    AdaptivePlan,
    DataModality,
    RetrievalStrategyName,
    SourceRoute,
)
from src.core.domain.decision import RoutingDecision
from src.decision.batch import answer_for, noul_for
from src.decision.judgment import PHASE_PRE_RETRIEVAL, JudgmentContext, call_phase_judge
from src.decision.questions import noul_from_answer, noul_is_yes
from src.rag.adaptive.cache import deserialize_plan, plan_cache_key, serialize_plan
from src.rag.adaptive.classifier import RulesClassifier, overlay_modality, overlay_strategy
from src.rag.adaptive.questions import build_query_questions, public_answers
from src.rag.adaptive.rewrite import rewrite_needed_from_jev, rules_need_rewrite
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.adaptive.top_k import resolve_top_k
from src.rag.retrieval.models import STRATEGY_HYBRID, STRATEGY_VECTOR

_COMPARE_RE = re.compile(
    r"\b(compara|comparar|contradic|versus|vs\.?|difference|diferenc)\w*\b",
    re.IGNORECASE,
)
_MULTI_DOC_RE = re.compile(r"\b(documentos?|fuentes?|pol[ií]ticas?)\b", re.IGNORECASE)
_GREETING_RE = re.compile(
    r"^\s*(hola|hello|hi|hey|buenas|buen d[ií]a|thanks|gracias)[\s\!\.\?]*$",
    re.IGNORECASE,
)


def _engine_strategy(name: str) -> tuple[str, float]:
    if name == RetrievalStrategyName.EXACT.value:
        return STRATEGY_HYBRID, 0.75
    if name == RetrievalStrategyName.LEXICAL.value:
        return STRATEGY_HYBRID, 0.70
    if name == RetrievalStrategyName.VECTOR.value:
        return STRATEGY_VECTOR, 0.15
    if name == RetrievalStrategyName.STRUCTURED.value:
        return STRATEGY_VECTOR, 0.20
    if name == RetrievalStrategyName.MIXED.value:
        return STRATEGY_HYBRID, 0.45
    return STRATEGY_HYBRID, 0.35


class AdaptivePlanner:
    def __init__(
        self,
        settings: AdaptiveRagSettings,
        *,
        judge=None,
        cache=None,
        high_confidence: float = 0.90,
    ) -> None:
        self._settings = settings
        self._judge = judge
        self._cache = cache
        self._high_confidence = high_confidence
        self._rules = RulesClassifier()

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
        apply = self._settings.should_apply(request_id)
        mode = self._settings.effective_mode
        cache_key = plan_cache_key(
            organization_id=organization_id,
            query=query,
            knowledge_base_id=knowledge_base_id,
            policy_version=self._settings.policy_version,
        )
        if self._cache is not None:
            try:
                cached = await self._cache.get(cache_key)
            except Exception:  # noqa: BLE001
                cached = None
            plan = deserialize_plan(cached, apply=apply, mode=mode)
            if plan is not None:
                return plan

        classification = self._rules.classify(query)
        sql_score = SqlIntentRouter.heuristic_score(query) if sql_enabled else 0.0
        greeting = bool(_GREETING_RE.match(query or ""))
        compare = bool(_COMPARE_RE.search(query or ""))
        multi = compare and bool(_MULTI_DOC_RE.search(query or ""))
        # Deterministic signal is strong enough on its own: do not spend a
        # second System One call on routing/understanding questions.
        deterministic = (
            greeting
            or classification.kind == "lexical"
            or (sql_enabled and sql_score >= 0.8)
        )

        if greeting:
            modality = DataModality.CONVERSATIONAL.value
            strategy = RetrievalStrategyName.VECTOR.value
            route = SourceRoute.DIRECT.value
            path = AdaptivePath.FAST.value
            rewrite = False
            complexity = "trivial"
        elif sql_score >= 0.8 and classification.kind != "lexical":
            modality = DataModality.STRUCTURED_DATA.value
            strategy = RetrievalStrategyName.STRUCTURED.value
            route = SourceRoute.DATABASE_QUERY.value
            path = AdaptivePath.FAST.value
            rewrite = False
            complexity = "bounded"
        elif sql_score >= 0.5:
            modality = DataModality.MIXED.value
            strategy = RetrievalStrategyName.MIXED.value
            route = SourceRoute.MIXED.value
            path = AdaptivePath.STANDARD.value
            rewrite = False
            complexity = "bounded"
        elif classification.kind == "lexical":
            modality = DataModality.DOCUMENTS.value
            strategy = (
                RetrievalStrategyName.EXACT.value
                if classification.lexical_ratio >= 0.7
                else RetrievalStrategyName.LEXICAL.value
            )
            route = SourceRoute.KNOWLEDGE_SEARCH.value
            path = AdaptivePath.FAST.value
            rewrite = False
            complexity = "trivial"
        elif multi:
            modality = DataModality.DOCUMENTS.value
            strategy = RetrievalStrategyName.HYBRID.value
            route = SourceRoute.KNOWLEDGE_SEARCH.value
            path = AdaptivePath.COMPLEX.value
            rewrite = False
            complexity = "reasoning"
        else:
            modality = DataModality.DOCUMENTS.value
            strategy = (
                RetrievalStrategyName.HYBRID.value
                if classification.kind == "mixed"
                else RetrievalStrategyName.VECTOR.value
            )
            route = SourceRoute.KNOWLEDGE_SEARCH.value
            path = AdaptivePath.STANDARD.value
            rewrite = False
            complexity = "bounded"

        rules_rewrite = rules_need_rewrite(query)
        if rules_rewrite is True:
            rewrite = True
        elif rules_rewrite is False:
            rewrite = False

        if routing is not None and routing.resolved:
            cap = routing.capability
            if cap.startswith("database."):
                route = SourceRoute.DATABASE_QUERY.value
                modality = DataModality.STRUCTURED_DATA.value
                strategy = RetrievalStrategyName.STRUCTURED.value
            elif cap in {"respond_directly", "llm.reason", "llm.generate"}:
                route = SourceRoute.DIRECT.value
                modality = DataModality.CONVERSATIONAL.value
            elif cap.startswith("tool."):
                route = SourceRoute.TOOL.value
                modality = DataModality.TOOL.value
            elif cap.startswith("workflow."):
                route = SourceRoute.WORKFLOW.value
                modality = DataModality.WORKFLOW.value
            elif cap.startswith("agent."):
                route = SourceRoute.AGENT.value
            needs_reason = answer_for(
                routing.raw_answers, "needs_complex_reasoning", "needs_reasoning"
            )
            if needs_reason is not None and noul_is_yes(
                noul_from_answer(needs_reason, 0.0), self._settings.noul_yes
            ):
                path = AdaptivePath.COMPLEX.value
                complexity = "reasoning"

        jev_answers: dict[str, Any] = {}
        provider = "rules"
        confidence = 0.85 if greeting or classification.kind == "lexical" or sql_score >= 0.8 else 0.6
        if self._judge is not None:
            state = {
                "user_request": (query or "")[:2000],
                "classification_kind": classification.kind,
                "lexical_ratio": classification.lexical_ratio,
                "sql_heuristic": sql_score,
                "sql_enabled": sql_enabled,
                "available_route": route,
            }
            context = JudgmentContext(
                phase=PHASE_PRE_RETRIEVAL,
                organization_id=organization_id,
                request_id=request_id,
            )
            # 1) Reutilizar el payload PRE_RETRIEVAL del request (routing ya pagó
            #    la llamada). 2) Sólo si no hay payload y las reglas no alcanzan,
            #    pedir el juicio con las preguntas del planner.
            payload = await call_phase_judge(
                self._judge,
                phase=PHASE_PRE_RETRIEVAL,
                state=state,
                questions=None,
                context=context,
            )
            if payload is None and not deterministic:
                try:
                    payload = await call_phase_judge(
                        self._judge,
                        phase=PHASE_PRE_RETRIEVAL,
                        state=state,
                        questions=build_query_questions(),
                        context=context,
                    )
                except Exception:  # noqa: BLE001
                    payload = None
            if isinstance(payload, dict):
                answers = payload.get("answers") if isinstance(payload.get("answers"), dict) else payload
                if isinstance(answers, dict) and answers:
                    jev_answers = public_answers(answers)
                    provider = "hybrid"
                    modality_ans = answer_for(answers, "modality") or {}
                    strategy_ans = answer_for(answers, "retrieval_strategy") or {}
                    modality = overlay_modality(
                        rules_modality=modality,
                        jev_modality=str(modality_ans.get("choice") or "") or None,
                        jev_confidence=float(modality_ans.get("confidence") or 0.0),
                        high_confidence=self._high_confidence,
                    )
                    strategy = overlay_strategy(
                        rules_strategy=strategy,
                        jev_strategy=str(strategy_ans.get("choice") or "") or None,
                        jev_confidence=float(strategy_ans.get("confidence") or 0.0),
                        high_confidence=self._high_confidence,
                    )
                    if rules_rewrite is None:
                        rewrite_noul = noul_for(
                            answers, "needs_rewrite", default=None
                        )
                        if rewrite_noul is not None:
                            rewrite = rewrite_needed_from_jev(
                                rewrite_noul, self._settings
                            )
                    reason_noul = noul_for(
                        answers,
                        "needs_reasoning",
                        "needs_complex_reasoning",
                        default=None,
                    )
                    if reason_noul is not None and noul_is_yes(
                        reason_noul, self._settings.noul_yes
                    ):
                        path = AdaptivePath.COMPLEX.value
                        complexity = "reasoning"
                    confs = [
                        float(v.get("confidence") or 0.0)
                        for v in (modality_ans, strategy_ans)
                        if isinstance(v, dict)
                    ]
                    if confs:
                        confidence = max(confidence, sum(confs) / len(confs))

        engine, lexical_weight = _engine_strategy(strategy)
        if strategy in {RetrievalStrategyName.LEXICAL.value, RetrievalStrategyName.EXACT.value}:
            lexical_weight = max(lexical_weight, classification.lexical_ratio)
        elif strategy == RetrievalStrategyName.HYBRID.value:
            lexical_weight = max(0.2, classification.lexical_ratio)

        if path == AdaptivePath.COMPLEX.value:
            reasoning = "complex"
        elif path == AdaptivePath.FAST.value:
            reasoning = "none"
        else:
            reasoning = "light"

        retrieval_req = "none" if route == SourceRoute.DIRECT.value else (
            "structured" if strategy == RetrievalStrategyName.STRUCTURED.value else (
                "lookup" if path == AdaptivePath.FAST.value else "semantic"
            )
        )
        if modality == DataModality.MIXED.value:
            retrieval_req = "mixed"

        skip_retrieval = route in {
            SourceRoute.DIRECT.value,
            SourceRoute.TOOL.value,
            SourceRoute.WORKFLOW.value,
            SourceRoute.DATABASE_QUERY.value,
        }
        skip_sql = route in {SourceRoute.KNOWLEDGE_SEARCH.value, SourceRoute.DIRECT.value}
        prefer_sql = route in {SourceRoute.DATABASE_QUERY.value, SourceRoute.MIXED.value}

        top_k = resolve_top_k(
            path=path,
            complexity=complexity,
            settings=self._settings,
            tenant_max=tenant_top_k_max,
        )
        plan = AdaptivePlan(
            mode=mode,
            apply=apply,
            intent=classification.kind if not greeting else "conversational",
            modality=modality,
            retrieval_requirement=retrieval_req,
            reasoning_requirement=reasoning,
            source_route=route,
            retrieval_strategy=strategy,
            engine_strategy=engine,
            lexical_weight=lexical_weight,
            top_k=top_k,
            path=path,
            skip_retrieval=skip_retrieval and path != AdaptivePath.COMPLEX.value,
            skip_sql=skip_sql,
            prefer_sql=prefer_sql and sql_enabled,
            rewrite_needed=bool(rewrite) and self._settings.rewrite_enabled,
            complexity=complexity,
            confidence=confidence,
            provider=provider,
            classification_kind=classification.kind,
            classification_lexical_ratio=classification.lexical_ratio,
            jev_answers=jev_answers,
        )
        if self._cache is not None:
            try:
                await self._cache.set(
                    cache_key,
                    serialize_plan(plan),
                    ttl_seconds=self._settings.cache_ttl_seconds,
                )
            except Exception:  # noqa: BLE001
                pass
        return plan
