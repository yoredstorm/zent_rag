# =============================================================================
# P18.1-02 — Corpus de destino determinista
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"p181-{uuid4().hex[:8]}@example.com",
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


@pytest.fixture
async def async_client():
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def org(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "P18.1 Corpus")
    org["session"] = await _owner_session(org["organization_id"])
    return org


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        settings, "KNOWLEDGE_QUEUE_KEY", f"rag:knowledge:queue:test:{uuid4().hex}"
    )
    return settings


@pytest.mark.asyncio
async def test_upload_resolves_principal_not_first_created_corpus(
    async_client, org, isolated_settings
) -> None:
    otros = await async_client.post(
        "/api/v1/knowledge/workspaces",
        headers=_headers(org),
        json={"name": "Otros"},
    )
    assert otros.status_code == 201, otros.text
    otros_id = otros.json()["corpus"]["id"]

    upload = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("manual.txt", b"# Manual\n\nContenido.", "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    resolved = upload.json()["corpus_id"]
    assert resolved != otros_id

    listed = await async_client.get(
        "/api/v1/knowledge/workspaces", headers=_headers(org)
    )
    assert listed.status_code == 200, listed.text
    by_id = {item["id"]: item for item in listed.json()["corpora"]}
    assert resolved in by_id
    assert by_id[resolved]["slug"] == "principal"


@pytest.mark.asyncio
async def test_upload_explicit_corpus_wins_and_is_idempotent(
    async_client, org, isolated_settings
) -> None:
    created = await async_client.post(
        "/api/v1/knowledge/workspaces",
        headers=_headers(org),
        json={"name": "Operaciones"},
    )
    corpus_id = created.json()["corpus"]["id"]

    for filename in ("uno.txt", "dos.txt"):
        upload = await async_client.post(
            f"/api/v1/sources/files/upload?corpus_id={corpus_id}",
            headers=_headers(org),
            files={"file": (filename, b"# Doc\n\nContenido.", "text/plain")},
        )
        assert upload.status_code == 201, upload.text
        assert upload.json()["corpus_id"] == corpus_id

    detail = await async_client.get(
        f"/api/v1/knowledge/workspaces/{corpus_id}", headers=_headers(org)
    )
    assert detail.status_code == 200, detail.text
    names = {source["name"] for source in detail.json()["sources"]}
    assert {"uno.txt", "dos.txt"}.issubset(names)


@pytest.mark.asyncio
async def test_upload_invalid_corpus_does_not_fall_back(
    async_client, org, isolated_settings
) -> None:
    upload = await async_client.post(
        f"/api/v1/sources/files/upload?corpus_id={uuid4()}",
        headers=_headers(org),
        files={"file": ("manual.txt", b"# Manual\n\nContenido.", "text/plain")},
    )
    assert upload.status_code == 404, upload.text
