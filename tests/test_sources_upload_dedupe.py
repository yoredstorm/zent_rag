# =============================================================================
# Upload de fuentes — dedupe por nombre+extensión (cualquier documento)
# =============================================================================
# Regla: si ya existe una fuente con el mismo nombre+extensión en la
# organización, el upload responde 409 con la fuente existente; force=true
# crea una copia. Detecta el sufijo "(1)" que agrega el navegador.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.api.routes.sources import _normalize_filename
from src.core.config import get_settings
from tests import tabular_fixtures as fx


def test_normalize_filename_handles_browser_copy_suffix() -> None:
    assert _normalize_filename("ATPCO (1).xlsx") == "atpco.xlsx"
    assert _normalize_filename("atpco.xlsx") == "atpco.xlsx"
    assert _normalize_filename("  ATPCO   (12).XLSX ") == "atpco.xlsx"
    assert _normalize_filename("Informe final (1).pdf") == "informe final.pdf"
    assert _normalize_filename("sin_extension") == "sin_extension"
    assert _normalize_filename("Guía (2).docx") == "guía.docx"


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"dedupe-{uuid4().hex[:8]}@example.com",
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
    organization = await _create_org(async_client, "Dedupe Upload")
    organization["session"] = await _owner_session(organization["organization_id"])
    return organization


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(
        settings, "KNOWLEDGE_QUEUE_KEY", f"rag:knowledge:queue:test:{uuid4().hex}"
    )
    return settings


async def test_upload_warns_on_same_name_and_extension(
    async_client, org, isolated_settings
) -> None:
    data = fx.atpco_workbook_bytes()
    first = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("ATPCO_TEST.xlsx", data, "application/octet-stream")},
    )
    assert first.status_code == 201, first.text
    source_id = first.json()["id"]

    duplicate = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("ATPCO_TEST (1).xlsx", data, "application/octet-stream")},
    )
    assert duplicate.status_code == 409, duplicate.text
    body = duplicate.json()
    assert body["error_code"] == "HTTP_409"
    details = body["details"]
    assert details["existing_source_id"] == source_id
    assert "force=true" in details["hint"]

    forced = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        params={"force": "true"},
        files={"file": ("ATPCO_TEST (1).xlsx", data, "application/octet-stream")},
    )
    assert forced.status_code == 201, forced.text
    assert forced.json()["id"] != source_id


async def test_upload_other_name_passes(async_client, org, isolated_settings) -> None:
    data = fx.atpco_workbook_bytes()
    first = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("ATPCO_TEST.xlsx", data, "application/octet-stream")},
    )
    assert first.status_code == 201, first.text

    other = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("OTRO_ARCHIVO.xlsx", data, "application/octet-stream")},
    )
    assert other.status_code == 201, other.text


async def test_batch_upload_reports_per_file_status(
    async_client, org, isolated_settings
) -> None:
    """El lote no se corta: created/duplicate/rejected por archivo."""
    data = fx.atpco_workbook_bytes()
    first = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("BATCH_A.xlsx", data, "application/octet-stream")},
    )
    assert first.status_code == 201, first.text

    batch = await async_client.post(
        "/api/v1/sources/files/upload-batch",
        headers=_headers(org),
        files=[
            ("files", ("BATCH_A.xlsx", data, "application/octet-stream")),
            ("files", ("BATCH_B.xlsx", data, "application/octet-stream")),
            ("files", ("notas.txt", b"hola mundo", "text/plain")),
            ("files", ("virus.exe", b"MZ\x90\x00", "application/octet-stream")),
        ],
    )
    assert batch.status_code == 200, batch.text
    body = batch.json()
    statuses = {item["filename"]: item["status"] for item in body["items"]}
    assert statuses["BATCH_A.xlsx"] == "duplicate"
    assert statuses["BATCH_B.xlsx"] == "created"
    assert statuses["notas.txt"] == "created"
    assert statuses["virus.exe"] == "rejected"
    assert body["created"] == 2
    assert body["duplicates"] == 1
    assert body["rejected"] == 1
    assert body["failed"] == 0
    duplicate = next(i for i in body["items"] if i["status"] == "duplicate")
    assert duplicate["existing_source_id"] == first.json()["id"]
    created_items = [i for i in body["items"] if i["status"] == "created"]
    assert all(i["job_id"] for i in created_items)
    assert all(i["name"] == i["filename"] for i in created_items)


async def test_batch_upload_force_creates_copy(
    async_client, org, isolated_settings
) -> None:
    data = fx.atpco_workbook_bytes()
    first = await async_client.post(
        "/api/v1/sources/files/upload",
        headers=_headers(org),
        files={"file": ("BATCH_FORCE.xlsx", data, "application/octet-stream")},
    )
    assert first.status_code == 201, first.text

    batch = await async_client.post(
        "/api/v1/sources/files/upload-batch",
        headers=_headers(org),
        params={"force": "true"},
        files=[
            ("files", ("BATCH_FORCE.xlsx", data, "application/octet-stream")),
        ],
    )
    assert batch.status_code == 200, batch.text
    body = batch.json()
    assert body["created"] == 1
    assert body["items"][0]["source_id"] != first.json()["id"]
