"""Smoke E2E del checkout manual P20 (ejecutar dentro del contenedor API).

Requiere la fuente externa P19 y los bindings `bodega.order.create`,
`bodega.stock.reserve_batch` y `bodega.stock.commit_batch`.

Uso:
    docker cp ops/p20/e2e_checkout_manual.py rag-api:/tmp/e2e.py
    docker exec rag-api python /tmp/e2e.py
"""
from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce import cart, store
from src.platform.workflows.engine import (
    create_from_template,
    decide_approval,
    run_workflow,
)

ORG = UUID(os.environ.get("P20_ORG", "e42d1f42-b87d-4baf-88dc-ec3da1541239"))
WS = UUID(os.environ.get("P20_WS", "074a851b-f056-4d16-9ccd-ceaddc387305"))
USER = UUID(os.environ.get("P20_USER", "ddbe826b-d7fc-4fa0-8c34-53a7e49357fc"))
SKU = os.environ.get("P20_SKU", "BD-ARROZ-01")
QTY = int(os.environ.get("P20_QTY", "2"))


async def main() -> None:
    conversation_id = uuid4()
    source_id = uuid4()
    await cart.add_item(
        ORG,
        conversation_id=conversation_id,
        workspace_id=WS,
        user_id=USER,
        sku=SKU,
        name="Arroz extra 1 kg",
        unit="kg",
        unit_price="4.80",
        currency="PEN",
        source_id=source_id,
        price_source="external:bodega.product_catalog_v",
        quantity=QTY,
        ttl_seconds=600,
    )
    workflow = await create_from_template(
        ORG, "retail_checkout_manual", workspace_id=WS
    )
    workflow_id = workflow.get("workflow_id") or workflow.get("id")
    print("workflow_id=", workflow_id)  # noqa: T201
    run = await run_workflow(
        UUID(str(workflow_id)),
        payload={
            "conversation_id": str(conversation_id),
            "customer_ref": "CUST-DEMO",
            "customer_name": "Cliente demo",
            "order_operation_id": f"p20-checkout-{conversation_id}",
        },
        trigger="manual",
        organization_id=ORG,
        workspace_id=WS,
        actor_id=USER,
        permissions=frozenset({"workflows:run", "external_actions:execute"}),
        system_context=True,
    )
    print("run_status=", run.get("status"), run.get("error"))  # noqa: T201
    if run.get("status") != "pending_approval":
        raise SystemExit(f"checkout no quedó pendiente: {run.get('status')}")

    session = await get_async_session()
    try:
        approval = (
            await session.execute(
                text(
                    "SELECT id FROM workflow_approvals WHERE run_id = :rid "
                    "AND status = 'pending' ORDER BY requested_at DESC LIMIT 1"
                ),
                {"rid": str(run.get("run_id"))},
            )
        ).fetchone()
    finally:
        await session.close()
    if approval is None:
        raise SystemExit("no hay aprobación pendiente")
    decision = await decide_approval(
        ORG,
        approval.id,
        "approved",
        uuid4(),
        "Aprobado por smoke test P20",
        workspace_id=WS,
        allow_owner_self_approval=True,
    )
    print("decision=", decision)  # noqa: T201
    await asyncio.sleep(1)

    order = await store.get_order_for_conversation(
        ORG, conversation_id=str(conversation_id)
    )
    if order is None:
        raise SystemExit("orden no encontrada")
    print(  # noqa: T201
        "order=",
        {
            "number": order["order_number"],
            "status": order["status"],
            "total": order["total"],
            "payment_provider": order["payment_provider"],
            "payment_reference": order["payment_reference"],
        },
    )
    if order["status"] != "PAID":
        raise SystemExit(f"orden no pagada: {order['status']}")
    if order["payment_provider"] != "manual_mvp":
        raise SystemExit(f"provider inesperado: {order['payment_provider']}")


if __name__ == "__main__":
    asyncio.run(main())
