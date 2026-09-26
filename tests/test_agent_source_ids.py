# =============================================================================
# Agent source_ids — adjunto de fuentes, snapshot, purpose, retrieval
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.agents.runtime.agent_runtime import (
    AgentRunRequest,
    AgentRuntime,
    compose_agent_instructions,
)
from src.agents.tools.base import ToolContext
from src.core.domain.entities import Agent, RetrievalChunk, RetrievalContext
from src.platform.deployments.versions import snapshot_agent
from src.rag.retrieval.models import RetrievalQuery

ORG = UUID("00000000-0000-0000-0000-000000000001")


def _agent(**overrides) -> Agent:
    base = dict(
        id=UUID("10000000-0000-0000-0000-000000000001"),
        organization_id=ORG,
        name="Gizmo",
        system_prompt="Habla como RRHH.",
        tools=["search_knowledge"],
        model="zent-default",
        config_json={
            "purpose": "Responder dudas de RRHH",
            "source_ids": [UUID("30000000-0000-0000-0000-000000000001")],
            "knowledge_base_ids": [UUID("20000000-0000-0000-0000-000000000001")],
        },
    )
    base.update(overrides)
    return Agent(**base)


def test_compose_agent_instructions_prepends_purpose() -> None:
    text = compose_agent_instructions(_agent())
    assert "## Purpose" in text
    assert "Responder dudas de RRHH" in text
    assert "Habla como RRHH." in text


def test_compose_agent_instructions_without_purpose_keeps_prompt() -> None:
    text = compose_agent_instructions(_agent(config_json={}, system_prompt="Solo esto"))
    assert text == "Solo esto"
    assert "## Purpose" not in text


def test_snapshot_includes_source_ids() -> None:
    snapshot = snapshot_agent(_agent())
    assert snapshot["config"]["source_ids"] == [
        "30000000-0000-0000-0000-000000000001"
    ]


def test_qdrant_filter_matches_any_source_id() -> None:
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    s1 = uuid4()
    s2 = uuid4()
    qfilter = store._build_qdrant_filter(
        ORG, None, None, "admin", None, source_ids=[s1, s2]
    )
    source_cond = next(
        c
        for c in qfilter.must
        if getattr(c, "key", None) == "metadata.source_id"
    )
    assert set(source_cond.match.any) == {str(s1), str(s2)}


@pytest.mark.asyncio
async def test_search_knowledge_filters_to_source_ids() -> None:
    from src.agents.tools.tools_builtin import SearchKnowledgeTool

    captured: list[RetrievalQuery] = []
    source_id = uuid4()

    class _FakeRetriever:
        async def retrieve(self, query: RetrievalQuery):
            captured.append(query)
            return RetrievalContext(
                chunks=[
                    RetrievalChunk(
                        document_id=uuid4(),
                        content="política de vacaciones",
                        score=0.9,
                        metadata={"source_id": str(source_id)},
                    )
                ]
            )

    class _StubEmbedder:
        async def embed(self, text, model=None):
            return [0.1, 0.2, 0.3]

    tool = SearchKnowledgeTool(_FakeRetriever(), embedder=_StubEmbedder())
    ctx = ToolContext(
        tenant_id=ORG,
        org_config={"source_ids": [str(source_id)]},
    )
    result = await tool.execute(ctx, {"query": "vacaciones"})
    assert result.error is None
    assert captured
    assert captured[0].source_ids == [source_id]
    assert source_id.hex in result.output.replace("-", "") or str(source_id) in result.output
    assert result.meta.get("source_ids") == [str(source_id)]


@pytest.mark.asyncio
async def test_search_knowledge_embeds_query_before_retrieve() -> None:
    from src.agents.tools.tools_builtin import SearchKnowledgeTool

    captured: dict = {}

    class _Embedder:
        async def embed(self, text, model=None):
            captured["text"] = text
            return [0.1, 0.2, 0.3]

    class _FakeRetriever:
        async def retrieve(self, query: RetrievalQuery):
            captured["embedding"] = query.query_embedding
            if query.query_embedding is None:
                raise ValueError("VectorRetriever requires query_embedding")
            return RetrievalContext(chunks=[])

    tool = SearchKnowledgeTool(_FakeRetriever(), embedder=_Embedder())
    ctx = ToolContext(tenant_id=ORG, org_config={"source_ids": [str(uuid4())]})
    result = await tool.execute(ctx, {"query": "gerente"})
    assert result.error is None
    assert captured["text"] == "gerente"
    assert captured["embedding"] == [0.1, 0.2, 0.3]
    assert result.output == "(no results)"


@pytest.mark.asyncio
async def test_search_knowledge_without_sources_does_not_scan_org() -> None:
    from src.agents.tools.tools_builtin import SearchKnowledgeTool

    called = {"n": 0}

    class _FakeRetriever:
        async def retrieve(self, query: RetrievalQuery):
            called["n"] += 1
            return RetrievalContext(chunks=[])

    tool = SearchKnowledgeTool(_FakeRetriever())
    ctx = ToolContext(tenant_id=ORG, org_config={})
    result = await tool.execute(ctx, {"query": "cualquier cosa"})
    assert called["n"] == 0
    assert result.output == "(no results)"


@pytest.mark.asyncio
async def test_runtime_injects_source_ids_into_org_config() -> None:
    from src.agents.tools.registry import register_tool
    from src.core.domain.entities import LLMResponse
    from src.core.ports import LLMProvider
    from tests.test_agent_runtime import _agent as runtime_agent
    from tests.test_agent_runtime import _EchoTool

    echo = _EchoTool()
    register_tool(echo)
    prompts: list[str] = []

    class _CaptureLLM(LLMProvider):
        def __init__(self) -> None:
            self.calls = 0
            self.contents = [
                '{"tool": "echo", "arguments": {"text": "x"}}',
                '{"answer": "listo"}',
            ]

        async def generate(self, prompt: str, **kwargs) -> LLMResponse:
            prompts.append(prompt)
            idx = min(self.calls, len(self.contents) - 1)
            self.calls += 1
            return LLMResponse(
                content=self.contents[idx],
                model="fake",
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            )

        async def generate_stream(self, *args, **kwargs):  # pragma: no cover
            raise NotImplementedError

        async def embed(self, text, model=None):  # pragma: no cover
            raise NotImplementedError

        async def rerank(self, query, documents, model=None, top_n=None):  # pragma: no cover
            return []

    source_id = uuid4()
    agent = runtime_agent(
        tools=["echo"],
        config_json={"source_ids": [str(source_id)], "purpose": "Inventario"},
        system_prompt="Sé breve.",
    )
    runtime = AgentRuntime(llm_provider=_CaptureLLM())
    await runtime.run(
        AgentRunRequest(
            agent=agent, message="cuentame sobre el record 4", role="admin"
        )
    )
    assert echo.calls
    assert echo.calls[0].org_config.get("source_ids") == [str(source_id)]
    assert prompts
    assert "Inventario" in prompts[0]
    assert "Sé breve." in prompts[0]


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"src-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }


@pytest.mark.asyncio
async def test_create_agent_persists_source_ids_and_derives_kbs(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Agent Sources Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"kb-{uuid4().hex[:8]}"},
        headers=headers,
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    source = await async_client.post(
        "/api/v1/sources",
        json={
            "name": f"src-{uuid4().hex[:8]}",
            "type": "web",
            "knowledge_base_id": kb_id,
            "config": {"url": "https://example.com"},
        },
        headers=headers,
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    create = await async_client.post(
        "/api/v1/agents",
        json={
            "name": f"agent-{uuid4().hex[:8]}",
            "tools": ["search_knowledge"],
            "config": {"purpose": "RRHH", "source_ids": [source_id]},
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    config = create.json()["config"]
    assert config["source_ids"] == [source_id]
    assert config["knowledge_base_ids"] == [kb_id]
    assert config["purpose"] == "RRHH"


@pytest.mark.asyncio
async def test_update_rejects_foreign_source_ids(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "Agent Src Org A")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b = await _create_org(async_client, "Agent Src Org B")
    org_b["session"] = await _owner_session(org_b["organization_id"])

    source = await async_client.post(
        "/api/v1/sources",
        json={
            "name": f"a-src-{uuid4().hex[:8]}",
            "type": "web",
            "config": {"url": "https://example.com"},
        },
        headers=_headers(org_a),
    )
    assert source.status_code == 201, source.text
    foreign_source = source.json()["id"]

    create = await async_client.post(
        "/api/v1/agents",
        json={"name": f"agent-b-{uuid4().hex[:8]}", "tools": ["search_knowledge"]},
        headers=_headers(org_b),
    )
    assert create.status_code == 201, create.text
    agent_id = create.json()["id"]

    update = await async_client.put(
        f"/api/v1/agents/{agent_id}",
        json={"config": {"source_ids": [foreign_source]}},
        headers=_headers(org_b),
    )
    assert update.status_code in (400, 404), update.text


def test_agent_config_accepts_500_source_ids() -> None:
    from src.api.routes.agents import AgentConfig

    ids = [uuid4() for _ in range(500)]
    cfg = AgentConfig(source_ids=ids)
    assert len(cfg.source_ids) == 500


def test_agent_config_rejects_501_source_ids_with_spanish_message() -> None:
    from pydantic import ValidationError

    from src.api.routes.agents import AgentConfig

    ids = [uuid4() for _ in range(501)]
    with pytest.raises(ValidationError) as exc:
        AgentConfig(source_ids=ids)
    assert "Un agente admite como máximo 500 fuentes." in str(exc.value)
