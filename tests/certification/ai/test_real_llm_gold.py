# =============================================================================
# Certification — generación real del Gold Workflow con LLM autorizado
# =============================================================================
# No usa providers deterministas ni la plantilla retail_sales_funnel. Requiere:
#   RAG_CERT_REAL_LLM=1
# y credenciales LLM reales en el entorno. Un skip no cuenta como PASS.
# =============================================================================
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.certification.workflows.gold_support import CATALOG, ready_tenant

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "artifacts" / "certification" / "ai" / "gold-real-llm.json"
pytestmark = pytest.mark.skipif(
    os.environ.get("RAG_CERT_REAL_LLM") != "1",
    reason="set RAG_CERT_REAL_LLM=1 with authorized real LLM credentials",
)

GOLD_PROMPT = """
Quiero un agente de ventas para una tienda.
Cuando un cliente escriba que necesita un producto, el sistema debe buscarlo en el
catálogo del negocio. Si existen varias marcas, debe mostrar alternativas y sus
precios reales. El cliente podrá elegir una alternativa, cambiar de opinión y
agregar más productos. Debe conservar el carrito durante toda la conversación.
Cuando el cliente termine, debe presentar el resumen con el precio total y pedir
confirmación. Después debe crear una orden y generar un enlace o QR de pago
utilizando el proveedor configurado. Debe esperar la confirmación real del
proveedor de pago antes de finalizar la venta. Si el pago falla, debe comunicarlo
y permitir un reintento seguro. Si el pago se confirma, debe finalizar la orden y
aplicar el movimiento de inventario exactamente una vez. Debe soportar mensajes
duplicados, reconexiones y reinicios del servidor.
""".strip()


@pytest.mark.asyncio
async def test_real_llm_generates_gold_workflow_without_installing_template(
    async_client: AsyncClient,
) -> None:
    org = await ready_tenant(async_client, "Cert AI Gold", catalog=CATALOG)
    response = await async_client.post(
        "/api/v1/workflows/architect/sessions",
        headers={
            "Authorization": f"Bearer {org['session']}",
            "X-Organization-Id": org["organization_id"],
            "Idempotency-Key": "cert-ai-gold-session",
        },
        json={"prompt": GOLD_PROMPT, "title": "Gold AI Sales"},
    )
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(
        json.dumps(
            {"status_code": response.status_code, "body": response.json()},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    initial_body = body
    proposal = body["proposal"]
    design = body["design_session"]
    if proposal.get("state") != "DRAFT_READY":
        answers = (
            "Usa la fuente de catálogo commerce: catalog.products.search y "
            "catalog.product.price; el stock sale de inventory.stock.get. "
            "Usa sales.cart.quote para el carrito. Crea la orden con "
            "sales.order.create, cobra con payments.checkout.create y espera el "
            "evento firmado payment.succeeded con timeout 1800 segundos. El canal "
            "de conversación es conversation.send. Moneda PEN. No inventes "
            "proveedores: usa el binding de pago configurado del tenant."
        )
        follow = await async_client.post(
            f"/api/v1/workflows/architect/sessions/{design['id']}/messages",
            headers={
                "Authorization": f"Bearer {org['session']}",
                "X-Organization-Id": org["organization_id"],
                "Idempotency-Key": "cert-ai-gold-answer",
            },
            json={"message": answers, "expected_revision": design["revision"]},
        )
        assert follow.status_code == 200, follow.text
        follow_body = follow.json()
        body = follow_body
        proposal = body["proposal"]
        ARTIFACT.write_text(
            json.dumps(
                {
                    "status_code": response.status_code,
                    "initial": initial_body,
                    "follow_up": follow_body,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    plan = proposal.get("plan") or {}
    graph = proposal.get("graph")
    assert proposal.get("state") == "DRAFT_READY", proposal
    assert graph is not None, proposal
    assert plan.get("steps"), plan
    # El flujo real debe contener interacción conversacional, checkout/pago,
    # espera durable y un resultado final; no basta con un grafo vacío.
    types = {node["type"] for node in graph["nodes"]}
    assert "conversation_wait" in types or "wait_event" in types, types
    serialized = json.dumps(plan, ensure_ascii=False).lower()
    assert "payment" in serialized or "checkout" in serialized or "pago" in serialized
    assert "order" in serialized or "orden" in serialized or "venta" in serialized
