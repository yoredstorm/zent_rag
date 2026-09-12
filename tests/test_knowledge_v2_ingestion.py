# =============================================================================
# Knowledge V2 — engine hook (Phase B): estructura V2 en paralelo a V1
# =============================================================================
# El motor con structured_doc_repo persiste el árbol StructuredDocument SIN
# cambiar el camino V1 (chunk → embed → Qdrant). Sin repo, el motor queda
# idéntico a V1 (compatibilidad).
# =============================================================================
from __future__ import annotations

import uuid
from uuid import uuid4

import pytest

from src.core.domain.entities import IngestionJobStatus
from src.core.ports.structured import StructuredDocumentRepository
from src.infrastructure.postgres.knowledge_repos import (
    PostgresDocumentRegistryRepository,
    PostgresIngestionJobRepository,
    PostgresSourceRepository,
    PostgresSyncStateRepository,
)
from src.infrastructure.postgres.relational_db import (
    PostgresKnowledgeBaseRepository,
    PostgresOrganizationRepository,
)
from src.knowledge.connectors.base import Record, SourceConnector
from src.knowledge.connectors.registry import register_connector
from src.knowledge.engine.service import KnowledgeIngestionEngine
from src.knowledge.structure.base import get_parser


class FakeStructuredDocRepo(StructuredDocumentRepository):
    def __init__(self) -> None:
        self.documents = []
        self.change_kinds: list[str] = []

    async def upsert_document(self, document) -> str:
        assert document.check_consistency() is None
        self.documents.append(document)
        change_kind = "created"
        self.change_kinds.append(change_kind)
        return change_kind

    async def get_document(self, organization_id, document_id):
        for doc in self.documents:
            if doc.organization_id == organization_id and doc.id == document_id:
                return {"id": str(doc.id), "title": doc.title}
        return None

    async def list_documents(self, organization_id, source_id, limit=100):
        return [
            {"id": str(d.id), "title": d.title}
            for d in self.documents
            if d.organization_id == organization_id and d.source_id == source_id
        ]

    async def delete_for_source(self, organization_id, source_id) -> None:
        self.documents = [
            d
            for d in self.documents
            if not (d.organization_id == organization_id and d.source_id == source_id)
        ]


class V2MarkdownConnector(SourceConnector):
    source_type = "test_v2_markdown"
    self_contained = False

    async def validate(self) -> None:
        pass

    async def iter_records(self, cursor: dict | None):
        content = "# Manual\n\nComisión 5% en contratos vigentes."
        yield Record(
            external_id="manual.md",
            content=content,
            metadata={"filename": "manual.md", "format": "md"},
            raw_data=content.encode("utf-8"),
            format="md",
        )


register_connector(V2MarkdownConnector)


@pytest.fixture
async def context():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"V2 Org {uuid4().hex[:6]}")
    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(
        organization.id,
        "KB V2",
        chunking_strategy="fixed",
        chunk_size=500,
        chunk_overlap=50,
    )
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        organization.id, "src-v2-md", "test_v2_markdown", knowledge_base_id=kb.id
    )
    return {
        "organization": organization,
        "kb": kb,
        "source": source,
    }


def build_engine(structured_repo: StructuredDocumentRepository | None) -> KnowledgeIngestionEngine:
    return KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=FakeVectorStore(),
        embedding_provider=FakeEmbedding(),
        backoff_base_seconds=1,
        max_attempts_default=2,
        structured_doc_repo=structured_repo,
    )


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserted: list = []
        self.deleted_points: list[str] = []

    async def search(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert(self, *args, **kwargs) -> None:
        self.upserted.append(args)

    async def upsert_batch(self, organization_id, points, knowledge_base_id=None) -> None:
        self.upserted.extend((organization_id, p, knowledge_base_id) for p in points)

    async def delete_by_organization(self, organization_id) -> None:
        pass

    async def delete_by_knowledge_base(self, organization_id, kb_id) -> None:
        pass

    async def delete_points(self, organization_id, point_ids) -> None:
        self.deleted_points.extend(point_ids)


class FakeEmbedding:
    async def embed(self, texts, model=None):
        if isinstance(texts, list):
            return [[0.1] * 8 for _ in texts]
        return [0.1] * 8


async def create_job(ctx) -> uuid.UUID:
    repo = PostgresIngestionJobRepository()
    job = await repo.create_job(
        ctx["organization"].id,
        job_type="sync_source:test_v2_markdown",
        source_id=ctx["source"].id,
        knowledge_base_id=ctx["kb"].id,
        max_attempts=2,
    )
    return job.id


@pytest.mark.asyncio
async def test_engine_with_v2_repo_runs_v2_and_v1_in_parallel(context) -> None:
    structured_repo = FakeStructuredDocRepo()
    engine = build_engine(structured_repo)
    vectors: FakeVectorStore = engine._vectors
    job_id = await create_job(context)

    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED
    assert job.records_processed == 1

    # V2: parseó y persistió estructura
    assert len(structured_repo.documents) == 1
    doc = structured_repo.documents[0]
    assert doc.title == "Manual"
    assert doc.block_count > 0
    assert doc.section_count == 1
    assert engine.v2_parsed == 1
    assert engine.v2_failed == 0
    # el registro V2 usa el parser correcto por extensión
    assert get_parser("md") is not None

    # V1 intacto: chunks aún se indexaron en Qdrant
    assert len(vectors.upserted) >= 1

    # V2: child chunks indexados con payload estructural (mismo collection)
    v2_points = [
        p for (_, p, _) in vectors.upserted if p[3] and p[3].get("v2_chunk") == "true"
    ]
    assert v2_points
    assert all(p[3]["document_id"] == str(doc.id) for p in v2_points)
    assert any(p[3].get("section_id") for p in v2_points)
    assert v2_points[0][3]["chunking_strategy"] == "document_structure+parent_child"
    # el adapter inyecta organization_id en el PAYLOAD top-level (no en metadata)
    assert v2_points[0][3]["source_id"] == str(context["source"].id)


@pytest.mark.asyncio
async def test_engine_without_v2_repo_keeps_v1_only(context) -> None:
    structured_repo = FakeStructuredDocRepo()
    engine = build_engine(None)
    vectors: FakeVectorStore = engine._vectors
    job_id = await create_job(context)

    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED
    assert structured_repo.documents == []
    assert engine.v2_parsed == 0
    assert len(vectors.upserted) >= 1  # camino V1 sin cambios
