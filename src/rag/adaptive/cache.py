# =============================================================================
# Decision-aware cache. Never crosses tenants. Plans only, not answers.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from uuid import UUID

from src.core.domain.adaptive import POLICY_VERSION, AdaptivePlan
from src.rag.retrieval.classify import normalize_query


def plan_cache_key(
    *,
    organization_id: UUID,
    query: str,
    knowledge_base_id: UUID | None,
    policy_version: str = POLICY_VERSION,
    decision_model: str = "rules",
) -> str:
    norm = normalize_query(query)
    raw = "|".join(
        [
            str(organization_id),
            str(knowledge_base_id or "-"),
            policy_version,
            decision_model,
            norm,
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"adaptive:plan:{organization_id.hex}:{digest}"


def serialize_plan(plan: AdaptivePlan) -> str:
    return json.dumps(plan.to_public_dict(), separators=(",", ":"))


def deserialize_plan(raw: str | None, *, apply: bool, mode: str) -> AdaptivePlan | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    plan = AdaptivePlan(
        mode=mode,
        apply=apply,
        intent=str(data.get("intent") or "general"),
        modality=str(data.get("modality") or "documents"),
        retrieval_requirement=str(data.get("retrieval_requirement") or "semantic"),
        reasoning_requirement=str(data.get("reasoning_requirement") or "none"),
        source_route=str(data.get("source_route") or "knowledge.search"),
        retrieval_strategy=str(data.get("retrieval_strategy") or "hybrid"),
        engine_strategy=str(data.get("engine_strategy") or "hybrid"),
        lexical_weight=float(data.get("lexical_weight") or 0.3),
        top_k=int(data.get("top_k") or 8),
        path=str(data.get("path") or "standard"),
        skip_retrieval=bool(data.get("skip_retrieval")),
        skip_sql=bool(data.get("skip_sql")),
        prefer_sql=bool(data.get("prefer_sql")),
        rewrite_needed=bool(data.get("rewrite_needed")),
        complexity=str(data.get("complexity") or "bounded"),
        confidence=float(data.get("confidence") or 0.0),
        provider=str(data.get("provider") or "rules"),
        classification_kind=str(data.get("classification_kind") or "semantic"),
        cache_hit=True,
    )
    return plan
