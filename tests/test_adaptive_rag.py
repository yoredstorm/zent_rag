# =============================================================================
# Adaptive RAG — unit tests. JEV mocked. Default mode off does not apply.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.adaptive import POLICY_VERSION, AdaptivePlan
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.rag.adaptive.cache import plan_cache_key
from src.rag.adaptive.classifier import RulesClassifier, overlay_strategy
from src.rag.adaptive.eval import compare_legacy_vs_adaptive
from src.rag.adaptive.evidence import build_evidence_set, evaluate_deterministic
from src.rag.adaptive.fast_path import extract_answer, should_fast_path
from src.rag.adaptive.grounding import evaluate_grounding
from src.rag.adaptive.planner import AdaptivePlanner
from src.rag.adaptive.retry import next_plan
from src.rag.adaptive.rewrite import rules_need_rewrite
from src.rag.adaptive.settings import AdaptiveRagSettings
from src.rag.adaptive.top_k import resolve_top_k
from src.rag.retrieval.classify import classify_query


def _settings(**kwargs) -> AdaptiveRagSettings:
    base = dict(mode="active", max_retrieval_attempts=3)
    base.update(kwargs)
    return AdaptiveRagSettings(**base)


def _chunk(content: str, score: float) -> RetrievalChunk:
    return RetrievalChunk(document_id=uuid4(), content=content, score=score)


@pytest.mark.asyncio
async def test_rules_classifier_keeps_classify_query() -> None:
    query = "SKU-1234 precio"
    assert RulesClassifier().classify(query).kind == classify_query(query).kind


@pytest.mark.asyncio
async def test_planner_sql_question_routes_structured() -> None:
    planner = AdaptivePlanner(_settings())
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="¿Cuántas ventas tuvimos ayer?",
        sql_enabled=True,
    )
    assert plan.apply is True
    assert plan.source_route == "database.query"
    assert plan.retrieval_strategy == "structured"
    assert plan.prefer_sql is True
    assert plan.skip_retrieval is True


@pytest.mark.asyncio
async def test_planner_policy_question_routes_knowledge() -> None:
    planner = AdaptivePlanner(_settings())
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="¿Qué dice nuestra política de vacaciones?",
        sql_enabled=True,
    )
    assert plan.source_route == "knowledge.search"
    assert plan.skip_sql is True
    assert plan.retrieval_strategy in {"vector", "hybrid"}


@pytest.mark.asyncio
async def test_planner_code_query_lexical_fast() -> None:
    planner = AdaptivePlanner(_settings())
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="SKU-1234",
        sql_enabled=False,
    )
    assert plan.path == "fast"
    assert plan.retrieval_strategy in {"exact", "lexical"}
    assert plan.lexical_weight >= 0.4
    assert plan.rewrite_needed is False


@pytest.mark.asyncio
async def test_planner_shadow_does_not_apply() -> None:
    planner = AdaptivePlanner(_settings(mode="shadow"))
    plan = await planner.plan(
        organization_id=uuid4(),
        request_id=uuid4(),
        query="¿Qué dice la política de vacaciones?",
        sql_enabled=True,
    )
    assert plan.apply is False
    assert plan.mode == "shadow"


@pytest.mark.asyncio
async def test_planner_off_disabled_via_settings() -> None:
    cfg = _settings(mode="off")
    assert cfg.enabled() is False
    assert cfg.should_apply(uuid4()) is False


def test_dynamic_top_k_caps() -> None:
    cfg = _settings(top_k_min=3, top_k_max=12, top_k_lookup=3, top_k_multi=12)
    assert resolve_top_k(path="fast", complexity="trivial", settings=cfg) == 3
    assert resolve_top_k(path="complex", complexity="reasoning", settings=cfg) == 12
    assert resolve_top_k(
        path="complex", complexity="reasoning", settings=cfg, tenant_max=5
    ) == 5


def test_evidence_empty_is_insufficient() -> None:
    quality = evaluate_deterministic(
        build_evidence_set(query="hola", retrieval=RetrievalContext(chunks=[]), sql_result=None),
        _settings(),
    )
    assert quality.sufficient is False
    assert quality.reason == "empty"


def test_evidence_high_score_sufficient() -> None:
    ctx = RetrievalContext(
        chunks=[_chunk("La política de vacaciones otorga 15 días hábiles.", 0.82)]
    )
    quality = evaluate_deterministic(
        build_evidence_set(query="política de vacaciones", retrieval=ctx),
        _settings(),
    )
    assert quality.sufficient is True


def test_evidence_exact_code_match() -> None:
    ctx = RetrievalContext(chunks=[_chunk("Carrier code SKU-1234 activo", 0.4)])
    quality = evaluate_deterministic(
        build_evidence_set(query="SKU-1234", retrieval=ctx),
        _settings(),
    )
    assert quality.exact_match is True
    assert quality.sufficient is True


def test_retry_stops_at_max() -> None:
    plan = AdaptivePlan(apply=True, engine_strategy="vector", retrieval_strategy="vector")
    quality = evaluate_deterministic(
        build_evidence_set(query="x", retrieval=RetrievalContext(chunks=[])),
        _settings(),
    )
    cfg = _settings(max_retrieval_attempts=3)
    second = next_plan(plan, quality, 2, cfg)
    third = next_plan(plan, quality, 3, cfg)
    fourth = next_plan(plan, quality, 4, cfg)
    assert second is not None
    assert second.engine_strategy == "hybrid"
    assert third is not None
    assert fourth is None


def test_rewrite_skips_codes() -> None:
    assert rules_need_rewrite("SKU-1234") is False
    assert rules_need_rewrite("eso") is True


def test_cache_key_isolates_tenants() -> None:
    a = uuid4()
    b = uuid4()
    query = "política de vacaciones"
    key_a = plan_cache_key(
        organization_id=a, query=query, knowledge_base_id=None, policy_version=POLICY_VERSION
    )
    key_b = plan_cache_key(
        organization_id=b, query=query, knowledge_base_id=None, policy_version=POLICY_VERSION
    )
    assert key_a != key_b
    assert a.hex in key_a
    assert b.hex in key_b


def test_overlay_keeps_rules_when_jev_low_confidence() -> None:
    assert overlay_strategy(
        rules_strategy="hybrid",
        jev_strategy="vector",
        jev_confidence=0.4,
        high_confidence=0.9,
    ) == "hybrid"
    assert overlay_strategy(
        rules_strategy="hybrid",
        jev_strategy="vector",
        jev_confidence=0.95,
        high_confidence=0.9,
    ) == "vector"


def test_fast_path_extracts_code() -> None:
    evidence = build_evidence_set(
        query="¿Cuál es el código del carrier SKU-1234?",
        retrieval=RetrievalContext(chunks=[_chunk("El carrier usa SKU-1234 en despacho.", 0.9)]),
    )
    plan = AdaptivePlan(apply=True, path="fast")
    quality = evaluate_deterministic(evidence, _settings())
    assert should_fast_path(plan, quality) is True
    extracted = extract_answer(evidence.query, evidence)
    assert extracted is not None
    assert "SKU-1234" in extracted


def test_grounding_abstain_is_grounded() -> None:
    evidence = build_evidence_set(query="x", retrieval=RetrievalContext(chunks=[]))
    result = evaluate_grounding(
        answer="No existe suficiente evidencia en las fuentes disponibles.",
        evidence=evidence,
        settings=_settings(),
    )
    assert result.grounded is True
    assert result.reason == "abstain"


def test_compare_legacy_vs_adaptive_savings() -> None:
    legacy = {
        "run_id": "legacy",
        "quality": {"composite_score": 0.7, "faithfulness": 0.8, "hallucination_rate": 0.1},
        "performance": {"avg_cost": 0.02, "avg_tokens": 1000, "latency": {"p95_ms": 800}},
    }
    adaptive = {
        "run_id": "adaptive",
        "quality": {"composite_score": 0.72, "faithfulness": 0.82, "hallucination_rate": 0.08},
        "performance": {"avg_cost": 0.01, "avg_tokens": 600, "latency": {"p95_ms": 700}},
        "adaptive": {"llm_calls_avoided": 4},
    }
    report = compare_legacy_vs_adaptive(adaptive, legacy)
    assert report["comparison"] == "legacy_vs_adaptive"
    assert report["savings"]["tokens_saved_vs_baseline"] == 400
    assert report["savings"]["llm_calls_avoided"] == 4
    assert "shadow" in report["rollout"]
