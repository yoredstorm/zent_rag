# =============================================================================
# C9 — Harness de escenarios cognitivos (14). Determinista, sin DB ni red.
# =============================================================================
# Cada escenario declara: id, query, modo, fakes extra y asserts. El test
# parametrizado corre el runtime real con fakes mínimos y valida la traza
# publicada (flow["cognitive"]), el método y las llamadas al LLM legacy.
# =============================================================================
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# Fakes mínimos (mismo patrón que runtime_shadow/deep_path, sin importarlos)
# ---------------------------------------------------------------------------
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


class FakeKnowledgeModel:
    """Lookup canónico en memoria para observar runners."""

    def __init__(self, *, names=None, aliases=None, edges=None, assertions=None):
        self.names = names or {}
        self.aliases = aliases or []
        self.edges = edges or {}
        self.assertions = assertions or {}

    async def find_objects_by_names(
        self, organization_id, names, *, kinds=None, limit=20, source_ids=None
    ):
        found = []
        for wanted in names:
            found.extend(self.names.get(wanted, []))
        return found[:limit]

    async def lookup_aliases(
        self, organization_id, normalized, *, limit=50, source_ids=None
    ):
        return [row for row in self.aliases if row["normalized"] in normalized][:limit]

    async def object_edges(
        self, organization_id, object_id, *, limit=200, source_ids=None
    ):
        return {"edges": self.edges.get(str(object_id), [])[:limit]}

    async def object_assertions(
        self, organization_id, object_id, *, limit=100, source_ids=None
    ):
        return self.assertions.get(str(object_id), [])[:limit]


class FakeCognitiveService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create_run(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        return {"run": {"id": str(uuid4())}, "tasks": [], "agents": []}


class FakeCognitiveExecutor:
    def __init__(self, *, answer: str | None = "Registro 1 OPEN") -> None:
        self.answer = answer
        self.calls: list[dict] = []

    async def execute_run(self, **kwargs: Any) -> dict:
        self.calls.append(kwargs)
        plan = {"final_answer": self.answer} if self.answer else {}
        return {
            "run": {
                "id": str(kwargs.get("run_id")),
                "status": "completed",
                "failure_mode": "",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _organization() -> Organization:
    return Organization(id=uuid4(), name="Test", status=OrganizationStatus.ACTIVE)


def _chunk(
    content: str = "Registro 1 OPEN | Registro 2 CLOSE",
    *,
    document_id: UUID | None = None,
    filename: str = "secuencia.txt",
    score: float = 0.9,
) -> RetrievalChunk:
    return RetrievalChunk(
        document_id=document_id or uuid4(),
        content=content,
        score=score,
        metadata={"filename": filename},
    )


def _retrieval(*chunks: RetrievalChunk) -> RetrievalContext:
    return RetrievalContext(
        chunks=list(chunks),
        query_embedding=[0.1] * 8,
        retrieval_latency_ms=1.0,
    )


def _empty_retrieval() -> RetrievalContext:
    return RetrievalContext(chunks=[], query_embedding=[0.1] * 8, retrieval_latency_ms=1.0)


def _entity(canonical_id: str, name: str) -> dict:
    return {
        "id": canonical_id,
        "kind": "entity",
        "name": name,
        "display_name": name,
        "confidence": 0.9,
    }


@dataclass
class ScenarioEnv:
    organization: Organization
    llm: FakeLLM
    orchestrator: Any
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    id: str
    query: str
    mode: str
    build: Callable[[Organization], ScenarioEnv]
    check: Callable[[ScenarioEnv, Any], None]


def _orchestrator(
    organization: Organization,
    llm: FakeLLM,
    *,
    retrieval: RetrievalContext,
    knowledge_model: Any = None,
    cognitive_service: Any = None,
    cognitive_executor: Any = None,
):
    from src.agents.runtime.orchestrator import RAGOrchestrator

    return RAGOrchestrator(
        organization_repo=FakeOrganizationRepo(organization),
        vector_store=FakeVectorStore(retrieval),
        llm_provider=llm,
        embedding_provider=FakeEmbed(),
        cache_provider=FakeCache(),
        score_threshold=0.0,
        knowledge_model=knowledge_model,
        cognitive_service=cognitive_service,
        cognitive_executor=cognitive_executor,
    )


def _env(
    organization: Organization,
    llm: FakeLLM,
    *,
    retrieval: RetrievalContext | None = None,
    knowledge_model: Any = None,
    cognitive_service: Any = None,
    cognitive_executor: Any = None,
    extras: dict[str, Any] | None = None,
) -> ScenarioEnv:
    return ScenarioEnv(
        organization=organization,
        llm=llm,
        orchestrator=_orchestrator(
            organization,
            llm,
            retrieval=retrieval if retrieval is not None else _retrieval(_chunk()),
            knowledge_model=knowledge_model,
            cognitive_service=cognitive_service,
            cognitive_executor=cognitive_executor,
        ),
        extras=extras or {},
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


# ---------------------------------------------------------------------------
# Escenarios: build + asserts
# ---------------------------------------------------------------------------
def _build_simple_factual(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_simple_factual(env: ScenarioEnv, result: Any) -> None:
    cognitive = result.flow["cognitive"]
    assert cognitive["mode"] == "shadow"
    assert "semantic_search" in cognitive["plan"]["needs"]
    assert result.method != "cognitive_os"
    assert result.llm_response is not None
    assert result.llm_response.content == env.llm.content
    assert len(env.llm.calls) == 1


def _build_exact_literal(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_exact_literal(env: ScenarioEnv, result: Any) -> None:
    cognitive = result.flow["cognitive"]
    assert "exact_lookup" in cognitive["plan"]["needs"]
    assert "graph_traversal" in cognitive["plan"]["needs"]
    representations = [
        item["representation"] for item in cognitive["strategy"]["representations"]
    ]
    assert "exact" in representations
    assert len(env.llm.calls) == 1


def _build_structured_excel(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_structured_excel(env: ScenarioEnv, result: Any) -> None:
    needs = result.flow["cognitive"]["plan"]["needs"]
    assert "structured_query" in needs
    assert "aggregation" in needs


def _build_graph_relationship(organization: Organization) -> ScenarioEnv:
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={"category 31": [_entity(canonical_id, "Category 31")]},
        edges={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_name": "Category 31",
                    "predicate": "requires",
                    "object_name": "Record 4",
                    "relationship_type": "depends_on",
                    "confidence": 0.8,
                }
            ]
        },
    )
    return _env(
        organization,
        FakeLLM(),
        retrieval=_retrieval(_chunk()),
        knowledge_model=model,
        extras={"canonical_id": canonical_id},
    )


def _assert_graph_relationship(env: ScenarioEnv, result: Any) -> None:
    cognitive = result.flow["cognitive"]
    graph = [r for r in cognitive["runners"] if r["representation"] == "graph"]
    assert graph and graph[0]["status"] == "ok"
    assert cognitive["evidence"]["counts"].get("relation", 0) >= 1
    assert len(env.llm.calls) == 1


def _build_temporal(organization: Organization) -> ScenarioEnv:
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={"category 31": [_entity(canonical_id, "Category 31")]},
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
    return _env(
        organization,
        FakeLLM(),
        retrieval=_retrieval(_chunk()),
        knowledge_model=model,
        extras={"canonical_id": canonical_id},
    )


def _assert_temporal(env: ScenarioEnv, result: Any) -> None:
    runners = result.flow["cognitive"]["runners"]
    temporal = [r for r in runners if r["representation"] == "temporal"]
    assert temporal and temporal[0]["status"] == "ok"
    assert temporal[0]["items"][0]["refs"]["validity"] == "historical"
    assert len(env.llm.calls) == 1


def _build_conflicting_sources(organization: Organization) -> ScenarioEnv:
    canonical_id = str(uuid4())
    model = FakeKnowledgeModel(
        names={"category 31": [_entity(canonical_id, "Category 31")]},
        assertions={
            canonical_id: [
                {
                    "id": str(uuid4()),
                    "subject_label": "Rule X",
                    "predicate": "aplica",
                    "object_value": "2024",
                    "confidence": 0.9,
                    "valid_from": "2024-01-01T00:00:00+00:00",
                    "valid_to": "2025-01-01T00:00:00+00:00",
                },
                {
                    "id": str(uuid4()),
                    "subject_label": "Rule X",
                    "predicate": "aplica",
                    "object_value": "2026",
                    "confidence": 0.8,
                    "valid_from": "2026-01-01T00:00:00+00:00",
                    "valid_to": None,
                },
            ]
        },
    )
    return _env(
        organization,
        FakeLLM(),
        retrieval=_retrieval(_chunk()),
        knowledge_model=model,
        extras={"canonical_id": canonical_id},
    )


def _assert_conflicting_sources(env: ScenarioEnv, result: Any) -> None:
    evidence = result.flow["cognitive"]["evidence"]
    conflicts = evidence["conflicts"]
    assert conflicts and conflicts[0]["values"] == ["2024", "2026"]
    assert any(unit["conflict"] for unit in evidence["units"])
    assert len(env.llm.calls) == 1


def _build_insufficient_evidence(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_empty_retrieval())


def _assert_insufficient_evidence(env: ScenarioEnv, result: Any) -> None:
    cognitive = result.flow["cognitive"]
    assert result.llm_response is not None
    assert "No tengo suficiente información" in result.llm_response.content
    assert cognitive["evidence"]["count"] == 0
    assert cognitive["verification"]["action"] in {"revise", "abstain"}
    assert cognitive["verification"]["unsupported"] >= 1
    assert env.llm.calls == []  # el camino legacy responde sin generador


def _build_multi_document(organization: Organization) -> ScenarioEnv:
    retrieval = _retrieval(
        _chunk(
            "Documento uno: Registro 1 OPEN.",
            filename="uno.txt",
        ),
        _chunk(
            "Documento dos: Registro 2 CLOSE.",
            filename="dos.txt",
        ),
    )
    return _env(organization, FakeLLM(), retrieval=retrieval)


def _assert_multi_document(env: ScenarioEnv, result: Any) -> None:
    counts = result.flow["cognitive"]["evidence"]["counts"]
    assert counts.get("excerpt") == 2
    assert len(env.llm.calls) == 1


def _build_greeting_no_knowledge(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_greeting_no_knowledge(env: ScenarioEnv, result: Any) -> None:
    cognitive = result.flow["cognitive"]
    assert cognitive["plan"]["needs"] == ["no_retrieval"]
    assert cognitive["plan"]["requires_knowledge"] is False
    assert len(env.llm.calls) == 1


def _build_tool_required(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_tool_required(env: ScenarioEnv, result: Any) -> None:
    needs = result.flow["cognitive"]["plan"]["needs"]
    assert "external_tool" in needs


def _build_knowledge_and_tool(organization: Organization) -> ScenarioEnv:
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_knowledge_and_tool(env: ScenarioEnv, result: Any) -> None:
    needs = result.flow["cognitive"]["plan"]["needs"]
    assert "rule_lookup" in needs
    assert "external_tool" in needs


def _build_jev_no_intervention(organization: Organization) -> ScenarioEnv:
    # Sin preflight_hook y con RAG_JEV_PREFLIGHT_MODE=off (default) el juicio
    # previo no participa: la señal cognitiva se expone igual.
    return _env(organization, FakeLLM(), retrieval=_retrieval(_chunk()))


def _assert_jev_no_intervention(env: ScenarioEnv, result: Any) -> None:
    assert "jev_preflight" not in result.flow
    assert "signals" in result.flow["cognitive"]
    assert len(env.llm.calls) == 1


def _build_verification_failure(organization: Organization) -> ScenarioEnv:
    llm = FakeLLM(content="El sistema usa blockchain cuántico.")
    return _env(organization, llm, retrieval=_retrieval(_chunk()))


def _assert_verification_failure(env: ScenarioEnv, result: Any) -> None:
    verification = result.flow["cognitive"]["verification"]
    assert verification["action"] == "revise"
    assert verification["unsupported"] >= 1


def _build_deep_l3_active(organization: Organization) -> ScenarioEnv:
    service = FakeCognitiveService()
    executor = FakeCognitiveExecutor(answer="Registro 1 OPEN")
    return _env(
        organization,
        FakeLLM(),
        retrieval=_retrieval(_chunk()),
        cognitive_service=service,
        cognitive_executor=executor,
        extras={"service": service, "executor": executor},
    )


def _assert_deep_l3_active(env: ScenarioEnv, result: Any) -> None:
    assert result.method == "cognitive_os"
    assert result.flow["cognitive"]["run_id"]
    assert result.llm_response is not None
    assert result.llm_response.content == env.extras["executor"].answer
    assert env.llm.calls == []  # el LLM legacy no se invoca
    assert env.extras["service"].calls and env.extras["executor"].calls


# ---------------------------------------------------------------------------
# Tabla de escenarios
# ---------------------------------------------------------------------------
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "simple_factual",
        "¿Qué dice el manual sobre el registro de secuencia?",
        "shadow",
        _build_simple_factual,
        _assert_simple_factual,
    ),
    Scenario(
        "exact_literal",
        "¿Qué significa el Byte 105 de Category 31?",
        "shadow",
        _build_exact_literal,
        _assert_exact_literal,
    ),
    Scenario(
        "structured_excel",
        "¿Cuál es el total de la columna 7?",
        "shadow",
        _build_structured_excel,
        _assert_structured_excel,
    ),
    Scenario(
        "graph_relationship",
        "¿Qué relación tiene Category 31?",
        "shadow",
        _build_graph_relationship,
        _assert_graph_relationship,
    ),
    Scenario(
        "temporal",
        "¿La Category 31 sigue vigente?",
        "shadow",
        _build_temporal,
        _assert_temporal,
    ),
    Scenario(
        "conflicting_sources",
        "¿La Category 31 sigue vigente?",
        "shadow",
        _build_conflicting_sources,
        _assert_conflicting_sources,
    ),
    Scenario(
        "insufficient_evidence",
        "¿Qué significa el Byte 105?",
        "shadow",
        _build_insufficient_evidence,
        _assert_insufficient_evidence,
    ),
    Scenario(
        "multi_document",
        "¿Qué dicen los registros?",
        "shadow",
        _build_multi_document,
        _assert_multi_document,
    ),
    Scenario(
        "greeting_no_knowledge",
        "Hola, buenos días",
        "shadow",
        _build_greeting_no_knowledge,
        _assert_greeting_no_knowledge,
    ),
    Scenario(
        "tool_required",
        "Envía un correo al proveedor",
        "shadow",
        _build_tool_required,
        _assert_tool_required,
    ),
    Scenario(
        "knowledge_and_tool",
        "¿Aplica la regla 12? Envía el resultado por correo",
        "shadow",
        _build_knowledge_and_tool,
        _assert_knowledge_and_tool,
    ),
    Scenario(
        "jev_no_intervention",
        "¿Qué significa el Byte 105?",
        "shadow",
        _build_jev_no_intervention,
        _assert_jev_no_intervention,
    ),
    Scenario(
        "verification_failure",
        "¿Qué relación tiene Category 31?",
        "shadow",
        _build_verification_failure,
        _assert_verification_failure,
    ),
    Scenario(
        "deep_l3_active",
        "Compara el total de la columna 7 entre 2024 y 2025",
        "active",
        _build_deep_l3_active,
        _assert_deep_l3_active,
    ),
)


def test_harness_declara_14_escenarios() -> None:
    assert len(SCENARIOS) == 14
    assert len({scenario.id for scenario in SCENARIOS}) == 14


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
@pytest.mark.asyncio
async def test_cognitive_scenario(monkeypatch, scenario: Scenario) -> None:
    monkeypatch.setattr(get_settings(), "COGNITIVE_OS_ENABLED", scenario.mode)
    monkeypatch.setattr(get_settings(), "RAG_JEV_PREFLIGHT_MODE", "off")
    organization = _organization()
    env = scenario.build(organization)
    result = await _execute(env.orchestrator, organization.id, scenario.query)
    assert result.flow is not None
    scenario.check(env, result)
