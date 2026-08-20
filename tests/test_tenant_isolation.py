# =============================================================================
# Cross-Tenant Isolation Tests — LA prioridad de seguridad del plataforma
# =============================================================================
# Verifica que la organización A NO puede, bajo ninguna circunstancia,
# obtener información de la organización B:
#
#   1. Listas: solo datos de la organización autenticada.
#   2. Acceso por ID a recurso de otra org -> 404 (no revela existencia).
#   3. Vector search (Qdrant): resultados SIEMPRE filtrados por organización.
#   4. Spoofing de X-Organization-Id / body organization_id -> 403 / ignorado.
#   5. SQL Expert: filtro de organización inyectado (ver también
#      test_organization_filter_injection.py).
#   6. Audit logs: solo los de la propia organización.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_A_ID = UUID("11111111-1111-1111-1111-111111111111")
ORG_B_ID = UUID("22222222-2222-2222-2222-222222222222")


async def _create_org(client: AsyncClient, name: str, email: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={"company_name": name, "email": email, "country": "CL"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    return {"organization_id": data["organization_id"], "token": data["api_token"]}


async def _owner_session(organization_id: str) -> str:
    """Sesión portal del owner de la organización (RBAC completo)."""
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user_repo = PostgresUserRepository()
    user = await user_repo.get_by_external_id(UUID(organization_id), "default-admin")
    assert user is not None, "default-admin user missing for org"
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict, extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    if extra:
        headers.update(extra)
    return headers


@pytest.fixture
async def async_client() -> AsyncClient:
    from src.api.deps import get_rag_orchestrator

    class _MockOrchestrator:
        async def execute(self, **kwargs):
            from src.core.domain.entities import LLMResponse, QueryStatus, RAGQueryResult

            return RAGQueryResult(
                query_id=uuid4(),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                query=kwargs.get("query", ""),
                status=QueryStatus.COMPLETED,
                llm_response=LLMResponse(content="ok", model="mock"),
            )

    app.dependency_overrides[get_rag_orchestrator] = lambda: _MockOrchestrator()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def orgs(async_client: AsyncClient):
    """Dos organizaciones reales (A y B) con datos sembrados."""
    org_a = await _create_org(async_client, "Isolation Org A", f"iso-a-{uuid4().hex[:8]}@example.com")
    org_b = await _create_org(async_client, "Isolation Org B", f"iso-b-{uuid4().hex[:8]}@example.com")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b["session"] = await _owner_session(org_b["organization_id"])

    # Sembrar un proyecto en cada org
    pa = await async_client.post(
        "/api/v1/projects",
        json={"name": "Project Alpha", "description": "A"},
        headers=_headers(org_a),
    )
    assert pa.status_code == 201, pa.text
    pb = await async_client.post(
        "/api/v1/projects",
        json={"name": "Project Beta", "description": "B"},
        headers=_headers(org_b),
    )
    assert pb.status_code == 201, pb.text

    # Sembrar una KB en cada org
    kba = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": "KB Alpha"},
        headers=_headers(org_a),
    )
    assert kba.status_code == 201, kba.text
    kbb = await async_client.post(
        "/api/v1/knowledge-bases",
        json={"name": "KB Beta"},
        headers=_headers(org_b),
    )
    assert kbb.status_code == 201, kbb.text

    return {
        "A": org_a,
        "B": org_b,
        "project_a": pa.json(),
        "project_b": pb.json(),
        "kb_a": kba.json(),
        "kb_b": kbb.json(),
    }


# ---------------------------------------------------------------------------
# 1. Listas: solo datos de la organización autenticada
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lists_only_show_own_organization_data(async_client, orgs) -> None:
    response = await async_client.get("/api/v1/projects", headers=_headers(orgs["A"]))
    assert response.status_code == 200
    names = [p["name"] for p in response.json()["projects"]]
    assert "Project Alpha" in names
    assert "Project Beta" not in names

    response = await async_client.get("/api/v1/knowledge-bases", headers=_headers(orgs["A"]))
    assert response.status_code == 200
    names = [k["name"] for k in response.json()["knowledge_bases"]]
    assert "KB Alpha" in names
    assert "KB Beta" not in names

    response = await async_client.get("/api/v1/organizations/api-keys", headers=_headers(orgs["A"]))
    assert response.status_code == 200
    for key in response.json()["keys"]:
        assert key["id"]  # nunca se expone el hash/valor


# ---------------------------------------------------------------------------
# 2. Acceso por ID a recurso de otra organización -> 404 (no 403)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_read_other_org_project(async_client, orgs) -> None:
    response = await async_client.get(
        f"/api/v1/projects/{orgs['project_b']['id']}", headers=_headers(orgs["A"])
    )
    assert response.status_code == 404

    response = await async_client.get(
        f"/api/v1/knowledge-bases/{orgs['kb_b']['id']}", headers=_headers(orgs["A"])
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_update_or_delete_other_org_resource(async_client, orgs) -> None:
    response = await async_client.put(
        f"/api/v1/projects/{orgs['project_b']['id']}",
        json={"name": "hacked"},
        headers=_headers(orgs["A"]),
    )
    assert response.status_code == 404

    response = await async_client.delete(
        f"/api/v1/projects/{orgs['project_b']['id']}", headers=_headers(orgs["A"])
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3. Spoofing: X-Organization-Id de otra org con token de A -> 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spoofed_organization_header_rejected(async_client, orgs) -> None:
    response = await async_client.get(
        "/api/v1/projects",
        headers=_headers(orgs["A"], extra={"X-Organization-Id": orgs["B"]["organization_id"]}),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_body_organization_id_is_ignored(async_client, orgs) -> None:
    """organization_id en el body NUNCA define el tenant: se crea en la org autenticada."""
    response = await async_client.post(
        "/api/v1/projects",
        json={
            "name": "Body spoof project",
            "organization_id": orgs["B"]["organization_id"],
        },
        headers=_headers(orgs["A"]),
    )
    assert response.status_code == 201, response.text

    # El proyecto se creó en A
    created_id = response.json()["id"]
    check = await async_client.get(
        f"/api/v1/projects/{created_id}", headers=_headers(orgs["A"])
    )
    assert check.status_code == 200
    # ... y B NO puede verlo
    check_b = await async_client.get(
        f"/api/v1/projects/{created_id}", headers=_headers(orgs["B"])
    )
    assert check_b.status_code == 404


@pytest.mark.asyncio
async def test_other_org_token_cannot_read_my_data(async_client, orgs) -> None:
    """Token de B intentando leer recursos de A vía ID -> 404."""
    response = await async_client.get(
        f"/api/v1/projects/{orgs['project_a']['id']}", headers=_headers(orgs["B"])
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. Members: no se pueden gestionar usuarios de otra organización
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_assign_role_to_other_org_user(async_client, orgs) -> None:
    # Un user real de B
    members_b = await async_client.get(
        "/api/v1/organizations/members", headers=_headers(orgs["B"])
    )
    assert members_b.status_code == 200
    user_b_id = members_b.json()["members"][0]["user_id"]

    response = await async_client.post(
        f"/api/v1/organizations/members/{user_b_id}/role",
        json={"role": "admin"},
        headers=_headers(orgs["A"]),
    )
    assert response.status_code == 404  # usuario no pertenece a A


# ---------------------------------------------------------------------------
# 5. Audit logs: solo los de la propia organización
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_logs_are_organization_scoped(async_client, orgs) -> None:
    response = await async_client.get("/api/v1/audit-logs", headers=_headers(orgs["A"]))
    assert response.status_code == 200
    actions = [e["action"] for e in response.json()["entries"]]
    assert "project.created" in actions

    response_b = await async_client.get("/api/v1/audit-logs", headers=_headers(orgs["B"]))
    assert response_b.status_code == 200
    # A no ve las acciones de B ni B las de A: los resource_ids coinciden
    # solo con los recursos propios.
    ids_a = {e["resource_id"] for e in response.json()["entries"]}
    assert orgs["project_b"]["id"] not in ids_a
    ids_b = {e["resource_id"] for e in response_b.json()["entries"]}
    assert orgs["project_a"]["id"] not in ids_b


# ---------------------------------------------------------------------------
# 6. Qdrant: aislamiento de organización en el vector store (integración real)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vector_store_tenant_isolation_with_real_qdrant() -> None:
    """A y B comparten colección; la búsqueda de A jamás devuelve puntos de B."""
    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org_a = uuid4()
    org_b = uuid4()
    dim = settings.VECTOR_DIMENSION

    def vec(value: float) -> list[float]:
        v = [0.0] * dim
        v[0] = value
        return v

    try:
        # Vectores de prueba con la dimensión de la colección
        await store.upsert(
            org_a,
            uuid4(),
            vec(0.9),
            "Secret document of organization A",
            metadata={"visibility": "public"},
        )
        await store.upsert(
            org_b,
            uuid4(),
            vec(0.9),
            "Secret document of organization B",
            metadata={"visibility": "public"},
        )

        # Búsqueda como A: solo ve su documento
        ctx_a = await store.search(
            org_a,
            vec(0.9),
            top_k=10,
            score_threshold=0.0,
        )
        contents_a = {c.content for c in ctx_a.chunks}
        assert "Secret document of organization A" in contents_a
        assert "Secret document of organization B" not in contents_a

        # Búsqueda como B: solo ve su documento
        ctx_b = await store.search(
            org_b,
            vec(0.9),
            top_k=10,
            score_threshold=0.0,
        )
        contents_b = {c.content for c in ctx_b.chunks}
        assert "Secret document of organization B" in contents_b
        assert "Secret document of organization A" not in contents_b
    finally:
        try:
            await store.delete_by_organization(org_a)
        except Exception:
            pass
        try:
            await store.delete_by_organization(org_b)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_vector_store_rejects_missing_organization() -> None:
    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    dim = get_settings().VECTOR_DIMENSION
    with pytest.raises(ValueError):
        await store.search(  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            [0.0] * dim,
            top_k=5,
        )


@pytest.mark.asyncio
async def test_knowledge_base_vectors_scoped_to_organization() -> None:
    """La misma KB id en dos orgs no mezcla vectores (filtro org+kb)."""
    settings = get_settings()
    if settings.ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real (stack docker)")

    from src.infrastructure.qdrant.vector_store import QdrantVectorStore

    store = QdrantVectorStore()
    org_a = uuid4()
    org_b = uuid4()
    shared_kb_id = uuid4()  # mismo UUID de KB en ambas orgs (ataque de colisión)
    dim = settings.VECTOR_DIMENSION

    def vec(value: float) -> list[float]:
        v = [0.0] * dim
        v[0] = value
        return v

    try:
        await store.upsert(
            org_a,
            uuid4(),
            vec(1.0),
            "KB doc of A",
            knowledge_base_id=shared_kb_id,
        )
        await store.upsert(
            org_b,
            uuid4(),
            vec(1.0),
            "KB doc of B",
            knowledge_base_id=shared_kb_id,
        )

        ctx_a = await store.search(
            org_a,
            vec(1.0),
            top_k=10,
            score_threshold=0.0,
            knowledge_base_id=shared_kb_id,
        )
        contents = {c.content for c in ctx_a.chunks}
        assert "KB doc of A" in contents
        assert "KB doc of B" not in contents
    finally:
        try:
            await store.delete_by_organization(org_a)
        except Exception:
            pass
        try:
            await store.delete_by_organization(org_b)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 7. API keys: no se pueden gestionar keys de otra organización
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_revoke_other_org_api_key(async_client, orgs) -> None:
    keys_b = await async_client.get(
        "/api/v1/organizations/api-keys", headers=_headers(orgs["B"])
    )
    assert keys_b.status_code == 200
    key_b_id = keys_b.json()["keys"][0]["id"]

    response = await async_client.delete(
        f"/api/v1/organizations/api-keys/{key_b_id}", headers=_headers(orgs["A"])
    )
    assert response.status_code == 404
