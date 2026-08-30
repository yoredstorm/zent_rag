# =============================================================================
# Google Drive connector — plugin, OAuth firmado, isolation, no leak de secrets
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app
from src.core.config import get_settings
from src.core.domain.entities import KbSource


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"gd-{uuid4().hex[:8]}@example.com",
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


class FakeDriveHTTP:
    """Lista + descarga + token exchange. Sin red."""

    def __init__(self) -> None:
        self.files = [
            {
                "id": "file-pdf-1",
                "name": "manual.pdf",
                "mimeType": "application/pdf",
                "modifiedTime": "2026-01-01T00:00:00.000Z",
            }
        ]
        self.contents = {
            "file-pdf-1": b"# Manual Drive\n\nContenido indexado desde Google Drive."
        }
        self.token_posts = 0
        self.last_refresh_token: str | None = None

    async def http_get(self, url: str, *, headers=None, params=None):
        params = params or {}
        if "/drive/v3/files" in url and params.get("alt") != "media":
            if "/export" in url:
                file_id = url.split("/files/")[1].split("/")[0]
                return 200, self.contents.get(file_id, b"")
            return 200, {"files": list(self.files)}
        if "alt=media" in url or params.get("alt") == "media":
            file_id = url.rstrip("/").split("/files/")[-1].split("?")[0]
            return 200, self.contents.get(file_id, b"")
        raise AssertionError(f"unexpected GET {url} {params}")

    async def http_post(self, url: str, *, data=None, headers=None, json=None):
        self.token_posts += 1
        payload = data or json or {}
        self.last_refresh_token = payload.get("refresh_token") or payload.get("code")
        body = {
            "access_token": "ya29.mock-access",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        if payload.get("grant_type") == "authorization_code" or payload.get("code"):
            body["refresh_token"] = "1//mock-refresh-token"
        return body


@pytest.fixture
async def async_client():
    from tests.conftest import attach_auto_idempotency

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield attach_auto_idempotency(client)


@pytest.fixture
async def org_a(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "Drive Org A")
    org["session"] = await _owner_session(org["organization_id"])
    return org


@pytest.fixture
async def org_b(async_client: AsyncClient) -> dict:
    org = await _create_org(async_client, "Drive Org B")
    org["session"] = await _owner_session(org["organization_id"])
    return org


@pytest.fixture
def google_oauth_settings(monkeypatch: pytest.MonkeyPatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(
        settings,
        "GOOGLE_OAUTH_CLIENT_SECRET",
        type(settings.CONNECTOR_SECRETS_KEY)("test-client-secret"),
    )
    monkeypatch.setattr(
        settings,
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://test/api/v1/connectors/oauth/drive/callback",
    )
    return settings


@pytest.fixture
def fake_drive(monkeypatch: pytest.MonkeyPatch) -> FakeDriveHTTP:
    from src.connectors.gdrive.client import set_gdrive_http

    fake = FakeDriveHTTP()
    set_gdrive_http(http_get=fake.http_get, http_post=fake.http_post)
    yield fake
    set_gdrive_http(http_get=None, http_post=None)


def test_gdrive_plugin_is_registered() -> None:
    import src.connectors.plugin.plugins  # noqa: F401
    from src.connectors.plugin import get_plugin_class

    cls = get_plugin_class("gdrive")
    assert cls is not None
    assert cls.connector_type == "gdrive"
    assert "refresh_token" in cls.required_secret_keys


@pytest.mark.asyncio
async def test_gdrive_plugin_lists_and_tests_with_mock_http(fake_drive) -> None:
    from src.connectors.plugin.plugins.gdrive import GDrivePlugin

    plugin = GDrivePlugin(
        {"folder_id": "folder-abc"},
        {"refresh_token": "1//tenant-a-refresh"},
    )
    result = await plugin.test_connection()
    assert result.ok is True

    discovery = await plugin.discover()
    assert discovery.source == "gdrive"
    assert any("manual.pdf" in t.name for t in discovery.tables)


@pytest.mark.asyncio
async def test_gdrive_source_indexes_pdf_via_normalizer(
    fake_drive, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.knowledge.normalize  # noqa: F401
    from src.knowledge.connectors.gdrive_source import GDriveSourceConnector
    from src.knowledge.normalize.base import get_normalizer

    monkeypatch.setattr(
        type(get_normalizer("pdf")),
        "normalize",
        lambda self, data, source_name="document": data.decode("utf-8"),
    )

    source = KbSource(
        id=uuid4(),
        organization_id=uuid4(),
        name="Drive docs",
        type="gdrive",
        config_json={"folder_id": "folder-abc", "connector_id": str(uuid4())},
    )
    connector = GDriveSourceConnector(source)
    connector.secrets = {"refresh_token": "1//tenant-a-refresh"}

    records = [record async for record in connector.iter_records(None)]
    assert len(records) == 1
    assert records[0].external_id == "file-pdf-1"
    assert "Contenido indexado" in records[0].content
    assert connector._last_cursor["done_keys"] == ["file-pdf-1"]


@pytest.mark.asyncio
async def test_gdrive_org_a_token_does_not_sync_org_b(
    async_client, org_a, org_b, fake_drive
) -> None:
    from src.infrastructure.secrets.secret_store_resolver import get_secret_store
    from src.knowledge.connectors.gdrive_source import GDriveSourceConnector

    headers_a = _headers(org_a)
    created = await async_client.post(
        "/api/v1/connectors",
        json={
            "name": f"drive-{uuid4().hex[:8]}",
            "type": "gdrive",
            "config": {"folder_id": "folder-abc"},
            "secrets": {"refresh_token": "1//org-a-only"},
        },
        headers=headers_a,
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["id"]

    store = get_secret_store()
    secrets_a = await store.get(UUID(org_a["organization_id"]), UUID(connector_id))
    assert secrets_a.get("refresh_token") == "1//org-a-only"
    secrets_b = await store.get(UUID(org_b["organization_id"]), UUID(connector_id))
    assert not secrets_b.get("refresh_token")

    source_b = KbSource(
        id=uuid4(),
        organization_id=UUID(org_b["organization_id"]),
        name="Stolen Drive",
        type="gdrive",
        config_json={"folder_id": "folder-abc", "connector_id": connector_id},
    )
    connector = GDriveSourceConnector(source_b)
    with pytest.raises(Exception, match="refresh_token|secret|not configured"):
        await connector.validate()


@pytest.mark.asyncio
async def test_create_gdrive_source_and_get_never_leaks_token(
    async_client, org_a
) -> None:
    headers = _headers(org_a)
    created = await async_client.post(
        "/api/v1/connectors",
        json={
            "name": f"drive-{uuid4().hex[:8]}",
            "type": "gdrive",
            "config": {"folder_id": "folder-abc"},
            "secrets": {"refresh_token": "1//never-in-get"},
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["id"]
    assert "1//never-in-get" not in created.text

    source = await async_client.post(
        "/api/v1/sources",
        json={
            "name": f"src-{uuid4().hex[:8]}",
            "type": "gdrive",
            "config": {"folder_id": "folder-abc", "connector_id": connector_id},
        },
        headers=headers,
    )
    assert source.status_code == 201, source.text
    assert source.json()["type"] == "gdrive"
    assert "1//never-in-get" not in source.text
    assert "refresh_token" not in str(source.json()["config"])

    fetched = await async_client.get(
        f"/api/v1/sources/{source.json()['id']}", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    blob = fetched.text
    assert "1//never-in-get" not in blob
    assert "refresh_token" not in str(fetched.json().get("config") or {})


@pytest.mark.asyncio
async def test_oauth_start_requires_auth(async_client) -> None:
    resp = await async_client.post(
        "/api/v1/connectors/oauth/drive/start",
        json={"name": "Drive", "folder_id": "folder-abc"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_oauth_start_returns_google_url_with_signed_state(
    async_client, org_a, google_oauth_settings
) -> None:
    resp = await async_client.post(
        "/api/v1/connectors/oauth/drive/start",
        json={"name": f"Drive {uuid4().hex[:6]}", "folder_id": "folder-abc"},
        headers=_headers(org_a),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "accounts.google.com" in data["authorization_url"]
    assert "state=" in data["authorization_url"]
    assert data["connector_id"]
    from urllib.parse import parse_qs, urlparse

    from src.connectors.gdrive.oauth import verify_drive_oauth_state

    state = parse_qs(urlparse(data["authorization_url"]).query)["state"][0]
    payload = verify_drive_oauth_state(state)
    assert payload["organization_id"] == org_a["organization_id"]
    assert payload["connector_id"] == data["connector_id"]


@pytest.mark.asyncio
async def test_oauth_callback_rejects_tampered_state(
    async_client, org_a, google_oauth_settings
) -> None:
    start = await async_client.post(
        "/api/v1/connectors/oauth/drive/start",
        json={"name": f"Drive {uuid4().hex[:6]}", "folder_id": "folder-abc"},
        headers=_headers(org_a),
    )
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
    tampered = state[:-2] + ("00" if state[-2:] != "00" else "ff")
    resp = await async_client.get(
        "/api/v1/connectors/oauth/drive/callback",
        params={"code": "4/fake-code", "state": tampered},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_oauth_callback_stores_refresh_token_for_signed_org(
    async_client, org_a, org_b, google_oauth_settings, fake_drive
) -> None:
    start = await async_client.post(
        "/api/v1/connectors/oauth/drive/start",
        json={"name": f"Drive {uuid4().hex[:6]}", "folder_id": "folder-abc"},
        headers=_headers(org_a),
    )
    assert start.status_code == 200, start.text
    connector_id = start.json()["connector_id"]
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(start.json()["authorization_url"]).query)["state"][0]
    resp = await async_client.get(
        "/api/v1/connectors/oauth/drive/callback",
        params={"code": "4/fake-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302), resp.text

    got = await async_client.get(
        f"/api/v1/connectors/{connector_id}", headers=_headers(org_a)
    )
    assert got.status_code == 200, got.text
    assert got.json()["has_secrets"] is True
    assert "1//mock-refresh-token" not in got.text

    # Org B no ve el conector ni puede leer secretos cruzados
    missing = await async_client.get(
        f"/api/v1/connectors/{connector_id}", headers=_headers(org_b)
    )
    assert missing.status_code == 404


def test_portal_knowledge_lists_gdrive_and_oauth() -> None:
    from pathlib import Path

    portal = Path(__file__).resolve().parents[1] / "portal" / "src"
    sources = (portal / "pages" / "knowledge" / "Sources.tsx").read_text(encoding="utf-8")
    connectors = (portal / "pages" / "Connectors.tsx").read_text(encoding="utf-8")
    assert "gdrive" in sources
    assert "/api/v1/connectors/oauth/drive/start" in sources or (
        "/api/v1/connectors/oauth/drive/start" in connectors
    )
    assert "gdrive" in connectors
    assert "Google Drive" in sources or "Google Drive" in connectors
