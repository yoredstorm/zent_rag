# =============================================================================
# Federated Search & Analytics (PROMPT 15)
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


class _Chunk:
    def __init__(self, cid: str, content: str, score: float, kb_id: str):
        self.id = cid
        self.score = score
        self.payload = {
            "content": content,
            "document_id": cid,
            "knowledge_base_id": kb_id,
            "organization_id": "org",
        }


class _Ctx:
    def __init__(self, chunks: list):
        self.chunks = chunks


class _FakeVectorStore:
    """Devuelve chunks deterministas por KB (simula Qdrant)."""

    def __init__(self):
        self.kb_chunks: dict[str, list] = {}
        self.calls: list[tuple[str, list]] = []  # (kb_id, top_k)

    async def search_hybrid(self, organization_id, query, embedding, top_k=5, knowledge_base_id=None, role="admin"):
        self.calls.append((str(knowledge_base_id), top_k))
        return _Ctx(self.kb_chunks.get(str(knowledge_base_id), []))


class _FakeEmbedding:
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"fed-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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
        "Idempotency-Key": f"fed-{uuid4().hex}",
    }


async def _create_kb(client: AsyncClient, org: dict, name: str) -> dict:
    resp = await client.post(
        "/api/v1/knowledge-bases",
        headers={**_headers(org), "Idempotency-Key": f"kb-{uuid4().hex}"},
        json={"name": name, "description": "d"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


async def _platform_admin(client: AsyncClient, email: str) -> dict:
    import hashlib as hl

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', :email, :ph, true)"
            ),
            {
                "ext": f"plat-{uuid4().hex[:12]}",
                "eh": hl.sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email},
        )
        await session.commit()
    finally:
        await session.close()
    login = await client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_usage(client: AsyncClient, org: dict, cost: float = 0.01) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        now = datetime.now(timezone.utc)
        for i in range(3):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "agent_id, model, provider, total_tokens, latency_ms, status, "
                    "estimated_cost, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, NULL, 'gpt-4o-mini', "
                    "'openai', 500, 200.0, 'completed', :cost, :created)"
                ),
                {"oid": UUID(org["organization_id"]), "cost": cost, "created": now - timedelta(hours=i)},
            )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_federated_search_merge_and_rank(async_client: AsyncClient) -> None:
    from src.api.deps import get_embedding_provider, get_vector_store
    from src.api.main import app

    org = await _create_org(async_client, "Fed Search Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    kb_a = await _create_kb(async_client, org, "KB Facturas")
    kb_b = await _create_kb(async_client, org, "KB Inventario")

    # Fake vector store: A devuelve 2 chunks (score alto/bajo), B devuelve 1 chunk fuerte.
    fake = _FakeVectorStore()
    fake.kb_chunks[kb_a["id"]] = [
        _Chunk("doc-a1", "Factura 001 del proveedor X", 0.85, kb_a["id"]),
        _Chunk("doc-a2", "Factura duplicada 001 (dedupe)", 0.60, kb_a["id"]),
    ]
    fake.kb_chunks[kb_b["id"]] = [
        _Chunk("doc-b1", "Inventario del almacén central", 0.95, kb_b["id"]),
    ]
    # Duplicado exacto del chunk a1 en B (dedupe por contenido).
    fake.kb_chunks[kb_b["id"]].append(_Chunk("doc-b2", "Factura 001 del proveedor X", 0.90, kb_b["id"]))

    app.dependency_overrides[get_vector_store] = lambda: fake
    app.dependency_overrides[get_embedding_provider] = lambda: _FakeEmbedding()

    resp = await async_client.post(
        "/api/v1/rag/federated",
        headers=h,
        json={"query": "facturas e inventario", "top_k": 10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kb_count"] == 2
    assert len(body["sources"]) == 3  # 4 chunks - 1 duplicado (contenido)
    # Ranking unificado: B top (score 1.0 por normalización), luego A.
    assert body["sources"][0]["kb_name"] == "KB Inventario"
    assert body["sources"][0]["score"] == pytest.approx(1.0, abs=0.01)
    # El duplicado se dedupe: solo aparece una vez "Factura 001 del proveedor X".
    contents = [s["content"] for s in body["sources"]]
    assert contents.count("Factura 001 del proveedor X") == 1
    # Workspace name presente.
    assert all(s["workspace_name"] for s in body["sources"])


@pytest.mark.asyncio
async def test_federated_search_org_isolation(async_client: AsyncClient) -> None:
    from src.api.deps import get_embedding_provider, get_vector_store
    from src.api.main import app

    org = await _create_org(async_client, "Fed Iso Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    kb = await _create_kb(async_client, org, "KB Aislada")

    other_org = await _create_org(async_client, "Fed Other")
    other_org["session"] = await _owner_session(other_org["organization_id"])
    other_kb = await _create_kb(async_client, other_org, "KB De Otro")

    fake = _FakeVectorStore()
    fake.kb_chunks[kb["id"]] = [_Chunk("doc-1", "contenido propio", 0.9, kb["id"])]
    app.dependency_overrides[get_vector_store] = lambda: fake
    app.dependency_overrides[get_embedding_provider] = lambda: _FakeEmbedding()

    # KB de OTRA org → resuelve 0 KBs → resultados vacíos, sin error.
    resp = await async_client.post(
        "/api/v1/rag/federated",
        headers=h,
        json={"query": "x", "knowledge_base_ids": [other_kb["id"]]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["kb_count"] == 0
    assert resp.json()["sources"] == []


@pytest.mark.asyncio
async def test_federated_analytics_and_export(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Fed Analytics Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-fed-{uuid4().hex[:8]}@zent.example")
    await _seed_usage(async_client, org, cost=5.0)

    agg = await async_client.get("/api/v1/platform/analytics/federated", headers=plat)
    assert agg.status_code == 200, agg.text
    body = agg.json()
    assert body["totals"]["requests"] >= 3
    assert body["totals"]["cost"] >= 15.0
    row = next(r for r in body["by_organization"] if r["organization_id"] == org["organization_id"])
    assert row["requests"] == 3
    assert row["error_rate_pct"] == 0.0

    # CSV export.
    csv_resp = await async_client.get(
        "/api/v1/platform/analytics/federated?format=csv", headers=plat
    )
    assert csv_resp.status_code == 200, csv_resp.text
    csv_body = csv_resp.json()
    assert csv_body["content_type"] == "text/csv"
    assert csv_body["filename"].endswith(".csv")
    assert "organization_id" in csv_body["payload"]
    assert "requests" in csv_body["payload"]

    # JSON export.
    json_resp = await async_client.get(
        "/api/v1/platform/analytics/federated?format=json", headers=plat
    )
    assert json_resp.status_code == 200, json_resp.text
    assert json_resp.json()["content_type"] == "application/json"

    # Drill-down del tenant.
    drill = await async_client.get(
        f"/api/v1/platform/analytics/organizations/{org['organization_id']}", headers=plat
    )
    assert drill.status_code == 200, drill.text
    d = drill.json()
    assert d["economics"]["requests"] == 3
    assert d["aggregate_slo_24h"]["status"] in ("healthy", "no_traffic")

    # Export CSV del tenant.
    org_csv = await async_client.get(
        f"/api/v1/platform/analytics/organizations/{org['organization_id']}?format=csv",
        headers=plat,
    )
    assert org_csv.status_code == 200, org_csv.text
    assert "metric,value" in org_csv.json()["payload"]
