# =============================================================================
# P18.2-10 — Métricas honestas: completitud no es comprensión
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.platform.knowledge_model.repository import PostgresKnowledgeModelRepository
from src.platform.knowledge_model.service import KnowledgeModelService


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
