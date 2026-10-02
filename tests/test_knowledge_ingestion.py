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

import src.knowledge.engine.service as engine_service
from src.core.domain.entities import IngestionJobStatus
from src.core.domain.knowledge_events import KnowledgeEventType
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
            metadata={
                "filename": "manual.md",
                "format": "md",
                "visibility": "admin",
                "acl_groups": ["legal"],
            },
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


def build_engine(
    structured_repo: StructuredDocumentRepository | None,
    *,
    system_emitter: object | None = None,
) -> KnowledgeIngestionEngine:
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
        system_emitter=system_emitter,
    )


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserted: list = []
        self.deleted_points: list[str] = []
        self.deleted_v2_documents: list = []
        self.deleted_stale_v2: list = []

    async def search(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert(self, *args, **kwargs) -> None:
        self.upserted.append(args)

    async def upsert_batch(
        self, organization_id, points, knowledge_base_id=None, workspace_id=None
    ) -> None:
        self.upserted.extend((organization_id, p, knowledge_base_id) for p in points)

    async def delete_by_organization(self, organization_id) -> None:
        pass

    async def delete_by_knowledge_base(self, organization_id, kb_id) -> None:
        pass

    async def delete_points(self, organization_id, point_ids) -> None:
        self.deleted_points.extend(point_ids)

    async def delete_v2_document(self, organization_id, document_id) -> None:
        self.deleted_v2_documents.append(document_id)

    async def delete_stale_v2_documents(
        self, organization_id, source_id, keep_external_ids
    ) -> None:
        self.deleted_stale_v2.append((source_id, set(keep_external_ids)))


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
async def test_engine_persists_structure_and_indexes_its_chunks(context) -> None:
    structured_repo = FakeStructuredDocRepo()
    engine = build_engine(structured_repo)
    vectors: FakeVectorStore = engine._vectors
    job_id = await create_job(context)

    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED
    assert job.records_processed == 1

    # El documento estructurado es obligatorio y se persiste primero
    assert len(structured_repo.documents) == 1
    doc = structured_repo.documents[0]
    assert doc.title == "Manual"
    assert doc.block_count > 0
    assert doc.section_count == 1
    assert engine.documents_parsed == 1
    assert engine.documents_failed == 0
    # el registro V2 usa el parser correcto por extensión
    assert get_parser("md") is not None

    # Los chunks se derivan de esa estructura y se indexan
    assert len(vectors.upserted) >= 1

    # V2: child chunks indexados con payload estructural (mismo collection)
    v2_points = [
        p for (_, p, _) in vectors.upserted if p[3] and p[3].get("v2_chunk") == "true"
    ]
    assert v2_points
    assert all(p[3]["document_id"] == str(doc.id) for p in v2_points)
    assert any(p[3].get("section_id") for p in v2_points)
    mode = (doc.metadata.get("understanding") or {}).get("mode")
    expected_strategy = (
        "semantic_units+parent_child" if mode == "active" else "document_structure+parent_child"
    )
    assert v2_points[0][3]["chunking_strategy"] == expected_strategy
    # el adapter inyecta organization_id en el PAYLOAD top-level (no en metadata)
    assert v2_points[0][3]["source_id"] == str(context["source"].id)

    # F2: ACL del record copiada al payload V2 (filtro pre-LLM)
    assert all(p[3]["visibility"] == "admin" for p in v2_points)
    assert all(p[3]["acl_groups"] == ["legal"] for p in v2_points)

    # F1: parent chunks (contexto de sección) también indexados
    parent_points = [
        p
        for (_, p, _) in vectors.upserted
        if p[3] and p[3].get("v2_parent") == "true"
    ]
    assert parent_points
    assert all(p[3].get("v2_chunk") == "false" for p in parent_points)
    assert all(
        p[3].get("chunk_type") == "document_structure" for p in parent_points
    )

    # F5: stale V2 points del documento se limpian antes de reindexar
    assert vectors.deleted_v2_documents == [doc.id]
    # F5: purga V2 de documentos que ya no existen en la fuente
    assert vectors.deleted_stale_v2 == [
        (context["source"].id, {"manual.md"})
    ]
    assert all(
        p[3].get("v2_doc") == "true"
        for (_, p, _) in vectors.upserted
        if p[3] and (p[3].get("v2_chunk") == "true" or p[3].get("v2_parent") == "true")
    )

    # F13: locators de cita en payload (chunk_id + section_path)
    assert v2_points[0][3]["chunk_id"]
    assert v2_points[0][3]["section_path"]


@pytest.mark.asyncio
async def test_engine_sin_repo_estructurado_falla_el_job(context) -> None:
    """Sin árbol canónico no hay conocimiento: el job falla, no indexa texto crudo."""
    structured_repo = FakeStructuredDocRepo()
    engine = build_engine(None)
    vectors: FakeVectorStore = engine._vectors
    job_id = await create_job(context)

    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.FAILED
    assert structured_repo.documents == []
    assert engine.documents_parsed == 0
    assert vectors.upserted == []


# ---------------------------------------------------------------------------
# C8: SOURCE_SUPERSEDED al registrar una versión actualizada
# ---------------------------------------------------------------------------


class FakeSystemEmitter:
    """Emisor C8 en memoria: registra los eventos de dominio emitidos."""

    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, event) -> None:
        self.events.append(event)

    def of_type(self, event_type: KnowledgeEventType) -> list:
        return [event for event in self.events if event.type == event_type]


class FakeUpdatedStructuredDocRepo(FakeStructuredDocRepo):
    """Registro V2 que siempre detecta una versión actualizada."""

    async def upsert_document(self, document) -> str:
        await super().upsert_document(document)
        return "updated"


@pytest.mark.asyncio
async def test_engine_emite_source_superseded_al_actualizar_version(
    context, monkeypatch
) -> None:
    """Con versión previa real y change_kind=updated se emite SOURCE_SUPERSEDED."""
    structured_repo = FakeUpdatedStructuredDocRepo()
    emitter = FakeSystemEmitter()
    engine = build_engine(structured_repo, system_emitter=emitter)

    async def fake_versions(organization_id, document_id):
        return [
            {"version": 2, "change_kind": "updated"},
            {"version": 1, "change_kind": "created"},
        ]

    # raising=False: en RED la función todavía no existe y el evento no se emite.
    monkeypatch.setattr(
        engine_service, "_load_document_versions", fake_versions, raising=False
    )

    job_id = await create_job(context)
    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED

    document = structured_repo.documents[0]
    events = emitter.of_type(KnowledgeEventType.SOURCE_SUPERSEDED)
    assert len(events) == 1
    event = events[0]
    assert event.organization_id == context["organization"].id
    assert event.document_id == document.id
    assert event.payload == {
        "document_id": str(document.id),
        "previous_version": 1,
        "current_version": 2,
        "change_kind": "updated",
    }
    assert event.requires_review is True
