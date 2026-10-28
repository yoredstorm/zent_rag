# =============================================================================
# P18.1-01 — Aislamiento efectivo del corpus en Preguntar
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from src.core.domain.entities import TenantContext


def _ctx(*, admin: bool = False) -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        roles=frozenset({"owner"} if admin else {"reader"}),
        permissions=frozenset({"knowledge:read"}),
        scopes=frozenset(),
    )


def _rig(
    monkeypatch,
    *,
    corpus_workspace,
    sources_by_corpus,
    ctx=None,
    viewer_workspace=None,
):
    import src.api.deps as deps
    import src.api.routes.knowledge_workspaces as route

    ctx = ctx or _ctx()
    workspace_id = viewer_workspace or corpus_workspace or uuid4()
    captured: dict = {}

    class Repo:
        async def get_corpus(self, org_id, cid):  # noqa: ANN001
            assert org_id == ctx.organization_id
            return {
                "id": str(cid),
                "workspace_id": str(corpus_workspace or workspace_id),
            }

    class Embedder:
        async def embed(self, _text):  # noqa: ANN001
            return [[0.0] * 8]

    class Retriever:
        async def retrieve(self, query, _options):  # noqa: ANN001
            captured["query"] = query
            return SimpleNamespace(context=(), retrieval_latency_ms=1.0)

    async def fake_workspace(_request):
        return SimpleNamespace(id=workspace_id)

    async def fake_sources(_org, cid, **_kwargs):  # noqa: ANN001
        return sources_by_corpus.get(str(cid), [])

    async def fake_groups(_org, _user):
        return []

    monkeypatch.setattr(
        "src.platform.rbac.policy.require_permission", lambda *a, **k: ctx
    )
    monkeypatch.setattr(route, "resolve_workspace", fake_workspace)
    monkeypatch.setattr(route, "get_corpus_repo", lambda: Repo())
    monkeypatch.setattr(route, "_sources_for_corpus", fake_sources)
    monkeypatch.setattr(deps, "get_embedding_provider", lambda: Embedder())
    monkeypatch.setattr(deps, "get_knowledge_retriever", lambda: Retriever())
    monkeypatch.setattr("src.platform.acl.groups.user_group_names", fake_groups)
    return route, ctx, workspace_id, captured


def _source(workspace_id, status="indexed"):
    return {
        "id": str(uuid4()),
        "name": "doc.pdf",
        "type": "file",
        "status": status,
        "workspace_id": str(workspace_id),
        "object_key": None,
    }


async def _chat(route, corpus_id, body):
    return await route.workspace_chat(
        corpus_id,
        body,
        SimpleNamespace(state=SimpleNamespace()),
    )


@pytest.mark.asyncio
async def test_chat_without_source_ids_restricts_to_corpus(monkeypatch) -> None:
    corpus_id = uuid4()
    other_corpus = uuid4()
    workspace = uuid4()
    own = _source(workspace)
    other = _source(workspace)
    route, _ctx_, _ws, captured = _rig(
        monkeypatch,
        corpus_workspace=workspace,
        sources_by_corpus={
            str(corpus_id): [own],
            str(other_corpus): [other],
        },
    )

    await _chat(route, corpus_id, route.ChatRequest(query="¿Qué dice?"))

    assert [str(value) for value in captured["query"].source_ids] == [own["id"]]
    assert str(other["id"]) not in {
        str(value) for value in captured["query"].source_ids
    }


@pytest.mark.asyncio
async def test_chat_rejects_mixed_corpus_source_ids(monkeypatch) -> None:
    corpus_id = uuid4()
    workspace = uuid4()
    own = _source(workspace)
    foreign = _source(workspace)
    route, _ctx_, _ws, _captured = _rig(
        monkeypatch,
        corpus_workspace=workspace,
        sources_by_corpus={str(corpus_id): [own]},
    )

    with pytest.raises(HTTPException) as exc:
        await _chat(
            route,
            corpus_id,
            route.ChatRequest(
                query="¿Qué dice?",
                source_ids=[UUID(own["id"]), UUID(foreign["id"])],
            ),
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_empty_corpus_never_queries_global_scope(monkeypatch) -> None:
    corpus_id = uuid4()
    workspace = uuid4()
    route, _ctx_, _ws, captured = _rig(
        monkeypatch,
        corpus_workspace=workspace,
        sources_by_corpus={str(corpus_id): []},
    )

    result = await _chat(route, corpus_id, route.ChatRequest(query="¿Qué dice?"))

    assert "query" not in captured
    assert result["retrieval_scope"]["source_count"] == 0
    assert result["retrieval_scope"]["restricted"] is True
    assert "No tengo suficiente" in result["grounded"]["answer"]


@pytest.mark.asyncio
async def test_chat_rejects_corpus_from_another_workspace(monkeypatch) -> None:
    corpus_id = uuid4()
    route, _ctx_, _ws, captured = _rig(
        monkeypatch,
        corpus_workspace=uuid4(),
        viewer_workspace=uuid4(),
        sources_by_corpus={str(corpus_id): []},
    )

    with pytest.raises(HTTPException) as exc:
        await _chat(route, corpus_id, route.ChatRequest(query="¿Qué dice?"))
    assert exc.value.status_code == 404
    assert "query" not in captured


@pytest.mark.asyncio
async def test_chat_pending_source_is_not_used_by_default(monkeypatch) -> None:
    corpus_id = uuid4()
    workspace = uuid4()
    pending = _source(workspace, status="processing")
    route, _ctx_, _ws, captured = _rig(
        monkeypatch,
        corpus_workspace=workspace,
        sources_by_corpus={str(corpus_id): [pending]},
    )

    result = await _chat(route, corpus_id, route.ChatRequest(query="¿Qué dice?"))

    assert "query" not in captured
    assert result["retrieval_scope"]["source_count"] == 0
