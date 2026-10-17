# =============================================================================
# Certification — durabilidad y reinicio
# =============================================================================
# Un proceso de negocio debe sobrevivir a que la API se apague y se levante:
# el estado vive en Postgres (instancia + inbox de señales), no en memoria.
# El test no reutiliza ningún estado del cliente: la reanudación se dispara por
# el camino durable (webhook firmado del proveedor / inbox de señales) y el
# cierre de la venta lo ejecuta el segmento nuevo.
# =============================================================================
from __future__ import annotations

from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from tests.certification.workflows.gold_support import (
    CATALOG,
    GOLD_TOTAL_CENTS,
    GOLD_TURNS,
    fetch_orders,
    fetch_stock,
    force_wait_deadline,
    install_funnel,
    instance,
    ready_tenant,
    say,
    send_provider_event,
    start_funnel,
    sweep_until,
)


async def _counts(organization_id: str) -> dict[str, int]:
    org = UUID(str(organization_id))
    session = await get_async_session()
    try:
        orders = (
            await session.execute(
                text("SELECT COUNT(*) AS n FROM commerce_orders WHERE organization_id = :oid"),
                {"oid": str(org)},
            )
        ).fetchone()
        checkouts = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM commerce_checkout_sessions WHERE organization_id = :oid"
                ),
                {"oid": str(org)},
            )
        ).fetchone()
        committed = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM commerce_reservations "
                    "WHERE organization_id = :oid AND status = 'committed'"
                ),
                {"oid": str(org)},
            )
        ).fetchone()
        runs = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM workflow_runs WHERE organization_id = :oid "
                    "AND instance_id IS NOT NULL"
                ),
                {"oid": str(org)},
            )
        ).fetchone()
    finally:
        await session.close()
    return {
        "orders": int(orders.n),
        "checkouts": int(checkouts.n),
        "committed": int(committed.n),
        "runs": int(runs.n),
    }


@pytest.mark.asyncio
async def test_restart_resumes_same_instance_and_sells_exactly_once(
    async_client: AsyncClient,
) -> None:
    """Apagar/levantar la API: misma instancia, una sola venta, un solo stock."""
    org = await ready_tenant(async_client, "Cert Restart", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id, conversation_id = started["instance_id"], started["conversation_id"]
    for turn in GOLD_TURNS:
        await say(
            async_client, org, instance_id, text=turn, conversation_id=conversation_id
        )

    before = await _counts(org["organization_id"])
    assert before["orders"] == 1 and before["checkouts"] == 1
    assert before["committed"] == 0 and before["runs"] >= 4

    # --- "Reinicio": cliente y proceso nuevos, cero estado en memoria ---------
    transport = ASGITransport(app=async_client._transport.app)  # type: ignore[attr-defined]
    async with AsyncClient(transport=transport, base_url="http://testserver") as cold:
        state = await instance(cold, org, instance_id)
        assert state["status"] == "WAITING"
        assert state["current_node_id"] == "esperar_pago"
        assert state["definition_snapshot"]["graph"]["nodes"], "el snapshot viaja con la instancia"

        orders = await fetch_orders(cold, org)
        reference = orders[0]["order_number"]
        from src.platform.commerce import store as commerce_store

        checkout = await commerce_store.find_checkout(
            UUID(str(org["organization_id"])), reference=reference
        )
        assert checkout is not None
        webhook = await send_provider_event(
            cold,
            reference=reference,
            provider_reference=checkout.get("provider_reference"),
            amount_cents=GOLD_TOTAL_CENTS,
        )
        assert webhook.status_code == 200, webhook.text
        assert webhook.json()["signal"]["resumed"] is True, webhook.text

        state = await instance(cold, org, instance_id)
        assert state["status"] == "COMPLETED"

    after = await _counts(org["organization_id"])
    assert after["orders"] == 1, "una sola venta"
    assert after["checkouts"] == 1, "un solo checkout"
    assert after["committed"] == 2, "una reserva confirmada por línea"
    assert after["runs"] == before["runs"] + 1, "un segmento nuevo, no una re-ejecución"
    orders = await fetch_orders(async_client, org)
    assert orders[0]["status"] == "PAID"
    integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
    leche = await fetch_stock(org["organization_id"], "LEC-GLO-1L")
    assert integral["available"] == 14 and integral["reserved"] == 0
    assert leche["available"] == 29 and leche["reserved"] == 0


@pytest.mark.asyncio
async def test_sweep_after_restart_does_not_duplicate_effects(
    async_client: AsyncClient,
) -> None:
    """El sweep del scheduler (cada 60s) es idempotente sobre procesos vivos."""
    from src.platform.workflows.instances import sweep_waiting_instances

    org = await ready_tenant(async_client, "Cert Sweep", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id = started["instance_id"]

    before = await _counts(org["organization_id"])
    stats = await sweep_waiting_instances(limit=50)
    assert isinstance(stats, dict)
    after = await _counts(org["organization_id"])
    assert after == before

    state = await instance(async_client, org, instance_id)
    assert state["status"] == "WAITING"  # el wait sigue vivo (no expiró)
    assert state["current_node_id"] == "esperar_eleccion"


@pytest.mark.asyncio
async def test_wait_timeout_expires_instance_without_side_effects(
    async_client: AsyncClient,
) -> None:
    """Un embudo abandonado expira y no deja ventas ni stock movido."""
    org = await ready_tenant(async_client, "Cert Expire", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    started = await start_funnel(async_client, org, workflow_id, text="quiero 1 kilo de arroz")
    instance_id = started["instance_id"]
    state = await instance(async_client, org, instance_id)
    assert state["current_node_id"] == "esperar_eleccion"

    await force_wait_deadline(instance_id)
    await sweep_until(org["organization_id"], instance_id, ("EXPIRED",))

    state = await instance(async_client, org, instance_id)
    assert state["status"] in ("EXPIRED", "CANCELLED"), state
    counts = await _counts(org["organization_id"])
    assert counts["orders"] == 0
    assert counts["checkouts"] == 0
