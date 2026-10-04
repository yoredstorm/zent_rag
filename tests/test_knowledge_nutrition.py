# =============================================================================
# Knowledge Nutrition — tests
# =============================================================================
# Reglas que se prueban:
#   - clasificación por SEÑALES reales (no intuición LLM)
#   - acciones no destructivas; feedback débil => observed
#   - score: dimensiones no medidas quedan None (nunca 0) y fórmula ponderada
#   - demanda por tipo/concepto
#   - store Postgres scoped por tenant
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.knowledge.acceptance import evaluate_probes, generate_probes
from src.knowledge.enrichment import enrich_document
from src.knowledge.nutrition import (
    NUTRITION_WEIGHTS,
    FailureSignals,
    FailureType,
    NutritionActionStatus,
    NutritionActionType,
    PostgresNutritionStore,
    action_for_classification,
    classify_failure,
    compute_nutrition_score,
    demand_profile_from_acceptance,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _understood(text: str, external_id: str = "manual.md", organization_id=None):
    parser = TextParser()
    document = parser.parse(
        text.encode("utf-8"),
        organization_id=organization_id or uuid4(),
        external_id=external_id,
        source_id=uuid4(),
        source_name=external_id,
    )
    return apply_understanding(document, filename=external_id)


def test_classify_retrieval_miss() -> None:
    result = classify_failure(
        FailureSignals(query="byte 105", retrieved_chunks=0, lexical_hit=False, semantic_hit=False)
    )
    assert result.failure_type == FailureType.RETRIEVAL_MISS.value
    assert result.confidence >= 0.8
    assert result.signals["retrieved_chunks"] == 0


def test_classify_bad_rank_with_low_score() -> None:
    result = classify_failure(
        FailureSignals(query="cat31", retrieved_chunks=8, top_score=0.1, evidence_used=1)
    )
    assert result.failure_type == FailureType.BAD_RANK.value


def test_classify_missing_knowledge_from_negative_feedback() -> None:
    result = classify_failure(
        FailureSignals(
            query="refund window",
            retrieved_chunks=0,
            feedback_rating="down",
            feedback_reason="wrong_answer",
        )
    )
    assert result.failure_type == FailureType.MISSING_KNOWLEDGE.value


def test_classify_stale_parser_and_temporal() -> None:
    assert (
        classify_failure(FailureSignals(stale=True)).failure_type
        == FailureType.STALE_KNOWLEDGE.value
    )
    assert (
        classify_failure(FailureSignals(parser_quality=0.2)).failure_type
        == FailureType.PARSER_FAILURE.value
    )
    assert (
        classify_failure(FailureSignals(temporal_mismatch=True)).failure_type
        == FailureType.TEMPORAL_MISMATCH.value
    )
    assert (
        classify_failure(FailureSignals(acl_filtered=True)).failure_type
        == FailureType.ACL_FILTERED.value
    )


def test_action_mapping_is_never_destructive() -> None:
    classification = classify_failure(
        FailureSignals(query="x", retrieved_chunks=0, lexical_hit=False, semantic_hit=False)
    )
    action = action_for_classification(
        classification, organization_id=str(uuid4()), document_id=str(uuid4())
    )
    assert action.action_type == NutritionActionType.GENERATE_RETRIEVAL_ALIASES.value
    assert action.destructive is False
    assert action.evidence["classification"]["failure_type"] == FailureType.RETRIEVAL_MISS.value


def test_weak_feedback_only_observed() -> None:
    classification = classify_failure(
        FailureSignals(
            query="ambiguous",
            retrieved_chunks=3,
            evidence_used=2,
            feedback_rating="down",
            feedback_reason="other",
        )
    )
    action = action_for_classification(classification)
    assert action.confidence < 0.55
    assert action.status == NutritionActionStatus.OBSERVED.value


def test_non_destructive_signals_can_be_applied() -> None:
    classification = classify_failure(
        FailureSignals(query="x", retrieved_chunks=5, top_score=0.1, evidence_used=1)
    )
    action = action_for_classification(classification)
    assert action.action_type == NutritionActionType.RECORD_RANKING_SIGNAL.value
    assert action.status == NutritionActionStatus.APPLIED.value
    assert action.destructive is False


def test_nutrition_score_keeps_unmeasured_dimensions_none() -> None:
    document = _understood(
        "# Manual\n\nCategory 31 defines voluntary changes.\n\nStatus: active.\n"
    )
    enrichment = enrich_document(document)
    score = compute_nutrition_score(document, enrichment=enrichment)
    dimensions = score.dimensions.to_dict()
    # Las dimensiones sin artefacto medido quedan None, no 0.
    assert dimensions["retrievability"] is None
    assert dimensions["freshness"] is None
    assert dimensions["structure_quality"] is not None
    assert dimensions["semantic_coverage"] is not None
    assert score.nutrition_score is not None
    assert 0.0 <= score.nutrition_score <= 1.0
    assert score.formula_version
    assert score.weights == NUTRITION_WEIGHTS
    assert score.measured_dimensions == len(score.dimensions.measured())
    assert 0 < score.coverage <= 1.0


def test_nutrition_score_includes_retrievability_from_acceptance() -> None:
    document = _understood("# Manual\n\nRecord 4 defines the exchange rule.\n")
    enrichment = enrich_document(document)
    probes = generate_probes(document, enrichment, max_probes=4)
    # Reporte sintético: recall medido.
    from src.knowledge.acceptance.contracts import AcceptanceReport

    report = AcceptanceReport(
        organization_id=document.organization_id,
        document_id=document.id,
        probes_total=4,
        probes_passed=2,
        probes_failed=2,
        recall_at_5=0.5,
        mrr=0.4,
    )
    score = compute_nutrition_score(
        document, enrichment=enrichment, acceptance=report, demand_coverage=0.5
    )
    assert score.dimensions.retrievability == 0.5
    assert score.dimensions.demand_coverage == 0.5
    assert score.measured_dimensions >= 4


@pytest.mark.asyncio
async def test_demand_profile_from_acceptance() -> None:
    document = _understood("# Manual\n\nCategory 31 defines voluntary changes.\n")
    enrichment = enrich_document(document)
    probes = generate_probes(document, enrichment, max_probes=6)
    from types import SimpleNamespace


    class FakeEmbedder:
        async def embed(self, texts, model=None):
            if isinstance(texts, str):
                return [0.1] * 4
            return [[0.1] * 4 for _ in texts]

    class EmptyStore:
        async def search(self, organization_id, query_embedding, top_k=5, filters=None):
            return SimpleNamespace(chunks=[])

    report = await evaluate_probes(
        probes,
        embedder=FakeEmbedder(),
        vector_store=EmptyStore(),
        measure_lexical=False,
    )
    profile = demand_profile_from_acceptance(report, enrichment=enrichment)
    assert profile.total_queries == len(probes)
    assert profile.demand_coverage == 0.0
    assert profile.items
    assert all(item.gap_frequency == item.frequency for item in profile.items)


@pytest.mark.asyncio
async def test_feedback_loop_persists_nutrition_action() -> None:
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
    from src.knowledge.nutrition import apply_feedback_nutrition

    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Feedback Org {uuid4().hex[:6]}"
    )
    document_id = uuid4()
    signals = FailureSignals(
        query="What does Byte 105 mean in Category 31?",
        retrieved_chunks=0,
        lexical_hit=False,
        semantic_hit=False,
        feedback_rating="down",
        feedback_reason="wrong_answer",
        document_id=str(document_id),
    )
    outcome = await apply_feedback_nutrition(signals, organization_id=organization.id)
    assert outcome.classification.failure_type == FailureType.RETRIEVAL_MISS.value
    assert outcome.persisted is True
    assert outcome.action_id
    assert outcome.action.destructive is False
    assert outcome.action.action_type == NutritionActionType.GENERATE_RETRIEVAL_ALIASES.value

    store = PostgresNutritionStore()
    actions = await store.list_actions(organization.id, document_id=document_id)
    assert actions
    assert actions[0]["failure_type"] == FailureType.RETRIEVAL_MISS.value
    assert actions[0]["evidence"]["classification"]["signals"]["retrieved_chunks"] == 0


def test_reembedding_estimates_are_explicit() -> None:
    from src.scripts.knowledge_reprocess import (
        ESTIMATED_TOKENS_PER_CHUNK,
        estimate_reembedding,
    )

    estimate = estimate_reembedding(100)
    assert estimate["vectors_affected"] == 100
    assert estimate["estimated_embeddings"] == 100
    assert estimate["estimated_tokens"] == 100 * ESTIMATED_TOKENS_PER_CHUNK
    assert estimate["tokens_per_chunk_assumption"] == ESTIMATED_TOKENS_PER_CHUNK
    assert estimate_reembedding(0)["estimated_tokens"] == 0


def test_nutrition_api_router_exposes_operational_endpoints() -> None:
    from src.api.routes.knowledge_nutrition import router

    paths = {route.path for route in router.routes}
    assert "/api/v1/knowledge/nutrition/score" in paths
    assert "/api/v1/knowledge/nutrition/actions" in paths
    assert "/api/v1/knowledge/retrieval-acceptance" in paths
    assert "/api/v1/knowledge/retrieval-probes" in paths
    assert "/api/v1/knowledge/retrieval-acceptance/reevaluate" in paths
    assert "/api/v1/knowledge/nutrition/feedback" in paths


@pytest.mark.asyncio
async def test_demand_model_aggregates_evaluations_and_feedback() -> None:
    from src.knowledge.nutrition import build_demand_model

    evaluations = [
        {
            "probes_total": 10,
            "probes_passed": 6,
            "probes_failed": 4,
            "failed_probes": [
                {"query_type": "exact_identifier", "query": "Byte 105"},
                {"query_type": "alias", "query": "CAT31"},
                {"query_type": "alias", "query": "Cat 31"},
                {"query_type": "semantic_paraphrase", "query": "status byte"},
            ],
            "metrics": {"state": "DEGRADED"},
        },
        {
            "probes_total": 5,
            "probes_passed": 5,
            "probes_failed": 0,
            "failed_probes": [],
            "metrics": {"state": "PASS"},
        },
    ]
    actions = [
        {"failure_type": "RETRIEVAL_MISS"},
        {"failure_type": "ANSWER_GENERATION_FAILURE"},
    ]
    model = build_demand_model(
        evaluations,
        actions,
        organization_id=str(uuid4()),
        document_id=str(uuid4()),
    )
    assert model.questions_total == 15
    assert model.success_rate == round(11 / 15, 4)
    assert model.retrieval_failure_rate == round(4 / 15, 4)
    assert model.negative_feedback_rate == round(1 / 15, 4)
    assert model.coverage == model.success_rate
    assert model.intents
    alias_intent = next(item for item in model.intents if item.key == "alias")
    assert alias_intent.gap_frequency == 2
    assert model.to_dict()["policy_version"]


@pytest.mark.asyncio
async def test_nutrition_store_roundtrip_is_scoped() -> None:
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Nutrition Org {uuid4().hex[:6]}"
    )
    document = _understood(
        "# Manual\n\nCategory 31 defines voluntary changes.\n",
        organization_id=organization.id,
    )
    enrichment = enrich_document(document)
    score = compute_nutrition_score(document, enrichment=enrichment)
    store = PostgresNutritionStore()
    await store.save_state(
        score,
        organization_id=document.organization_id,
        workspace_id=document.workspace_id,
        source_id=document.source_id,
        document_id=document.id,
    )
    state = await store.get_state(
        document.organization_id,
        scope="document",
        scope_id=score.scope_id,
    )
    assert state is not None
    assert state["nutrition_score"] == score.nutrition_score
    assert state["dimensions"]["dimensions"]["retrievability"] is None

    # Otro tenant no ve el estado.
    assert await store.get_state(uuid4(), scope="document", scope_id=score.scope_id) is None

    classification = classify_failure(
        FailureSignals(query="x", retrieved_chunks=0, lexical_hit=False, semantic_hit=False)
    )
    action = action_for_classification(
        classification,
        organization_id=str(document.organization_id),
        document_id=str(document.id),
    )
    action_id = await store.save_action(action, organization_id=document.organization_id)
    assert action_id
    actions = await store.list_actions(
        document.organization_id, document_id=document.id
    )
    assert actions
    assert actions[0]["destructive"] is False
    assert await store.list_actions(uuid4()) == []
