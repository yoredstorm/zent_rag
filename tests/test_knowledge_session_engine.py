# =============================================================================
# Learning Session ↔ Ingestion Engine — el aprendizaje observado es real
# =============================================================================
# Corre el engine productivo (con repos Postgres reales) sobre una fuente de
# prueba registrada en una sesión y verifica que los eventos de la sesión
# provienen del trabajo realmente ocurrido: recibir, entender, indexar y
# consolidar. Sin mocks del observer.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

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
from src.platform.knowledge_sessions.repository import (
    PostgresKnowledgeSessionRepository,
)
from src.platform.knowledge_sessions.service import LearningSessionService


class FakeStructuredDocRepo(StructuredDocumentRepository):
    def __init__(self) -> None:
        self.documents = []

    async def upsert_document(self, document) -> str:
        assert document.check_consistency() is None
        self.documents.append(document)
        return "created"

    async def get_document(self, organization_id, document_id):
        return None

    async def list_documents(self, organization_id, source_id, limit=100):
        return []

    async def delete_for_source(self, organization_id, source_id) -> None:
        self.documents = []


class SessionMarkdownConnector(SourceConnector):
    source_type = "test_session_md"
    self_contained = False

    async def validate(self) -> None:
        pass

    async def iter_records(self, cursor: dict | None):
        content = (
            "# Manual de comisiones\n\n"
            "La comisión por venta es del 5%.\n\n"
            "## Campos\n\n"
            "Carrier Code identifica a la aerolínea.\n"
        )
        yield Record(
            external_id="manual.md",
            content=content,
            metadata={"filename": "manual.md"},
            raw_data=content.encode("utf-8"),
            format="md",
        )


register_connector(SessionMarkdownConnector)


class FakeVectorStore:
    async def search(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert(self, *args, **kwargs) -> None:
        pass

    async def upsert_batch(self, *args, **kwargs) -> None:
        pass

    async def delete_by_organization(self, organization_id) -> None:
        pass

    async def delete_by_knowledge_base(self, organization_id, kb_id) -> None:
        pass

    async def delete_points(self, organization_id, point_ids) -> None:
        pass

    async def delete_v2_document(self, organization_id, document_id) -> None:
        pass

    async def delete_stale_v2_documents(
        self, organization_id, source_id, keep_external_ids
    ) -> None:
        pass


class FakeEmbedding:
    async def embed(self, texts, model=None):
        if isinstance(texts, list):
            return [[0.1] * 8 for _ in texts]
        return [0.1] * 8


@pytest.mark.asyncio
async def test_engine_emite_el_aprendizaje_real_en_la_sesion() -> None:
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Session Engine {uuid4().hex[:6]}"
    )
    kb = await PostgresKnowledgeBaseRepository().create_kb(
        org.id,
        "KB Session",
        chunking_strategy="fixed",
        chunk_size=500,
        chunk_overlap=50,
    )
    source = await PostgresSourceRepository().create_source(
        org.id, f"manual-{uuid4().hex[:6]}.md", "test_session_md", knowledge_base_id=kb.id
    )

    repo = PostgresKnowledgeSessionRepository()
    await repo.ensure_tables()
    service = LearningSessionService(repo)
    session = await service.start_session(org.id, title="Aprendiendo 1 fuente", origin="test")

    jobs = PostgresIngestionJobRepository()
    job = await jobs.create_job(
        org.id,
        job_type="sync_source:test_session_md",
        source_id=source.id,
        knowledge_base_id=kb.id,
    )
    await service.attach_source(
        session,
        source_id=source.id,
        job_id=job.id,
        name=source.name,
        source_type=source.type,
    )

    engine = KnowledgeIngestionEngine(
        job_repo=jobs,
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=FakeVectorStore(),
        embedding_provider=FakeEmbedding(),
        structured_doc_repo=FakeStructuredDocRepo(),
        backoff_base_seconds=1,
        max_attempts_default=1,
        session_service=service,
    )

    finished = await engine.execute_job(job.id)
    assert finished is not None
    assert str(finished.status) == "completed"

    detail = await service.get_session_detail(org.id, session.id)
    assert detail is not None
    assert detail["sources"][0]["status"] == "completed"
    assert detail["sources"][0]["stage"] == "learned"

    events = await repo.list_events(org.id, session.id, limit=2000)
    types = [event["event_type"] for event in events]
    # Nacidos del pipeline real, en orden de aprendizaje.
    for expected in (
        "SESSION_STARTED",
        "SOURCE_RECEIVED",
        "PARSING_STARTED",
        "STRUCTURE_DISCOVERED",
        "SOURCE_AVAILABLE",
        "KNOWLEDGE_READY",
    ):
        assert expected in types, f"falta el evento real {expected}: {types}"

    # Los textos son humanos: la UI no recibe el evento crudo.
    matched = next(event for event in events if event["event_type"] == "STRUCTURE_DISCOVERED")
    assert "comprendió" in matched["message"] or "estructura" in matched["message"]

    # Métricas y delta derivan de los contadores reales de la fuente.
    stats = detail["sources"][0]["stats"]
    assert stats.get("sources") == 1
    assert detail["metrics"]["sources_available"] == 1
    assert detail["knowledge_delta"] is not None
