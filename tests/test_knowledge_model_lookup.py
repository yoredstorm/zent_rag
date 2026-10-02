# =============================================================================
# Knowledge Model — lecturas para entity resolution (C2).
# =============================================================================
# Alias normalizados, nombres canónicos exactos y vigencia de assertions.
# Postgres real (migración 135): el contrato es SQL, no un fake.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

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


async def _seed_scoped_objects(
    repo: PostgresKnowledgeModelRepository, org_id, label: str
) -> tuple[UUID, UUID, UUID, dict[str, UUID]]:
    """Tres objetos con el mismo nombre: fuente s1, fuente s2 y sin fuente (NULL)."""
    s1, s2 = uuid4(), uuid4()
    ids = {"s1": uuid4(), "s2": uuid4(), "null": uuid4()}
    for key, source in (("s1", s1), ("s2", s2), ("null", None)):
        await repo.upsert_object(
            org_id,
            object_id=ids[key],
            kind="entity",
            natural_key=f"{label}-{key}",
            name=f"{label} shared",
            source_id=source,
        )
    return s1, s2, ids["null"], ids


@pytest.mark.asyncio
async def test_find_objects_by_names_filtra_por_source_ids(org) -> None:
    repo = PostgresKnowledgeModelRepository()
    s1, s2, null_id, ids = await _seed_scoped_objects(repo, org.id, "Policy X")

    all_found = await repo.find_objects_by_names(org.id, ["policy x shared"])
    assert {item["id"] for item in all_found} == {
        str(ids["s1"]),
        str(ids["s2"]),
        str(ids["null"]),
    }

    scoped = await repo.find_objects_by_names(org.id, ["policy x shared"], source_ids=(s1,))
    assert {item["id"] for item in scoped} == {str(ids["s1"]), str(null_id)}

    scoped_other = await repo.find_objects_by_names(
        org.id, ["policy x shared"], source_ids=(s2,)
    )
    assert {item["id"] for item in scoped_other} == {str(ids["s2"]), str(null_id)}

    empty_scope = await repo.find_objects_by_names(
        org.id, ["policy x shared"], source_ids=()
    )
    assert {item["id"] for item in empty_scope} == {
        str(ids["s1"]),
        str(ids["s2"]),
        str(ids["null"]),
    }


@pytest.mark.asyncio
async def test_lookup_aliases_filtra_por_source_ids(org) -> None:
    repo = PostgresKnowledgeModelRepository()
    s1, s2, null_id, ids = await _seed_scoped_objects(repo, org.id, "Alias X")

    session = await get_async_session()
    try:
        for key, entity_id in ids.items():
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_entity_aliases
                        (organization_id, entity_id, alias, normalized, confidence)
                    VALUES (:org, :entity, :alias, 'alias x shared', 0.9)
                    """
                ),
                {"org": org.id, "entity": entity_id, "alias": f"Alias {key}"},
            )
        await session.commit()
    finally:
        await session.close()

    all_rows = await repo.lookup_aliases(org.id, ["alias x shared"])
    assert {row["entity_id"] for row in all_rows} == {
        str(ids["s1"]),
        str(ids["s2"]),
        str(ids["null"]),
    }

    scoped = await repo.lookup_aliases(org.id, ["alias x shared"], source_ids=(s1,))
    assert {row["entity_id"] for row in scoped} == {str(ids["s1"]), str(null_id)}


@pytest.mark.asyncio
async def test_object_edges_filtra_por_source_ids(org) -> None:
    repo = PostgresKnowledgeModelRepository()
    org_id = org.id
    s1, s2 = uuid4(), uuid4()
    focus = uuid4()
    await repo.upsert_object(
        org_id,
        object_id=focus,
        kind="entity",
        natural_key="focus-1",
        name="Focus",
    )
    targets = {"s1": uuid4(), "s2": uuid4(), "null": uuid4()}
    for key, target in targets.items():
        await repo.upsert_object(
            org_id,
            object_id=target,
            kind="concept",
            natural_key=f"target-{key}",
            name=f"Target {key}",
        )
    await repo.upsert_edge(
        org_id,
        subject_id=focus,
        predicate="points_to",
        object_id=targets["s1"],
        relationship_type="logical",
        confidence=0.9,
        status="observed",
        provenance="OBSERVED",
        source_id=s1,
    )
    await repo.upsert_edge(
        org_id,
        subject_id=focus,
        predicate="points_to",
        object_id=targets["s2"],
        relationship_type="logical",
        confidence=0.8,
        status="observed",
        provenance="OBSERVED",
        source_id=s2,
    )
    await repo.upsert_edge(
        org_id,
        subject_id=focus,
        predicate="points_to",
        object_id=targets["null"],
        relationship_type="logical",
        confidence=0.7,
        status="observed",
        provenance="OBSERVED",
        source_id=None,
    )

    all_data = await repo.object_edges(org_id, focus)
    assert all_data["count"] == 3

    scoped = await repo.object_edges(org_id, focus, source_ids=(s1,))
    assert scoped["count"] == 2
    assert {edge["object_id"] for edge in scoped["edges"]} == {
        str(targets["s1"]),
        str(targets["null"]),
    }

    unscoped = await repo.object_edges(org_id, focus, source_ids=())
    assert unscoped["count"] == 3


@pytest.mark.asyncio
async def test_object_assertions_filtra_por_source_ids(org) -> None:
    repo = PostgresKnowledgeModelRepository()
    org_id = org.id
    s1, s2 = uuid4(), uuid4()
    focus = uuid4()
    await repo.upsert_object(
        org_id,
        object_id=focus,
        kind="rule",
        natural_key="rule-focus",
        name="Rule Focus",
    )
    for key, source in (("s1", s1), ("s2", s2), ("null", None)):
        await repo.upsert_assertion(
            org_id,
            subject_id=focus,
            subject_label="Rule Focus",
            predicate="applies_to",
            object_value=f"value {key}",
            confidence=0.7,
            source_id=source,
        )

    all_rows = await repo.object_assertions(org_id, focus)
    assert len(all_rows) == 3

    scoped = await repo.object_assertions(org_id, focus, source_ids=(s1,))
    assert {row["object_value"] for row in scoped} == {"value s1", "value null"}

    unscoped = await repo.object_assertions(org_id, focus, source_ids=())
    assert len(unscoped) == 3


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

    service = KnowledgeModelService(PostgresKnowledgeModelRepository(), None)
    assert await service.lookup_aliases(org.id, ["cat 31"]) == []
    assert await service.find_objects_by_names(org.id, ["no existe"]) == []


@pytest.mark.asyncio
async def test_service_object_assertions_acepta_limit(org) -> None:
    from src.platform.knowledge_model.service import KnowledgeModelService

    service = KnowledgeModelService(PostgresKnowledgeModelRepository(), None)
    assert await service.object_assertions(org.id, uuid4(), limit=1) == []
