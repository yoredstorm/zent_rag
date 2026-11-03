# ruff: noqa: T201 - herramienta CLI: print es la salida
"""P19.1-07 - chaos real: 100 reservas concurrentes contra stock limitado.

Requiere PostgreSQL externo de ops/p19-external. Crea fixtures sinteticas y las
limpia al final. No usa datos de clientes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from uuid import uuid4

import asyncpg

from src.infrastructure.postgres.relational_db import (
    PostgresConnectorRepository,
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.secrets.secret_store_resolver import get_secret_store
from src.platform.workflows.inventory_adapter import execute_inventory_action

SKU = "LOAD-TEST-01"
ORDERS = 100
STOCK = 10


async def _seed(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "INSERT INTO bodega.products (sku, name, category, unit, price) "
        "VALUES ($1, 'Load test', 'test', 'unit', 1.00) ON CONFLICT (sku) DO NOTHING",
        SKU,
    )
    await conn.execute(
        "INSERT INTO bodega.stock (sku, on_hand, reserved, version) "
        "VALUES ($1, $2, 0, 0) ON CONFLICT (sku) DO UPDATE SET on_hand = $2, reserved = 0",
        SKU,
        STOCK,
    )
    for index in range(ORDERS):
        order = f"LOAD-{index:04d}"
        await conn.execute(
            "INSERT INTO bodega.orders (order_number, customer_ref, status, payment_status, total) "
            "VALUES ($1, 'LOAD', 'pending_approval', 'pending', 0) ON CONFLICT (order_number) DO NOTHING",
            order,
        )


async def _cleanup(conn: asyncpg.Connection) -> None:
    await conn.execute("DELETE FROM bodega.stock_reservations WHERE sku = $1", SKU)
    await conn.execute("DELETE FROM bodega.stock_movements WHERE sku = $1", SKU)
    await conn.execute("DELETE FROM bodega.orders WHERE order_number LIKE 'LOAD-%'")
    await conn.execute("DELETE FROM bodega.stock WHERE sku = $1", SKU)
    await conn.execute("DELETE FROM bodega.products WHERE sku = $1", SKU)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("P19_EXTERNAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.environ.get("P19_EXTERNAL_PORT", "55432")))
    parser.add_argument("--db", default=os.environ.get("P19_EXTERNAL_DB", "zent_external_mvp"))
    parser.add_argument("--admin-user", default="p19_admin")
    parser.add_argument("--admin-password", default="p19_admin_dev_2026")
    parser.add_argument("--writer-user", default="p19_writer")
    parser.add_argument("--writer-password", default="p19_writer_dev_2026")
    parser.add_argument("--out", default="artifacts/certification/inventory-concurrency.json")
    args = parser.parse_args()

    ext = await asyncpg.connect(
        host=args.host,
        port=args.port,
        database=args.db,
        user=args.admin_user,
        password=args.admin_password,
    )
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P19 Load {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(org.id, "Default", "default")
    connector = await PostgresConnectorRepository().create_connector(
        org.id,
        f"P19 Load {uuid4().hex[:6]}",
        "postgres",
        workspace_id=workspace.id,
        config_json={
            "host": args.host,
            "port": args.port,
            "database": args.db,
            "user": args.writer_user,
            "ssl": False,
        },
    )
    await get_secret_store().put(org.id, connector.id, {"password": args.writer_password})
    binding = {
        "id": str(uuid4()),
        "organization_id": str(org.id),
        "workspace_id": str(workspace.id),
        "capability_ref": "bodega.stock.reserve",
        "provider_kind": "inventory",
        "config": {
            "action": "reserve_stock",
            "write": True,
            "connector_id": str(connector.id),
            "max_quantity": 2,
        },
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }
    try:
        await _seed(ext)

        sem = asyncio.Semaphore(20)

        async def _reserve(index: int):
            async with sem:
                return await execute_inventory_action(
                    org.id,
                    binding,
                    {
                        "order_number": f"LOAD-{index:04d}",
                        "sku": SKU,
                        "quantity": 1,
                        "ttl_seconds": 60,
                    },
                    workspace_id=workspace.id,
                )

        results = await asyncio.gather(
            *[_reserve(index) for index in range(ORDERS)], return_exceptions=True
        )
        reserved = sum(1 for item in results if isinstance(item, dict) and item.get("status") == "RESERVED")
        conflicts = sum(
            1
            for item in results
            if getattr(item, "code", "") == "CONFLICT"
        )
        errors = [
            f"{type(item).__name__}:{item}"
            for item in results
            if isinstance(item, BaseException) and getattr(item, "code", "") != "CONFLICT"
        ]
        row = await ext.fetchrow(
            "SELECT on_hand, reserved FROM bodega.stock WHERE sku = $1", SKU
        )
        ledger = await ext.fetchval(
            "SELECT COUNT(*) FROM bodega.stock_reservations WHERE sku = $1 AND status = 'active'",
            SKU,
        )
        evidence = {
            "schema": "zent.cert.inventory-concurrency/1",
            "orders": ORDERS,
            "initial_stock": STOCK,
            "reserved": reserved,
            "conflicts": conflicts,
            "unexpected_errors": errors[:5],
            "on_hand": int(row["on_hand"]),
            "reserved_counter": int(row["reserved"]),
            "active_reservations": int(ledger),
            "negative_stock": int(row["on_hand"]) - int(row["reserved"]) < 0,
            "pass": reserved == STOCK
            and conflicts == ORDERS - STOCK
            and not errors
            and int(row["reserved"]) == STOCK
            and int(ledger) == STOCK,
        }
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        from pathlib import Path

        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if evidence["pass"] else 1
    finally:
        await _cleanup(ext)
        await ext.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
