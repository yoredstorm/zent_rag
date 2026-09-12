# =============================================================================
# Knowledge V2 — cost tracking (§41) + suggested questions (§35)
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.domain.knowledge_v2 import KnowledgeCorpus
from src.infrastructure.postgres.knowledge_corpora import (
    PostgresKnowledgeCorpusRepository,
)
from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository
from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.knowledge.cost import KnowledgeUsageTracker
from src.knowledge.structure import TextParser
from src.rag.suggestions import QuestionSuggestionService

_PARSER = TextParser()

_MD = (
    "# Manual Operaciones\n\n"
    "Comisión 5% con vigencia desde 2024-01-01.\n\n"
    "El incumplimiento genera penalización del 10%.\n\n"
    "| Clave | Valor |\n| --- | --- |\n| A | 5% |\n"
)


async def _seed(org, workspace):
    corpus_repo = PostgresKnowledgeCorpusRepository()
    corpus = KnowledgeCorpus(
        id=uuid4(),
        organization_id=org.id,
        workspace_id=workspace.id,
        name="Operaciones",
        slug="operaciones",
    )
    await corpus_repo.create_corpus(corpus)
    source = await PostgresSourceRepository().create_source(
        org.id, "manual", "file", workspace_id=workspace.id
    )
    await corpus_repo.attach_source(org.id, source.id, corpus.id)
    doc = _PARSER.parse(
        _MD.encode("utf-8"),
        organization_id=org.id,
        external_id="manual.md",
        source_id=source.id,
        workspace_id=workspace.id,
    )
    doc.check_consistency()
    await PostgresStructuredDocumentRepository().upsert_document(doc)
    return corpus, source, doc


@pytest.fixture
async def org_ws():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Cost Org {uuid4().hex[:6]}")
    workspace = await PostgresWorkspaceRepository().create_workspace(
        organization.id, "Operaciones", "ops"
    )
    return organization, workspace


@pytest.mark.asyncio
async def test_usage_tracker_roundtrip_and_isolation(org_ws) -> None:
    organization, workspace = org_ws
    tracker = KnowledgeUsageTracker()
    await tracker.record_embedding_tokens(
        organization.id, 1200, workspace_id=workspace.id
    )
    await tracker.record(
        organization.id,
        category="llm",
        tokens=800,
        workspace_id=workspace.id,
        corpus_id=uuid4(),
        metadata={"model": "x"},
    )

    summary = await tracker.summary(organization.id)
    assert summary.get("embedding", {}).get("tokens") == 1200
    assert summary.get("llm", {}).get("tokens") == 800

    # otro tenant no ve nada
    assert await tracker.summary(uuid4()) == {}


@pytest.mark.asyncio
async def test_suggested_questions_are_evidence_based(org_ws) -> None:
    organization, workspace = org_ws
    corpus, _source, _doc = await _seed(organization, workspace)

    questions = await QuestionSuggestionService().suggest(
        organization.id, corpus.id
    )
    texts = [q.text for q in questions]

    # lista de obligaciones sobre el título real
    assert any("obligaciones" in t and "Manual Operaciones" in t for t in texts)
    # temporal porque hay fechas reales
    assert any("fechas críticas" in t for t in texts)
    # riesgos porque hay cues reales
    assert any("riesgos" in t for t in texts)
    assert all(q.basis and q.intent for q in questions)


class _NeverEmbed:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts, model=None):
        self.calls += 1
        raise AssertionError("embed must not be called (fingerprint skip)")


class _NoopTracker:
    def __init__(self) -> None:
        self.calls = 0

    async def record_embedding_tokens(self, organization_id, chunk_token_count, **kwargs):
        self.calls += 1


@pytest.mark.asyncio
async def test_engine_skips_reembed_when_content_unchanged() -> None:
    from src.knowledge.engine.service import KnowledgeIngestionEngine

    doc = _PARSER.parse(
        _MD.encode("utf-8"),
        organization_id=uuid4(),
        external_id="manual.md",
        source_id=uuid4(),
    )
    assert doc.section_count > 0

    embedder = _NeverEmbed()
    tracker = _NoopTracker()
    engine = KnowledgeIngestionEngine(
        job_repo=object(),  # type: ignore[arg-type]
        sync_state_repo=object(),  # type: ignore[arg-type]
        doc_registry_repo=object(),  # type: ignore[arg-type]
        kb_repo=object(),  # type: ignore[arg-type]
        source_repo=object(),  # type: ignore[arg-type]
        vector_store=object(),  # type: ignore[arg-type]
        embedding_provider=embedder,  # type: ignore[arg-type]
        usage_tracker=tracker,
    )
    job = SimpleNamespace(organization_id=uuid4(), knowledge_base_id=None)
    source = SimpleNamespace(id=uuid4(), workspace_id=None)
    await engine._index_v2_chunks(  # noqa: SLF001
        job, source, doc, change_kind="unchanged"
    )
    assert embedder.calls == 0
    assert tracker.calls == 0
