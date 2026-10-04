# =============================================================================
# Progressive Semantic Ingestion — manifiesto, plan y reanudación (Fases 1-2)
# =============================================================================
# Reglas que se prueban:
#   - coverage_ratio ponderado: nunca 100% si falta una etapa requerida;
#   - el servicio es fail-soft y en modo active reanuda solo si la fuente y la
#     versión del pipeline no cambiaron;
#   - el store Postgres guarda manifiesto + ventanas scoped por tenant;
#   - el engine escribe el manifiesto al ingerir y en la segunda corrida no
#     vuelve a parsear ni a embeber (SKIP real).
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
from src.knowledge.semantic import (
    PostgresSemanticIngestionStore,
    SemanticIngestionService,
    SemanticWindowPlanner,
    SourceIngestionManifest,
    manifest_with,
    semantic_versions,
)
from src.knowledge.structure.text_parser import TextParser
from src.knowledge.understanding.engine import apply_understanding


def _understood(text: str, external_id: str = "manual.md"):
    parser = TextParser()
    document = parser.parse(
        text.encode("utf-8"),
        organization_id=uuid4(),
        external_id=external_id,
        source_id=uuid4(),
        source_name=external_id,
    )
    return apply_understanding(document, filename=external_id)


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------


def test_coverage_ratio_never_100_without_required_stages() -> None:
    base = SourceIngestionManifest(
        organization_id=uuid4(), source_id=uuid4(), external_id="a.md"
    )
    without_semantic = manifest_with(
        base,
        parsing_complete=True,
        indexing_complete=True,
        versions={"semantic_required": False},
    )
    assert without_semantic.coverage_ratio == 1.0

    with_semantic = manifest_with(
        base,
        parsing_complete=True,
        indexing_complete=True,
        versions={"semantic_required": True},
    )
    # 0.40 (parsing) + 0.15 (indexing) sobre un total de 1.0.
    assert with_semantic.coverage_ratio == 0.55


def test_set_stage_and_to_dict_are_auditable() -> None:
    base = SourceIngestionManifest(
        organization_id=uuid4(), source_id=uuid4(), external_id="a.md"
    )
    from src.knowledge.semantic import IngestionStage, StageStatus, set_stage

    manifest = set_stage(base, IngestionStage.PARSING, StageStatus.COMPLETE)
    assert manifest.stage(IngestionStage.PARSING) == "complete"
    payload = manifest.to_dict()
    assert payload["external_id"] == "a.md"
    assert payload["stages"]["parsing"] == "complete"
    assert payload["pipeline_complete"] is False


# ---------------------------------------------------------------------------
# Servicio con fake store (sin DB)
# ---------------------------------------------------------------------------


class FakeSemanticStore:
    def __init__(self) -> None:
        self.manifests: dict[tuple[str, str, str], SourceIngestionManifest] = {}
        self.plan = None
        self.results: dict[tuple[str, int], dict] = {}
        self.states: dict[tuple[str, int], object] = {}
        self.threads: dict[tuple[str, str], object] = {}
        self.units: list = []
        self.relations: list = []
        self.regional_models: list = []
        self.global_model: object | None = None
        self.fabric_nodes: list = []
        self.fabric_edges: list = []
        self.identities: list = []

    async def get_manifest(self, organization_id, *, source_id=None, external_id=None, document_id=None):
        return self.manifests.get(
            (str(organization_id), str(source_id), str(external_id))
        )

    async def upsert_manifest(self, manifest: SourceIngestionManifest) -> None:
        key = (
            str(manifest.organization_id),
            str(manifest.source_id),
            manifest.external_id,
        )
        self.manifests[key] = manifest

    async def save_window_plan(self, organization_id, *, source_id, workspace_id, document_id, plan):
        self.plan = plan

    async def get_window_result(self, organization_id, *, document_id, window_index):
        return self.results.get((str(document_id), int(window_index)))

    async def list_window_results(
        self, organization_id, *, document_id, include_items=False, limit=2000
    ):
        return [
            dict(payload)
            for (doc, _index), payload in sorted(self.results.items())
            if doc == str(document_id)
        ][:limit]

    async def save_window_result(
        self, organization_id, *, workspace_id, source_id, document_id, result
    ):
        self.results[(str(document_id), int(result.window_index))] = {
            "organization_id": str(organization_id),
            "document_id": str(document_id),
            "window_index": int(result.window_index),
            "status": result.status,
            "fingerprint": result.fingerprint,
            "carry_fingerprint": result.carry_fingerprint,
            "item_count": len(result.items),
            "items": [item.to_dict() for item in result.items],
        }

    async def get_state(self, organization_id, *, document_id, window_index):
        return self.states.get((str(document_id), int(window_index)))

    async def save_state(
        self, organization_id, *, workspace_id, source_id, document_id, state
    ):
        self.states[(str(document_id), int(state.window_index))] = state

    async def update_window_status(
        self, organization_id, *, document_id, window_index, status
    ):
        return None

    async def list_threads(self, organization_id, *, document_id, **kwargs):
        return [
            thread
            for (doc, _key), thread in self.threads.items()
            if doc == str(document_id)
        ]

    async def save_threads(
        self, organization_id, *, workspace_id, source_id, document_id, threads
    ):
        for thread in threads:
            self.threads[(str(document_id), thread.thread_key)] = thread

    async def replace_stitch(
        self, organization_id, *, workspace_id, source_id, document_id, units, relations
    ):
        self.units = list(units)
        self.relations = list(relations)

    async def replace_regional_models(
        self, organization_id, *, workspace_id, source_id, document_id, models
    ):
        self.regional_models = list(models)

    async def replace_global_model(
        self, organization_id, *, workspace_id, source_id, document_id, model
    ):
        self.global_model = model

    async def find_fabric_nodes_by_labels(
        self, organization_id, labels, *, exclude_document_id=None, limit=1000
    ):
        return []

    async def replace_fabric(
        self, organization_id, *, workspace_id, source_id, document_id, nodes, edges
    ):
        self.fabric_nodes = list(nodes)
        self.fabric_edges = list(edges)

    async def save_identity_candidates(self, organization_id, *, candidates):
        self.identities = list(candidates)

    async def delete_window_artifacts(self, organization_id, *, document_id):
        prefix = str(document_id)
        self.results = {
            key: value for key, value in self.results.items() if key[0] != prefix
        }
        self.states = {
            key: value for key, value in self.states.items() if key[0] != prefix
        }
        self.threads = {
            key: value for key, value in self.threads.items() if key[0] != prefix
        }
        self.units = []
        self.relations = []
        self.regional_models = []
        self.global_model = None
        self.fabric_nodes = []
        self.fabric_edges = []
        self.identities = []


@pytest.mark.asyncio
async def test_service_active_resumes_only_when_unchanged() -> None:
    store = FakeSemanticStore()
    service = SemanticIngestionService(store, mode="active")
    document = _understood("# Manual\n\nComisión 5% en contratos vigentes.")
    payload = b"# Manual\n\nComisi\u00f3n 5% en contratos vigentes."
    organization_id = document.organization_id

    first = await service.begin(
        organization_id=organization_id,
        source_id=document.source_id,
        workspace_id=None,
        external_id=document.external_id,
        source_type="file",
        raw_data=payload,
    )
    assert first is False
    plan = await service.parsed(document)
    assert plan is not None and plan.window_count >= 1
    assert store.plan is not None
    outcome = await service.process_windows(document, plan=plan)
    assert outcome is not None and outcome.complete
    await service.indexed(document, indexed_units=3, window_plan=plan)
    await service.finished(document)

    manifest = store.manifests[
        (str(organization_id), str(document.source_id), document.external_id)
    ]
    assert manifest.pipeline_complete is True
    assert manifest.coverage_ratio == 1.0

    # Misma fuente + misma versión de pipeline => reanudar sin reprocesar.
    assert (
        await service.begin(
            organization_id=organization_id,
            source_id=document.source_id,
            workspace_id=None,
            external_id=document.external_id,
            source_type="file",
            raw_data=payload,
            versions=semantic_versions(),
        )
        is True
    )

    # Bytes distintos => NO reanudar (se reprocesa).
    assert (
        await service.begin(
            organization_id=organization_id,
            source_id=document.source_id,
            workspace_id=None,
            external_id=document.external_id,
            source_type="file",
            raw_data=b"# Manual\n\ncontenido nuevo",
        )
        is False
    )


@pytest.mark.asyncio
async def test_service_marks_failure_without_breaking() -> None:
    store = FakeSemanticStore()
    service = SemanticIngestionService(store, mode="shadow")
    organization_id = uuid4()
    source_id = uuid4()
    await service.begin(
        organization_id=organization_id,
        source_id=source_id,
        workspace_id=None,
        external_id="roto.pdf",
        source_type="file",
        raw_data=b"bytes",
    )
    await service.failed(
        organization_id=organization_id,
        source_id=source_id,
        external_id="roto.pdf",
        error="RuntimeError: parser",
    )
    manifest = store.manifests[(str(organization_id), str(source_id), "roto.pdf")]
    assert manifest.stage("parsing") == "failed"
    assert manifest.pipeline_complete is False
    assert "parser" in manifest.details.get("last_error", "")


# ---------------------------------------------------------------------------
# Store Postgres
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_postgres_store_manifests_windows_and_summary() -> None:
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SI Org {uuid4().hex[:6]}"
    )
    store = PostgresSemanticIngestionStore()
    source_id = uuid4()
    document_id = uuid4()

    manifest = SourceIngestionManifest(
        organization_id=organization.id,
        source_id=source_id,
        external_id="manual.md",
        source_type="file",
        raw_fingerprint="a" * 64,
        total_bytes=128,
        versions={"semantic_required": False},
    )
    manifest = manifest_with(
        manifest,
        parsing_complete=True,
        indexing_complete=True,
        pipeline_complete=True,
        structural_units=3,
        processed_units=3,
    )
    await store.upsert_manifest(manifest)

    loaded = await store.get_manifest(
        organization.id, source_id=source_id, external_id="manual.md"
    )
    assert loaded is not None
    assert loaded.raw_fingerprint == "a" * 64
    assert loaded.pipeline_complete is True
    assert loaded.coverage_ratio == 1.0

    summary = await store.coverage_summary(organization.id, source_id=source_id)
    assert summary["documents_total"] == 1
    assert summary["documents_complete"] == 1
    assert summary["coverage_ratio"] == 1.0

    document = _understood(
        "# Manual\n\n" + "\n\n".join(f"parrafo {i} con contenido" for i in range(30))
    )
    plan = SemanticWindowPlanner().plan(
        document, model="deepseek-chat", max_tokens=400, reserves=0, min_tokens=100
    )
    await store.save_window_plan(
        organization.id,
        source_id=source_id,
        workspace_id=None,
        document_id=document_id,
        plan=plan,
    )
    windows = await store.list_windows(organization.id, document_id=document_id)
    assert len(windows) == plan.window_count
    assert windows[0]["status"] == "planned"
    assert windows[0]["fingerprint"] == plan.fingerprint


# ---------------------------------------------------------------------------
# Engine: manifiesto + reanudación end-to-end
# ---------------------------------------------------------------------------


class FakeStructuredDocRepo(StructuredDocumentRepository):
    def __init__(self) -> None:
        self.documents = []

    async def upsert_document(self, document) -> str:
        assert document.check_consistency() is None
        self.documents.append(document)
        return "created"

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


class SemanticMarkdownConnector(SourceConnector):
    source_type = "test_semantic_markdown"
    self_contained = False

    async def validate(self) -> None:
        pass

    async def iter_records(self, cursor: dict | None):
        content = (
            "# Manual\n\n"
            "Comision 5% en contratos vigentes.\n\n"
            "El campo FCLAS usa la mascara &&&F.\n\n"
            + "\n\n".join(
                f"Parrafo {index} con contenido operativo del manual." for index in range(40)
            )
            + "\n\nSee note NX7 for details.\n\nNX7 - Fare class note definition."
        )
        yield Record(
            external_id="semantic.md",
            content=content,
            metadata={"filename": "semantic.md", "format": "md"},
            raw_data=content.encode("utf-8"),
            format="md",
        )


register_connector(SemanticMarkdownConnector)


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserted: list = []
        self.deleted_v2_documents: list = []
        self.deleted_stale_v2: list = []

    async def search(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert_batch(
        self, organization_id, points, knowledge_base_id=None, workspace_id=None,
        sparse_texts=None,
    ) -> None:
        self.upserted.extend((organization_id, p, knowledge_base_id) for p in points)

    async def delete_points(self, organization_id, point_ids) -> None:
        return None

    async def delete_v2_document(self, organization_id, document_id) -> None:
        self.deleted_v2_documents.append(document_id)

    async def delete_stale_v2_documents(
        self, organization_id, source_id, keep_external_ids
    ) -> None:
        self.deleted_stale_v2.append((source_id, set(keep_external_ids)))


class FakeEmbedding:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts, model=None):
        if isinstance(texts, list):
            self.texts.extend(str(text) for text in texts)
            return [[0.1] * 8 for _ in texts]
        self.texts.append(str(texts))
        return [0.1] * 8


@pytest.fixture
async def semantic_context():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"SI Engine Org {uuid4().hex[:6]}"
    )
    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(
        organization.id, "KB SI", chunking_strategy="fixed", chunk_size=500, chunk_overlap=50
    )
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        organization.id, "src-si-md", "test_semantic_markdown", knowledge_base_id=kb.id
    )
    return {"organization": organization, "kb": kb, "source": source}


async def _create_job(ctx) -> uuid.UUID:
    repo = PostgresIngestionJobRepository()
    job = await repo.create_job(
        ctx["organization"].id,
        job_type="sync_source:test_semantic_markdown",
        source_id=ctx["source"].id,
        knowledge_base_id=ctx["kb"].id,
        max_attempts=2,
    )
    return job.id


@pytest.mark.asyncio
async def test_engine_writes_manifest_and_skips_unchanged_source(semantic_context) -> None:
    structured_repo = FakeStructuredDocRepo()
    store = PostgresSemanticIngestionStore()
    engine = KnowledgeIngestionEngine(
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
        semantic_ingestion=SemanticIngestionService(store, mode="active"),
    )
    job_id = await _create_job(semantic_context)
    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED
    assert job.records_processed == 1

    organization_id = semantic_context["organization"].id
    source_id = semantic_context["source"].id
    manifest = await store.get_manifest(
        organization_id, source_id=source_id, external_id="semantic.md"
    )
    assert manifest is not None
    assert manifest.parsing_complete is True
    assert manifest.indexing_complete is True
    assert manifest.pipeline_complete is True
    assert manifest.windows_total >= 1
    assert manifest.coverage_ratio == 1.0
    windows = await store.list_windows(
        organization_id, document_id=manifest.document_id
    )
    assert len(windows) == manifest.windows_total

    # Fase 3: cada ventana tiene resultado estructurado + estado semántico.
    results = await store.list_window_results(
        organization_id, document_id=manifest.document_id
    )
    assert len(results) == manifest.windows_total
    assert all(row["status"] in ("complete", "partial") for row in results)
    assert manifest.semantic_complete is True
    assert manifest.windows_processed == manifest.windows_total
    final_state = await store.latest_state(
        organization_id, document_id=manifest.document_id
    )
    assert final_state is not None
    assert final_state.window_index == manifest.windows_total - 1

    # Fase 4: threads durables persistidos por el engine.
    threads = await store.list_threads(
        organization_id, document_id=manifest.document_id
    )
    assert threads
    assert any(
        thread.thread_type == "REFERENCE" for thread in threads
    )
    assert manifest.details["window_processing"]["threads_opened"] >= 1

    # Fase 5: stitch de unidades + relaciones + cierre de threads.
    assert manifest.stitching_complete is True
    units = await store.list_units(organization_id, document_id=manifest.document_id)
    relations = await store.list_relations(
        organization_id, document_id=manifest.document_id
    )
    assert units
    assert relations
    assert manifest.details["stitching"]["relations"] >= 1

    # Fase 6: modelos regionales persistidos.
    regions = await store.list_regional_models(
        organization_id, document_id=manifest.document_id
    )
    assert regions
    assert manifest.details["regional_models"]["count"] == len(regions)

    # Fase 7: modelo global estructurado.
    assert manifest.global_synthesis_complete is True
    global_row = await store.get_global_model(
        organization_id, document_id=manifest.document_id
    )
    assert global_row is not None
    assert global_row["model"]["glossary"]
    assert global_row["model"]["stats"]["regions"] >= 1
    assert manifest.details["global_model"]["glossary"] >= 1

    # Fase 8: Semantic Fabric (nodos/aristas + identidad cross-source).
    fabric_nodes = await store.list_fabric_nodes(
        organization_id, document_id=manifest.document_id
    )
    fabric_edges = await store.list_fabric_edges(
        organization_id, document_id=manifest.document_id
    )
    assert fabric_nodes and fabric_edges
    assert manifest.details["fabric"]["nodes"] == len(fabric_nodes)
    assert any(node["node_type"] == "Evidence" for node in fabric_nodes)
    assert any(edge["relation_type"] == "DERIVED_FROM" for edge in fabric_edges)

    # Fase 9: nutrient retrieval units enriquecidas con el fabric.
    fabric_payloads = [
        point[3]
        for (_, point, _) in engine._vectors.upserted
        if point[3] and point[3].get("fabric_version")
    ]
    assert fabric_payloads
    assert any(payload.get("fabric_node_ids") for payload in fabric_payloads)
    assert any(payload.get("fabric_labels") for payload in fabric_payloads)
    assert any(
        payload.get("embedding_representation") == "content"
        for payload in fabric_payloads
    )

    # Fase 14: métricas de Retrieval Acceptance V2 en la evaluación real.
    from src.knowledge.acceptance import PostgresAcceptanceStore

    evaluations = await PostgresAcceptanceStore().list_evaluations(
        organization_id, document_id=manifest.document_id, limit=1
    )
    assert evaluations
    assert (
        evaluations[0]["metrics"].get("version") == "knowledge-acceptance-v2"
    )

    # Fase 15: fingerprints por etapa para invalidación selectiva.
    stage_fp = manifest.details.get("stage_fingerprints") or {}
    assert {"windows", "stitch", "regional", "global", "fabric"} <= set(stage_fp)
    assert all(stage_fp.values())

    upserts_before = len(engine._vectors.upserted)
    documents_before = len(structured_repo.documents)

    # Segunda corrida: misma fuente + mismo pipeline => SKIP real.
    second_job_id = await _create_job(semantic_context)
    second_job = await engine.execute_job(second_job_id)
    assert second_job.status == IngestionJobStatus.COMPLETED
    assert len(engine._vectors.upserted) == upserts_before
    assert len(structured_repo.documents) == documents_before
    results_after = await store.list_window_results(
        organization_id, document_id=manifest.document_id
    )
    assert len(results_after) == len(results)
    threads_after = await store.list_threads(
        organization_id, document_id=manifest.document_id
    )
    assert len(threads_after) == len(threads)
    relations_after = await store.list_relations(
        organization_id, document_id=manifest.document_id
    )
    assert len(relations_after) == len(relations)
    global_after = await store.get_global_model(
        organization_id, document_id=manifest.document_id
    )
    assert global_after is not None
    assert global_after["fingerprint"] == global_row["fingerprint"]


@pytest.mark.asyncio
async def test_engine_uses_semantic_representation_when_configured(
    semantic_context, monkeypatch
) -> None:
    """Fase 10: con representación `semantic`, el dense usa contexto del fabric."""
    from src.core.config import get_settings

    monkeypatch.setattr(
        get_settings(),
        "RAG_EMBEDDING_DENSE_REPRESENTATION",
        "semantic",
        raising=False,
    )
    structured_repo = FakeStructuredDocRepo()
    engine = KnowledgeIngestionEngine(
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
        semantic_ingestion=SemanticIngestionService(
            PostgresSemanticIngestionStore(), mode="active"
        ),
    )
    job_id = await _create_job(semantic_context)
    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED
    assert any(
        "Semantic context:" in text for text in engine._embeddings.texts
    )
    semantic_payloads = [
        point[3]
        for (_, point, _) in engine._vectors.upserted
        if point[3] and point[3].get("embedding_representation") == "semantic"
    ]
    assert semantic_payloads
