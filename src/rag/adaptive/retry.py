# =============================================================================
# Limited retrieval retry. Max attempts. Never infinite.
# =============================================================================
from __future__ import annotations

from src.core.domain.adaptive import AdaptivePlan, EvidenceQuality
from src.rag.adaptive.settings import AdaptiveRagSettings


def next_plan(
    plan: AdaptivePlan,
    quality: EvidenceQuality,
    attempt: int,
    settings: AdaptiveRagSettings,
) -> AdaptivePlan | None:
    """Attempt 2 = alternate strategy / expanded terms. Attempt 3 = alternate source."""
    if attempt > settings.max_retrieval_attempts:
        return None
    nxt = AdaptivePlan(
        mode=plan.mode,
        apply=plan.apply,
        intent=plan.intent,
        modality=plan.modality,
        retrieval_requirement=plan.retrieval_requirement,
        reasoning_requirement=plan.reasoning_requirement,
        source_route=plan.source_route,
        retrieval_strategy=plan.retrieval_strategy,
        engine_strategy=plan.engine_strategy,
        lexical_weight=plan.lexical_weight,
        top_k=min(settings.top_k_max, plan.top_k + 2),
        path=plan.path,
        skip_retrieval=False,
        skip_sql=plan.skip_sql,
        prefer_sql=plan.prefer_sql,
        rewrite_needed=plan.rewrite_needed,
        rewritten_query=plan.rewritten_query,
        complexity=plan.complexity,
        confidence=plan.confidence,
        provider=plan.provider,
        classification_kind=plan.classification_kind,
        classification_lexical_ratio=plan.classification_lexical_ratio,
        jev_answers=dict(plan.jev_answers),
    )
    if attempt == 2:
        if plan.engine_strategy == "vector":
            nxt.engine_strategy = "hybrid"
            nxt.retrieval_strategy = "hybrid"
            nxt.lexical_weight = max(plan.lexical_weight, 0.4)
        elif plan.engine_strategy == "lexical":
            nxt.engine_strategy = "hybrid"
            nxt.retrieval_strategy = "hybrid"
            nxt.lexical_weight = min(plan.lexical_weight, 0.5)
        else:
            nxt.lexical_weight = min(0.8, plan.lexical_weight + 0.2)
        if quality.coverage < 0.2:
            nxt.rewrite_needed = True
        return nxt
    # attempt 3: alternate source
    if plan.prefer_sql and plan.skip_retrieval:
        nxt.skip_retrieval = False
        nxt.engine_strategy = "hybrid"
        nxt.source_route = "mixed"
    elif plan.skip_sql:
        nxt.skip_sql = False
        nxt.prefer_sql = True
        nxt.source_route = "mixed"
    else:
        nxt.prefer_sql = not plan.prefer_sql
        nxt.source_route = "mixed"
    return nxt
