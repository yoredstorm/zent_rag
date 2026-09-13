# =============================================================================
# Canonical Knowledge Model — identidad canónica + mapping (Phase 1 slice 1)
# =============================================================================
# Dominio puro (sin DB) + roundtrip Postgres con aislamiento estricto por
# organization_id. Las tablas viven en la migración 102.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.core.domain.canonical import (
    CanonicalKind,
    CanonicalObject,
    CanonicalRef,
    CanonicalSystem,
    assert_approval_law,
    block_natural_key,
    canonical_uuid,
    chunk_natural_key,
    document_natural_key,
    entity_natural_key,
    fact_natural_key,
    glossary_natural_key,
    metric_natural_key,
    rule_natural_key,
    section_natural_key,
    source_natural_key,
)
from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import KnowledgeObjectStatus

# ---------------------------------------------------------------------------
# Dominio puro
# ---------------------------------------------------------------------------

def test_canonical_uuid_deterministic_and_scoped() -> None:
    org_a, org_b = uuid4(), uuid4()
    first = canonical_uuid(org_a, CanonicalKind.ENTITY, "entity:organization:acme")
    assert first == canonical_uuid(org_a, CanonicalKind.ENTITY, "entity:organization:acme")
    assert first != canonical_uuid(org_b, CanonicalKind.ENTITY, "entity:organization:acme")
    assert first != canonical_uuid(org_a, CanonicalKind.DOCUMENT, "entity:organization:acme")
    assert first != canonical_uuid(org_a, CanonicalKind.ENTITY, "entity:organization:other")


def test_canonical_object_derives_identity() -> None:
    org = uuid4()
    obj = CanonicalObject(
        organization_id=org,
        kind=CanonicalKind.DOCUMENT,
        natural_key="document:abc",
        title="Manual",
    )
    assert obj.canonical_id == canonical_uuid(org, CanonicalKind.DOCUMENT, "document:abc")


def test_canonical_object_rejects_invalid_fields() -> None:
    org = uuid4()
    with pytest.raises(ValueError):
        CanonicalObject(organization_id=org, kind=CanonicalKind.DOCUMENT, natural_key="")
    with pytest.raises(ValueError):
        CanonicalObject(
            organization_id=org,
            kind=CanonicalKind.ENTITY,
            natural_key="entity:a",
            confidence=1.5,
        )
    with pytest.raises(ValueError):
        CanonicalObject(
            organization_id=org,
            kind=CanonicalKind.DOCUMENT,
            natural_key="document:x",
            title="x" * 513,
        )


def test_approval_law_blocks_approved_without_approval() -> None:
    org = uuid4()
    with pytest.raises(ValueError):
        CanonicalObject(
            organization_id=org,
            kind=CanonicalKind.FACT,
            natural_key="fact:a:b:c",
            provenance=CatalogProvenance.INFERRED,
            status=KnowledgeObjectStatus.APPROVED,
        )
    approved = CanonicalObject(
        organization_id=org,
        kind=CanonicalKind.FACT,
        natural_key="fact:a:b:c",
        provenance=CatalogProvenance.APPROVED,
        status=KnowledgeObjectStatus.APPROVED,
    )
    assert approved.status is KnowledgeObjectStatus.APPROVED


def test_approval_law_matches_knowledge_v2_contract() -> None:
    from src.core.domain.knowledge_v2 import KnowledgeEntity

    with pytest.raises(ValueError):
        assert_approval_law(CatalogProvenance.OBSERVED, KnowledgeObjectStatus.APPROVED)
    assert_approval_law(CatalogProvenance.APPROVED, KnowledgeObjectStatus.APPROVED)
    with pytest.raises(ValueError):
        KnowledgeEntity(
            organization_id=uuid4(),
            name="x",
            provenance=CatalogProvenance.INFERRED,
            status=KnowledgeObjectStatus.APPROVED,
        )


def test_natural_key_helpers_are_stable_and_normalized() -> None:
    doc_id = uuid4()
    assert source_natural_key(doc_id) == f"source:{doc_id}"
    assert document_natural_key(doc_id) == f"document:{doc_id}"
    assert section_natural_key(doc_id, ("5", "5.2")) == f"section:{doc_id}:5/5.2"
    assert block_natural_key(doc_id, 3, "abc") == f"block:{doc_id}:3:abc"
    assert chunk_natural_key(doc_id, 7, "abc") == f"chunk:{doc_id}:7:abc"
    assert entity_natural_key("  ACME   S.A. ", "Organization") == "entity:organization:acme s.a."
    assert fact_natural_key(" Penalty ", " IS ", " 7% ") == "fact:penalty:is:7%"
    assert rule_natural_key("notice-30d") == "rule:notice-30d"
    assert metric_natural_key("revenue") == "metric:revenue"
    assert glossary_natural_key(" SLA ") == "glossary:sla"


def test_canonical_ref_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        CanonicalRef(system=CanonicalSystem.CATALOG, object_type="", object_ref="x")
    with pytest.raises(ValueError):
        CanonicalRef(system=CanonicalSystem.CATALOG, object_type="catalog_entity", object_ref="")
    ref = CanonicalRef(
        system=CanonicalSystem.CATALOG,
        object_type="catalog_entity",
        object_ref=str(uuid4()),
    )
    assert ref.object_type == "catalog_entity"


# ---------------------------------------------------------------------------
# Postgres (migración 102)
# ---------------------------------------------------------------------------

@pytest.fixture
async def org():
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Canonical Org {uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_canonical_repo_roundtrip_and_isolation(org) -> None:
    from src.infrastructure.postgres.canonical import (
        PostgresCanonicalKnowledgeRepository,
    )

    repo = PostgresCanonicalKnowledgeRepository()
    obj = CanonicalObject(
        organization_id=org.id,
        kind=CanonicalKind.ENTITY,
        natural_key=entity_natural_key("ACME", "organization"),
        title="ACME",
    )
    saved = await repo.upsert_object(obj)
    assert saved.canonical_id == obj.canonical_id

    fetched = await repo.get_object(org.id, obj.canonical_id)
    assert fetched is not None and fetched.title == "ACME"
    assert await repo.get_object(uuid4(), obj.canonical_id) is None

    by_key = await repo.get_by_natural_key(org.id, CanonicalKind.ENTITY, obj.natural_key)
    assert by_key is not None and by_key.canonical_id == obj.canonical_id
    assert await repo.get_by_natural_key(uuid4(), CanonicalKind.ENTITY, obj.natural_key) is None

    renamed = CanonicalObject(
        organization_id=org.id,
        kind=CanonicalKind.ENTITY,
        natural_key=obj.natural_key,
        title="ACME Corporation",
        provenance=CatalogProvenance.INFERRED,
        status=KnowledgeObjectStatus.INFERRED,
    )
    again = await repo.upsert_object(renamed)
    assert again.canonical_id == obj.canonical_id
    fetched = await repo.get_object(org.id, obj.canonical_id)
    assert fetched.title == "ACME Corporation"
    assert fetched.provenance is CatalogProvenance.INFERRED


@pytest.mark.asyncio
async def test_canonical_links_resolve_and_primary_uniqueness(org) -> None:
    from src.infrastructure.postgres.canonical import (
        PostgresCanonicalKnowledgeRepository,
    )

    repo = PostgresCanonicalKnowledgeRepository()
    doc = CanonicalObject(
        organization_id=org.id,
        kind=CanonicalKind.DOCUMENT,
        natural_key=document_natural_key(uuid4()),
        title="Contrato",
    )
    await repo.upsert_object(doc)
    doc_ref = CanonicalRef(
        system=CanonicalSystem.V2_STRUCTURED,
        object_type="structured_document",
        object_ref=str(uuid4()),
    )
    insight_ref = CanonicalRef(
        system=CanonicalSystem.DATA_ONBOARDING,
        object_type="document_insight",
        object_ref=str(uuid4()),
    )

    await repo.link(org.id, doc.canonical_id, doc_ref, is_primary=True)
    await repo.link(org.id, doc.canonical_id, insight_ref)

    links = await repo.list_links(org.id, doc.canonical_id)
    assert {link.ref.object_type for link in links} == {
        "structured_document",
        "document_insight",
    }
    resolved = await repo.resolve(org.id, doc_ref)
    assert resolved is not None and resolved.canonical_id == doc.canonical_id
    resolved_insight = await repo.resolve(org.id, insight_ref)
    assert resolved_insight is not None and resolved_insight.canonical_id == doc.canonical_id

    # re-link del mismo ref es idempotente
    await repo.link(org.id, doc.canonical_id, doc_ref, is_primary=True, metadata={"role": "primary"})
    assert len(await repo.list_links(org.id, doc.canonical_id)) == 2

    # dos primarios en el mismo objeto canónico → única parcial
    with pytest.raises(IntegrityError):
        await repo.link(
            org.id,
            doc.canonical_id,
            CanonicalRef(
                system=CanonicalSystem.CATALOG,
                object_type="catalog_entity",
                object_ref=str(uuid4()),
            ),
            is_primary=True,
        )

    # cross-tenant: no se puede enlazar a un canónico de otra org
    with pytest.raises(ValueError):
        await repo.link(
            uuid4(),
            doc.canonical_id,
            CanonicalRef(
                system=CanonicalSystem.CATALOG,
                object_type="catalog_entity",
                object_ref=str(uuid4()),
            ),
        )


@pytest.mark.asyncio
async def test_canonical_unlink_and_missing_ref(org) -> None:
    from src.infrastructure.postgres.canonical import (
        PostgresCanonicalKnowledgeRepository,
    )

    repo = PostgresCanonicalKnowledgeRepository()
    obj = CanonicalObject(
        organization_id=org.id,
        kind=CanonicalKind.METRIC,
        natural_key=metric_natural_key("churn"),
        title="Churn",
    )
    await repo.upsert_object(obj)
    ref = CanonicalRef(
        system=CanonicalSystem.CATALOG,
        object_type="catalog_metric",
        object_ref=str(uuid4()),
    )
    await repo.link(org.id, obj.canonical_id, ref)
    await repo.unlink(org.id, ref)
    assert await repo.list_links(org.id, obj.canonical_id) == []
    assert await repo.resolve(org.id, ref) is None


@pytest.mark.asyncio
async def test_canonical_db_rejects_approved_without_approval(org) -> None:
    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO knowledge_canonical_objects "
                    "(id, organization_id, kind, natural_key, provenance, status) "
                    "VALUES (gen_random_uuid(), :oid, 'fact', 'fact:raw:x', 'INFERRED', 'approved')"
                ),
                {"oid": str(org.id)},
            )
            await session.commit()
    finally:
        await session.rollback()
        await session.close()
