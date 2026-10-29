# =============================================================================
# P18.2-10 — Métricas honestas: completitud no es comprensión
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.platform.knowledge_model.repository import PostgresKnowledgeModelRepository
from src.platform.knowledge_model.service import KnowledgeModelService


class _NarrativeRepo:
    async def stats(self, organization_id):
        return {
            "objects": {
                "total": 109,
                "verified": 0,
                "inferred": 0,
                "discovered": 109,
                "unsupported": 0,
                "undescribed": 108,
            },
            "by_kind": {
                "concept": {"total": 106, "verified": 0},
                "attribute": {"total": 2, "verified": 0},
                "business_rule": {"total": 1, "verified": 0},
            },
            "assertions": {
                "total": 0,
                "verified": 0,
                "conflicted": 0,
                "stale": 0,
                "unsupported": 0,
                "low_confidence": 0,
            },
            "evidence": {"total": 108, "with_excerpt": 108},
            "edges": {"total": 2, "verified": 0, "physical": 0, "semantic": 2},
            "conflicts": {"open": 0},
            "gaps": {"total": 0, "high": 0, "resolved": 0},
            "questions": {"pending": 0},
            "sources": {"total": 0, "degraded": 0, "stale": 0},
            "indexed": {"sources": 1, "documents": 1, "ready_sources": 1},
        }

    async def retrieval_signals(self, organization_id):
        return {"traces": {"total": 0, "failed": 0}, "evaluation": None}

    async def source_genres(self, organization_id):
        return {"narrative": 1}

    async def document_signals(self, organization_id):
        return {
            "total": 1,
            "with_sections": 1,
            "extraction_score": 0.73,
            "text_fidelity": 0.82,
        }


@pytest.mark.asyncio
async def test_narrative_health_excludes_business_rules_and_unreviewed_validation() -> None:
    service = KnowledgeModelService(_NarrativeRepo(), None)
    health = await service.health(uuid4())

    assert health.scoring_profile == "narrative"
    rules = next(
        dimension
        for dimension in health.dimensions
        if dimension.key == "rules_metrics"
    )
    validation = next(
        dimension
        for dimension in health.dimensions
        if dimension.key == "human_validation"
    )
    coverage = next(
        dimension for dimension in health.dimensions if dimension.key == "coverage"
    )
    assert rules.applicable is False
    assert rules.measured is False
    assert rules.score is None
    assert "No aplica" in rules.reason
    assert validation.measured is False
    assert validation.score is None
    assert validation.signals["evaluation_state"] == "not_evaluated"
    assert coverage.label == "Cobertura de evidencia"
    assert health.not_applicable_dimensions == 1
    # 100*.20 + 73*.25 + 100*.15 + 100*.20 + .92*.20 + 40*.15 + 100*.05
    # = 84.43 / 1.20 = 70.36
    assert health.overall == pytest.approx(70.36, abs=0.2)



@pytest.mark.asyncio
async def test_narrative_document_only_profile_measures_extraction_not_business() -> None:
    class Repo(_NarrativeRepo):
        async def stats(self, organization_id):
            data = await super().stats(organization_id)
            data["objects"] = {
                "total": 0,
                "verified": 0,
                "inferred": 0,
                "discovered": 0,
                "unsupported": 0,
                "undescribed": 0,
            }
            data["by_kind"] = {}
            data["evidence"] = {"total": 0, "with_excerpt": 0}
            data["edges"] = {"total": 0, "verified": 0, "physical": 0, "semantic": 0}
            return data

    service = KnowledgeModelService(Repo(), None)
    health = await service.health(uuid4())

    assert health.scoring_profile == "narrative"
    assert health.state == "partial"
    assert health.overall == pytest.approx(83.12, abs=0.2)
    assert health.not_applicable_dimensions >= 4
    citations = next(
        dimension
        for dimension in health.dimensions
        if dimension.key == "citation_coverage"
    )
    assert citations.measured is False
    assert citations.score is None


@pytest.mark.asyncio
async def test_description_completeness_is_not_labelled_as_comprehension() -> None:
    org = await PostgresOrganizationRepository().create_organization(uuid4(), f"P18.2 Metrics {uuid4().hex[:6]}")
    service = KnowledgeModelService(PostgresKnowledgeModelRepository(), None)
    health = await service.health(org.id)

    semantic = next(dimension for dimension in health.dimensions if dimension.key == "semantic_understanding")
    assert semantic.label == "Completitud de descripciones"
    assert semantic.signals["comprehension_evaluated"] is False
    assert semantic.signals["metric_scope"] == "description_completeness"
    assert "comprensión" in semantic.reason.lower()
