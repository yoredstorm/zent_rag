# =============================================================================
# Knowledge Pipeline — profiling, index versions, training runs
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"kp-{uuid4().hex[:8]}@example.com",
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
    }


class TestProfilingHeuristics:
    def test_pii_flags_detected(self) -> None:
        from src.connectors.sql.profiling import _flags_for_column

        assert "email" in _flags_for_column("client_email")[0]
        assert "phone" in _flags_for_column("telefono_contacto")[0]
        assert "national_id" in _flags_for_column("rut_cliente")[0]
        assert "secret" in _flags_for_column("api_key")[0]
        assert "payment_card" in _flags_for_column("credit_card_number")[0]
        assert "health" in _flags_for_column("diagnostico_medico")[0]

    def test_sensitive_flags(self) -> None:
        from src.connectors.sql.profiling import _flags_for_column

        _pii, sensitive = _flags_for_column("product_cost")
        assert sensitive is True
        _pii2, sensitive2 = _flags_for_column("product_name")
        assert sensitive2 is False

    def test_plain_column_no_flags(self) -> None:
        from src.connectors.sql.profiling import _flags_for_column

        pii, sensitive = _flags_for_column("display_name")
        assert pii == []
        assert sensitive is False


@pytest.mark.asyncio
async def test_profile_endpoint_sql_source(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Profile Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    kb = (
        await async_client.post(
            "/api/v1/knowledge-bases", headers=h, json={"name": "Prof KB"}
        )
    ).json()
    source = await async_client.post(
        "/api/v1/sources",
        headers=h,
        json={
            "name": "Products SQL",
            "type": "sql",
            "knowledge_base_id": kb["id"],
            "config": {"schema": "farmacia", "tables": ["products"]},
        },
    )
    assert source.status_code == 201, source.text
    sid = source.json()["id"]

    profiled = await async_client.post(f"/api/v1/sources/{sid}/profile", headers=h)
    assert profiled.status_code == 200, profiled.text
    body = profiled.json()
    assert body["status"] == "profiled"
    assert body["tables"][0]["name"] == "products"
    columns = body["tables"][0]["columns"]
    assert len(columns) > 5
    by_name = {c["name"]: c for c in columns}
    assert by_name["name"]["is_pk"] is False
    assert by_name["price"]["data_type"]
    assert "null_rate" in by_name["price"]
    assert "cardinality" in by_name["price"]

    fetched = await async_client.get(f"/api/v1/sources/{sid}/profile", headers=h)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["profile_id"]

    # El estado de la fuente transitó por discovering → profiled.
    listing = await async_client.get("/api/v1/sources", headers=h)
    src = next(s for s in listing.json()["sources"] if s["id"] == sid)
    assert src["status"] == "profiled"


@pytest.mark.asyncio
async def test_index_versions_endpoint(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "IndexVer Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    kb = (
        await async_client.post(
            "/api/v1/knowledge-bases", headers=h, json={"name": "Index KB"}
        )
    ).json()
    versions = await async_client.get(
        f"/api/v1/knowledge-bases/{kb['id']}/index-versions", headers=h
    )
    assert versions.status_code == 200, versions.text
    assert versions.json()["count"] == 0

    # Cross-org: otro tenant no ve la KB.
    org_b = await _create_org(async_client, "IndexVer B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.get(
        f"/api/v1/knowledge-bases/{kb['id']}/index-versions", headers=_headers(org_b)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_training_run_creates_linked_jobs(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Train Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    kb = (
        await async_client.post(
            "/api/v1/knowledge-bases", headers=h, json={"name": "Train KB"}
        )
    ).json()
    src = await async_client.post(
        "/api/v1/sources",
        headers=h,
        json={
            "name": "Categories SQL",
            "type": "sql",
            "knowledge_base_id": kb["id"],
            "config": {"schema": "farmacia", "tables": ["categories"]},
        },
    )
    assert src.status_code == 201, src.text

    created = await async_client.post(
        "/api/v1/training/runs",
        headers=h,
        json={"knowledge_base_id": kb["id"]},
    )
    assert created.status_code == 201, created.text
    run = created.json()["run"]
    assert run["status"] == "pending"
    assert run["current_step"] == "preparation"
    assert run["progress"] == 0

    # El run debe tener al menos 1 job enlazado (la fuente ready de la KB).
    assert created.json()["job_count"] >= 1

    # El agregado responde sin importar el estado actual del worker.
    detail = await async_client.get(f"/api/v1/training/runs/{run['id']}", headers=h)
    assert detail.status_code == 200, detail.text
    agg = detail.json()["run"]
    assert agg["status"] in ("pending", "running", "completed", "failed", "partial")
    assert agg["current_step"] in ("preparation", "indexing", "validation")
    assert 0 <= agg["progress"] <= 100

    # Aislamiento: otro tenant no ve el run.
    org_b = await _create_org(async_client, "Train B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.get(
        f"/api/v1/training/runs/{run['id']}", headers=_headers(org_b)
    )
    assert resp.status_code == 404

    # Listado.
    listing = await async_client.get("/api/v1/training/runs", headers=h)
    assert listing.status_code == 200
    assert listing.json()["count"] >= 1


@pytest.mark.asyncio
async def test_training_run_unknown_kb_404(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Train 404")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    resp = await async_client.post(
        "/api/v1/training/runs",
        headers=h,
        json={"knowledge_base_id": str(uuid4())},
    )
    assert resp.status_code == 404
