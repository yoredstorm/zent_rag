# =============================================================================
# Knowledge Nutrition — integración end-to-end
# =============================================================================
# source -> parse -> reconstruct -> enrich -> compile (vista) -> index
#        -> retrieve -> acceptance -> nutrition state -> fingerprint skip
#
# Demuestra:
#   - enrichment y fingerprint persistidos en la metadata del documento
#   - payload de índice con conceptos/aliases/preguntas y vista compilada
#   - parent embebido con representación compuesta (no truncamiento)
#   - acceptance mide retrieval real y persiste evaluación
#   - segunda corrida sin cambios: fingerprint SKIP (no re-embed)
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

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
from src.knowledge.acceptance import PostgresAcceptanceStore
from src.knowledge.connectors.base import Record, SourceConnector
from src.knowledge.connectors.registry import register_connector
from src.knowledge.engine.service import KnowledgeIngestionEngine

MANUAL = """# Category 31 - Voluntary Changes

Category 31 (CAT31) defines voluntary changes for exchange eligibility.

Field: Status Byte
Bytes: 105-105
Description: status of the voluntary change

Byte 105 indicates the status for voluntary changes.

If the status is A, then the change is accepted.
"""


class NutritionConnector(SourceConnector):
    source_type = "test_nutrition_md"
    self_contained = False

    async def validate(self) -> None:
        pass

    async def iter_records(self, cursor: dict | None):
        yield Record(
            external_id="nutrition.md",
            content=MANUAL,
            metadata={"filename": "nutrition.md", "format": "md"},
            raw_data=MANUAL.encode("utf-8"),
            format="md",
        )


register_connector(NutritionConnector)


class FakeStructuredDocRepo(StructuredDocumentRepository):
    def __init__(self) -> None:
        self.documents = []
        self.runtime_metadata: dict[str, dict] = {}
        self.change_kinds: list[str] = []

    async def upsert_document(self, document) -> str:
        document.check_consistency()
        existing = next(
            (
                doc
                for doc in self.documents
                if doc.organization_id == document.organization_id
                and doc.external_id == document.external_id
            ),
            None,
        )
        if existing is None:
            self.documents.append(document)
            change_kind = "created"
        elif existing.content_hash == document.content_hash:
            change_kind = "unchanged"
        else:
            change_kind = "updated"
        self.change_kinds.append(change_kind)
        return change_kind

    async def get_document(self, organization_id, document_id):
        doc = next(
            (
                item
                for item in self.documents
                if item.organization_id == organization_id and item.id == document_id
            ),
            None,
        )
        if doc is None:
            return None
        metadata = {**(doc.metadata or {}), **self.runtime_metadata.get(str(document_id), {})}
        return {"id": str(doc.id), "title": doc.title, "metadata": metadata}

    async def list_documents(self, organization_id, source_id, limit=100):
        return [
            {"id": str(doc.id), "title": doc.title}
            for doc in self.documents
            if doc.organization_id == organization_id and doc.source_id == source_id
        ]

    async def delete_for_source(self, organization_id, source_id) -> None:
        self.documents = [
            doc
            for doc in self.documents
            if not (doc.organization_id == organization_id and doc.source_id == source_id)
        ]

    async def set_runtime_metadata(self, organization_id, document_id, values) -> None:
        current = self.runtime_metadata.setdefault(str(document_id), {})
        current.update(values or {})


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.points: dict[str, tuple] = {}
        self.deleted_documents: list = []
        self.search_calls = 0
        self.sparse_texts: list[str] = []
        self.payload_updates: list[tuple[str, dict]] = []

    async def upsert_batch(
        self,
        organization_id,
        points,
        knowledge_base_id=None,
        workspace_id=None,
        sparse_texts=None,
    ) -> None:
        for point_id, vector, content, metadata in points:
            self.points[str(point_id)] = (
                str(organization_id),
                vector,
                content,
                metadata or {},
            )
        self.sparse_texts = list(sparse_texts or [])

    async def update_document_payload(
        self, organization_id, document_id, payload
    ) -> None:
        self.payload_updates.append((str(document_id), dict(payload)))
        for key, value in self.points.items():
            org, vector, content, metadata = value
            if org != str(organization_id):
                continue
            if str(metadata.get("document_id")) != str(document_id):
                continue
            metadata.update(payload or {})
            self.points[key] = (org, vector, content, metadata)

    async def delete_v2_document(self, organization_id, document_id) -> None:
        self.deleted_documents.append(document_id)
        self.points = {
            key: value
            for key, value in self.points.items()
            if not (
                value[0] == str(organization_id)
                and str(value[3].get("document_id")) == str(document_id)
            )
        }

    async def delete_v2_tables(self, organization_id, document_id, table_ids) -> None:
        return None

    async def delete_points(self, organization_id, point_ids) -> None:
        for point_id in point_ids:
            self.points.pop(str(point_id), None)

    async def delete_by_organization(self, organization_id) -> None:
        return None

    async def delete_by_knowledge_base(self, organization_id, kb_id) -> None:
        return None

    async def delete_stale_v2_documents(self, organization_id, source_id, keep_external_ids):
        return None

    async def search(
        self,
        organization_id,
        query_embedding,
        top_k=5,
        filters=None,
        exclude_filters=None,
        score_threshold=0.1,
        role="admin",
        knowledge_base_id=None,
        user_id=None,
        groups=None,
        workspace_id=None,
        source_ids=None,
    ):
        self.search_calls += 1
        chunks = []
        for org, _vector, content, metadata in self.points.values():
            if org != str(organization_id):
                continue
            if workspace_id is not None and str(metadata.get("workspace_id")) != str(workspace_id):
                continue
            chunks.append(
                SimpleNamespace(
                    document_id=UUID(int=0),
                    content=content,
                    score=0.9,
                    metadata=metadata,
                )
            )
        return SimpleNamespace(chunks=chunks[:top_k])


class RecordingEmbedding:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts, model=None):
        if isinstance(texts, str):
            self.calls.append([texts])
            return [0.1] * 8
        self.calls.append(list(texts))
        return [[0.1] * 8 for _ in texts]

    @property
    def document_batch_calls(self) -> list[list[str]]:
        """Llamados de indexación (varios textos) vs acceptance (queries)."""
        return [call for call in self.calls if len(call) > 1]


class RecordingUsageTracker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, float]] = []

    async def record_embedding_tokens(
        self, organization_id, tokens, *, cost_usd, workspace_id=None, source_id=None
    ) -> None:
        self.calls.append(("embedding", int(tokens), float(cost_usd)))

    async def record_llm_tokens(self, *args, **kwargs) -> None:
        return None


@pytest.fixture
async def context():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Nutrition {uuid4().hex[:6]}")
    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(
        organization.id, "KB Nutrition", chunking_strategy="fixed", chunk_size=500, chunk_overlap=50
    )
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        organization.id, "src-nutrition", "test_nutrition_md", knowledge_base_id=kb.id
    )
    return {"organization": organization, "kb": kb, "source": source}


def build_engine(structured_repo, embedder, usage_tracker=None):
    return KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=InMemoryVectorStore(),
        embedding_provider=embedder,
        backoff_base_seconds=1,
        max_attempts_default=2,
        structured_doc_repo=structured_repo,
        usage_tracker=usage_tracker,
    )


async def _create_job(context):
    repo = PostgresIngestionJobRepository()
    job = await repo.create_job(
        context["organization"].id,
        job_type="sync_source:test_nutrition_md",
        source_id=context["source"].id,
        knowledge_base_id=context["kb"].id,
        max_attempts=2,
    )
    return job.id


class FailingEmbedding:
    """Provider caído: todos los batches fallan."""

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts, model=None):
        self.calls += 1
        raise TimeoutError("embedding provider timeout")


@pytest.mark.asyncio
async def test_all_embeddings_failed_does_not_persist_fingerprint(context) -> None:
    """Fallo total de embeddings: contadores visibles y fuente en error."""
    structured = FakeStructuredDocRepo()
    embedder = FailingEmbedding()
    engine = build_engine(structured, embedder)
    job = await engine.execute_job(await _create_job(context))

    assert job.status == IngestionJobStatus.COMPLETED
    assert job.records_failed >= 1
    assert job.records_processed == 0
    # Sin fingerprint indexado: el próximo sync reintenta la representación.
    assert structured.runtime_metadata == {}
    assert embedder.calls >= 1
    # La fuente NO se declara indexada con cero documentos.
    from src.infrastructure.postgres.knowledge_repos import PostgresSyncStateRepository

    state = await PostgresSyncStateRepository().get_state(context["source"].id)
    assert state is not None
    assert state.last_error  # visible: no se declara éxito silencioso


@pytest.mark.asyncio
async def test_nutrition_pipeline_end_to_end_and_fingerprint_skip(context) -> None:
    structured = FakeStructuredDocRepo()
    embedder = RecordingEmbedding()
    tracker = RecordingUsageTracker()
    engine = build_engine(structured, embedder, tracker)

    job = await engine.execute_job(await _create_job(context))
    assert job.status == IngestionJobStatus.COMPLETED

    document = structured.documents[0]
    # 1. Enrichment + fingerprint persistidos y auditables.
    enrichment_payload = document.metadata.get("enrichment") or {}
    assert enrichment_payload["enrichment_version"]
    assert enrichment_payload["derived"] is True
    assert enrichment_payload["canonical"] is False
    assert enrichment_payload["concepts"]
    fingerprint_payload = document.metadata.get("retrieval_fingerprint") or {}
    assert fingerprint_payload["fingerprint"]
    assert fingerprint_payload["embedding_model"]

    # 2. Payload de índice con conocimiento derivado + vista compilada.
    points = list(engine._vectors.points.values())
    child_points = [p for p in points if p[3].get("v2_chunk") == "true"]
    parent_points = [p for p in points if p[3].get("v2_parent") == "true"]
    assert child_points and parent_points
    assert all(p[3].get("representation_fingerprint") for p in points)
    assert all(p[3].get("enrichment_derived") == "true" for p in points)
    assert any(p[3].get("retrieval_aliases") for p in child_points)
    assert any(p[3].get("retrieval_questions") for p in child_points)
    assert any(p[3].get("compiled_entity_names") for p in child_points)
    # Dos representaciones por child: contenido (dense) + retrieval (sparse).
    assert all(p[3].get("content_representation_version") for p in child_points)
    assert all(p[3].get("retrieval_representation_version") for p in child_points)
    assert engine._vectors.sparse_texts, "el sparse debe usar la representación de retrieval"
    assert any("Questions:" in text or "Identifiers:" in text for text in engine._vectors.sparse_texts)

    # PASS 2: ids canónicos actualizados en payload sin re-embedding.
    assert engine._vectors.payload_updates, "el PASS 2 debe actualizar payloads"
    updated_payload = engine._vectors.payload_updates[-1][1]
    assert updated_payload.get("compiled_status") == "completed"
    assert updated_payload.get("canonical_entity_ids")

    # 3. Parent: contenido real intacto + representación compuesta embebida.
    parent = parent_points[0]
    assert parent[3].get("parent_representation_version")
    assert "Category 31" in parent[2]  # contenido real (evidencia)
    batch_calls = embedder.document_batch_calls
    assert batch_calls, "la indexación debe embeber los chunks"
    embedded_texts = [text for call in batch_calls for text in call]
    composed = [
        text
        for text in embedded_texts
        if "Category 31" in text and len(text) < len(parent[2])
    ]
    assert composed, "el parent debe embeber una representación compuesta"

    # 4. Acceptance corrió, persistió evaluación y el documento es retrievable.
    store = PostgresAcceptanceStore()
    evaluation = await store.last_evaluation(context["organization"].id, document.id)
    assert evaluation is not None
    assert evaluation["probes_total"] > 0
    assert evaluation["accepted"] is True
    assert evaluation["recall_at_5"] == 1.0, evaluation["failed_probes"]
    assert engine._vectors.search_calls > 0

    # 5. Fingerprint indexado persistido en runtime metadata + razón auditable.
    runtime = structured.runtime_metadata.get(str(document.id), {})
    assert runtime.get("indexed_representation_fingerprint") == fingerprint_payload["fingerprint"]
    assert runtime.get("last_index_reason") == "missing_index"
    assert (
        runtime.get("indexed_representation_descriptor", {}).get("fingerprint")
        == fingerprint_payload["fingerprint"]
    )

    # 5b. Cost tracking: indexación + queries de acceptance registran tokens.
    assert len(tracker.calls) >= 2, tracker.calls
    assert all(kind == "embedding" for kind, _tokens, _cost in tracker.calls)
    assert sum(tokens for _kind, tokens, _cost in tracker.calls) > 0

    # 6. Segunda corrida sin cambios: SKIP (sin re-embed de documento).
    calls_before = len(embedder.document_batch_calls)
    deleted_before = len(engine._vectors.deleted_documents)
    usage_before = len(tracker.calls)

    async def _skip_acceptance(job, document, enrichment):
        return None

    engine._run_acceptance = _skip_acceptance  # type: ignore[method-assign]
    job2 = await engine.execute_job(await _create_job(context))
    assert job2.status == IngestionJobStatus.COMPLETED
    assert structured.change_kinds[-1] == "unchanged"
    assert len(embedder.document_batch_calls) == calls_before
    assert len(engine._vectors.deleted_documents) == deleted_before
    assert len(tracker.calls) == usage_before
