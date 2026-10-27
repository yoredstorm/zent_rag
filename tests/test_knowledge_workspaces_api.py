# =============================================================================
# Knowledge Workspaces API — corpora V2 (Phase G UI backend)
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.core.domain.entities import TenantContext


async def test_workspace_list_and_detail(async_client, monkeypatch) -> None:
    from src.core.config import get_settings

    get_settings.cache_clear()

    # Embeddings deterministas: el chat no debe depender de credenciales LLM
    # externas (CI no tiene OPENAI_API_KEY). El retriever canónico sigue
    # corriendo real contra Qdrant con el vector del query.
    class _FakeEmbeddingProvider:
        async def embed(self, _text: str):
            return [[0.0] * 1024]

    import src.api.deps as deps

    monkeypatch.setattr(
        deps, "get_embedding_provider", lambda: _FakeEmbeddingProvider()
    )

    resp = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": "WS API Co", "email": f"ws-{uuid4().hex[:8]}@example.com"},
    )
    assert resp.status_code == 200, resp.text
    auth = resp.json()
    headers = {
        "Authorization": f"Bearer {auth['api_token']}",
        "X-Organization-Id": auth["organization_id"],
    }

    # sin corpora → lista vacía (nunca datos falsos)
    listed = await async_client.get("/api/v1/knowledge/workspaces", headers=headers)
    assert listed.status_code == 200, listed.text

    # crear uno vía API
    created = await async_client.post(
        "/api/v1/knowledge/workspaces",
        headers=headers,
        json={"name": "Operaciones Aeroméxico"},
    )
    assert created.status_code == 201, created.text
    corpus_id = created.json()["corpus"]["id"]

    detail = await async_client.get(
        f"/api/v1/knowledge/workspaces/{corpus_id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["corpus"]["name"] == "Operaciones Aeroméxico"
    assert detail.json()["sources"] == []

    listed2 = await async_client.get("/api/v1/knowledge/workspaces", headers=headers)
    assert listed2.status_code == 200
    assert len(listed2.json()["corpora"]) == 1
    assert listed2.json()["corpora"][0]["source_count"] == 0

    # otro tenant nunca ve el corpus
    other = await async_client.get(
        f"/api/v1/knowledge/workspaces/{corpus_id}",
        headers={
            "Authorization": f"Bearer {auth['api_token']}",
            "X-Organization-Id": str(uuid4()),
        },
    )
    assert other.status_code in (401, 403, 404)

    # chat grounded: el retriever canónico está siempre disponible.
    chat = await async_client.post(
        f"/api/v1/knowledge/workspaces/{corpus_id}/chat",
        headers=headers,
        json={"query": "¿Cuál es la comisión?"},
    )
    assert chat.status_code == 200, chat.text

    # studio: artefactos reales sobre el corpus.
    studio = await async_client.post(
        f"/api/v1/knowledge/workspaces/{corpus_id}/studio",
        headers=headers,
        json={"artifact": "key_facts"},
    )
    assert studio.status_code == 200, studio.text

    # sugerencias: preguntas sugeridas reales.
    suggestions = await async_client.get(
        f"/api/v1/knowledge/workspaces/{corpus_id}/suggestions",
        headers=headers,
    )
    assert suggestions.status_code == 200, suggestions.text


async def _captured_chat_role(monkeypatch, roles: set[str]) -> str:
    import src.api.deps as deps
    import src.api.routes.knowledge_workspaces as route

    organization_id = uuid4()
    workspace_id = uuid4()
    corpus_id = uuid4()
    captured: dict[str, str] = {}

    class Repo:
        async def get_corpus(self, org_id, cid):  # noqa: ANN001
            assert org_id == organization_id
            assert cid == corpus_id
            return {"id": str(cid), "workspace_id": str(workspace_id)}

    class Embedder:
        async def embed(self, text: str):  # noqa: ANN001
            return [[0.0] * 8]

    class Retriever:
        async def retrieve(self, query, options):  # noqa: ANN001
            captured["role"] = query.role
            return SimpleNamespace(context=[])

    ctx = TenantContext(
        tenant_id=organization_id,
        user_id=uuid4(),
        roles=frozenset(roles),
        permissions=frozenset({"knowledge:read"}),
        scopes=frozenset(),
    )

    async def fake_resolve(_request):
        return SimpleNamespace(id=workspace_id)

    async def fake_groups(_org, _user):
        return []

    monkeypatch.setattr(
        "src.platform.rbac.policy.require_permission", lambda *a, **k: ctx
    )
    monkeypatch.setattr(route, "resolve_workspace", fake_resolve)
    monkeypatch.setattr(route, "get_corpus_repo", lambda: Repo())
    monkeypatch.setattr(deps, "get_embedding_provider", lambda: Embedder())
    monkeypatch.setattr(deps, "get_knowledge_retriever", lambda: Retriever())
    monkeypatch.setattr("src.platform.acl.groups.user_group_names", fake_groups)

    result = await route.workspace_chat(
        corpus_id,
        route.ChatRequest(query="¿Cuál es la comisión?"),
        SimpleNamespace(state=SimpleNamespace()),
    )
    assert result["grounded"]["answer"]
    return captured["role"]


@pytest.mark.asyncio
async def test_workspace_chat_passes_reader_role_to_retrieval(monkeypatch) -> None:
    """Un reader no debe llegar al retriever como admin (bypass ACL)."""
    assert await _captured_chat_role(monkeypatch, {"reader"}) == "user"


@pytest.mark.asyncio
async def test_workspace_chat_passes_admin_role_to_retrieval(monkeypatch) -> None:
    assert await _captured_chat_role(monkeypatch, {"owner"}) == "admin"
