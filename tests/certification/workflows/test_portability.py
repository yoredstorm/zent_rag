# =============================================================================
# Certification — portabilidad del Gold Workflow
# =============================================================================
# EXPORT → IMPORT (tenant limpio) → DEPENDENCY RESOLUTION → RECONFIGURE →
# EXECUTE. Un workflow portable depende de CAPACIDADES, nunca de tablas,
# acciones concretas ni credenciales.
# =============================================================================
from __future__ import annotations

import pytest
from httpx import AsyncClient

from src.platform.commerce import contracts as C
from tests.certification.workflows.gold_support import (
    CATALOG,
    bind_commerce,
    bind_conversation,
    configure_sandbox_payments,
    fetch_orders,
    install_funnel,
    instance,
    make_tenant,
    ready_tenant,
    say,
    seed_catalog,
    start_funnel,
)
from tests.test_workflows import _headers


def _statuses(report: dict) -> dict[str, str]:
    return {item["ref"]: item["status"] for item in report.get("items") or []}


async def _inspect(client: AsyncClient, org: dict, package: dict) -> dict:
    resp = await client.post(
        "/api/v1/workflows/import/inspect", headers=_headers(org), json={"package": package}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _import(client: AsyncClient, org: dict, package: dict) -> dict:
    return await client.post(
        "/api/v1/workflows/import", headers=_headers(org), json={"package": package}
    )


@pytest.mark.asyncio
async def test_export_import_dependency_resolution_and_execution(
    async_client: AsyncClient,
) -> None:
    # --- Tenant A: embudo listo y exportado ---------------------------------
    tenant_a = await ready_tenant(async_client, "Portable A", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, tenant_a)
    exported = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/export", headers=_headers(tenant_a)
    )
    assert exported.status_code == 200, exported.text
    package = exported.json().get("package") or exported.json()
    assert package["schema"] == "zent.workflow.package/v1"
    assert package["security"]["contains_secrets"] is False
    refs = {dep["ref"] for dep in package["dependencies"]}
    assert C.CAP_CATALOG_SEARCH in refs
    assert C.CAP_STOCK_GET in refs
    assert C.CAP_PAYMENT_CHECKOUT_CREATE in refs
    assert "conversation.send" in refs
    events = {item["ref"] for item in package["events"]}
    assert C.EVENT_PAYMENT_SUCCEEDED in events, events
    assert "conversation.message" in events, events
    assert package["parameters"]["currency"] == "PEN"
    assert package["parameters"]["reservation_policy"] in C.RESERVATION_POLICIES

    # --- Tenant B limpio: readiness con huecos ------------------------------
    tenant_b = await make_tenant(async_client, "Portable B")
    report = await _inspect(async_client, tenant_b, package)
    statuses = _statuses(report)
    assert statuses[C.CAP_CATALOG_SEARCH] == "MISSING", statuses
    assert statuses[C.CAP_STOCK_GET] == "MISSING", statuses
    # Pago: MISSING si no hay proveedor publicado en el catálogo global, o
    # NEEDS_CREDENTIALS si lo hay pero el tenant no lo configuró (IZIPAY
    # disponible pero no configurado). Ambos bloquean la publicación.
    assert statuses[C.CAP_PAYMENT_CHECKOUT_CREATE] in ("MISSING", "NEEDS_CREDENTIALS"), statuses
    assert statuses["conversation.message"] == "RESOLVED", statuses
    # La mensajería la provee Zent: no es un hueco del tenant.
    assert statuses["conversation.send"] == "RESOLVED", statuses
    assert report["blocking"] > 0

    blocked = await _import(async_client, tenant_b, package)
    assert blocked.status_code == 409, blocked.text
    blocked_body = blocked.json()
    assert "requisitos sin resolver" in str(blocked_body.get("message") or ""), blocked_body

    # --- Binding catálogo ---------------------------------------------------
    await seed_catalog(
        tenant_b["organization_id"],
        [
            {"sku": "B-ARROZ", "name": "Arroz del Sur", "price": 6.10, "unit": "KG", "stock": 9},
        ],
    )
    await bind_commerce(tenant_b["organization_id"], [C.CAP_CATALOG_SEARCH, C.CAP_CATALOG_GET])
    report = await _inspect(async_client, tenant_b, package)
    statuses = _statuses(report)
    assert statuses[C.CAP_CATALOG_SEARCH] == "RESOLVED", statuses
    assert statuses[C.CAP_STOCK_GET] == "MISSING", statuses

    # --- Binding inventario -------------------------------------------------
    await bind_commerce(
        tenant_b["organization_id"],
        [C.CAP_STOCK_GET, C.CAP_STOCK_RESERVE, C.CAP_STOCK_RELEASE, C.CAP_STOCK_COMMIT],
    )
    report = await _inspect(async_client, tenant_b, package)
    statuses = _statuses(report)
    assert statuses[C.CAP_STOCK_GET] == "RESOLVED", statuses
    assert statuses[C.CAP_PAYMENT_CHECKOUT_CREATE] in ("MISSING", "NEEDS_CREDENTIALS"), statuses

    # --- "Instalar y configurar IZIPAY" (proveedor de pago del tenant) ------
    await bind_commerce(
        tenant_b["organization_id"],
        [C.CAP_ORDER_CREATE, C.CAP_CART_QUOTE, C.CAP_ORDER_MARK_PAID, C.CAP_ORDER_CANCEL],
    )
    await bind_conversation(tenant_b["organization_id"])
    await configure_sandbox_payments(tenant_b["organization_id"])
    report = await _inspect(async_client, tenant_b, package)
    statuses = _statuses(report)
    assert statuses[C.CAP_PAYMENT_CHECKOUT_CREATE] == "RESOLVED", statuses
    assert "payment.succeeded" in statuses and statuses["payment.succeeded"] == "RESOLVED"
    assert report["blocking"] == 0, report

    # --- Import (draft) + publicar ------------------------------------------
    imported = await _import(async_client, tenant_b, package)
    assert imported.status_code == 200, imported.text
    new_workflow_id = imported.json().get("workflow_id") or imported.json().get("id")
    assert new_workflow_id
    published = await async_client.post(
        f"/api/v1/workflows/{new_workflow_id}/publish", headers=_headers(tenant_b)
    )
    # Un flujo importado con efectos externos no publica sin certificado
    # sandbox/provider. La ejecución de abajo valida el grafo en draft.
    assert published.status_code == 409, published.text
    assert published.json()["details"]["code"] == "release_blocked"
    assert "certification_required" in str(published.json()["details"]["blockers"])

    # --- Ejecutar el flujo importado con los datos de B ---------------------
    started = await start_funnel(
        async_client, tenant_b, str(new_workflow_id), text="quiero 1 kilo de arroz"
    )
    state = await instance(async_client, tenant_b, started["instance_id"])
    assert state["status"] == "WAITING"
    assert state["current_node_id"] == "esperar_mas"
    cart = (state.get("state") or {}).get("cart", {}).get("items") or []
    assert [line["name"] for line in cart] == ["Arroz del Sur"], cart
    assert cart[0]["unit_price"] == 6.10
    assert cart[0]["unit"] == "KG"

    # Conversación completa en el tenant nuevo: confirmar y cobrar.
    await say(
        async_client,
        tenant_b,
        started["instance_id"],
        text="no, nada más",
        conversation_id=started["conversation_id"],
    )
    state = await instance(async_client, tenant_b, started["instance_id"])
    assert state["current_node_id"] == "esperar_confirmacion", state
    await say(
        async_client,
        tenant_b,
        started["instance_id"],
        text="sí",
        conversation_id=started["conversation_id"],
    )
    state = await instance(async_client, tenant_b, started["instance_id"])
    assert state["current_node_id"] == "esperar_pago", state
    orders = await fetch_orders(async_client, tenant_b)
    assert len(orders) == 1
    assert orders[0]["total"] == pytest.approx(6.10, abs=0.01)
    assert orders[0]["currency"] == "PEN"
    assert orders[0]["workflow_instance_id"] == started["instance_id"]


@pytest.mark.asyncio
async def test_import_rejects_package_with_secrets(async_client: AsyncClient) -> None:
    tenant = await make_tenant(async_client, "Portable Unsafe")
    package = {
        "schema": "zent.workflow.package/v1",
        "package_version": "1.0.0",
        "metadata": {"name": "Con secretos"},
        "workflow": {"graph": {"workflow_version": 2, "nodes": [], "edges": [], "entrypoints": []}},
        "capabilities": [],
        "events": [],
        "security": {"contains_secrets": True},
        "api_key": "sk_live_no_debe_viajar",
    }
    report = await _inspect(async_client, tenant, package)
    statuses = {item["ref"]: item["status"] for item in report.get("items") or []}
    assert "UNSAFE" in statuses.values(), report
    response = await _import(async_client, tenant, package)
    assert response.status_code == 409, response.text
