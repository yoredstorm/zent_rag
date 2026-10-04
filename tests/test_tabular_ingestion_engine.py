# =============================================================================
# Knowledge Tabular — end-to-end por el engine (Excel real como DATOS)
# =============================================================================
# Repos Postgres reales; vector store y embeddings falsos. Verifica:
#   - el archivo entra como UN documento (estructura fila/columna en tabular_*);
#   - V2 persiste StructuredDocument + representación estructurada tabular;
#   - dual indexing con metadata jerárquica y point keys deterministas;
#   - incremental: re-sync sin cambios NO re-embebe tablas; cambio de una fila
#     re-embebe solo esa tabla;
#   - aislamiento por organización.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import IngestionJobStatus
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
from src.infrastructure.postgres.structured_documents import (
    PostgresStructuredDocumentRepository,
)
from src.infrastructure.postgres.tabular import PostgresTabularRepository
from src.knowledge.engine.service import KnowledgeIngestionEngine
from tests import tabular_fixtures as fx


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserted: list[tuple] = []
        self.deleted_points: list[str] = []
        self.deleted_v2_documents: list[tuple] = []
        self.deleted_v2_tables: list[tuple] = []

    async def search(self, *args, **kwargs):
        raise NotImplementedError

    async def upsert(self, *args, **kwargs) -> None:
        self.upserted.append(args)

    async def upsert_batch(
        self, organization_id, points, knowledge_base_id=None, workspace_id=None,
        sparse_texts=None,
    ) -> None:
        self.upserted.extend(
            (organization_id, point, knowledge_base_id) for point in points
        )

    async def delete_by_organization(self, organization_id) -> None:
        pass

    async def delete_by_knowledge_base(self, organization_id, kb_id) -> None:
        pass

    async def delete_points(self, organization_id, point_ids) -> None:
        self.deleted_points.extend(point_ids)

    async def delete_v2_document(self, organization_id, document_id) -> None:
        self.deleted_v2_documents.append((organization_id, document_id))

    async def delete_v2_tables(self, organization_id, document_id, table_ids) -> None:
        self.deleted_v2_tables.append((organization_id, str(document_id), list(table_ids)))

    async def delete_stale_v2_documents(self, organization_id, source_id, keep) -> None:
        pass

    def tabular_points(self) -> list:
        return [
            point
            for _org, point, _kb in self.upserted
            if (point[3] or {}).get("v2_tabular") == "true"
        ]


class FakeEmbedding:
    async def embed(self, texts, model=None):
        if isinstance(texts, list):
            return [[0.1] * 8 for _ in texts]
        return [0.1] * 8


def build_engine(vectors: FakeVectorStore) -> KnowledgeIngestionEngine:
    return KnowledgeIngestionEngine(
        job_repo=PostgresIngestionJobRepository(),
        sync_state_repo=PostgresSyncStateRepository(),
        doc_registry_repo=PostgresDocumentRegistryRepository(),
        kb_repo=PostgresKnowledgeBaseRepository(),
        source_repo=PostgresSourceRepository(),
        vector_store=vectors,
        embedding_provider=FakeEmbedding(),
        structured_doc_repo=PostgresStructuredDocumentRepository(),
        tabular_repo=PostgresTabularRepository(),
        backoff_base_seconds=1,
        max_attempts_default=2,
    )


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "KNOWLEDGE_QUEUE_KEY", f"test:{uuid4().hex}")
    return settings


@pytest.fixture
async def ctx(isolated_settings):
    from src.knowledge.storage import store_upload

    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"Tabular Engine {uuid4().hex[:6]}"
    )
    other = await org_repo.create_organization(
        uuid4(), f"Tabular Other {uuid4().hex[:6]}"
    )
    kb_repo = PostgresKnowledgeBaseRepository()
    kb = await kb_repo.create_kb(
        organization.id,
        "KB tabular",
        chunking_strategy="fixed",
        chunk_size=500,
        chunk_overlap=50,
    )
    object_key = store_upload(
        organization.id, "ATPCO_TEST.xlsx", fx.atpco_workbook_bytes()
    )
    source_repo = PostgresSourceRepository()
    source = await source_repo.create_source(
        organization.id,
        "ATPCO_TEST.xlsx",
        "excel",
        knowledge_base_id=kb.id,
        config_json={"object_key": object_key, "filename": "ATPCO_TEST.xlsx"},
    )

    async def replace_upload(data: bytes) -> None:
        from src.knowledge.storage import resolve_path

        resolve_path(organization.id, object_key).write_bytes(data)

    return {
        "organization": organization,
        "other": other,
        "kb": kb,
        "source": source,
        "object_key": object_key,
        "replace_upload": replace_upload,
    }


async def run_engine(ctx, vectors) -> None:
    repo = PostgresIngestionJobRepository()
    job = await repo.create_job(
        ctx["organization"].id,
        job_type="sync_source:excel",
        source_id=ctx["source"].id,
        knowledge_base_id=ctx["kb"].id,
        max_attempts=2,
    )
    engine = build_engine(vectors)
    result = await engine.execute_job(job.id)
    assert result.status == IngestionJobStatus.COMPLETED, result.error_summary
    return result


async def test_excel_single_path_structure_and_tabular(ctx) -> None:
    # Instancia el fixture de forma explícita para mantener el nombre claro.
    context = ctx
    vectors = FakeVectorStore()
    result = await run_engine(context, vectors)

    # Un archivo = un documento. La estructura fila/columna NO viaja como
    # records de texto: vive en la representación tabular.
    assert result.records_processed == 1

    # Documento estructurado con esqueleto tabular.
    structured_repo = PostgresStructuredDocumentRepository()
    documents = await structured_repo.list_documents(
        context["organization"].id, context["source"].id
    )
    assert len(documents) == 1
    assert documents[0]["metadata"].get("tabular") is True
    assert documents[0]["table_count"] == 1

    # Representación estructurada: tabla + filas con valores exactos.
    tabular_repo = PostgresTabularRepository()
    tables = await tabular_repo.list_tables(
        context["organization"].id, context["source"].id
    )
    assert len(tables) == 1
    table = tables[0]
    assert table["name"] == "ATPCO RECORD 2 RULES"
    rows = await tabular_repo.fetch_rows(context["organization"].id, UUID(table["id"]))
    assert [row["physical_row"] for row in rows] == [5, 6, 7, 8]
    carrier = next(row for row in rows if row["values"]["field_name"] == "Carrier Code")
    assert carrier["values"]["start_position"] == "28"
    assert carrier["values"]["end_position"] == "29"
    assert carrier["values"]["length"] == "2"

    # Representación semántica: chunks multinivel con metadata jerárquica.
    points = vectors.tabular_points()
    assert points, "no se indexaron chunks tabulares"
    levels = {int(point[3]["level"]) for point in points}
    assert {0, 1, 2, 3, 4}.issubset(levels)

    row_points = [point for point in points if point[3]["knowledge_type"] == "table_row"]
    assert len(row_points) == 4
    carrier_point = next(
        point for point in row_points if point[3]["physical_row"] == 5
    )
    metadata = carrier_point[3]
    assert metadata["table_name"] == "ATPCO RECORD 2 RULES"
    assert metadata["sheet"] == "Record2"
    assert metadata["workbook"] == "ATPCO_TEST.xlsx"
    assert metadata["v2_chunk"] == "true"
    assert metadata["v2_parent"] == "false"
    assert metadata["v2_doc"] == "true"
    assert metadata["columns"][:2] == ["field_name", "start_position"]
    assert metadata["values"]["start_position"] == "28"
    assert carrier_point[2].count("Carrier Code") >= 1
    # El upsert siempre va scoped a la organización del job (tenant isolation).
    tabular_org_ids = {
        str(entry[0])
        for entry in vectors.upserted
        if (entry[1][3] or {}).get("v2_tabular") == "true"
    }
    assert tabular_org_ids == {str(context["organization"].id)}

    parent_points = [point for point in points if point[3]["v2_parent"] == "true"]
    assert len(parent_points) == 3  # workbook + sheet + schema
    schema_point = next(
        point for point in parent_points if point[3]["knowledge_type"] == "table_schema"
    )
    from src.knowledge.tabular.ids import point_id_for

    assert carrier_point[3]["parent_id"] == str(
        point_id_for(schema_point[3]["point_key"])
    )
    assert carrier_point[3]["schema_id"] == carrier_point[3]["parent_id"]

    # Aislamiento: otra organización no ve la tabla.
    assert await tabular_repo.list_tables(context["other"].id) == []
    assert await tabular_repo.fetch_rows(context["other"].id, UUID(table["id"])) == []


async def test_excel_incremental_resync_skips_and_updates(ctx) -> None:
    context = ctx
    vectors = FakeVectorStore()
    await run_engine(context, vectors)
    baseline = len(vectors.tabular_points())
    assert baseline > 0

    # 1) Re-sync sin cambios → fingerprint → NO re-embebe chunks tabulares.
    await run_engine(context, vectors)
    assert len(vectors.tabular_points()) == baseline

    # 2) Cambia UNA fila → solo esa tabla se purga y se re-embebe.
    import io

    from openpyxl import load_workbook

    original = fx.atpco_workbook_bytes()

    workbook = load_workbook(io.BytesIO(original))
    sheet = workbook["Record2"]
    sheet["D6"] = 4  # Tariff Number length 3 → 4
    buffer = io.BytesIO()
    workbook.save(buffer)
    await context["replace_upload"](buffer.getvalue())

    await run_engine(context, vectors)
    assert vectors.deleted_v2_tables, "no se purgaron las tablas cambiadas"
    org_id, _document_id, table_ids = vectors.deleted_v2_tables[-1]
    assert str(org_id) == str(context["organization"].id)
    assert len(table_ids) == 1

    tabular_repo = PostgresTabularRepository()
    tables = await tabular_repo.list_tables(
        context["organization"].id, context["source"].id
    )
    rows = await tabular_repo.fetch_rows(context["organization"].id, UUID(tables[0]["id"]))
    tariff = next(row for row in rows if row["values"]["field_name"] == "Tariff Number")
    assert tariff["values"]["length"] == "4"

    # Solo la tabla cambió: el último upsert vuelve a indexar los niveles de
    # tabla (schema + row groups + rows) de la tabla afectada.
    latest = vectors.tabular_points()[baseline:]
    assert latest, "no se re-indexó la tabla cambiada"
    table_levels = [point for point in latest if int(point[3]["level"]) >= 2]
    assert table_levels
    assert all(point[3]["table_id"] for point in table_levels)


async def test_chunking_policy_change_triggers_full_reindex(ctx, monkeypatch) -> None:
    """Cambiar la política de chunking purga y re-indexa aunque el archivo no cambie."""
    from src.core.config import get_settings

    settings = get_settings()
    context = ctx

    vectors_first = FakeVectorStore()
    await run_engine(context, vectors_first)
    assert vectors_first.tabular_points()

    # Cambio de política (tamaño de grupo): los point_keys anteriores quedan
    # obsoletos → purga total del documento y re-index completo.
    monkeypatch.setattr(settings, "KNOWLEDGE_TABULAR_ROW_GROUP_SIZE", 5)
    vectors_second = FakeVectorStore()
    await run_engine(context, vectors_second)

    assert vectors_second.deleted_v2_documents, "no se purgó el documento"
    levels = {int(point[3]["level"]) for point in vectors_second.tabular_points()}
    assert {0, 1, 2, 3, 4}.issubset(levels)
