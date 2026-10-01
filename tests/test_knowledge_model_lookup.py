# =============================================================================
# Knowledge Model — lecturas para entity resolution (C2).
# =============================================================================
# Alias normalizados, nombres canónicos exactos y vigencia de assertions.
# Postgres real (migración 135): el contrato es SQL, no un fake.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.core.domain.canonical import CanonicalKind, CanonicalObject, entity_natural_key
from src.infrastructure.postgres.canonical import PostgresCanonicalKnowledgeRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_model.repository import (
    PostgresKnowledgeModelRepository,
    _assertion_row,
)


@pytest.fixture
async def org():
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Lookup Org {uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_lookup_aliases_resuelve_por_alias_normalizado(org) -> None:
    canonical = PostgresCanonicalKnowledgeRepository()
    entity = await canonical.upsert_object(
        CanonicalObject(
            organization_id=org.id,
            kind=CanonicalKind.ENTITY,
            natural_key=entity_natural_key("category 31", "concept"),
            title="Category 31",
        )
    )
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO knowledge_entity_aliases
                    (organization_id, entity_id, alias, normalized, confidence)
                VALUES (:org, :entity, 'Cat 31', 'cat 31', 0.9)
                """
            ),
            {"org": org.id, "entity": entity.canonical_id},
        )
        await session.commit()
    finally:
        await session.close()

    repo = PostgresKnowledgeModelRepository()
    rows = await repo.lookup_aliases(org.id, ["cat 31"])
    assert len(rows) == 1
    assert rows[0]["entity_id"] == str(entity.canonical_id)
    assert rows[0]["name"] == "Category 31"

    assert await repo.lookup_aliases(uuid4(), ["cat 31"]) == []


@pytest.mark.asyncio
async def test_find_objects_by_names_exacto_y_scoped(org) -> None:
    canonical = PostgresCanonicalKnowledgeRepository()
    entity = await canonical.upsert_object(
        CanonicalObject(
            organization_id=org.id,
            kind=CanonicalKind.ENTITY,
            natural_key=entity_natural_key("category 31", "concept"),
            title="Category 31",
        )
    )
    repo = PostgresKnowledgeModelRepository()
    found = await repo.find_objects_by_names(org.id, ["category 31"])
    assert [item["id"] for item in found] == [str(entity.canonical_id)]
    assert found[0]["name"] == "Category 31"
    assert await repo.find_objects_by_names(uuid4(), ["category 31"]) == []
    assert await repo.find_objects_by_names(org.id, ["cat 31"]) == []


def test_assertion_row_expone_vigencia() -> None:
    row = _assertion_row(
        SimpleNamespace(
            id=uuid4(),
            subject_id=uuid4(),
            subject_label="Rule X",
            predicate="applies_to",
            object_id=None,
            object_value="Category 31",
            assertion_type="rule",
            confidence=0.9,
            confidence_detail=None,
            status="approved",
            provenance="APPROVED",
            method="compiler",
            source_id=None,
            evidence_count=2,
            version=3,
            verified_at=None,
            stale_at=None,
            valid_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2025, 1, 1, tzinfo=timezone.utc),
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
    )
    assert row["valid_from"] == "2024-01-01T00:00:00+00:00"
    assert row["valid_to"] == "2025-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_service_passthrough(org) -> None:
    from src.platform.knowledge_model.service import KnowledgeModelService

    service = KnowledgeModelService(PostgresKnowledgeModelRepository())
    assert await service.lookup_aliases(org.id, ["cat 31"]) == []
    assert await service.find_objects_by_names(org.id, ["no existe"]) == []
