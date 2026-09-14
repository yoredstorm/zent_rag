# =============================================================================
# Universal API Connector (misiones §11-§17) — parser OpenAPI, seguridad,
# borradores, revisión humana e instalación. Los HTTP calls se mockean.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.marketplace.connector_drafts import apply_draft_patch
from src.platform.marketplace.models import validate_integration_manifest
from src.platform.marketplace.openapi_import import (
    OpenApiImportError,
    build_draft,
    detect_auth,
    draft_to_manifest,
    parse_openapi_document,
    validate_server_url,
)
from tests.test_workflows import _create_org, _headers, _owner_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _sample_doc(*, with_auth: bool = False) -> dict:
    doc: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {"title": "Acme Commerce", "version": "1.2.0", "description": "API de pedidos"},
        "servers": [{"url": "https://example.com/api/v1"}],
        "paths": {
            "/customers/{customerId}": {
                "get": {
                    "operationId": "getCustomerById",
                    "summary": "Obtener cliente",
                    "tags": ["Clientes"],
                    "parameters": [
                        {
                            "name": "customerId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                            "description": "Identificador del cliente",
                        },
                        {
                            "name": "expand",
                            "in": "query",
                            "schema": {"type": "string", "enum": ["address", "orders"]},
                        },
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "integer"},
                                            "fullName": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/orders": {
                "post": {
                    "operationId": "createOrder",
                    "tags": ["Pedidos"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["customerId"],
                                    "properties": {
                                        "customerId": {"type": "integer"},
                                        "notes": {"type": "string"},
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "orderId": {"type": "integer"},
                                            "status": {"type": "string"},
                                        },
                                    }
                                }
                            }
                        }
                    },
                }
            },
            "/inventory/{sku}": {
                "get": {
                    "operationId": "getInventoryBySku",
                    "parameters": [
                        {"name": "sku", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "sku": {"type": "string"},
                                            "available": {"type": "integer"},
                                        },
                                    }
                                }
                            }
                        }
                    },
                },
                "delete": {
                    "operationId": "deleteSku",
                    "responses": {"204": {"description": "ok"}},
                },
            },
        },
    }
    if with_auth:
        doc["components"] = {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
            }
        }
        doc["security"] = [{"bearerAuth": []}]
    return doc


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver DNS determinista para tests offline."""
    from src.agents.tools.tools_builtin import CallApiTool

    monkeypatch.setattr(CallApiTool, "_resolve_ip", staticmethod(lambda host: "93.184.216.34"))


class FakeResponse:
    def __init__(self, payload: Any, status: int = 200, headers: dict | None = None) -> None:
        self._payload = payload
        self.status_code = status
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self) -> Any:
        return self._payload


class FakeClient:
    payload: Any = {}
    status: int = 200
    headers: dict = {}
    calls: list[dict] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    def _respond(self) -> FakeResponse:
        return FakeResponse(FakeClient.payload, FakeClient.status, FakeClient.headers)

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "GET", "url": url, "params": params or {}, "json": None})
        return self._respond()

    async def post(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "POST", "url": url, "json": json})
        return self._respond()

    async def put(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "PUT", "url": url, "json": json})
        return self._respond()

    async def patch(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "PATCH", "url": url, "json": json})
        return self._respond()


# ---------------------------------------------------------------------------
# Parser y seguridad
# ---------------------------------------------------------------------------
def test_parse_json_yaml_y_documentos_invalidos() -> None:
    doc = _sample_doc()
    assert parse_openapi_document(json.dumps(doc))["info"]["title"] == "Acme Commerce"
    yaml_text = (
        "openapi: 3.0.3\n"
        "info:\n  title: YAML API\n  version: '1'\n"
        "paths:\n  /ping:\n    get:\n      responses:\n        '200': {description: ok}\n"
    )
    assert parse_openapi_document(yaml_text)["info"]["title"] == "YAML API"

    with pytest.raises(OpenApiImportError) as swagger:
        parse_openapi_document({"swagger": "2.0", "paths": {}})
    assert swagger.value.code == "OPENAPI_UNSUPPORTED_VERSION"

    with pytest.raises(OpenApiImportError):
        parse_openapi_document("no es un documento")
    with pytest.raises(OpenApiImportError) as no_paths:
        parse_openapi_document({"openapi": "3.0.0"})
    assert no_paths.value.code == "OPENAPI_NO_OPERATIONS"
    with pytest.raises(OpenApiImportError) as too_big:
        parse_openapi_document("x" * 2_000_001)
    assert too_big.value.code == "OPENAPI_TOO_LARGE"


def test_validate_server_bloquea_hosts_inseguros() -> None:
    with pytest.raises(OpenApiImportError) as insecure:
        validate_server_url("http://example.com")
    assert insecure.value.code == "OPENAPI_UNSAFE_SERVER"
    with pytest.raises(OpenApiImportError):
        validate_server_url("https://127.0.0.1")
    with pytest.raises(OpenApiImportError):
        validate_server_url("https://localhost")
    assert validate_server_url("https://example.com/api") == "example.com"


def test_build_draft_agrupa_acciones_y_schemas_de_negocio() -> None:
    draft = build_draft(_sample_doc(), source_kind="url", source_url="https://example.com/openapi.json")
    assert draft["slug"] == "acme-commerce"
    assert draft["base_url"] == "https://example.com/api/v1"
    assert draft["auth"]["kind"] == "none"

    caps = {c["slug"]: c for c in draft["capabilities"]}
    assert {"clientes", "pedidos", "inventory"} <= set(caps)
    assert caps["clientes"]["name"] == "Clientes"

    get_customer = caps["clientes"]["actions"][0]
    assert get_customer["action_id"] == "acme-commerce.getcustomerbyid"
    assert get_customer["display_name"] == "Obtener cliente"  # summary humano gana
    assert get_customer["method"] == "GET"
    assert get_customer["path_template"] == "/customers/{customerId}"
    assert get_customer["read_only"] is True
    props = get_customer["input_schema"]["properties"]
    assert props["customerId"]["x-business-label"]
    assert props["customerId"]["x-business-help"] == "Identificador del cliente"
    assert "customerId" in get_customer["input_schema"]["required"]
    assert "expand" in props and props["expand"]["enum"] == ["address", "orders"]
    assert get_customer["output_schema"]["properties"]["fullName"]["x-business-label"]
    assert get_customer["output_map"] == {"id": "id", "fullName": "fullName", "email": "email"}

    create_order = caps["pedidos"]["actions"][0]
    assert create_order["read_only"] is False
    assert create_order["method"] == "POST"
    assert create_order["risk_level"] == "normal"
    assert "customerId" in create_order["input_schema"]["required"]
    assert create_order["output_map"] == {"orderId": "orderId", "status": "status"}

    # DELETE queda fuera de la allowlist y se reporta.
    skipped = [(s["method"], s["path"]) for s in draft["report"]["skipped"]]
    assert ("DELETE", "/inventory/{sku}") in skipped


def test_detect_auth_variantes() -> None:
    api_key = {
        "components": {"securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Acme-Key"}}},
        "security": [{"key": []}],
    }
    assert detect_auth(api_key)["kind"] == "api_key"
    assert detect_auth(api_key)["header_name"] == "X-Acme-Key"

    basic = {
        "components": {"securitySchemes": {"b": {"type": "http", "scheme": "basic"}}},
        "security": [{"b": []}],
    }
    assert detect_auth(basic)["kind"] == "basic"

    oauth = {
        "components": {"securitySchemes": {"o": {"type": "oauth2", "flows": {}}}},
        "security": [{"o": []}],
    }
    assert detect_auth(oauth)["kind"] == "oauth2"
    assert detect_auth({})["kind"] == "none"


def test_draft_a_manifest_y_revision_humana() -> None:
    draft = build_draft(_sample_doc())
    patched = apply_draft_patch(
        draft,
        {
            "name": "Acme Producción",
            "auth_kind": "bearer",
            "rate_limits": {"requests_per_minute": 30},
            "actions": [
                {
                    "action_id": "acme-commerce.getcustomerbyid",
                    "display_name": "Buscar cliente",
                    "output_map": {"nombre": "fullName", "correo": "email"},
                },
                {"action_id": "acme-commerce.createorder", "enabled": False},
            ],
        },
    )
    assert patched["name"] == "Acme Producción"
    assert patched["auth"]["kind"] == "bearer"
    manifest = draft_to_manifest(patched, slug="acme-commerce", organization_id=uuid4())
    errors = validate_integration_manifest(manifest)
    assert errors == []
    assert manifest["auth_modes"] == ["BYOC"]
    assert manifest["rate_limits"] == {"requests_per_minute": 30}
    assert manifest["pricing"]["model"] == "BYOC_NO_MARKUP"

    action_ids = [a["action_id"] for c in manifest["capabilities"] for a in c["actions"]]
    assert action_ids == [
        "acme-commerce.getcustomerbyid",
        "acme-commerce.getinventorybysku",
    ]  # createorder deshabilitada
    action = manifest["capabilities"][0]["actions"][0]
    assert action["display_name"] == "Buscar cliente"
    assert action["provider_config"]["kind"] == "rest"
    assert action["provider_config"]["output_map"] == {"nombre": "fullName", "correo": "email"}

    from src.platform.marketplace.connector_drafts import DraftError

    with pytest.raises(DraftError):
        apply_draft_patch(draft, {"auth_kind": "carrier-pigeon"})


# ---------------------------------------------------------------------------
# API + persistencia (drafts, install, ejecución, tenants)
# ---------------------------------------------------------------------------
async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


@pytest.mark.asyncio
async def test_import_draft_review_install_and_execute(async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    org = await _org(async_client, "Connector Import")
    h = _headers(org)
    slug = f"conn-{uuid4().hex[:8]}"
    doc = _sample_doc()
    doc["info"]["title"] = slug  # slug determinista y único

    imported = await async_client.post(
        "/api/v1/integrations/import/openapi",
        headers={**h, "Idempotency-Key": f"imp-{uuid4().hex}"},
        json={"document": doc},
    )
    assert imported.status_code == 201, imported.text
    body = imported.json()
    draft_id = body["draft_id"]
    assert body["slug"] == slug
    assert body["counts"]["actions"] == 3
    assert body["counts"]["capabilities"] == 3
    assert body["report"]["actions_generated"] == 3

    listed = await async_client.get("/api/v1/integrations/drafts", headers=h)
    assert listed.status_code == 200
    assert any(d["draft_id"] == draft_id for d in listed.json()["drafts"])

    # Revisión humana: renombrar y deshabilitar una acción.
    patched = await async_client.patch(
        f"/api/v1/integrations/drafts/{draft_id}",
        headers={**h, "Idempotency-Key": f"patch-{uuid4().hex}"},
        json={
            "name": "Acme Demo",
            "actions": [
                {"action_id": f"{slug}.createorder", "enabled": False},
                {"action_id": f"{slug}.getcustomerbyid", "display_name": "Buscar cliente"},
            ],
        },
    )
    assert patched.status_code == 200, patched.text

    installed = await async_client.post(
        f"/api/v1/integrations/drafts/{draft_id}/install",
        headers={**h, "Idempotency-Key": f"install-{uuid4().hex}"},
    )
    assert installed.status_code == 200, installed.text
    install_body = installed.json()
    assert install_body["integration_slug"] == slug
    assert install_body["credentials_required"] is False
    assert install_body["actions"] == 2
    install_id = install_body["install_id"]

    # Formularios dinámicos de la acción importada.
    ports = await async_client.get(
        f"/api/v1/workflows/marketplace/ports/{slug}.getcustomerbyid", headers=h
    )
    assert ports.status_code == 200, ports.text
    param_keys = {p["key"] for p in ports.json()["input_parameters"]}
    assert "inputs.customerId" in param_keys

    # Consola de prueba: ejecuta con inputs de negocio (httpx mockeado).
    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = {"id": 7, "fullName": "Ada Lovelace", "email": "ada@example.com"}
    FakeClient.status = 200
    FakeClient.calls = []
    executed = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/{slug}.getcustomerbyid/execute",
        headers={**h, "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"customerId": 7}, "force_refresh": True},
    )
    assert executed.status_code == 200, executed.text
    result = executed.json()
    assert result["ok"] is True, result
    assert result["data"]["fullName"] == "Ada Lovelace"
    assert FakeClient.calls[0]["method"] == "GET"
    assert "/customers/7" in FakeClient.calls[0]["url"]
    assert FakeClient.calls[0]["params"].get("customerId") is None  # path param no viaja en query

    # El manifest importado no se filtra a otro tenant.
    other = await _org(async_client, "Connector Other")
    other_catalog = await async_client.get("/api/v1/integrations/catalog", headers=_headers(other))
    assert other_catalog.status_code == 200
    slugs = {item["slug"] for item in other_catalog.json()["catalog"]}
    assert slug not in slugs

    cross = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/{slug}.getcustomerbyid/execute",
        headers={**_headers(other), "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"customerId": 7}},
    )
    assert cross.status_code == 200
    assert cross.json()["ok"] is False
    assert cross.json()["error_code"] == "NOT_INSTALLED"


@pytest.mark.asyncio
async def test_import_rechaza_ssrf_y_documento_invalido(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Connector SSRF")
    h = _headers(org)

    ssrf = await async_client.post(
        "/api/v1/integrations/import/openapi",
        headers={**h, "Idempotency-Key": f"ssrf-{uuid4().hex}"},
        json={"url": "https://127.0.0.1/openapi.json"},
    )
    assert ssrf.status_code == 400
    assert "OPENAPI_UNSAFE_URL" in ssrf.text

    invalid = await async_client.post(
        "/api/v1/integrations/import/openapi",
        headers={**h, "Idempotency-Key": f"bad-{uuid4().hex}"},
        json={"document": {"swagger": "2.0", "paths": {"/a": {}}}},
    )
    assert invalid.status_code == 400
    assert "OPENAPI_UNSUPPORTED_VERSION" in invalid.text

    both = await async_client.post(
        "/api/v1/integrations/import/openapi",
        headers={**h, "Idempotency-Key": f"both-{uuid4().hex}"},
        json={"url": "https://example.com/openapi.json", "document": "{}"},
    )
    assert both.status_code == 422


@pytest.mark.asyncio
async def test_rate_limit_y_retry_after(async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    org = await _org(async_client, "Connector Limits")
    h = _headers(org)
    slug = f"limited-{uuid4().hex[:8]}"
    from src.platform.marketplace import catalog

    manifest = draft_to_manifest(build_draft(_sample_doc()), slug=slug, organization_id=None)
    manifest["rate_limits"] = {"requests_per_minute": 1}
    await catalog.register_manifest(
        manifest, organization_id=UUID(org["organization_id"])
    )
    installed = await async_client.post(
        "/api/v1/integrations/installs",
        headers={**h, "Idempotency-Key": f"inst-{uuid4().hex}"},
        json={"integration_slug": slug},
    )
    assert installed.status_code == 201, installed.text
    install_id = installed.json()["install_id"]

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = {"id": 1, "fullName": "Uno", "email": "u@example.com"}
    FakeClient.status = 200
    FakeClient.headers = {}
    first = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/{slug}.getcustomerbyid/execute",
        headers={**h, "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"customerId": 1}, "force_refresh": True},
    )
    assert first.json()["ok"] is True
    second = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/{slug}.getcustomerbyid/execute",
        headers={**h, "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"customerId": 2}, "force_refresh": True},
    )
    assert second.json()["ok"] is False
    assert second.json()["error_code"] == "RATE_LIMITED"
    assert int(second.json()["retry_after"]) >= 1

    # 429 del proveedor respeta Retry-After (limpio el contador propio primero).
    from src.infrastructure.redis.cache import _get_redis

    redis = await _get_redis()
    keys = await redis.keys(f"mkt:rl:{UUID(org['organization_id']).hex}:{install_id}:*")
    if keys:
        await redis.delete(*keys)
    FakeClient.status = 429
    FakeClient.headers = {"Retry-After": "42"}
    third = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/{slug}.createorder/execute",
        headers={**h, "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"customerId": 1}},
    )
    assert third.json()["ok"] is False
    assert third.json()["error_code"] == "PROVIDER_RATE_LIMITED"
    assert third.json()["retry_after"] == 42
