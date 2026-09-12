# =============================================================================
# Knowledge V2 — KnowledgeCorpus repository (Phase D slice 2, Postgres real)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.core.domain.knowledge_v2 import KnowledgeCorpus, KnowledgeObjectStatus
from src.infrastructure.postgres.knowledge_corpora import (
    PostgresKnowledgeCorpusRepository,
)
from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository
from src.infrastructure.postgres.relational_db import (
    PostgresKnowledgeBaseRepository,
    PostgresOrganizationRepository,
)
from src.infrastructure.postgres.session import get_async_session


def _corpus(org, workspace, *, name="Operaciones", slug="operaciones") -> KnowledgeCorpus:
    return KnowledgeCorpus(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        name=name,
        slug=slug,
        description="Conocimiento de Operaciones",
        status=KnowledgeObjectStatus.DRAFT,
    )


@pytest.fixture
async def context():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Corpus Org {uuid4().hex[:6]}")
    from src.infrastructure.postgres.relational_db import PostgresWorkspaceRepository

    workspace = await PostgresWorkspaceRepository().create_workspace(
        organization.id, "Operaciones", "ops"
    )
    return {"organization": organization, "workspace": workspace}


@pytest.mark.asyncio
async def test_corpus_repo_roundtrip_and_isolation(context) -> None:
    repo = PostgresKnowledgeCorpusRepository()
    corpus = _corpus(context["organization"], context["workspace"])
    await repo.create_corpus(corpus)
    # idempotente
    await repo.create_corpus(_corpus(context["organization"], context["workspace"]))

    meta = await repo.get_corpus(context["organization"].id, corpus.id)
    assert meta is not None
    assert meta["name"] == "Operaciones"
    assert meta["slug"] == "operaciones"
    assert meta["status"] == "draft"

    by_slug = await repo.get_corpus_by_slug(
        context["organization"].id, context["workspace"].id, "operaciones"
    )
    assert by_slug is not None

    listed = await repo.list_corpora(context["organization"].id, workspace_id=context["workspace"].id)
    assert len(listed) == 1

    # otro tenant nunca lo ve
    foreign = await repo.get_corpus(uuid4(), corpus.id)
    assert foreign is None
    assert await repo.get_corpus_by_slug(uuid4(), context["workspace"].id, "operaciones") is None


@pytest.mark.asyncio
async def test_corpus_attach_detach_source_scoped(context) -> None:
    repo = PostgresKnowledgeCorpusRepository()
    corpus = _corpus(context["organization"], context["workspace"])
    await repo.create_corpus(corpus)

    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(context["organization"].id, "KB Ops", chunking_strategy="fixed")
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        context["organization"].id,
        "src-ops",
        "test_rows",
        knowledge_base_id=kb.id,
        workspace_id=context["workspace"].id,
    )

    await repo.attach_source(context["organization"].id, source.id, corpus.id)
    await repo.detach_source(context["organization"].id, source.id)

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT corpus_id FROM kb_sources WHERE id = :sid"),
                {"sid": source.id},
            )
        ).fetchone()
        assert row is not None and row.corpus_id is None
    finally:
        await session.close()
