# =============================================================================
# Long-Context Fase 4 — wiring en el orquestador y "Ver flujo"
# =============================================================================
# El motor corre dentro del flujo real:
#   - active: el contexto expandido reemplaza al retrieval base y el paso
#     `long_context` aparece en el flow con budget/anchors/requirements.
#   - shadow: mide y publica, pero NO altera la respuesta.
# off no es un caso de este archivo: cientos de tests legacy ya lo cubren.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.core.domain.entities import (
    LLMResponse,
    Organization,
    OrganizationStatus,
    RetrievalChunk,
    RetrievalContext,
)
from src.rag.retrieval.hybrid import HybridRetriever


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
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        return LLMResponse(
            content="Respuesta [Doc: 1]",
            model="fake-llm",
            total_tokens=12,
            latency_ms=1.0,
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

    async def get_documents_by_chunk_ids(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])

    async def get_neighborhood(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])

    async def scan_text_literal(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])

    async def scan_text(self, *args: Any, **kwargs: Any):
        return RetrievalContext(chunks=[])


def _retrieval() -> RetrievalContext:
    return RetrievalContext(
        chunks=[
            RetrievalChunk(
                document_id=uuid4(),
                content="FCLAS aparece mencionado sin explicar el resto.",
                score=0.2,
                metadata={"filename": "manual.pdf", "source_id": "s1"},
            )
        ],
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _orchestrator(store: FakeVectorStore):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(
            Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)
        ),
        vector_store=store,
        llm_provider=FakeLLM(),
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        retriever=HybridRetriever(vector_store=store),
    )


def _enable_long_context(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "RAG_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(settings, "RAG_LONG_CONTEXT_MODE", mode)
    monkeypatch.setattr(settings, "RAG_LONG_CONTEXT_MAX_EXPANSIONS", 2)
    monkeypatch.setattr(settings, "RAG_MODEL_DEFAULT_CONTEXT_WINDOW", 64000)
    monkeypatch.setattr(settings, "RAG_LONG_CONTEXT_REQUIREMENT_MIN", 0.0)


def _long_context_step(flow: Any) -> dict:
    steps = flow.get("steps") if isinstance(flow, dict) else None
    assert isinstance(steps, list)
    step = next(
        (item for item in steps if isinstance(item, dict) and item.get("type") == "long_context"),
        None,
    )
    assert step is not None, "el flow debe publicar el paso long_context"
    return step


@pytest.mark.asyncio
async def test_active_mode_applies_expanded_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_long_context(monkeypatch, "active")
    store = FakeVectorStore(_retrieval())
    orchestrator = _orchestrator(store)

    result = await orchestrator.execute(
        organization_id=orchestrator._organization_repo.organization.id,
        user_id=uuid4(),
        query="consulta si FCLAS &&&F acepta QNNF0SME",
        role="admin",
        model="fake-llm",
    )

    step = _long_context_step(result.flow)
    assert step["mode"] == "active"
    assert step["applied"] is True
    assert step["model_context_limit"] == 64000
    assert step["stop_reason"]
    assert step["anchors"]["requested"] >= 2
    assert step["requirements"]["requested"] >= 2
    assert step["timeline"], "la vista de debug del contexto debe venir en el flow"
    assert isinstance(step["headroom_tokens"], int)
    # El contexto aplicado es el empaquetado del motor.
    assert result.retrieval_context is not None
    assert result.retrieval_context.chunks
    # Paquete final de generación publicado antes de llamar al LLM.
    steps = result.flow.get("steps") if isinstance(result.flow, dict) else None
    package = next(
        (
            item
            for item in (steps or [])
            if isinstance(item, dict) and item.get("type") == "generation_package"
        ),
        None,
    )
    assert package is not None
    assert package["mode"] in ("generate", "generate_with_limits")
    assert package["citation_map"]
    # Evidencia incompleta en este corpus sintético: incertidumbre de retrieval.
    assert step["uncertainty"] == "retrieval"


@pytest.mark.asyncio
async def test_anchor_roles_step_separates_user_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La pregunta crítica: la regla completa, el valor del usuario sin exigir."""
    _enable_long_context(monkeypatch, "active")
    rule_chunk = RetrievalChunk(
        document_id=uuid4(),
        content=(
            "Record 2: FCLAS indica la clase tarifaria. La máscara &&&F exige "
            "que el fare basis tenga la longitud indicada."
        ),
        score=0.5,
        metadata={"filename": "manual.pdf", "source_id": "s1"},
    )
    store = FakeVectorStore(
        RetrievalContext(
            chunks=[rule_chunk],
            query_embedding=[0.1] * 8,
            retrieval_latency_ms=1.0,
        )
    )
    orchestrator = _orchestrator(store)

    result = await orchestrator.execute(
        organization_id=orchestrator._organization_repo.organization.id,
        user_id=uuid4(),
        query=(
            "consulta si me viene en el record 2 esto en FCLAS &&&F quiere decir "
            "que el farebasis debe ser de ese tamaño? en el boleto viene asi "
            "QNNF0SME cumplira?"
        ),
        role="admin",
        model="fake-llm",
    )

    steps = result.flow.get("steps") if isinstance(result.flow, dict) else None
    anchor_step = next(
        (
            item
            for item in (steps or [])
            if isinstance(item, dict) and item.get("type") == "anchor_roles"
        ),
        None,
    )
    assert anchor_step is not None, "Ver flujo debe publicar anchor_roles"
    assert anchor_step["rule_evidence"] == "complete"
    # FCLAS (field) + &&&F (rule) + record 2 (entidad) documentables.
    assert anchor_step["documentable_requested"] == 3
    assert anchor_step["documentable_found"] == 3
    field_values = {entry["value"] for entry in anchor_step["fields"]}
    rule_values = {entry["value"] for entry in anchor_step["rules"]}
    assert "FCLAS" in field_values
    assert "&&&F" in rule_values
    example = anchor_step["examples"][0]
    assert example["value"] == "QNNF0SME"
    assert example["requires_source_match"] is False
    assert "USER EXAMPLE QNNF0SME" in anchor_step["detail"]


@pytest.mark.asyncio
async def test_shadow_mode_does_not_alter_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_long_context(monkeypatch, "shadow")
    store = FakeVectorStore(_retrieval())
    orchestrator = _orchestrator(store)

    result = await orchestrator.execute(
        organization_id=orchestrator._organization_repo.organization.id,
        user_id=uuid4(),
        query="consulta si FCLAS &&&F acepta QNNF0SME",
        role="admin",
        model="fake-llm",
    )

    step = _long_context_step(result.flow)
    assert step["mode"] == "shadow"
    assert step["applied"] is False
    # El retrieval visible sigue siendo el original (score del retrieval base).
    assert result.retrieval_context is not None
    assert result.retrieval_context.chunks[0].score == pytest.approx(0.2)
