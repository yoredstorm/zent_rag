# =============================================================================
# Knowledge Tabular V2 — auto-ingesta al consultar (lazy) para Excel/CSV
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.postgres.relational_db import (
    PostgresKnowledgeBaseRepository,
    PostgresOrganizationRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.postgres.tabular import PostgresTabularRepository
from src.knowledge.storage import store_upload
from src.knowledge.tabular.lazy import TabularLazyIngestionService
from tests import tabular_fixtures as fx


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "KNOWLEDGE_QUEUE_KEY", f"test:{uuid4().hex}")
    monkeypatch.setattr(settings, "KNOWLEDGE_V2_ENABLED", True)
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_ENABLED", True)
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_LAZY_ENABLED", True)
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_LAZY_TIMEOUT_SECONDS", 15)
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_LAZY_MAX_SOURCES", 3)
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_LAZY_MAX_ROWS", 200)
    return settings


async def _make_source(*, ingest_something: bool = False):
    from src.infrastructure.postgres.knowledge_repos import PostgresSourceRepository

    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Tabular Lazy {uuid4().hex[:6]}"
    )
    kb = await PostgresKnowledgeBaseRepository().create_kb(
        organization.id, "KB lazy", chunking_strategy="fixed"
    )
    source_repo = PostgresSourceRepository()
    object_key = store_upload(
        organization.id, "ATPCO_TEST.xlsx", fx.atpco_workbook_bytes()
    )
    source = await source_repo.create_source(
        organization.id,
        "ATPCO_TEST.xlsx",
        "excel",
        knowledge_base_id=kb.id,
        config_json={"object_key": object_key, "filename": "ATPCO_TEST.xlsx"},
    )
    if ingest_something:
        from src.knowledge.structure import get_parser
        from src.knowledge.tabular.persistence import persist_tabular_workbook

        document = get_parser("xlsx").parse(
            fx.atpco_workbook_bytes(),
            organization_id=organization.id,
            external_id=object_key,
            source_id=source.id,
            source_name="ATPCO_TEST.xlsx",
        )
        await persist_tabular_workbook(
            PostgresTabularRepository(), document.tabular
        )
    return {"organization": organization, "kb": kb, "source": source, "object_key": object_key}


async def test_lazy_ingests_structure_and_enqueues_sync(isolated_settings) -> None:
    context = await _make_source()
    repository = PostgresTabularRepository()
    service = TabularLazyIngestionService(repository, enqueue_sync=True)

    outcome = await service.ensure_ingested(context["organization"].id)
    assert outcome.triggered is True
    assert outcome.sources_considered == 1
    assert outcome.workbooks_persisted == 1
    assert outcome.rows_persisted == 4
    assert outcome.jobs_enqueued == 1
    assert outcome.errors == []

    tables = await repository.list_tables(
        context["organization"].id, context["source"].id
    )
    assert len(tables) == 1
    rows = await repository.fetch_rows(context["organization"].id, UUID(tables[0]["id"]))
    assert [row["physical_row"] for row in rows] == [5, 6, 7, 8]

    # Job de sync encolado para completar embeddings (representación semántica).
    session = await get_async_session()
    try:
        job_count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS total FROM ingestion_jobs "
                    "WHERE organization_id = :oid AND source_id = :sid "
                    "AND job_type = :jt"
                ),
                {
                    "oid": context["organization"].id,
                    "sid": context["source"].id,
                    "jt": "sync_source:excel",
                },
            )
        ).fetchone()
    finally:
        await session.close()
    assert int(job_count.total) == 1

    # Segunda consulta: ya no hay pendientes → no re-ingesta.
    second = await service.ensure_ingested(context["organization"].id)
    assert second.triggered is False
    assert second.skipped_reason == "nothing_pending"

    # Y el query service encuentra la tabla recién ingestada por SQL-first.
    from src.knowledge.tabular.query import TabularQueryService

    result = await TabularQueryService(repository).try_answer(
        context["organization"].id, "What is the start position of Carrier Code?"
    )
    assert result is not None
    assert result.rows == [["Carrier Code", "28"]]


async def test_lazy_respects_disabled_flag(isolated_settings, monkeypatch) -> None:
    context = await _make_source()
    monkeypatch.setattr(isolated_settings, "KNOWLEDGE_TABULAR_LAZY_ENABLED", False)
    service = TabularLazyIngestionService(PostgresTabularRepository())

    outcome = await service.ensure_ingested(context["organization"].id)
    assert outcome.triggered is False
    assert outcome.skipped_reason == "lazy_disabled"
    assert await PostgresTabularRepository().list_tables(
        context["organization"].id, context["source"].id
    ) == []


async def test_lazy_skips_already_ingested_source(isolated_settings) -> None:
    context = await _make_source(ingest_something=True)
    service = TabularLazyIngestionService(PostgresTabularRepository())
    outcome = await service.ensure_ingested(context["organization"].id)
    assert outcome.triggered is False
    assert outcome.skipped_reason == "nothing_pending"
