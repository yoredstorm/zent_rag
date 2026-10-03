# =============================================================================
# Knowledge Workspaces API — corpora V2 (Phase G UI backend)
# =============================================================================
from __future__ import annotations

from uuid import uuid4


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
