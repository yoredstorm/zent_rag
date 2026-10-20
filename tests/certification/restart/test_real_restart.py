# =============================================================================
# Certification — reinicio real de proceso (no ASGI en el mismo proceso)
# =============================================================================
# Requiere una base Postgres/Redis/Qdrant accesibles y se ejecuta explícitamente:
#   RAG_CERT_REAL_RESTART=1 pytest tests/certification/restart -q
#
# El test levanta uvicorn en un subproceso, crea la instancia WAITING, mata el
# proceso, levanta uno nuevo, entrega el webhook firmado y verifica la reanudación
# y los efectos exactamente una vez. Un skip no cuenta como certificación.
# =============================================================================
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from tests.certification.workflows.gold_support import (
    CATALOG,
    GOLD_TOTAL_CENTS,
    GOLD_TURNS,
    fetch_orders,
    fetch_stock,
    install_funnel,
    instance,
    ready_tenant,
    say,
    send_provider_event,
    start_funnel,
)

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    os.environ.get("RAG_CERT_REAL_RESTART") != "1",
    reason="set RAG_CERT_REAL_RESTART=1 to run the real process restart certification",
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_api(port: int) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(ROOT))
    log_dir = ROOT / "artifacts" / "certification" / "restart"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = (log_dir / f"api-{port}.log").open("ab")
    return subprocess.Popen(  # noqa: S603 — comando fijo del propio repositorio
        [
            sys.executable,
            "-m",
            "uvicorn",
            "src.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )


async def _wait_health(client: httpx.AsyncClient) -> None:
    for _ in range(90):
        try:
            response = await client.get("/health")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError("la API real no respondió /health")


def _stop_api(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    assert proc.poll() is not None


async def _counts(organization_id: str) -> dict[str, int]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        orders = (
            await session.execute(
                text("SELECT COUNT(*) FROM commerce_orders WHERE organization_id = :oid"),
                {"oid": organization_id},
            )
        ).scalar()
        checkouts = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM commerce_checkout_sessions "
                    "WHERE organization_id = :oid"
                ),
                {"oid": organization_id},
            )
        ).scalar()
        committed = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM commerce_reservations "
                    "WHERE organization_id = :oid AND status = 'committed'"
                ),
                {"oid": organization_id},
            )
        ).scalar()
    finally:
        await session.close()
    return {
        "orders": int(orders),
        "checkouts": int(checkouts),
        "committed": int(committed),
    }


@pytest.mark.asyncio
async def test_real_process_restart_resumes_and_does_not_duplicate(
    async_client: AsyncClient,
) -> None:
    org = await ready_tenant(async_client, "Cert Real Restart", catalog=CATALOG)
    workflow_id = await install_funnel(async_client, org)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    proc = _start_api(port)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=120.0) as http:
            await _wait_health(http)
            started = await start_funnel(
                http, org, workflow_id, text="quiero 1 kilo de arroz"
            )
            instance_id = started["instance_id"]
            conversation_id = started["conversation_id"]
            for turn in GOLD_TURNS:
                await say(
                    http,
                    org,
                    instance_id,
                    text=turn,
                    conversation_id=conversation_id,
                )
            state = await instance(http, org, instance_id)
            assert state["status"] == "WAITING", state
            assert state["current_node_id"] == "esperar_pago", state
            orders = await fetch_orders(http, org)
            assert len(orders) == 1
            reference = orders[0]["order_number"]
            before = await _counts(org["organization_id"])
            assert before["orders"] == 1 and before["checkouts"] == 1

            # Corte real del proceso que atiende la API.
            _stop_api(proc)
            proc = _start_api(port)
            await _wait_health(http)

            # La instancia sigue viva en PostgreSQL; el webhook de un proceso
            # nuevo debe reanudarla sin estado en memoria.
            from uuid import UUID

            from src.platform.commerce import store as commerce_store

            checkout = await commerce_store.find_checkout(
                UUID(str(org["organization_id"])), reference=reference
            )
            assert checkout is not None
            event_id = f"evt-real-restart-{uuid4().hex}"
            webhook = await send_provider_event(
                http,
                reference=reference,
                provider_reference=checkout.get("provider_reference"),
                event_id=event_id,
                amount_cents=GOLD_TOTAL_CENTS,
            )
            assert webhook.status_code == 200, webhook.text
            assert webhook.json()["signal"]["resumed"] is True, webhook.text

            state = await instance(http, org, instance_id)
            assert state["status"] == "COMPLETED", state
            orders = await fetch_orders(http, org)
            assert len(orders) == 1 and orders[0]["status"] == "PAID"
            integral = await fetch_stock(org["organization_id"], "ARZ-INT-1KG")
            leche = await fetch_stock(org["organization_id"], "LEC-GLO-1L")
            assert integral["available"] == 14
            assert leche["available"] == 29

            duplicate = await send_provider_event(
                http,
                reference=reference,
                provider_reference=checkout.get("provider_reference"),
                event_id=event_id,
                amount_cents=GOLD_TOTAL_CENTS,
            )
            assert duplicate.status_code == 200, duplicate.text
            assert duplicate.json()["status"] == "duplicate"
            after = await _counts(org["organization_id"])
            assert after["orders"] == 1
            assert after["checkouts"] == 1
            assert await fetch_stock(org["organization_id"], "ARZ-INT-1KG") == integral
    finally:
        _stop_api(proc)
