# =============================================================================
# Integration Experience (Fases A-E) — manifest v2, provider public_rest,
# PokéAPI / Open-Meteo / Demo Records, formularios dinámicos y recetas demo.
# Los HTTP calls se mockean: CI no depende de APIs externas.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.marketplace.demo_integrations import (
    DEMO_RECIPES,
    ensure_demo_integrations,
    ensure_demo_recipes,
)
from src.platform.marketplace.models import (
    validate_action_manifest,
    validate_event_manifest,
    validate_integration_manifest,
)
from src.platform.marketplace.runtime import _execute_public_rest
from src.platform.workflows.capabilities import ports_for_action
from tests.test_workflows import _create_org, _headers, _owner_session


# ---------------------------------------------------------------------------
# Manifest v2
# ---------------------------------------------------------------------------
def test_manifest_v2_accepts_events() -> None:
    manifest = {
        "slug": "acme",
        "name": "Acme",
        "category": "operations",
        "status": "PUBLISHED",
        "auth_modes": ["NONE"],
        "capabilities": [
            {
                "slug": "orders",
                "actions": [
                    {
                        "action_id": "acme.orders.list",
                        "display_name": "Listar pedidos",
                        "input_schema": {"type": "object", "properties": {}},
                        "output_schema": {"type": "object", "properties": {}},
                        "provider_config": {
                            "kind": "public_rest",
                            "base_url": "https://api.acme.test/v1",
                            "path_template": "/orders",
                        },
                        "timeout_ms": 5000,
                    }
                ],
            }
        ],
        "events": [
            {
                "id": "acme.order.created",
                "business_name": "Se creó un pedido",
                "description": "Nuevo pedido en Acme.",
                "event_schema": {"type": "object", "properties": {"order": {"type": "string"}}},
                "delivery_mode": "webhook",
                "permissions": ["orders:read"],
            }
        ],
    }
    assert validate_integration_manifest(manifest) == []


def test_manifest_v2_rejects_bad_events_and_actions() -> None:
    errors = validate_event_manifest(
        {"id": "other.event", "business_name": "", "event_schema": {"type": "string"}, "delivery_mode": "carrier-pigeon"},
        "acme",
    )
    assert any("debe empezar" in e for e in errors)
    assert any("business_name" in e for e in errors)
    assert any("event_schema" in e for e in errors)
    assert any("delivery_mode" in e for e in errors)

    action_errors = validate_action_manifest(
        {
            "action_id": "acme.x",
            "display_name": "X",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "provider_config": {"kind": "public_rest", "base_url": "http://insecure.test", "path_template": ""},
        },
        "acme",
    )
    assert any("base_url https" in e for e in action_errors)
    assert any("path_template" in e for e in action_errors)


# ---------------------------------------------------------------------------
# Provider public_rest (SSRF, mapping y query)
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, payload: Any, status: int = 200, text: str | None = None) -> None:
        self._payload = payload
        self.status_code = status
        self.text = text if text is not None else json.dumps(payload)

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("sin json")
        return self._payload


class FakeClient:
    payload: Any = {}
    status: int = 200
    calls: list[dict] = []

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(self, url: str, params: dict | None = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "GET", "url": url, "params": params or {}, "headers": headers or {}})
        return FakeResponse(FakeClient.payload, FakeClient.status)

    async def post(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "POST", "url": url, "json": json, "headers": headers or {}})
        return FakeResponse(FakeClient.payload, FakeClient.status)

    async def put(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "PUT", "url": url, "json": json, "headers": headers or {}})
        return FakeResponse(FakeClient.payload, FakeClient.status)

    async def patch(self, url: str, json: Any = None, headers: dict | None = None) -> FakeResponse:
        FakeClient.calls.append({"method": "PATCH", "url": url, "json": json, "headers": headers or {}})
        return FakeResponse(FakeClient.payload, FakeClient.status)


def _pokemon_payload() -> dict:
    return {
        "name": "pikachu",
        "id": 25,
        "height": 4,
        "weight": 60,
        "types": [{"slot": 1, "type": {"name": "electric"}}],
        "abilities": [{"ability": {"name": "static"}}],
        "stats": [{"base_stat": 55, "stat": {"name": "hp"}}],
    }


@pytest.mark.asyncio
async def test_public_rest_maps_business_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = _pokemon_payload()
    FakeClient.status = 200
    FakeClient.calls = []

    action = {
        "provider_config": {
            "kind": "public_rest",
            "base_url": "https://pokeapi.co/api/v2",
            "path_template": "/pokemon/{name}",
            "method": "GET",
            "output_map": {"name": "name", "id": "id", "types": "types"},
        },
        "timeout_ms": 5000,
    }
    result = await _execute_public_rest(action, {}, {"name": "pikachu"}, uuid4())
    assert result["ok"] is True
    assert result["data"]["name"] == "pikachu"
    assert result["data"]["id"] == 25
    assert result["data"]["source"] == "pokeapi.co"
    assert FakeClient.calls[0]["url"] == "https://pokeapi.co/api/v2/pokemon/pikachu"


@pytest.mark.asyncio
async def test_public_rest_get_merges_static_query_and_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = {"current": {"temperature_2m": 31.5}}
    FakeClient.status = 200
    FakeClient.calls = []

    action = {
        "provider_config": {
            "kind": "public_rest",
            "base_url": "https://api.open-meteo.com/v1",
            "path_template": "/forecast",
            "method": "GET",
            "query": {"current": "temperature_2m", "timezone": "auto"},
            "output_map": {"temperature": "current.temperature_2m"},
        },
        "timeout_ms": 5000,
    }
    result = await _execute_public_rest(
        action, {}, {"latitude": -12.0464, "longitude": -77.0428}, uuid4()
    )
    params = FakeClient.calls[0]["params"]
    assert params["current"] == "temperature_2m"
    assert params["latitude"] == -12.0464
    assert result["data"]["temperature"] == 31.5


@pytest.mark.asyncio
async def test_public_rest_blocks_ssrf_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    action = {
        "provider_config": {
            "kind": "public_rest",
            "base_url": "https://127.0.0.1",
            "path_template": "/admin",
            "method": "GET",
        },
        "timeout_ms": 5000,
    }
    with pytest.raises(Exception) as exc:
        await _execute_public_rest(action, {}, {}, uuid4())
    assert "127.0.0.1" in str(exc.value) or "no permit" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_public_rest_post_and_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = {"id": 101, "title": "demo"}
    FakeClient.status = 201
    FakeClient.calls = []
    action = {
        "provider_config": {
            "kind": "public_rest",
            "base_url": "https://jsonplaceholder.typicode.com",
            "path_template": "/posts",
            "method": "POST",
            "output_map": {"id": "id", "title": "title"},
        },
        "timeout_ms": 5000,
    }
    result = await _execute_public_rest(action, {}, {"title": "demo", "userId": 1}, uuid4())
    assert FakeClient.calls[0]["method"] == "POST"
    assert result["data"]["id"] == 101

    FakeClient.status = 500
    FakeClient.payload = {"error": "boom"}
    failure = await _execute_public_rest(action, {}, {"title": "demo"}, uuid4())
    assert failure["_http_error"] is True


# ---------------------------------------------------------------------------
# API: seeding, formularios dinámicos, ejecución y recetas
# ---------------------------------------------------------------------------
async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


@pytest.mark.asyncio
async def test_demo_seeding_is_idempotent_and_forms_are_dynamic(async_client: AsyncClient) -> None:
    first = await ensure_demo_integrations()
    second = await ensure_demo_integrations()
    assert first["integrations"] == 3 == second["integrations"]
    assert first["actions"] == 10 == second["actions"]
    assert await ensure_demo_recipes() == len(DEMO_RECIPES)

    ports = await ports_for_action("pokemon.get")
    assert ports is not None
    params = {p["key"]: p for p in ports["input_parameters"]}
    assert params["inputs.name"]["required"] is True
    assert params["inputs.name"]["label"] == "Pokémon"
    assert ports["outputs"]["name"]["x-business-label"] == "Nombre"


@pytest.mark.asyncio
async def test_execute_pokemon_action_and_template_install(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _org(async_client, "Integration Experience")
    h = _headers(org)
    await ensure_demo_integrations()
    await ensure_demo_recipes()

    install = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**h, "Idempotency-Key": f"inst-{uuid4().hex}"},
        json={"integration_slug": "pokeapi"},
    )
    assert install.status_code == 200, install.text
    install_id = install.json()["install_id"]

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = _pokemon_payload()
    FakeClient.status = 200

    executed = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/pokemon.get/execute",
        headers={**h, "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"name": "pikachu"}, "force_refresh": True},
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["ok"] is True, body
    assert body["data"]["name"] == "pikachu"
    assert body["data"]["types"]

    # La receta instala la integración demo y reemplaza el placeholder.
    made = await async_client.post(
        "/api/v1/workflows/templates/pokemon-analyst/install",
        headers={**h, "Idempotency-Key": f"tpl-{uuid4().hex}"},
    )
    assert made.status_code == 200, made.text
    workflow_id = made.json()["workflow_id"]
    detail = await async_client.get(f"/api/v1/workflows/{workflow_id}", headers=h)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert "{{_pack." not in json.dumps(payload["steps"])
    first_step = payload["steps"][0]
    assert first_step["type"] == "marketplace_action"
    assert first_step["config"]["install_id"] == install_id


@pytest.mark.asyncio
async def test_cross_tenant_action_execution_is_denied(
    async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_a = await _org(async_client, "Integration Tenant A")
    org_b = await _org(async_client, "Integration Tenant B")
    await ensure_demo_integrations()

    install = await async_client.post(
        "/api/v1/workflows/marketplace/install",
        headers={**_headers(org_a), "Idempotency-Key": f"inst-{uuid4().hex}"},
        json={"integration_slug": "jsonplaceholder"},
    )
    assert install.status_code == 200, install.text
    install_id = install.json()["install_id"]

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    FakeClient.payload = {"id": 1, "name": "Demo"}
    cross = await async_client.post(
        f"/api/v1/integrations/installs/{install_id}/actions/demo_records.get_user/execute",
        headers={**_headers(org_b), "Idempotency-Key": f"exec-{uuid4().hex}"},
        json={"inputs": {"id": 1}, "force_refresh": True},
    )
    assert cross.status_code == 200
    assert cross.json()["ok"] is False
    assert cross.json()["error_code"] == "NOT_INSTALLED"


@pytest.mark.asyncio
async def test_demo_recipes_are_listed(async_client: AsyncClient) -> None:
    org = await _org(async_client, "Integration Recipes")
    await ensure_demo_recipes()
    templates = await async_client.get(
        "/api/v1/workflows/templates", headers=_headers(org)
    )
    assert templates.status_code == 200, templates.text
    slugs = {t["slug"] for t in templates.json()["templates"]}
    assert {"pokemon-analyst", "weather-heat-alert", "weather-logistics-analyst"} <= slugs
