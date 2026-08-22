# =============================================================================
# Tests — Lazy ingestion fallback (RAG orchestrator + PostgresIngestionService)
# =============================================================================
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4, uuid5

import pytest

from src.connectors.sql.ingestion import _VECTOR_NS, PostgresIngestionService, extract_query_keywords
from src.core.config import get_settings
from src.core.domain.entities import (
    LLMResponse,
    Organization,
    OrganizationStatus,
    RetrievalChunk,
    RetrievalContext,
)
from src.core.domain.services import ColumnMeta, DataSource, IngestionResult, IngestionService
from src.core.ports.sql_expert import SqlQueryResult
from src.platform.usage.lazy_activity import lazy_log_cache_key, lazy_rows_cache_key

NO_INFO_ADMIN = "No tengo suficiente información"


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    @staticmethod
    def _hash_query(organization_id: str, query: str, model: str, role: str = "") -> str:
        return f"hash:{organization_id}:{query}:{model}:{role}"

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.store

    async def append_to_list(self, key: str, value: str, ttl_seconds: int = 3600) -> None:
        self.lists.setdefault(key, []).append(value)

    async def get_list(self, key: str) -> list[str]:
        return list(self.lists.get(key, []))

    async def trim_list(self, key: str, max_items: int) -> None:
        self.lists[key] = self.lists.get(key, [])[-max_items:]

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        current = int(self.store.get(key, 0))
        self.store[key] = str(current + by)
        return current + by


class FakeOrganizationRepo:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        return self.organization if organization_id == self.organization.id else None

    async def check_rate_limit(self, organization_id: UUID) -> bool:
        return True

    async def log_usage(self, **kwargs: Any) -> None:
        return None


class FakeLLM:
    def __init__(self, content: str = "Respuesta usando contexto lazy") -> None:
        self.calls: list[dict] = []
        self.content = content

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(content=self.content, model="fake-llm", total_tokens=12, latency_ms=1.0)


class FakeEmbed:
    async def embed(self, text: str | list[str], model: str | None = None) -> list[float] | list[list[float]]:
        if isinstance(text, list):
            return [[0.1] * 8 for _ in text]
        return [0.1] * 8


class FakeVectorStore:
    def __init__(self) -> None:
        self.search_calls: list[dict] = []
        self.search_queue: list[RetrievalContext] = []
        self.points: dict[UUID, tuple[list[float], str, dict | None]] = {}

    def enqueue_search(self, ctx: RetrievalContext) -> None:
        self.search_queue.append(ctx)

    async def search(self, **kwargs: Any) -> RetrievalContext:
        self.search_calls.append(kwargs)
        if self.search_queue:
            return self.search_queue.pop(0)
        return RetrievalContext(chunks=[], query_embedding=[0.1] * 8, retrieval_latency_ms=1.0)

    async def upsert(self, organization_id: UUID, document_id: UUID, embedding: list[float], content: str, metadata: dict | None = None) -> None:
        self.points[document_id] = (embedding, content, metadata)

    async def upsert_batch(self, organization_id: UUID, points: list) -> None:
        for doc_id, emb, content, meta in points:
            self.points[doc_id] = (emb, content, meta)

    async def delete_by_organization(self, organization_id: UUID) -> None:
        self.points.clear()


class FakeSqlExpert:
    def __init__(self, result: SqlQueryResult | None = None) -> None:
        self.result = result or SqlQueryResult(sql="", error="Cannot generate query for this question")
        self.calls = 0

    async def execute(
        self,
        organization_id: UUID,
        question: str,
        role: str,
        permissions: dict | None = None,
        user_id: UUID | None = None,
    ) -> SqlQueryResult:
        self.calls += 1
        return self.result

    async def validate_sql(self, sql: str, sources: list, role: str) -> None:
        return None


class FakeLazyIngestion(IngestionService):
    def __init__(
        self,
        result: IngestionResult | None = None,
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self.result = result
        self.delay = delay
        self.error = error

    async def discover_sources(self, organization_id: UUID) -> list[DataSource]:
        return []

    async def sync_all(self, organization_id: UUID, full_refresh: bool = False) -> IngestionResult:
        return IngestionResult(organization_id=organization_id, tables_processed=0)

    async def sync_table(
        self, organization_id: UUID, schema_name: str, table_name: str, full_refresh: bool = False
    ) -> IngestionResult:
        return IngestionResult(organization_id=organization_id, tables_processed=0)

    async def ingest_candidates(
        self,
        organization_id: UUID,
        query: str,
        role: str,
        max_tables: int,
        max_rows_per_table: int,
        timeout_seconds: int,
    ) -> IngestionResult:
        self.calls.append(
            {
                "organization_id": organization_id,
                "query": query,
                "role": role,
                "max_tables": max_tables,
                "max_rows_per_table": max_rows_per_table,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result or IngestionResult(
            organization_id=organization_id,
            tables_processed=1,
            rows_indexed=2,
            vectors_upserted=2,
            indexed_tables=["farmacia.products"],
            table_row_counts={"farmacia.products": 2},
        )


def _organization(tid: UUID | None = None) -> Organization:
    return Organization(
        id=tid or uuid4(),
        name="Test",
        status=OrganizationStatus.ACTIVE,
    )


def _empty_ctx() -> RetrievalContext:
    return RetrievalContext(chunks=[], query_embedding=[0.1] * 8, retrieval_latency_ms=1.0)


def _chunk_ctx(score: float = 0.9, content: str = "Paracetamol 500mg tabletas") -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content=content,
                score=score,
                metadata={"table_name": "products", "ingestion_mode": "lazy"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _build_orchestrator(
    *,
    organization: Organization,
    vector_store: FakeVectorStore,
    llm: FakeLLM,
    embed: FakeEmbed,
    cache: FakeCache,
    sql_expert: FakeSqlExpert | None = None,
    lazy_ingestion: IngestionService | None = None,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=vector_store,
        llm_provider=llm,
        embedding_provider=embed,
        cache_provider=cache,
        score_threshold=0.0,
        sql_expert=sql_expert,
        lazy_ingestion=lazy_ingestion,
    )


@pytest.fixture
def enable_lazy(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGESTION_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_TIMEOUT_SECONDS", 4)
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_MAX_TABLES", 5)
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_MAX_ROWS_PER_TABLE", 25)
    return settings


# -----------------------------------------------------------------------------
# Keyword extraction
# -----------------------------------------------------------------------------
def test_extract_query_keywords_drops_stopwords_and_short_tokens() -> None:
    tokens = extract_query_keywords("¿Cuál es el precio del paracetamol 500mg?")
    assert "paracetamol" in tokens
    assert "500mg" in tokens
    assert "el" not in tokens
    assert "del" not in tokens
    assert all(len(t) >= 3 for t in tokens)


# -----------------------------------------------------------------------------
# Orchestrator gates
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cached_no_info_answer_is_regenerated() -> None:
    """Una respuesta 'no tengo información' cacheada se descarta y se regenera.

    Evita que un fallo transitorio del SQL Expert sirva respuestas negativas
    obsoletas durante 5 minutos.
    """
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_chunk_ctx())
    vs.enqueue_search(_chunk_ctx())
    llm = FakeLLM(content="El producto más vendido es Paracetamol.")
    cache = FakeCache()
    key = cache._hash_query(
        str(organization.id), "cuál es el producto más vendido", "default", "admin"
    )
    cache.store[key] = json.dumps(
        "No tengo suficiente información para responder esta pregunta. "
        "¿Podrías reformularla o consultar sobre otro tema?"
    )
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=cache,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="cuál es el producto más vendido",
        use_cache=True,
    )

    assert len(llm.calls) == 1
    assert result.llm_response is not None
    assert result.llm_response.content == "El producto más vendido es Paracetamol."
    assert cache.store[key] == json.dumps("El producto más vendido es Paracetamol.")


@pytest.mark.asyncio
async def test_lazy_disabled_keeps_anti_hallucination_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG_LAZY_INGESTION_ENABLED=False → mismo mensaje de 'no tengo información'."""
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGESTION_ENABLED", False)
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion()
    llm = FakeLLM()
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del paracetamol",
        use_cache=False,
    )

    assert result.llm_response is not None
    assert NO_INFO_ADMIN in result.llm_response.content
    assert result.llm_response.model == "none"
    assert lazy.calls == []
    assert llm.calls == []
    assert result.lazy_ingested is False
    assert result.lazy_rows_indexed == 0
    assert result.lazy_tables == []


@pytest.mark.asyncio
async def test_lazy_not_triggered_when_sql_has_data(enable_lazy) -> None:
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion()
    llm = FakeLLM(content="Hay 42 ventas.")
    sql = FakeSqlExpert(
        SqlQueryResult(sql="SELECT COUNT(*) FROM sales", columns=["count"], rows=[["42"]], row_count=1)
    )
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        sql_expert=sql,
        lazy_ingestion=lazy,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="cuantas ventas hay",
        use_cache=False,
    )

    assert lazy.calls == []
    assert llm.calls
    assert result.method == "sql"
    assert result.llm_response is not None
    assert "42" in result.llm_response.content


@pytest.mark.asyncio
async def test_sql_first_prompt_excludes_vector_chunks_and_uses_temp_zero() -> None:
    poison = "POISON_DOC_PANALES_BAGO"
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_chunk_ctx(score=0.95, content=poison))
    vs.enqueue_search(_empty_ctx())
    llm = FakeLLM(content="El último producto vendido es Colágeno.")
    sql = FakeSqlExpert(
        SqlQueryResult(
            sql="SELECT p.name FROM farmacia.sales s JOIN farmacia.products p ON s.product_id = p.id LIMIT 1",
            columns=["producto"],
            rows=[["Colágeno Hidrolizado"]],
            row_count=1,
        )
    )
    cache = FakeCache()
    conversation_id = uuid4()
    conv_key = f"rag:conv:{organization.id.hex}:{conversation_id.hex}"
    await cache.append_to_list(
        conv_key,
        json.dumps({"role": "cited_chunks", "content": [poison]}),
    )
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=cache,
        sql_expert=sql,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="cuál es el último producto vendido",
        use_cache=False,
        conversation_id=conversation_id,
        temperature=0.3,
    )

    assert result.method == "sql"
    assert result.lazy_ingested is False
    assert llm.calls
    prompt = str(llm.calls[0].get("prompt") or "")
    system = str(llm.calls[0].get("system_prompt") or "")
    assert poison not in prompt
    assert poison not in system
    assert "Supplementary context from documents" not in prompt
    assert llm.calls[0].get("temperature") == 0
    assert "ÚNICA fuente" in system or "ONLY SOURCE" in prompt or "única fuente" in system.lower()


@pytest.mark.asyncio
async def test_lazy_not_triggered_when_meaningful_chunks(enable_lazy) -> None:
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_chunk_ctx(score=0.9))
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion()
    llm = FakeLLM(content="El paracetamol cuesta $1.990")
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del paracetamol",
        use_cache=False,
    )

    assert lazy.calls == []
    assert llm.calls
    assert result.llm_response is not None
    assert "paracetamol" in result.llm_response.content.lower()


@pytest.mark.asyncio
async def test_lazy_fallback_indexes_and_retries_vector_search(enable_lazy) -> None:
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_chunk_ctx(score=0.85, content="Nombre: Paracetamol. Precio: $1990."))
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion()
    llm = FakeLLM(content="El Paracetamol cuesta $1.990 [Doc: 1]")
    cache = FakeCache()
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=cache,
        lazy_ingestion=lazy,
    )

    query = "precio del paracetamol"
    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query=query,
        use_cache=False,
        role="admin",
    )

    assert len(lazy.calls) == 1
    assert lazy.calls[0]["query"] == query
    assert llm.calls
    assert result.llm_response is not None
    assert NO_INFO_ADMIN not in result.llm_response.content
    assert "Paracetamol" in result.llm_response.content
    assert result.retrieval_context is not None
    assert result.retrieval_context.chunks
    assert result.lazy_ingested is True
    assert result.lazy_rows_indexed == 2
    assert result.lazy_tables == ["products"]
    log_key = lazy_log_cache_key(organization.id)
    assert log_key in cache.lists
    assert len(cache.lists[log_key]) == 1
    event = json.loads(cache.lists[log_key][0])
    assert event["tables"] == ["products"]
    assert event["rows_indexed"] == 2
    assert event["query_preview"] == query[:80]
    assert "at" in event
    rows_key = lazy_rows_cache_key(organization.id, "farmacia", "products")
    assert cache.store[rows_key] == "2"


@pytest.mark.asyncio
async def test_lazy_no_candidates_falls_back_to_no_info(enable_lazy) -> None:
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion(
        result=IngestionResult(organization_id=organization.id, tables_processed=0, rows_indexed=0)
    )
    llm = FakeLLM()
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del unicornio espacial",
        use_cache=False,
    )

    assert lazy.calls
    assert llm.calls == []
    assert result.llm_response is not None
    assert NO_INFO_ADMIN in result.llm_response.content
    assert result.error_message is None
    assert result.lazy_ingested is False


@pytest.mark.asyncio
async def test_lazy_timeout_returns_no_info_without_raising(enable_lazy, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_TIMEOUT_SECONDS", 1)
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion(delay=5.0)
    llm = FakeLLM()
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del paracetamol",
        use_cache=False,
    )

    assert result.status.value == "completed"
    assert result.error_message is None
    assert result.llm_response is not None
    assert NO_INFO_ADMIN in result.llm_response.content
    assert llm.calls == []
    assert result.lazy_ingested is False


@pytest.mark.asyncio
async def test_lazy_exception_does_not_break_request(enable_lazy) -> None:
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    lazy = FakeLazyIngestion(error=RuntimeError("db down"))
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=FakeLLM(),
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del paracetamol",
        use_cache=False,
    )

    assert result.error_message is None
    assert result.llm_response is not None
    assert NO_INFO_ADMIN in result.llm_response.content
    assert result.lazy_ingested is False


@pytest.mark.asyncio
async def test_lazy_ingest_without_vector_hits_does_not_set_flag(enable_lazy) -> None:
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    cache = FakeCache()
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=FakeLLM(),
        embed=FakeEmbed(),
        cache=cache,
        lazy_ingestion=FakeLazyIngestion(),
    )

    result = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del paracetamol",
        use_cache=False,
    )

    assert result.lazy_ingested is False
    log_key = lazy_log_cache_key(organization.id)
    assert cache.lists.get(log_key, []) == []


# -----------------------------------------------------------------------------
# Salvaguarda anti full-scan: tablas grandes sin índice trigram (B1)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_large_table_without_trigram_index_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_MAX_TABLE_ROWS_FOR_SCAN", 100)
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())
    big_source = DataSource(
        schema_name="farmacia",
        table_name="products",
        columns=[
            ColumnMeta(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
            ColumnMeta(name="name", data_type="text", is_nullable=False),
        ],
        row_count=10_000,
    )
    queried: list[str] = []
    enqueued: list[dict] = []

    async def fake_discover(organization_id: UUID) -> list[DataSource]:
        return [big_source]

    async def fake_find(self, session, source, keywords, limit, **kwargs):  # type: ignore[no-untyped-def]
        queried.append(source.table_name)
        return [{"id": "1", "name": "x"}]

    async def fake_indexed(self, session, schema, table):  # type: ignore[no-untyped-def]
        return set()  # sin índice trigram

    async def fake_ensure(organization_id, schema, table, columns):  # type: ignore[no-untyped-def]
        enqueued.append({"organization_id": organization_id, "schema": schema, "table": table, "columns": columns})

    monkeypatch.setattr(svc, "discover_sources", fake_discover)
    monkeypatch.setattr(PostgresIngestionService, "_find_candidate_rows", fake_find)
    monkeypatch.setattr(PostgresIngestionService, "_trigram_indexed_columns", fake_indexed)
    monkeypatch.setattr(svc, "_ensure_trigram_index_background", fake_ensure)
    monkeypatch.setattr(
        "src.connectors.sql.ingestion.get_async_session",
        _dummy_async_session,
    )

    result = await svc.ingest_candidates(
        organization_id=uuid4(),
        query="paracetamol",
        role="admin",
        max_tables=5,
        max_rows_per_table=25,
        timeout_seconds=4,
    )

    assert queried == []  # nunca se escaneó la tabla grande
    assert len(enqueued) == 1  # y se encoló la creación del índice
    assert enqueued[0]["table"] == "products"
    assert "name" in enqueued[0]["columns"]


@pytest.mark.asyncio
async def test_large_table_with_trigram_index_proceeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_MAX_TABLE_ROWS_FOR_SCAN", 100)
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())
    big_source = DataSource(
        schema_name="farmacia",
        table_name="products",
        columns=[
            ColumnMeta(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
            ColumnMeta(name="name", data_type="text", is_nullable=False),
        ],
        row_count=10_000,
    )
    queried: list[str] = []

    async def fake_discover(organization_id: UUID) -> list[DataSource]:
        return [big_source]

    async def fake_find(self, session, source, keywords, limit, **kwargs):  # type: ignore[no-untyped-def]
        queried.append(source.table_name)
        return []

    async def fake_indexed(self, session, schema, table):  # type: ignore[no-untyped-def]
        return {"name"}  # índice confirmado

    monkeypatch.setattr(svc, "discover_sources", fake_discover)
    monkeypatch.setattr(PostgresIngestionService, "_find_candidate_rows", fake_find)
    monkeypatch.setattr(PostgresIngestionService, "_trigram_indexed_columns", fake_indexed)
    monkeypatch.setattr(
        "src.connectors.sql.ingestion.get_async_session",
        _dummy_async_session,
    )

    await svc.ingest_candidates(
        organization_id=uuid4(),
        query="paracetamol",
        role="admin",
        max_tables=5,
        max_rows_per_table=25,
        timeout_seconds=4,
    )

    assert queried == ["products"]


# -----------------------------------------------------------------------------
# Concurrencia: ingest_candidates simultáneos sobre la misma tabla (B5)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_candidates_concurrent_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())
    source = _products_source()
    rows = [
        {"id": "row-1", "name": "Paracetamol", "description": "500mg"},
        {"id": "row-2", "name": "Ibuprofeno", "description": "400mg"},
    ]

    async def fake_discover(organization_id: UUID) -> list[DataSource]:
        return [source]

    async def fake_find(self, session, source, keywords, limit, **kwargs):  # type: ignore[no-untyped-def]
        return rows

    async def fake_fk(self, session, source):  # type: ignore[no-untyped-def]
        return {}

    async def fake_images(self, session, schema, table):  # type: ignore[no-untyped-def]
        return {}

    monkeypatch.setattr(svc, "discover_sources", fake_discover)
    monkeypatch.setattr(PostgresIngestionService, "_find_candidate_rows", fake_find)
    monkeypatch.setattr(PostgresIngestionService, "_build_fk_resolutions", fake_fk)
    monkeypatch.setattr(PostgresIngestionService, "_load_product_images", fake_images)

    organization_id = uuid4()
    results = await asyncio.gather(
        *[
            svc.ingest_candidates(
                organization_id=organization_id,
                query="paracetamol ibuprofeno",
                role="admin",
                max_tables=5,
                max_rows_per_table=25,
                timeout_seconds=4,
            )
            for _ in range(5)
        ]
    )

    assert all(not r.errors for r in results)
    expected_ids = {
        uuid5(_VECTOR_NS, f"farmacia.products:{pk}") for pk in ("row-1", "row-2")
    }
    assert set(vs.points) == expected_ids
    for r in results:
        assert r.rows_indexed == 2


# -----------------------------------------------------------------------------
# Rate limiting de triggers por organization (B2)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lazy_rate_limited_after_max_triggers(
    enable_lazy, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_MAX_TRIGGERS_PER_HOUR", 1)
    organization = _organization()
    vs = FakeVectorStore()
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_chunk_ctx())
    lazy = FakeLazyIngestion()
    llm = FakeLLM(content="ok")
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    first = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="precio del paracetamol",
        use_cache=False,
    )
    assert len(lazy.calls) == 1
    assert first.lazy_ingested is True

    vs.enqueue_search(_empty_ctx())
    vs.enqueue_search(_empty_ctx())
    second = await orch.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="otra pregunta muy rara",
        use_cache=False,
    )

    assert len(lazy.calls) == 1  # rate limited: no segundo trigger
    assert second.lazy_ingested is False
    assert second.llm_response is not None
    assert NO_INFO_ADMIN in second.llm_response.content


# -----------------------------------------------------------------------------
# Auto-promoción de tablas tras N triggers (A2)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lazy_table_auto_promoted_after_threshold(
    enable_lazy, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_LAZY_INGEST_PROMOTE_THRESHOLD", 2)
    enqueued: list[dict] = []

    async def fake_enqueue(organization_id, schema_name=None, table_name=None, full_refresh=False):  # type: ignore[no-untyped-def]
        enqueued.append(
            {
                "organization_id": organization_id,
                "schema_name": schema_name,
                "table_name": table_name,
                "full_refresh": full_refresh,
            }
        )
        return "job-1"

    monkeypatch.setattr("src.connectors.sql.queue.enqueue_sync", fake_enqueue)

    organization = _organization()
    vs = FakeVectorStore()
    lazy = FakeLazyIngestion()
    llm = FakeLLM(content="ok")
    orch = _build_orchestrator(
        organization=organization,
        vector_store=vs,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        lazy_ingestion=lazy,
    )

    for _ in range(2):
        vs.enqueue_search(_empty_ctx())
        vs.enqueue_search(_empty_ctx())
        vs.enqueue_search(_chunk_ctx())
        result = await orch.execute(
            organization_id=organization.id,
            user_id=uuid4(),
            query="precio del paracetamol",
            use_cache=False,
        )
        assert result.lazy_ingested is True

    assert len(enqueued) == 1
    assert enqueued[0]["organization_id"] == organization.id
    assert enqueued[0]["schema_name"] == "farmacia"
    assert enqueued[0]["table_name"] == "products"


# -----------------------------------------------------------------------------
# PostgresIngestionService.ingest_candidates
# -----------------------------------------------------------------------------
class _DummyResult:
    def scalar(self) -> bool:
        return False

    def fetchall(self) -> list:
        return []

    def keys(self) -> list:
        return []


class _DummySession:
    async def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return _DummyResult()

    async def close(self) -> None:
        return None


async def _dummy_async_session() -> _DummySession:
    return _DummySession()


def _products_source() -> DataSource:
    return DataSource(
        schema_name="farmacia",
        table_name="products",
        columns=[
            ColumnMeta(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
            ColumnMeta(name="name", data_type="text", is_nullable=False),
            ColumnMeta(name="description", data_type="character varying", is_nullable=True),
        ],
        row_count=10,
        is_view=False,
    )


def _sales_source() -> DataSource:
    return DataSource(
        schema_name="farmacia",
        table_name="sales",
        columns=[
            ColumnMeta(name="id", data_type="uuid", is_nullable=False, is_primary_key=True),
            ColumnMeta(name="notes", data_type="text", is_nullable=True),
        ],
        row_count=1000,
        is_view=False,
    )


def _admin_view_source() -> DataSource:
    return DataSource(
        schema_name="farmacia",
        table_name="product_stats",
        columns=[
            ColumnMeta(name="product_name", data_type="text", is_nullable=True),
            ColumnMeta(name="total_revenue", data_type="numeric", is_nullable=True),
        ],
        row_count=50,
        is_view=True,
    )


@pytest.mark.asyncio
async def test_ingest_candidates_never_touches_skip_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "INGEST_SKIP_TABLES", "sales,product_reviews,inventory")
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())
    queried: list[str] = []

    async def fake_discover(organization_id: UUID) -> list[DataSource]:
        return [_sales_source(), _products_source()]

    async def fake_find(self, session, source, keywords, limit, **kwargs):  # type: ignore[no-untyped-def]
        queried.append(source.table_name)
        return []

    monkeypatch.setattr(svc, "discover_sources", fake_discover)
    monkeypatch.setattr(PostgresIngestionService, "_find_candidate_rows", fake_find)
    monkeypatch.setattr(
        "src.connectors.sql.ingestion.get_async_session",
        _dummy_async_session,
    )

    result = await svc.ingest_candidates(
        organization_id=uuid4(),
        query="notas de venta paracetamol",
        role="admin",
        max_tables=5,
        max_rows_per_table=25,
        timeout_seconds=4,
    )

    assert "sales" not in queried
    assert result.errors == [] or "timeout" not in ",".join(result.errors)


@pytest.mark.asyncio
async def test_ingest_candidates_timeout_swallows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())

    async def fake_discover(organization_id: UUID) -> list[DataSource]:
        await asyncio.sleep(5)
        return [_products_source()]

    monkeypatch.setattr(svc, "discover_sources", fake_discover)

    result = await svc.ingest_candidates(
        organization_id=uuid4(),
        query="paracetamol",
        role="admin",
        max_tables=5,
        max_rows_per_table=25,
        timeout_seconds=1,
    )

    assert result.rows_indexed == 0
    assert any("timeout" in e.lower() for e in result.errors)


@pytest.mark.asyncio
async def test_ingest_rows_idempotent_uuid5() -> None:
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())
    source = _products_source()
    organization_id = uuid4()
    rows = [{"id": "row-1", "name": "Paracetamol", "description": "500mg"}]

    first = await svc._ingest_rows(organization_id, source, rows, ingestion_mode="lazy")
    ids_first = set(vs.points)
    second = await svc._ingest_rows(organization_id, source, rows, ingestion_mode="lazy")

    expected = uuid5(_VECTOR_NS, "farmacia.products:row-1")
    assert expected in vs.points
    assert ids_first == set(vs.points)
    assert first.vectors_upserted >= 1
    assert second.vectors_upserted >= 1
    meta = vs.points[expected][2]
    assert meta is not None
    assert meta.get("ingestion_mode") == "lazy"
    assert meta.get("organization_id") == str(organization_id)


@pytest.mark.asyncio
async def test_ingest_candidates_customer_skips_admin_only_views(monkeypatch: pytest.MonkeyPatch) -> None:
    vs = FakeVectorStore()
    svc = PostgresIngestionService(vs, FakeEmbed(), FakeCache())
    queried: list[str] = []

    async def fake_discover(organization_id: UUID) -> list[DataSource]:
        return [_admin_view_source(), _products_source()]

    async def fake_find(self, session, source, keywords, limit, **kwargs):  # type: ignore[no-untyped-def]
        queried.append(source.table_name)
        return [{"id": "1", "name": "secret revenue"}] if source.is_view else []

    monkeypatch.setattr(svc, "discover_sources", fake_discover)
    monkeypatch.setattr(PostgresIngestionService, "_find_candidate_rows", fake_find)
    monkeypatch.setattr(
        "src.connectors.sql.ingestion.get_async_session",
        _dummy_async_session,
    )

    await svc.ingest_candidates(
        organization_id=uuid4(),
        query="ingresos totales paracetamol",
        role="customer",
        max_tables=5,
        max_rows_per_table=25,
        timeout_seconds=4,
    )

    assert "product_stats" not in queried
