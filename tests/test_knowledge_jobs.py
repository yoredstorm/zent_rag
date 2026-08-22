# =============================================================================
# Knowledge Engine — retry, resume, dead letter, delete detection
# =============================================================================
# Unit/integration del motor con repos Postgres REALES (retry/dead-letter
# auditable) y vector store/embedder falsos.
# =============================================================================
from __future__ import annotations

import uuid
from uuid import uuid4

import pytest

from src.core.domain.entities import (
    IngestionJobStatus,
    KbSource,
)
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
from src.knowledge.connectors.base import ConnectorError, Record, SourceConnector
from src.knowledge.connectors.registry import register_connector
from src.knowledge.engine.service import (
    KnowledgeIngestionEngine,
    compute_retry_delay,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserted: list[tuple] = []
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


class RowsConnector(SourceConnector):
    source_type = "test_rows"
    self_contained = False
    records_yielded: int = 3
    seen_cursor: dict | None = None
    fail = False
    missing_metadata = False

    def __init__(self, source: KbSource) -> None:
        super().__init__(source)
        self._last_cursor = {"page": 2}

    async def validate(self) -> None:
        if self.fail:
            raise ConnectorError("connector configured to fail")

    async def iter_records(self, cursor: dict | None):
        type(self).seen_cursor = cursor
        for i in range(self.records_yielded):
            metadata = {"category": f"cat-{i}"}
            if self.missing_metadata:
                metadata = {}
            yield Record(
                external_id=f"row:{i}",
                content=f"Documento de prueba {i}",
                metadata=metadata,
            )


class SelfContainedConnector(SourceConnector):
    source_type = "test_self"
    self_contained = True

    async def validate(self) -> None:
        pass

    async def sync(self, cursor):
        from src.knowledge.connectors.base import SyncOutcome

        return SyncOutcome(records_processed=5, cursor={"page": 7})


register_connector(RowsConnector)
register_connector(SelfContainedConnector)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def context():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(uuid4(), f"Knowledge Org {uuid4().hex[:6]}")
    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(
        organization.id,
        "KB test",
        chunking_strategy="fixed",
        chunk_size=500,
        chunk_overlap=50,
    )
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        organization.id, "src-rows", "test_rows", knowledge_base_id=kb.id
    )
    return {
        "organization": organization,
        "kb": kb,
        "source": source,
        "kb_repo": kb_repo,
        "source_repo": source_repo,
    }


def build_engine(backoff_base: int = 1) -> KnowledgeIngestionEngine:
    return KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=FakeVectorStore(),
        embedding_provider=FakeEmbedding(),
        backoff_base_seconds=backoff_base,
        max_attempts_default=2,
    )


async def create_job(ctx) -> uuid.UUID:
    repo = PostgresIngestionJobRepository()
    job = await repo.create_job(
        ctx["organization"].id,
        job_type="sync_source:test_rows",
        source_id=ctx["source"].id,
        knowledge_base_id=ctx["kb"].id,
        max_attempts=2,
    )
    return job.id


# ---------------------------------------------------------------------------
# Retry / dead letter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_run_completes_and_indexes(context) -> None:
    engine = build_engine()
    vectors = engine._vectors
    job_id = await create_job(context)

    job = await engine.execute_job(job_id)
    assert job.status == IngestionJobStatus.COMPLETED
    assert job.records_processed == 3
    assert len(vectors.upserted) >= 3

    # registry: 3 chunks activos (un chunk por record, contenido corto)
    registry = PostgresDocumentRegistryRepository()
    stale = await registry.mark_missing_deleted(context["source"].id, {"row:0", "row:1", "row:2"})
    assert stale == []


@pytest.mark.asyncio
async def test_failed_then_dead_after_max_attempts(context) -> None:
    RowsConnector.fail = True
    try:
        engine = build_engine()
        job_id = await create_job(context)

        job = await engine.execute_job(job_id)
        assert job.status == IngestionJobStatus.FAILED
        assert job.attempts == 1
        assert job.retry_at is not None
        assert "connector configured to fail" in (job.error_summary or {}).get("error", "")

        # reintento automático del worker -> segundo intento -> dead letter
        job = await engine.execute_job(job_id)
        assert job.status == IngestionJobStatus.DEAD
        assert job.attempts == 2
        assert job.completed_at is not None

        # historial de errores persistido
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            rows = await session.execute(
                text("SELECT COUNT(*) FROM ingestion_job_errors WHERE job_id = :jid"),
                {"jid": job_id},
            )
            assert rows.scalar() == 2
        finally:
            await session.close()
    finally:
        RowsConnector.fail = False


@pytest.mark.asyncio
async def test_retry_resets_attempts(context) -> None:
    RowsConnector.fail = True
    try:
        engine = build_engine()
        repo = PostgresIngestionJobRepository()
        job_id = await create_job(context)
        await engine.execute_job(job_id)
        await repo.update_job(
            job_id, status=IngestionJobStatus.PENDING.value, attempts=0, retry_at=None
        )
        RowsConnector.fail = False
        job = await engine.execute_job(job_id)
        assert job.status == IngestionJobStatus.COMPLETED
        assert job.attempts == 1
    finally:
        RowsConnector.fail = False


# ---------------------------------------------------------------------------
# Resume (cursor) y delete detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_passes_cursor_snapshot(context) -> None:
    engine = build_engine()
    repo = PostgresIngestionJobRepository()
    job_id = await create_job(context)
    await repo.update_job(job_id, cursor_snapshot={"page": 42})
    await engine.execute_job(job_id)
    assert RowsConnector.seen_cursor == {"page": 42}
    # cursor final persistido en sync state
    state = await PostgresSyncStateRepository().get_state(context["source"].id)
    assert state is not None
    assert state.cursor == {"page": 2}


@pytest.mark.asyncio
async def test_delete_detection_removes_missing_documents(context) -> None:
    engine = build_engine()
    repo = PostgresIngestionJobRepository()

    RowsConnector.records_yielded = 3
    job_id = await create_job(context)
    await engine.execute_job(job_id)

    # segundo sync: la fuente ahora solo tiene 1 record
    RowsConnector.records_yielded = 1
    job_id = await create_job(context)
    await engine.execute_job(job_id)

    vectors = engine._vectors
    assert len(vectors.deleted_points) >= 2  # los chunks de row:1 y row:2

    registry = PostgresDocumentRegistryRepository()
    stale = await registry.mark_missing_deleted(context["source"].id, {"row:0"})
    assert stale == []
    RowsConnector.records_yielded = 3


@pytest.mark.asyncio
async def test_metadata_schema_validation_counts_failures(context) -> None:
    await context["kb_repo"].update_kb(
        context["organization"].id,
        context["kb"].id,
        metadata_schema={"fields": {"category": {"type": "str", "required": True}}},
    )
    RowsConnector.missing_metadata = True
    try:
        engine = build_engine()
        job_id = await create_job(context)
        job = await engine.execute_job(job_id)
        assert job.status == IngestionJobStatus.COMPLETED
        assert job.records_failed == 3
        assert job.records_processed == 0
    finally:
        RowsConnector.missing_metadata = False


@pytest.mark.asyncio
async def test_self_contained_connector_path(context) -> None:
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        context["organization"].id, "src-self", "test_self",
        knowledge_base_id=context["kb"].id,
    )
    engine = build_engine()
    repo = PostgresIngestionJobRepository()
    job = await repo.create_job(
        context["organization"].id,
        job_type="sync_source:test_self",
        source_id=source.id,
        knowledge_base_id=context["kb"].id,
    )
    result = await engine.execute_job(job.id)
    assert result.status == IngestionJobStatus.COMPLETED
    assert result.records_processed == 5


def test_compute_retry_delay_exponential() -> None:
    assert compute_retry_delay(1, base_seconds=10) == 10
    assert compute_retry_delay(2, base_seconds=10) == 20
    assert compute_retry_delay(3, base_seconds=10) == 40
    assert compute_retry_delay(10, base_seconds=10, cap_seconds=300) == 300
