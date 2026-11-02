# ruff: noqa: T201 - herramienta CLI: print es la salida
"""P19.1-07 - doble commit concurrente sobre PostgreSQL real."""
from __future__ import annotations

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

SKU = "DOUBLE-TEST-01"
ORDER = "DOUBLE-0001"


async def main() -> int:
    host = os.environ.get("P19_EXTERNAL_HOST", "127.0.0.1")
    port = int(os.environ.get("P19_EXTERNAL_PORT", "55432"))
    database = os.environ.get("P19_EXTERNAL_DB", "zent_external_mvp")
    ext = await asyncpg.connect(
        host=host,
        port=port,
        database=database,
        user="p19_admin",
        password="p19_admin_dev_2026",
    )
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P19 Double {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(org.id, "Default", "default")
    connector = await PostgresConnectorRepository().create_connector(
        org.id,
        f"P19 Double {uuid4().hex[:6]}",
        "postgres",
        workspace_id=workspace.id,
        config_json={
            "host": host,
            "port": port,
            "database": database,
            "user": "p19_writer",
            "ssl": False,
        },
    )
    await get_secret_store().put(org.id, connector.id, {"password": "p19_writer_dev_2026"})
    base_binding = {
        "id": str(uuid4()),
        "organization_id": str(org.id),
        "workspace_id": str(workspace.id),
        "capability_ref": "bodega.stock.commit",
        "provider_kind": "inventory",
        "config": {
            "action": "reserve_stock",
            "write": True,
            "connector_id": str(connector.id),
            "max_quantity": 5,
        },
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }
    try:
        await ext.execute(
            "INSERT INTO bodega.products (sku, name, category, unit, price) "
            "VALUES ($1, 'Double test', 'test', 'unit', 1.00) ON CONFLICT (sku) DO NOTHING",
            SKU,
        )
        await ext.execute(
            "INSERT INTO bodega.stock (sku, on_hand, reserved, version) VALUES ($1, 5, 0, 0) "
            "ON CONFLICT (sku) DO UPDATE SET on_hand = 5, reserved = 0",
            SKU,
        )
        await ext.execute(
            "INSERT INTO bodega.orders (order_number, customer_ref, status, payment_status, total) "
            "VALUES ($1, 'DOUBLE', 'pending_approval', 'pending', 5.00) "
            "ON CONFLICT (order_number) DO NOTHING",
            ORDER,
        )
        reserved = await execute_inventory_action(
            org.id,
            base_binding,
            {"order_number": ORDER, "sku": SKU, "quantity": 1, "ttl_seconds": 60},
            workspace_id=workspace.id,
        )
        commit_binding = {
            **base_binding,
            "config": {**base_binding["config"], "action": "commit_stock"},
        }

        async def _commit():
            return await execute_inventory_action(
                org.id,
                commit_binding,
                {"order_number": ORDER, "sku": SKU, "quantity": 1},
                workspace_id=workspace.id,
            )

        results = await asyncio.gather(_commit(), _commit(), return_exceptions=True)
        statuses = [item.get("status") if isinstance(item, dict) else type(item).__name__ for item in results]
        stock = await ext.fetchrow("SELECT on_hand, reserved FROM bodega.stock WHERE sku = $1", SKU)
        movements = await ext.fetchval(
            "SELECT COUNT(*) FROM bodega.stock_movements WHERE sku = $1 AND order_number = $2",
            SKU,
            ORDER,
        )
        reservations = await ext.fetchval(
            "SELECT COUNT(*) FROM bodega.stock_reservations WHERE sku = $1 AND order_number = $2 AND status = 'committed'",
            SKU,
            ORDER,
        )
        evidence = {
            "schema": "zent.cert.inventory-double-commit/1",
            "reserve_status": reserved.get("status"),
            "commit_statuses": statuses,
            "on_hand": int(stock["on_hand"]),
            "reserved": int(stock["reserved"]),
            "movements": int(movements),
            "committed_reservations": int(reservations),
            "pass": reserved.get("status") == "RESERVED"
            and sorted(statuses) == ["ALREADY_APPLIED", "COMMITTED"]
            and int(stock["on_hand"]) == 4
            and int(movements) == 1
            and int(reservations) == 1,
        }
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        from pathlib import Path

        out = Path("artifacts/certification/inventory-double-commit.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if evidence["pass"] else 1
    finally:
        await ext.execute("DELETE FROM bodega.stock_reservations WHERE sku = $1", SKU)
        await ext.execute("DELETE FROM bodega.stock_movements WHERE sku = $1", SKU)
        await ext.execute("DELETE FROM bodega.orders WHERE order_number = $1", ORDER)
        await ext.execute("DELETE FROM bodega.stock WHERE sku = $1", SKU)
        await ext.execute("DELETE FROM bodega.products WHERE sku = $1", SKU)
        await ext.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
