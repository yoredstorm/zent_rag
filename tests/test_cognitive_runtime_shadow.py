# =============================================================================
# Cognitive runtime (W1/C1) — shadow: plan + strategy en el flow, sin cambiar
# la ejecución. Escenarios base del harness de evaluación.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.core.config import get_settings
from src.core.domain.entities import (
    LLMResponse,
    Organization,
    OrganizationStatus,
    RetrievalChunk,
    RetrievalContext,
)
from src.core.ports.sql_expert import SqlQueryResult


class FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

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
        return None

    async def get_list(self, key: str) -> list[str]:
        return []

    async def trim_list(self, key: str, max_items: int) -> None:
        return None

    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        return 1


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
    def __init__(self, content: str = "Respuesta generada") -> None:
        self.calls: list[dict] = []
        self.content = content

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content=self.content, model="fake-llm", total_tokens=12, latency_ms=1.0
        )


class FakeEmbed:
    async def embed(
        self, text: str | list[str], model: str | None = None
    ) -> list[float] | list[list[float]]:
        if isinstance(text, list):
            return [[0.1] * 8 for _ in text]
        return [0.1] * 8


class FakeVectorStore:
    def __init__(self, context: RetrievalContext) -> None:
        self.context = context

    async def search(self, **kwargs: Any) -> RetrievalContext:
        return self.context

    async def upsert(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def upsert_batch(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def delete_by_organization(self, organization_id: UUID) -> None:
        return None


class FakeKnowledgeModel:
    """Lookup canónico en memoria para observar runners."""

    def __init__(self, *, names=None, aliases=None, edges=None, assertions=None, boom=False):
        self.names = names or {}
        self.aliases = aliases or []
        self.edges = edges or {}
        self.assertions = assertions or {}
        self.boom = boom

    async def find_objects_by_names(self, organization_id, names, *, kinds=None, limit=20):
        if self.boom:
            raise RuntimeError("db caída")
        found = []
        for wanted in names:
            found.extend(self.names.get(wanted, []))
        return found[:limit]

    async def lookup_aliases(self, organization_id, normalized, *, limit=50):
        if self.boom:
            raise RuntimeError("db caída")
        return [row for row in self.aliases if row["normalized"] in normalized][:limit]

    async def object_edges(self, organization_id, object_id, *, limit=200):
        return {"edges": self.edges.get(str(object_id), [])[:limit]}

    async def object_assertions(self, organization_id, object_id, *, limit=100):
        return self.assertions.get(str(object_id), [])[:limit]


class FakeTabular:
    def __init__(self, answer=None):
        self.answer = answer
        self.calls = 0

    async def try_answer(self, organization_id, question, **kwargs):
        self.calls += 1
        return self.answer


class FakeKnowledgeRetriever:
    """Retriever canónico falso: registra la query y devuelve un contexto."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    async def retrieve(self, query: Any, options: Any = None) -> Any:
        from types import SimpleNamespace

        self.queries.append(str(getattr(query, "query", "")))
        return SimpleNamespace(
            context=[
                RetrievalChunk(
                    document_id=uuid4(),
                    content="Registro 1 OPEN | Registro 2 CLOSE",
                    score=0.9,
                    metadata={"filename": "secuencia.txt"},
                )
            ],
            children=[],
            parents=[],
            retrieval_latency_ms=1.0,
        )


def _organization() -> Organization:
    return Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)


def _retrieval(*, score: float = 0.9) -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="Registro 1 OPEN | Registro 2 UPDATE | Registro 3 CLOSE",
                score=score,
                metadata={"filename": "secuencia.txt"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _build(
    *,
    organization: Organization,
    llm: FakeLLM,
    vector_store: FakeVectorStore,
    knowledge_model: Any = None,
    tabular_query: Any = None,
    tabular_sql_first: bool = True,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=vector_store,
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        knowledge_model=knowledge_model,
        tabular_query=tabular_query,
        tabular_sql_first=tabular_sql_first,
    )


def _build_knowledge(
    *,
    organization: Organization,
    llm: FakeLLM,
    retriever: FakeKnowledgeRetriever,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=FakeVectorStore(_retrieval()),
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        knowledge_retriever=retriever,
    )


async def _execute(orchestrator, organization_id: UUID, query: str):
    return await orchestrator.execute(
        organization_id=organization_id,
        user_id=uuid4(),
        query=query,
        role="admin",
        model="fake-llm",
        use_cache=False,
    )


@pytest.mark.asyncio
async def test_off_no_agrega_bloque_cognitivo(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "off")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué significa el Byte 105 de Category 31?"
    )
    assert result.flow is not None
    assert "cognitive" not in result.flow
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_traza_plan_y_strategy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué significa el Byte 105 de Category 31?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["mode"] == "shadow"
    assert "exact_lookup" in cognitive["plan"]["needs"]
    assert "vector" in [
        item["representation"] for item in cognitive["strategy"]["representations"]
    ]
    assert cognitive["strategy"]["scope"]["organization_id"] == str(organization.id)
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_saludo_no_requiere_conocimiento(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(orchestrator, organization.id, "Hola, buenos días")
    cognitive = result.flow["cognitive"]
    assert cognitive["plan"]["needs"] == ["no_retrieval"]
    assert cognitive["plan"]["requires_knowledge"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected_need"),
    [
        ("¿Qué cambió en la regla X respecto a la versión anterior?", "temporal_lookup"),
        ("Compara el total de la columna 7 entre 2024 y 2025", "comparison"),
        ("¿Aplica la regla 12 para este caso?", "rule_lookup"),
    ],
)
async def test_shadow_escenarios(monkeypatch, query: str, expected_need: str) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(orchestrator, organization.id, query)
    assert expected_need in result.flow["cognitive"]["plan"]["needs"]


@pytest.mark.asyncio
async def test_shadow_reconstruye_strategy_con_el_plan_del_retriever(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    retriever = FakeKnowledgeRetriever()
    orchestrator = _build_knowledge(
        organization=organization, llm=FakeLLM(), retriever=retriever
    )
    query = "¿Qué cambió en la regla X respecto a la versión anterior?"
    result = await _execute(orchestrator, organization.id, query)
    assert retriever.queries and retriever.queries[0] == query
    from src.rag.retrieval.planner import KnowledgeRetrievalPlanner
    from src.runtime.knowledge_strategy import build_knowledge_strategy

    expected = build_knowledge_strategy(
        KnowledgeRetrievalPlanner().plan(query),
        organization_id=str(organization.id),
        role="admin",
    )
    assert result.flow["cognitive"]["strategy"] == expected.to_public_dict()


@pytest.mark.asyncio
async def test_shadow_plan_falla_no_rompe_el_run(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("plan roto")

    monkeypatch.setattr("src.runtime.cognitive_plan.build_cognitive_plan", _boom)
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(orchestrator, organization.id, "¿Qué significa el Byte 105?")
    assert len(llm.calls) == 1
    assert "cognitive" not in (result.flow or {})


@pytest.mark.asyncio
async def test_shadow_resuelve_entidades_y_traza_grafo(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={
            "category 31": [
                {
                    "id": canonical_id,
                    "kind": "entity",
                    "name": "Category 31",
                    "display_name": "Category 31",
                    "confidence": 0.9,
                }
            ]
        },
        edges={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_name": "Category 31",
                    "predicate": "requires",
                    "object_name": "Record 4",
                    "confidence": 0.8,
                }
            ]
        },
    )
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=model,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["entities"]["resolved"] is True
    graph = [r for r in cognitive["runners"] if r["representation"] == "graph"]
    assert graph and graph[0]["status"] == "ok"
    assert len(llm.calls) == 1  # observación: la generación no cambió


@pytest.mark.asyncio
async def test_shadow_runner_temporal(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={
            "category 31": [
                {
                    "id": canonical_id,
                    "kind": "entity",
                    "name": "Category 31",
                    "display_name": "Category 31",
                    "confidence": 0.9,
                }
            ]
        },
        assertions={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_label": "Category 31",
                    "predicate": "valid_for",
                    "object_value": "2024",
                    "confidence": 0.9,
                    "valid_from": "2024-01-01T00:00:00+00:00",
                    "valid_to": "2025-01-01T00:00:00+00:00",
                }
            ]
        },
    )
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=model,
    )
    result = await _execute(
        orchestrator, organization.id, "¿La Category 31 sigue vigente?"
    )
    temporal = [
        r for r in result.flow["cognitive"]["runners"]
        if r["representation"] == "temporal"
    ]
    assert temporal and temporal[0]["items"][0]["refs"]["validity"] == "historical"


@pytest.mark.asyncio
async def test_shadow_runner_tabular(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    answer = SqlQueryResult(
        sql="SELECT sum(col7) FROM t",
        columns=["total"],
        rows=[["1284"]],
        row_count=1,
        metadata={"table": "sheet_1"},
    )
    tabular = FakeTabular(answer)
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
        tabular_query=tabular,
        tabular_sql_first=False,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Cuál es el total de la columna 7?"
    )
    structured = [
        r for r in result.flow["cognitive"]["runners"]
        if r["representation"] == "structured"
    ]
    assert structured and structured[0]["status"] == "ok"
    assert tabular.calls == 1


@pytest.mark.asyncio
async def test_observacion_no_duplica_tabular_productivo(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    tabular = FakeTabular(
        SqlQueryResult(sql="SELECT 1", columns=["total"], rows=[["1"]], row_count=1)
    )
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
        tabular_query=tabular,
    )
    result = await _execute(
        orchestrator, organization.id, "¿Cuál es el total de la columna 7?"
    )
    runners = result.flow["cognitive"]["runners"]
    assert all(r["representation"] != "structured" for r in runners)


@pytest.mark.asyncio
async def test_shadow_observacion_falla_no_rompe_el_run(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        vector_store=FakeVectorStore(_retrieval()),
        knowledge_model=FakeKnowledgeModel(boom=True),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué relación tiene Category 31 con Record 4?"
    )
    cognitive = result.flow["cognitive"]
    assert cognitive["entities"] is None
    assert all(
        runner["status"] in {"skipped", "error"} for runner in cognitive["runners"]
    )
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_shadow_expone_signals(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "shadow")
    organization = _organization()
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        vector_store=FakeVectorStore(_retrieval()),
    )
    result = await _execute(
        orchestrator, organization.id, "¿Qué significa el Byte 105?"
    )
    signals = result.flow["cognitive"]["signals"]
    assert signals["exact_lookup_declared"] is True
    assert signals["entity_resolved"] is None
