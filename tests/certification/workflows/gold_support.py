# =============================================================================
# Fixtures del Gold Workflow (Retail Sales Funnel)
# =============================================================================
# Monta un tenant real y ejecutable: catálogo con precios reales, stock,
# capacidades bindeadas y un proveedor de pago sandbox firmado. Nada simulado
# salvo la pasarela externa (sandbox determinista = mismo contrato, sin red).
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce import contracts as C
from src.platform.commerce import sales_funnel
from src.platform.commerce import store as commerce_store
from src.platform.commerce.payments import service as payment_service
from src.platform.workflows.bindings import upsert_binding
from tests.test_workflows import _create_org, _headers, _owner_session

#: Catálogo de referencia del escenario (precios reales del tenant).
CATALOG: list[dict[str, Any]] = [
    {
        "sku": "ARZ-COS-1KG",
        "name": "Arroz Costeño",
        "price": 5.90,
        "unit": "KG",
        "aliases": ["arroz", "costeno"],
        "stock": 40,
    },
    {
        "sku": "ARZ-PAI-1KG",
        "name": "Arroz Paisana",
        "price": 5.50,
        "unit": "KG",
        "aliases": ["arroz", "paisana"],
        "stock": 25,
    },
    {
        "sku": "ARZ-INT-1KG",
        "name": "Arroz Integral",
        "price": 7.20,
        "unit": "KG",
        "aliases": ["arroz", "integral"],
        "stock": 15,
    },
    {
        "sku": "LEC-GLO-1L",
        "name": "Leche Gloria",
        "price": 4.20,
        "unit": "L",
        "aliases": ["leche", "gloria"],
        "stock": 30,
    },
]

SANDBOX_WEBHOOK_SECRET = "sandbox-webhook-secret-cert"


async def make_tenant(client: AsyncClient, name: str) -> dict:
    """Tenant con sesión de owner lista para operar."""
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


async def seed_catalog(organization_id: str, catalog: list[dict[str, Any]] | None = None) -> None:
    org = UUID(str(organization_id))
    for item in catalog or CATALOG:
        await commerce_store.upsert_product(
            org,
            sku=item["sku"],
            name=item["name"],
            price=item["price"],
            currency=item.get("currency", "PEN"),
            unit=item.get("unit", "UNIT"),
            aliases=item.get("aliases") or [],
            category=item.get("category"),
            stock=item.get("stock", 0),
        )


async def bind_commerce(organization_id: str, capabilities: list[str] | None = None) -> None:
    """Bindea capacidades de negocio al provider `commerce` (datos de Zent)."""
    org = UUID(str(organization_id))
    for capability in capabilities or C.COMMERCE_CAPABILITIES:
        contract = C.contract_for(capability)
        await upsert_binding(
            org,
            capability,
            C.COMMERCE_PROVIDER_KIND,
            config={"warehouse": "main", "currency": "PEN"},
            contract_input_schema=contract.get("input") or {},
            contract_output_schema=contract.get("output") or {},
        )


async def bind_conversation(organization_id: str) -> None:
    org = UUID(str(organization_id))
    await upsert_binding(
        org,
        "conversation.send",
        "conversation",
        config={"channel": "in_app"},
        contract_input_schema={"type": "object", "required": ["message"]},
        contract_output_schema={"type": "object"},
    )


async def configure_sandbox_payments(
    organization_id: str, *, webhook_secret: str = SANDBOX_WEBHOOK_SECRET
) -> dict:
    """Configura el proveedor sandbox y deja las capacidades de pago en verde."""
    return await payment_service.configure_provider(
        UUID(str(organization_id)),
        provider="sandbox",
        secrets={"webhook_secret": webhook_secret},
        mode="test",
        config={"payment_page_url": "https://sandbox.zent.local/pay"},
    )


async def seed_sales_agent(organization_id: str) -> str:
    """Agente de ventas real del tenant, listo para el planner.

    No es un mock del LLM: es una fila `agents` con propósito y tools; el
    planner la descubre por `agent.search` y el runtime la ejecuta si el plan
    la elige. El test real de generación necesita un tenant que pueda cumplir
    "quiero un agente de ventas".
    """
    agent_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO agents (id, organization_id, name, status, is_active, "
                "description, system_prompt, tools, config_json) "
                "VALUES (:id, :oid, :name, 'ready', true, :desc, :prompt, "
                "CAST(:tools AS jsonb), CAST(:config AS jsonb))"
            ),
            {
                "id": agent_id,
                "oid": UUID(str(organization_id)),
                "name": "Asesor de ventas",
                "desc": "Atiende consultas de catálogo, carrito y cierre de venta.",
                "prompt": (
                    "Eres un asesor de ventas. Interpreta la necesidad del cliente, "
                    "consulta catálogo/stock y nunca inventes precios ni stock."
                ),
                "tools": json.dumps(["search_knowledge", "query_database"]),
                "config": json.dumps(
                    {
                        "purpose": (
                            "Interpretar pedidos de productos, detectar cambios de "
                            "opinión y confirmar el resumen antes de cobrar."
                        ),
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "selection": {"type": "object"},
                                "confirmed": {"type": "boolean"},
                                "valid": {"type": "boolean"},
                            },
                        },
                    }
                ),
            },
        )
        await session.commit()
    finally:
        await session.close()
    return str(agent_id)


async def seed_knowledge_base(organization_id: str) -> str:
    kb_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (id, organization_id, name) "
                "VALUES (:id, :oid, :name)"
            ),
            {
                "id": kb_id,
                "oid": UUID(str(organization_id)),
                "name": "Base de conocimiento de certificación",
            },
        )
        await session.commit()
    finally:
        await session.close()
    return str(kb_id)


async def seed_managed_db(organization_id: str) -> None:
    session = await get_async_session()
    try:
        workspace = (
            await session.execute(
                text(
                    "SELECT id FROM workspaces WHERE organization_id = :oid "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"oid": str(organization_id)},
            )
        ).fetchone()
        if workspace is None:
            raise RuntimeError("el tenant de certificación no tiene workspace")
        await session.execute(
            text(
                "INSERT INTO managed_databases (id, organization_id, workspace_id, db_name) "
                "VALUES (gen_random_uuid(), :oid, :ws, :db)"
            ),
            {
                "oid": str(organization_id),
                "ws": workspace.id,
                "db": f"cert_gold_{uuid4().hex[:8]}",
            },
        )
        await session.commit()
    finally:
        await session.close()


async def ready_tenant(
    client: AsyncClient,
    name: str,
    *,
    catalog: list[dict[str, Any]] | None = None,
    with_payments: bool = True,
    with_agent: bool = False,
    with_managed_db: bool = False,
) -> dict:
    """Tenant completo: catálogo + stock + bindings (+ pago sandbox)."""
    org = await make_tenant(client, name)
    await seed_catalog(org["organization_id"], catalog)
    await bind_commerce(org["organization_id"])
    await bind_conversation(org["organization_id"])
    if with_payments:
        await configure_sandbox_payments(org["organization_id"])
    if with_agent:
        org["agent_id"] = await seed_sales_agent(org["organization_id"])
    if with_managed_db:
        await seed_managed_db(org["organization_id"])
    return org


async def install_funnel(client: AsyncClient, org: dict) -> str:
    """Instala la plantilla oficial y devuelve el workflow_id."""
    resp = await client.post(
        f"/api/v1/workflows/templates/{sales_funnel.TEMPLATE_SLUG}/install",
        headers=_headers(org),
        json={"name": sales_funnel.TEMPLATE_NAME},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    workflow_id = body.get("workflow_id") or body.get("id")
    assert workflow_id, body
    return str(workflow_id)


async def create_funnel_workflow(client: AsyncClient, org: dict, name: str = "Embudo") -> str:
    """Crea el workflow directamente con el grafo de la plantilla (sin catálogo)."""
    resp = await client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={
            "name": name,
            "trigger_type": "event",
            "trigger_config": {"event_type": "conversation.message"},
            "graph": sales_funnel.build_graph(),
            "workflow_version": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["workflow_id"])


async def start_funnel(
    client: AsyncClient,
    org: dict,
    workflow_id: str,
    *,
    text: str,
    conversation_id: str | None = None,
) -> dict:
    """Arranca la instancia durable con el primer mensaje del cliente."""
    conversation_id = conversation_id or str(uuid4())
    resp = await client.post(
        f"/api/v1/workflows/{workflow_id}/instances",
        headers={**_headers(org), "Idempotency-Key": f"inst-{uuid4().hex}"},
        json={
            "payload": {"text": text, "conversation_id": conversation_id},
            "conversation_id": conversation_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    body["conversation_id"] = conversation_id
    return body


async def say(
    client: AsyncClient,
    org: dict,
    instance_id: str,
    *,
    text: str,
    conversation_id: str,
    message_id: str | None = None,
) -> dict:
    """Turno del cliente: señal `conversation.message` a la MISMA instancia."""
    resp = await client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers={**_headers(org), "Idempotency-Key": f"sig-{uuid4().hex}"},
        json={
            "event_type": "conversation.message",
            "correlation": {"conversation_id": conversation_id},
            "payload": {"text": text, "conversation_id": conversation_id},
            "external_event_id": message_id or f"msg-{uuid4().hex}",
            "idempotency_key": f"msg:{message_id or uuid4().hex}",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def instance(client: AsyncClient, org: dict, instance_id: str) -> dict:
    resp = await client.get(
        f"/api/v1/workflows/instances/{instance_id}", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def sign_sandbox_event(payload: dict, *, secret: str = SANDBOX_WEBHOOK_SECRET) -> dict:
    """Firma un evento de proveedor como lo haría la pasarela (HMAC real)."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return {"raw": raw, "headers": {"X-Zent-Signature": f"sha256={signature}"}}


async def send_provider_event(
    client: AsyncClient,
    *,
    provider: str = "sandbox",
    reference: str,
    provider_reference: str | None = None,
    event_id: str | None = None,
    status: str = "paid",
    amount_cents: int | None = None,
    currency: str | None = None,
    secret: str = SANDBOX_WEBHOOK_SECRET,
) -> Any:
    payload: dict[str, Any] = {
        "event_id": event_id or f"evt-{uuid4().hex}",
        "type": f"sandbox.payment.{status}",
        "status": status,
        "reference": reference,
    }
    if provider_reference:
        payload["provider_reference"] = provider_reference
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    if currency is not None:
        payload["currency"] = currency
    signed = sign_sandbox_event(payload, secret=secret)
    return await client.post(
        f"/api/v1/public/payments/{provider}/webhook",
        content=signed["raw"],
        headers={**signed["headers"], "Content-Type": "application/json"},
    )


def orders_of(orders: list[dict], reference: str) -> list[dict]:
    return [o for o in orders if o.get("order_number") == reference]


async def fetch_orders(client: AsyncClient, org: dict) -> list[dict]:
    resp = await client.get("/api/v1/commerce/orders", headers=_headers(org))
    assert resp.status_code == 200, resp.text
    return resp.json()["orders"]


async def fetch_stock(organization_id: str, sku: str) -> dict:
    org = UUID(str(organization_id))
    product = await commerce_store.get_product(org, sku=sku)
    assert product is not None
    return await commerce_store.stock_get(org, product_id=product["product_id"])


#: Turnos del escenario de referencia (dos líneas en el carrito: 7.20 + 4.20).
GOLD_TURNS: tuple[str, ...] = ("mejor integral", "también una leche", "no, nada más", "sí")
GOLD_TOTAL_CENTS = 1140


async def sweep_until(organization_id: str, instance_id: str, statuses: tuple[str, ...]) -> dict:
    """Corre el sweep (es global) hasta que la instancia salga de WAITING."""
    from src.platform.workflows.instances import sweep_waiting_instances

    stats: dict = {}
    for _ in range(8):
        stats = await sweep_waiting_instances(limit=200)
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text("SELECT status FROM workflow_instances WHERE id = :iid"),
                    {"iid": instance_id},
                )
            ).fetchone()
        finally:
            await session.close()
        if row is None or str(row.status) not in ("WAITING", "RUNNING"):
            break
    return stats


async def force_wait_deadline(instance_id: str) -> None:
    """Vence el wait de la instancia ahora mismo (sin dormir 24h)."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_instances SET wait_deadline = NOW() - INTERVAL '1 minute' "
                "WHERE id = :iid"
            ),
            {"iid": instance_id},
        )
        await session.commit()
    finally:
        await session.close()


async def force_wait_timeout(client: AsyncClient, org: dict, instance_id: str) -> dict:
    """Dispara el mismo evento que emite el sweep (determinista, sin esperar 60s).

    El sweep global se certifica aparte; aquí interesa la rama de negocio.
    """
    resp = await client.post(
        f"/api/v1/workflows/instances/{instance_id}/signal",
        headers={**_headers(org), "Idempotency-Key": f"to-{uuid4().hex}"},
        json={
            "event_type": "workflow.wait.timeout",
            "correlation": {"instance_id": instance_id},
            "payload": {"expired": True},
            "idempotency_key": f"timeout:{instance_id}:manual",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
