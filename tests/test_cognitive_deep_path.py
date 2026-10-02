# =============================================================================
# Deep path C5 — DAG cognitivo para L3+ en modo active.
# =============================================================================
from __future__ import annotations

import asyncio
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
    def __init__(self, content: str = "Respuesta legacy") -> None:
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


class FakeCognitiveService:
    def __init__(self, *, boom: bool = False) -> None:
        self.boom = boom
        self.calls: list[dict] = []

    async def create_run(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("planner caído")
        return {"run": {"id": str(uuid4())}, "tasks": [], "agents": []}


class FakeCognitiveExecutor:
    def __init__(
        self,
        *,
        answer: str | None = "Registro 1 OPEN",
        status: str = "completed",
        failure_mode: str = "",
        boom: bool = False,
    ) -> None:
        self.answer = answer
        self.status = status
        self.failure_mode = failure_mode
        self.boom = boom
        self.calls: list[dict] = []

    async def execute_run(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        if self.boom:
            raise RuntimeError("executor caído")
        plan = {"final_answer": self.answer} if self.answer else {}
        return {
            "run": {
                "id": str(kwargs.get("run_id")),
                "status": self.status,
                "failure_mode": self.failure_mode,
                "plan": plan,
            },
            "tasks": [],
            "messages": [],
            "executions": [],
            "metrics": {
                "tokens": 120,
                "cost_usd": 0.01,
                "latency_ms": 50.0,
                "llm_calls": 2,
                "has_answer": bool(self.answer),
            },
        }


def _organization() -> Organization:
    return Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)


def _retrieval() -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="Registro 1 OPEN | Registro 2 CLOSE",
                score=0.9,
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
    service: FakeCognitiveService,
    executor: FakeCognitiveExecutor,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=FakeVectorStore(_retrieval()),
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        cognitive_service=service,
        cognitive_executor=executor,
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


_L3_QUERY = "Compara el total de la columna 7 entre 2024 y 2025"


@pytest.mark.asyncio
async def test_active_l3_usa_el_dag(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    service = FakeCognitiveService()
    executor = FakeCognitiveExecutor(answer="Registro 1 OPEN")
    orchestrator = _build(
        organization=organization, llm=llm, service=service, executor=executor
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method == "cognitive_os"
    assert result.llm_response is not None
    assert result.llm_response.content == "Registro 1 OPEN"
    assert llm.calls == []  # el LLM legacy no se invoca
    cognitive = result.flow["cognitive"]
    assert cognitive["run_id"]
    assert cognitive["deep"]["metrics"]["tokens"] == 120
    assert service.calls and executor.calls


@pytest.mark.asyncio
async def test_limited_no_usa_el_dag(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "limited")
    organization = _organization()
    llm = FakeLLM()
    service = FakeCognitiveService()
    executor = FakeCognitiveExecutor()
    orchestrator = _build(
        organization=organization, llm=llm, service=service, executor=executor
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method != "cognitive_os"
    assert len(llm.calls) == 1
    assert service.calls == []


@pytest.mark.asyncio
async def test_deep_sin_respuesta_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(answer=None)
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method != "cognitive_os"
    assert len(llm.calls) == 1
    assert result.flow["cognitive"]["run_id"]


@pytest.mark.asyncio
async def test_deep_budget_limit_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(
        answer=None, status="failed", failure_mode="budget_limit"
    )
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert len(llm.calls) == 1
    assert result.flow["cognitive"]["deep"]["failure_mode"] == "budget_limit"


@pytest.mark.asyncio
async def test_deep_boom_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(boom=True),
        executor=FakeCognitiveExecutor(),
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.llm_response is not None
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_active_agrega_nota_de_limites(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(
        answer="El sistema usa blockchain cuántico."
    )
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert "Límites de esta respuesta:" in result.llm_response.content


@pytest.mark.asyncio
async def test_deep_failed_con_respuesta_parcial_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeCognitiveExecutor(
        answer="Respuesta parcial del DAG",
        status="failed",
        failure_mode="budget_limit",
    )
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert result.method != "cognitive_os"
    assert len(llm.calls) == 1
    assert result.flow["cognitive"]["deep"]["status"] == "failed"


@pytest.mark.asyncio
async def test_active_streaming_emite_nota_de_limites(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    deltas: list[str] = []

    async def _on_delta(text: str) -> None:
        deltas.append(text)

    executor = FakeCognitiveExecutor(answer="El sistema usa blockchain cuántico.")
    orchestrator = _build(
        organization=organization,
        llm=FakeLLM(),
        service=FakeCognitiveService(),
        executor=executor,
    )
    await orchestrator.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query=_L3_QUERY,
        role="admin",
        model="fake-llm",
        use_cache=False,
        on_delta=_on_delta,
    )
    assert any("Límites de esta respuesta:" in delta for delta in deltas)


class FakeTimeoutExecutor(FakeCognitiveExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.marked: list[dict] = []

    async def execute_run(self, **kwargs: Any) -> dict:
        raise asyncio.TimeoutError()

    async def mark_failed(self, **kwargs: Any) -> None:
        self.marked.append(kwargs)


@pytest.mark.asyncio
async def test_deep_timeout_marca_run_failed_y_cae_a_legacy(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", "active")
    organization = _organization()
    llm = FakeLLM()
    executor = FakeTimeoutExecutor()
    orchestrator = _build(
        organization=organization,
        llm=llm,
        service=FakeCognitiveService(),
        executor=executor,
    )
    result = await _execute(orchestrator, organization.id, _L3_QUERY)
    assert len(llm.calls) == 1
    assert executor.marked and executor.marked[0]["failure_mode"] == "timeout"
    assert result.flow["cognitive"]["deep"]["failure_mode"] == "timeout"
