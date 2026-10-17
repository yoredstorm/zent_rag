"""Smoke end-to-end del Retail Sales Funnel contra el stack LOCAL (docker).

Ejercita el camino real por HTTP (sin ASGITransport): tenant, catálogo,
proveedor de pago sandbox, bindings, instalación de la plantilla, conversación
de 5 turnos, webhook de pago firmado y cierre con venta + inventario.

Uso (stack levantado con `docker compose up -d`):
    python scripts/smoke_sales_funnel.py [--base-url http://127.0.0.1:8000]

Sale con código 0 si todo el embudo cierra; 1 si algo falla (imprime el detalle).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

SANDBOX_SECRET = "smoke-sandbox-webhook-secret"

CATALOG = [
    {"sku": "ARZ-COS-1KG", "name": "Arroz Costeño", "price": 5.90, "unit": "KG", "stock": 40},
    {"sku": "ARZ-PAI-1KG", "name": "Arroz Paisana", "price": 5.50, "unit": "KG", "stock": 25},
    {"sku": "ARZ-INT-1KG", "name": "Arroz Integral", "price": 7.20, "unit": "KG", "stock": 15},
    {"sku": "LEC-GLO-1L", "name": "Leche Gloria", "price": 4.20, "unit": "L", "stock": 30},
]

BINDINGS = [
    "catalog.products.search",
    "catalog.product.get",
    "catalog.product.price",
    "inventory.stock.get",
    "inventory.reserve",
    "inventory.release",
    "inventory.commit",
    "sales.order.create",
    "sales.cart.quote",
    "sales.order.get",
    "sales.order.mark_paid",
    "sales.order.cancel",
    "sales.order.confirm",
    "sales.order.fulfill",
]

TURNS = ["mejor integral", "también una leche", "no, nada más", "sí"]


class SmokeFailure(AssertionError):
    pass


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok   {label}")
        return
    raise SmokeFailure(f"{label} -> {detail}")


def _session_token(organization_id: str) -> str:
    """Token de sesión firmado con la misma clave que usa la API."""
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = _run(PostgresUserRepository().get_by_external_id(UUID(organization_id), "default-admin"))
    if user is None:
        raise SmokeFailure("el tenant no tiene usuario default-admin")
    return encrypt_session(user.id, UUID(organization_id))


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    with httpx.Client(base_url=base, timeout=60.0) as client:
        health = client.get("/health")
        check("API saludable", health.status_code == 200, health.text[:200])

        created = client.post(
            "/api/v1/billing/subscription/create-trial",
            json={
                "company_name": f"Smoke Funnel {uuid4().hex[:6]}",
                "email": f"smoke-{uuid4().hex[:8]}@example.com",
                "country": "CL",
            },
        )
        check("tenant de prueba creado", created.status_code == 200, created.text[:200])
        organization_id = created.json()["organization_id"]
        headers = {
            "Authorization": f"Bearer {_session_token(organization_id)}",
            "X-Organization-Id": organization_id,
            "Idempotency-Key": uuid4().hex,
        }

        for item in CATALOG:
            response = client.post(
                "/api/v1/commerce/products",
                headers={**headers, "Idempotency-Key": uuid4().hex},
                json={
                    "sku": item["sku"],
                    "name": item["name"],
                    "price": item["price"],
                    "unit": item["unit"],
                    "stock": item["stock"],
                    "currency": "PEN",
                },
            )
            check(f"catálogo {item['sku']}", response.status_code == 200, response.text[:200])

        for capability in BINDINGS:
            response = client.put(
                f"/api/v1/workflows/capability-bindings/{capability}",
                headers={**headers, "Idempotency-Key": uuid4().hex},
                json={"provider_kind": "commerce", "config": {"warehouse": "main"}},
            )
            check(f"binding {capability}", response.status_code == 200, response.text[:200])

        conversation = client.put(
            "/api/v1/workflows/capability-bindings/conversation.send",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"provider_kind": "conversation", "config": {"channel": "in_app"}},
        )
        check("binding conversation.send", conversation.status_code == 200, conversation.text[:200])

        provider = client.put(
            "/api/v1/commerce/payments/providers/sandbox",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={
                "secrets": {"webhook_secret": SANDBOX_SECRET},
                "mode": "test",
                "config": {"payment_page_url": "https://sandbox.zent.local/pay"},
            },
        )
        check("proveedor sandbox configurado", provider.status_code == 200, provider.text[:200])
        check(
            "credenciales nunca devueltas",
            "webhook_secret" not in provider.text,
            provider.text[:200],
        )

        readiness = client.get(
            "/api/v1/commerce/sales-funnel/readiness", headers={**headers, "Idempotency-Key": uuid4().hex}
        )
        check("readiness 200", readiness.status_code == 200, readiness.text[:200])
        check("checklist listo", readiness.json()["ready"] is True, readiness.json())

        installed = client.post(
            "/api/v1/workflows/templates/retail_sales_funnel/install",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"name": "Embudo smoke"},
        )
        check("plantilla instalada", installed.status_code == 200, installed.text[:300])
        workflow_id = installed.json()["workflow_id"]

        conversation_id = str(uuid4())
        started = client.post(
            f"/api/v1/workflows/{workflow_id}/instances",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={
                "payload": {"text": "quiero 1 kilo de arroz", "conversation_id": conversation_id},
                "conversation_id": conversation_id,
            },
        )
        check("instancia arrancada", started.status_code == 200, started.text[:300])
        instance_id = started.json()["instance_id"]

        state = client.get(
            f"/api/v1/workflows/instances/{instance_id}", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()
        check("WAIT en la elección", state["current_node_id"] == "esperar_eleccion", state)
        options = (state.get("state") or {}).get("catalog", {}).get("options") or []
        check("3 opciones reales con precio", len(options) == 3, options)

        for turn in TURNS:
            signal = client.post(
                f"/api/v1/workflows/instances/{instance_id}/signal",
                headers={**headers, "Idempotency-Key": uuid4().hex},
                json={
                    "event_type": "conversation.message",
                    "correlation": {"conversation_id": conversation_id},
                    "payload": {"text": turn, "conversation_id": conversation_id},
                    "external_event_id": f"smoke-{uuid4().hex}",
                    "idempotency_key": f"smoke:{uuid4().hex}",
                },
            )
            check(f"turno «{turn}»", signal.status_code == 200, signal.text[:200])

        state = client.get(
            f"/api/v1/workflows/instances/{instance_id}", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()
        check("WAIT en el pago", state["current_node_id"] == "esperar_pago", state)
        cart = (state.get("state") or {}).get("cart", {}).get("items") or []
        check("carrito con 2 líneas", len(cart) == 2, cart)

        orders = client.get(
            "/api/v1/commerce/orders", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()["orders"]
        check("1 orden", len(orders) == 1, orders)
        order = orders[0]
        check("total server-side 11.40", abs(order["total"] - 11.40) < 0.01, order["total"])

        payload = {
            "event_id": f"smoke-evt-{uuid4().hex}",
            "type": "sandbox.payment.paid",
            "status": "paid",
            "reference": order["order_number"],
            "amount_cents": 1140,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(SANDBOX_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        webhook = client.post(
            "/api/v1/public/payments/sandbox/webhook",
            content=raw,
            headers={"Content-Type": "application/json", "X-Zent-Signature": f"sha256={signature}"},
        )
        check("webhook firmado procesado", webhook.status_code == 200, webhook.text[:300])
        check("señal reanudó la instancia", webhook.json()["signal"]["resumed"] is True, webhook.json())

        state = client.get(
            f"/api/v1/workflows/instances/{instance_id}", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()
        check("instancia COMPLETED", state["status"] == "COMPLETED", state)

        orders = client.get(
            "/api/v1/commerce/orders", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()["orders"]
        check("venta PAID", orders[0]["status"] == "PAID", orders[0])

        products = client.get(
            "/api/v1/commerce/products?q=integral", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()
        check("catálogo sigue consultable", products["count"] >= 1, products)

        kpis = client.get(
            "/api/v1/commerce/kpis", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()
        check("KPIs: 1 completada", kpis["instances"]["completed"] == 1, kpis)
        check("KPIs: 1 pagada", kpis["orders"]["paid"] == 1, kpis)

        events = client.get(
            "/api/v1/commerce/payments/events", headers={**headers, "Idempotency-Key": uuid4().hex}
        ).json()["events"]
        check("evento de proveedor auditado", any(e["verified"] for e in events), events[:2])

    print("\nSMOKE OK: embudo completo contra el stack local.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"\nSMOKE FALLÓ: {exc}")
        raise SystemExit(1) from exc
