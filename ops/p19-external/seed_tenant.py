# =============================================================================
# P19-06 — Publica el conector externo y sus planes en un tenant demo.
#
# Uso (desde la raíz, con la DB externa levantada):
#   $env:ORG_ID="..."; $env:WORKSPACE_ID="..."
#   .\.venv\Scripts\python.exe ops\p19-external\seed_tenant.py
# =============================================================================
from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
from src.infrastructure.secrets.secret_store_resolver import get_secret_store
from src.platform.workflows.bindings import upsert_binding


def _price_plan(connector_id: UUID) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "catalog", "name": "product_prices", "kind": "table"},
        "operation": "get_one",
        "projection": ["sku", "product_name", "price", "currency", "valid_from", "valid_to"],
        "allowed_columns": [
            "sku",
            "product_name",
            "price",
            "currency",
            "valid_from",
            "valid_to",
            "channel",
        ],
        "required_predicates": [
            {"field": "channel", "op": "eq", "source": "binding", "value": "retail"}
        ],
        "parameters": [
            {"name": "sku", "field": "sku", "operator": "eq", "type": "string", "required": True}
        ],
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
        "resource_ref": "catálogo/product_prices",
        "column_types": {
            "sku": "string",
            "product_name": "string",
            "price": "number",
            "currency": "string",
            "valid_from": "date",
            "valid_to": "date",
        },
    }


def _loyalty_plan(connector_id: UUID) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "loyalty", "name": "loyalty_balances", "kind": "table"},
        "operation": "get_one",
        "projection": ["customer_ref", "points_balance", "status", "last_activity_at"],
        "allowed_columns": ["customer_ref", "points_balance", "status", "last_activity_at"],
        "ownership": {
            "field": "customer_ref",
            "principal_claim": "customer_ref",
            "required": True,
        },
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True, "pii_class": "personal"},
        "resource_ref": "fidelidad/loyalty_balances",
        "column_types": {
            "customer_ref": "string",
            "points_balance": "integer",
            "status": "string",
            "last_activity_at": "datetime",
        },
    }


def _order_plan(connector_id: UUID) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "sales", "name": "orders", "kind": "table"},
        "operation": "get_one",
        "projection": ["order_number", "status", "total", "currency", "updated_at"],
        "allowed_columns": [
            "order_number",
            "customer_ref",
            "status",
            "total",
            "currency",
            "updated_at",
            "shipping_address",
        ],
        "parameters": [
            {
                "name": "order_number",
                "field": "order_number",
                "operator": "eq",
                "type": "string",
                "required": True,
            }
        ],
        "ownership": {
            "field": "customer_ref",
            "principal_claim": "customer_ref",
            "required": True,
        },
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True, "pii_class": "personal"},
        "resource_ref": "ventas/orders",
        "column_types": {
            "order_number": "string",
            "status": "string",
            "total": "number",
            "currency": "string",
            "updated_at": "datetime",
        },
    }


def _bodega_plan(connector_id: UUID) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "bodega", "name": "product_catalog_v", "kind": "view"},
        "operation": "get_one",
        "projection": ["sku", "name", "category", "unit", "price", "currency", "available"],
        "allowed_columns": [
            "sku",
            "name",
            "category",
            "unit",
            "price",
            "currency",
            "available",
            "on_hand",
            "reserved",
        ],
        "parameters": [
            {"name": "sku", "field": "sku", "operator": "eq", "type": "string", "required": True}
        ],
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
        "resource_ref": "bodega/product_catalog",
        "column_types": {
            "sku": "string",
            "name": "string",
            "category": "string",
            "unit": "string",
            "price": "number",
            "currency": "string",
            "available": "integer",
        },
    }


def _inventory_binding(connector_id: UUID) -> dict:
    return {
        "connector_id": str(connector_id),
        "action": "commit_stock",
        "write": True,
        "max_quantity": 100,
    }


async def main() -> None:
    org_id = UUID(os.environ["ORG_ID"])
    workspace_id = UUID(os.environ["WORKSPACE_ID"])
    connector = await PostgresConnectorRepository().create_connector(
        org_id,
        f"ERP externo P19 {uuid4().hex[:6]}",
        "postgres",
        workspace_id=workspace_id,
        config_json={
            "host": os.environ.get("P19_EXTERNAL_HOST", "host.docker.internal"),
            "port": int(os.environ.get("P19_EXTERNAL_PORT", "55432")),
            "database": os.environ.get("P19_EXTERNAL_DB", "zent_external_mvp"),
            "user": os.environ.get("P19_EXTERNAL_USER", "p19_reader"),
            "ssl": False,
            "managed": False,
        },
    )
    await get_secret_store().put(
        org_id,
        connector.id,
        {"password": os.environ.get("P19_EXTERNAL_PASSWORD", "p19_reader_dev_2026")},
    )
    writer = await PostgresConnectorRepository().create_connector(
        org_id,
        f"ERP externo P19 escritura {uuid4().hex[:6]}",
        "postgres",
        workspace_id=workspace_id,
        config_json={
            "host": os.environ.get("P19_EXTERNAL_HOST", "host.docker.internal"),
            "port": int(os.environ.get("P19_EXTERNAL_PORT", "55432")),
            "database": os.environ.get("P19_EXTERNAL_DB", "zent_external_mvp"),
            "user": os.environ.get("P19_WRITER_USER", "p19_writer"),
            "ssl": False,
            "managed": False,
            "write": True,
        },
    )
    await get_secret_store().put(
        org_id,
        writer.id,
        {"password": os.environ.get("P19_WRITER_PASSWORD", "p19_writer_dev_2026")},
    )
    plans = {
        "p19.external.price": _price_plan(connector.id),
        "p19.external.loyalty": _loyalty_plan(connector.id),
        "p19.external.order": _order_plan(connector.id),
        "bodega.product.get": _bodega_plan(connector.id),
    }
    for capability_ref, config in plans.items():
        await upsert_binding(
            org_id,
            capability_ref,
            "connected_db",
            config=config,
            workspace_id=workspace_id,
        )
    await upsert_binding(
        org_id,
        "bodega.stock.commit",
        "inventory",
        config=_inventory_binding(writer.id),
        workspace_id=workspace_id,
    )
    print(f"connector_id={connector.id}")  # noqa: T201
    print(f"writer_connector_id={writer.id}")  # noqa: T201
    print("bindings=" + ",".join([*plans, "bodega.stock.commit"]))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
