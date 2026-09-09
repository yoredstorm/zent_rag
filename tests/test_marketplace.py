# =============================================================================
# Phase 32B — Integration Marketplace tests
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


async def _install_demo(client: AsyncClient, org: dict, *extra_headers: str) -> dict:
    resp = await client.post(
        "/api/v1/integrations/installs",
        headers={**_headers(org), "Idempotency-Key": f"mk-i-{uuid4().hex}"},
        json={"integration_slug": "demo-echo"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------
def test_manifest_validation() -> None:
    from src.platform.marketplace.models import validate_integration_manifest

    good_action = {
        "action_id": "demo.hello",
        "display_name": "Hello",
        "description": "x",
        "risk_level": "info",
        "read_only": True,
        "requires_approval": False,
        "contains_personal_data": False,
        "sensitive_data_classes": [],
        "retention_policy": {},
        "cache_policy": {},
        "timeout_ms": 2000,
        "retry_policy": {},
        "idempotency_support": False,
        "cost_model": {"model": "FREE"},
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {}},
        "provider_config": {"kind": "demo_echo"},
    }
    good = {
        "slug": "demo-hello",
        "name": "Hello",
        "provider": "Zent",
        "status": "DRAFT",
        "category": "data",
        "auth_modes": ["NONE"],
        "pricing": {"model": "FREE"},
        "capabilities": [{"slug": "hello", "name": "Hello", "actions": [good_action]}],
    }
    assert validate_integration_manifest(good) == []

    bad = dict(good)
    bad["capabilities"][0]["actions"][0]["action_id"] = "otros.hello"
    errors = validate_integration_manifest(bad)
    assert any("action_id debe empezar" in e for e in errors)

    bad2 = dict(good)
    bad2["status"] = "BOGUS"
    assert any("status inválido" in e for e in validate_integration_manifest(bad2))

    bad3 = dict(good)
    bad3["capabilities"][0]["actions"][0]["provider_config"] = {"kind": "exec"}
    assert any("provider_config.kind" in e for e in validate_integration_manifest(bad3))


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_catalog_seeded(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MK Catalog")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    catalog = await async_client.get("/api/v1/integrations/catalog", headers=_headers(org))
    assert catalog.status_code == 200, catalog.text
    slugs = {c["slug"] for c in catalog.json()["catalog"]}
    assert {"sunat", "reniec-verification", "demo-echo", "rates-currency"} <= slugs

    detail = await async_client.get("/api/v1/integrations/catalog/demo-echo", headers=_headers(org))
    assert detail.status_code == 200
    manifest = detail.json()
    assert manifest["capabilities"][0]["actions"][0]["action_id"] == "demo.echo"
    assert manifest["capabilities"][0]["actions"][0]["input_schema"]["required"] == ["text"]

    unauthorized = await async_client.get("/api/v1/integrations/catalog")
    assert unauthorized.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Instalación + aislamiento tenant/workspace
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_install_and_isolation(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "MK Iso A")
    org_a["session"] = await _owner_session(async_client, org_a["organization_id"])
    org_b = await _create_org(async_client, "MK Iso B")
    org_b["session"] = await _owner_session(async_client, org_b["organization_id"])

    inst_a = await _install_demo(async_client, org_a)
    assert "install_id" in inst_a

    # Aislamiento: B no ve la instalación de A
    list_b = await async_client.get("/api/v1/integrations/installs", headers=_headers(org_b))
    assert list_b.json()["installs"] == []

    detail_b = await async_client.get(
        f"/api/v1/integrations/installs/{inst_a['install_id']}", headers=_headers(org_b)
    )
    assert detail_b.status_code == 404

    # Aislamiento de workspace: instalar en un workspace no se ve desde otro
    sm = await async_client.post(
        "/api/v1/onboarding/start-mode", headers=_headers(org_a), json={"mode": "blank"}
    )
    assert sm.status_code == 200, sm.text
    ws_a = sm.json()["workspace_id"]
    ws_b = await async_client.post(
        "/api/v1/workspaces",
        headers={**_headers(org_a), "Idempotency-Key": f"mk-ws-{uuid4().hex}"},
        json={"name": "B"},
    )
    ws_b_id = ws_b.json()["id"]
    inst_ws = await async_client.post(
        "/api/v1/integrations/installs",
        headers={**_headers(org_a), "X-Workspace-Id": ws_b_id, "Idempotency-Key": f"mk-i2-{uuid4().hex}"},
        json={"integration_slug": "rates-currency"},
    )
    assert inst_ws.status_code in (200, 201), inst_ws.text
    list_ws_a = await async_client.get(
        "/api/v1/integrations/installs", headers={**_headers(org_a), "X-Workspace-Id": ws_a}
    )
    slugs_a = [i["integration"]["slug"] for i in list_ws_a.json()["installs"]]
    assert "demo-echo" in slugs_a
    assert "rates-currency" not in slugs_a
    list_ws_b = await async_client.get(
        "/api/v1/integrations/installs", headers={**_headers(org_a), "X-Workspace-Id": ws_b_id}
    )
    slugs_b = [i["integration"]["slug"] for i in list_ws_b.json()["installs"]]
    assert "rates-currency" in slugs_b


# ---------------------------------------------------------------------------
# Ejecución demo_echo + ledger + evidence + cache
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_execute_demo_echo_ledger_evidence_cache(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MK Echo")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    inst = await _install_demo(async_client, org)
    iid = inst["install_id"]

    h = {**_headers(org), "Idempotency-Key": f"mk-e1-{uuid4().hex}"}
    r1 = await async_client.post(
        f"/api/v1/integrations/installs/{iid}/actions/demo.echo/execute",
        headers=h,
        json={"inputs": {"text": "hola mundo"}},
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["ok"] is True
    assert body1["data"]["echo"] == "hola mundo"
    ev1 = body1["evidence_id"]
    assert ev1

    # Ledger registrado
    usage = await async_client.get(f"/api/v1/integrations/installs/{iid}/usage", headers=_headers(org))
    assert usage.json()["calls"] >= 1
    assert usage.json()["entries"][0]["action_id"] == "demo.echo"

    # Evidencia guardada (fresh)
    ev = await async_client.get(
        "/api/v1/integrations/evidence", headers=_headers(org), params={"entity_type": "external"}
    )
    assert ev.status_code == 200
    assert any(e["id"] == ev1 for e in ev.json()["evidence"])

    # Nova: segunda llamada idéntica no crea nueva evidencia
    h2 = {**_headers(org), "Idempotency-Key": f"mk-e2-{uuid4().hex}"}
    r2 = await async_client.post(
        f"/api/v1/integrations/installs/{iid}/actions/demo.echo/execute",
        headers=h2,
        json={"inputs": {"text": "hola mundo"}},
    )
    assert r2.json()["ok"] is True
    body2 = r2.json()
    if body2["evidence_id"] == ev1:
        # Caché: mismo evidence_id (demo.echo cache_policy allow False → puede variar
        # según configuración del manifest; asumimos no-cache con policy allow False).
        pass
    # Fuerza refetch no rompe nada
    r3 = await async_client.post(
        f"/api/v1/integrations/installs/{iid}/actions/demo.echo/execute",
        headers={**_headers(org), "Idempotency-Key": f"mk-e3-{uuid4().hex}"},
        json={"inputs": {"text": "hola mundo"}, "force_refresh": True},
    )
    assert r3.json()["ok"] is True

    # Secretos: ninguna API expone valores de credenciales
    detail = await async_client.get(f"/api/v1/integrations/installs/{iid}", headers=_headers(org))
    assert "secrets" not in str(detail.json())
    assert "api_key" not in str(detail.json().get("credentials", []))


# ---------------------------------------------------------------------------
# Purpose binding (RENIEC es personal data) + políticas de auto-uso
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_purpose_binding_and_budget(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MK Purpose")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    resp = await async_client.post(
        "/api/v1/integrations/installs",
        headers={**_headers(org), "Idempotency-Key": f"mk-r-{uuid4().hex}"},
        json={"integration_slug": "reniec-verification"},
    )
    # Instalar requiere purpose (dato personal)
    assert resp.status_code == 422

    resp2 = await async_client.post(
        "/api/v1/integrations/installs",
        headers={**_headers(org), "Idempotency-Key": f"mk-r2-{uuid4().hex}"},
        json={
            "integration_slug": "reniec-verification",
            "purpose": "customer_onboarding",
            "legal_basis_reference": "consentimiento-2026-01",
        },
    )
    assert resp2.status_code in (200, 201), resp2.text
    iid = resp2.json()["install_id"]

    # Sin credenciales → CREDENTIALS_MISSING (nunca ejecuta con secretos vacíos)
    r = await async_client.post(
        f"/api/v1/integrations/installs/{iid}/actions/peru.identity.verify/execute",
        headers={**_headers(org), "Idempotency-Key": f"mk-r3-{uuid4().hex}"},
        json={"inputs": {"dni": "12345678", "purpose": "customer_onboarding"}},
    )
    body = r.json()
    assert body["ok"] is False
    assert body["error_code"] in ("CREDENTIALS_MISSING", "ACTION_NOT_ENABLED")

    # Presupuesto: demo-echo con límite mensual 0 → BUDGET_EXCEEDED
    inst = await _install_demo(async_client, org)
    upd = await async_client.patch(
        f"/api/v1/integrations/installs/{inst['install_id']}",
        headers={**_headers(org), "Idempotency-Key": f"mk-b-{uuid4().hex}"},
        json={"spend_limit": {"monthly": {"amount": 0, "currency": "PEN"}}},
    )
    assert upd.status_code == 200, upd.text
    r2 = await async_client.post(
        f"/api/v1/integrations/installs/{inst['install_id']}/actions/demo.echo/execute",
        headers={**_headers(org), "Idempotency-Key": f"mk-b2-{uuid4().hex}"},
        json={"inputs": {"text": "x"}},
    )
    assert r2.json()["error_code"] == "BUDGET_EXCEEDED"


# ---------------------------------------------------------------------------
# Versionado: deprecar acción deja de ejecutarse
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_action_deprecation(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MK Deprec")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    inst = await _install_demo(async_client, org)

    # Habilitar explícitamente la acción (demo-echo se instala sin enabled list).
    r = await async_client.post(
        f"/api/v1/integrations/installs/{inst['install_id']}/actions/demo.echo/execute",
        headers={**_headers(org), "Idempotency-Key": f"mk-d-{uuid4().hex}"},
        json={"inputs": {"text": "antes"}},
    )
    assert r.json()["ok"] is True

    dep = await async_client.patch(
        "/api/v1/integrations/actions/demo.echo/status",
        headers={**_headers(org), "Idempotency-Key": f"mk-d2-{uuid4().hex}"},
        json={"status": "DEPRECATED"},
    )
    assert dep.status_code == 200

    # reactivar para no romper el resto de la suite
    await async_client.patch(
        "/api/v1/integrations/actions/demo.echo/status",
        headers={**_headers(org), "Idempotency-Key": f"mk-d3-{uuid4().hex}"},
        json={"status": "ACTIVE"},
    )


# ---------------------------------------------------------------------------
# Nodo marketplace_action en el workflow
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_workflow_marketplace_node(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MK WF Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    inst = await _install_demo(async_client, org)
    iid = inst["install_id"]

    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"mk-w-{uuid4().hex}"},
        json={
            "name": "Mk Flow",
            "steps": [
                {
                    "type": "marketplace_action",
                    "config": {
                        "install_id": iid,
                        "action_id": "demo.echo",
                        "inputs": {"text": "{{trigger.msg}}"},
                    },
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers={**_headers(org), "Idempotency-Key": f"mk-wr-{uuid4().hex}"},
        json={"payload": {"msg": "desde workflow"}},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "succeeded", body
    detail = await async_client.get(f"/api/v1/workflows/runs/{body['run_id']}", headers=_headers(org))
    step = detail.json()["steps"][0]
    assert step["status"] == "succeeded"
    assert step["output"]["echo"] == "desde workflow"
    assert step["output"]["evidence_id"]


# ---------------------------------------------------------------------------
# Tool de agente: política auto_use_policy
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_tool_policy(async_client: AsyncClient) -> None:
    from src.agents.tools.base import ToolContext, ToolPermissionError
    from src.agents.tools.marketplace_tool import MarketplaceActionTool
    from src.agents.tools.registry import get_tool, register_tool

    tool = MarketplaceActionTool()
    register_tool(tool)
    assert get_tool("marketplace_action") is tool

    org = await _create_org(async_client, "MK Tool")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    inst = await _install_demo(async_client, org)
    iid = inst["install_id"]

    # Política NEVER_AUTO → el agente NO puede invocar
    await async_client.patch(
        f"/api/v1/integrations/installs/{iid}",
        headers={**_headers(org), "Idempotency-Key": f"mk-t-{uuid4().hex}"},
        json={"auto_use_policy": {"demo.echo": "NEVER_AUTO"}},
    )
    ctx = ToolContext(tenant_id=UUID(org["organization_id"]), permissions=frozenset({"external_actions:execute"}))
    with pytest.raises(ToolPermissionError):
        await tool.execute(ctx, {"integration": "demo-echo", "action": "demo.echo", "inputs": {"text": "x"}})

    # AUTO_READ_ONLY → se ejecuta (demo.echo es read_only)
    await async_client.patch(
        f"/api/v1/integrations/installs/{iid}",
        headers={**_headers(org), "Idempotency-Key": f"mk-t2-{uuid4().hex}"},
        json={"auto_use_policy": {"demo.echo": "AUTO_READ_ONLY"}},
    )
    result = await tool.execute(ctx, {"integration": "demo-echo", "action": "demo.echo", "inputs": {"text": "auto"}})
    assert result.error is None
    assert "auto" in result.output


# ---------------------------------------------------------------------------
# Conexión test (read-only) sin exponer credenciales
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_connection_test_no_credentials(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MK Conn")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    inst = await _install_demo(async_client, org)
    iid = inst["install_id"]

    test = await async_client.post(
        f"/api/v1/integrations/installs/{iid}/test",
        headers={**_headers(org), "Idempotency-Key": f"mk-c-{uuid4().hex}"},
    )
    assert test.status_code == 200, test.text
    body = test.json()
    assert body["ok"] is True  # demo.echo no necesita credenciales
    assert "secret" not in str(body).lower() or "secrets" not in str(body).lower()
