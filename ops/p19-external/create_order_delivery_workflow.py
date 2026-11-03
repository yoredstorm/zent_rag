r"""Instala el demo de pedido, cliente y delivery en un tenant.

Uso:
  $env:ORG_ID="..."; $env:WORKSPACE_ID="..."; $env:CREATED_BY="..."
  $env:P19_WRITER_PASSWORD="..."
  .\.venv\Scripts\python.exe ops\p19-external\create_order_delivery_workflow.py

Requisitos:
- conector lector de P19 ya registrado en el workspace;
- rol p19_writer con permisos de escritura en bodega.*;
- DB externa levantada.
"""
from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
from src.infrastructure.postgres.session import get_async_session
from src.infrastructure.secrets.secret_store_resolver import get_secret_store
from src.platform.commerce.order_delivery_demo import (
    TEMPLATE_NAME,
    TEMPLATE_SLUG,
    build_graph,
    demo_payload,
    template_row,
)
from src.platform.workflows.bindings import upsert_binding
from src.platform.workflows.engine import create_workflow, list_workflows, update_workflow

WRITER_NAME = "Bodega pepito escritura"
WORKFLOW_NAME = TEMPLATE_NAME


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def _product_plan(connector_id: UUID) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "bodega", "name": "product_catalog_v", "kind": "view"},
        "operation": "get_one",
        "projection": ["sku", "name", "unit", "price", "currency", "available"],
        "allowed_columns": [
            "sku",
            "name",
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
            "unit": "string",
            "price": "number",
            "currency": "string",
            "available": "integer",
        },
    }


def _history_plan(connector_id: UUID) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "connection_ref": str(connector_id),
        "resource": {"schema": "bodega", "name": "orders", "kind": "table"},
        "operation": "list",
        "projection": ["order_number", "status", "total", "currency", "created_at"],
        "allowed_columns": [
            "order_number",
            "customer_ref",
            "status",
            "total",
            "currency",
            "created_at",
        ],
        "parameters": [
            {
                "name": "customer_ref",
                "field": "customer_ref",
                "operator": "eq",
                "type": "string",
                "required": True,
            }
        ],
        "order_by": [{"field": "created_at", "direction": "desc"}],
        "policy": {
            "max_rows": 5,
            "timeout_ms": 3000,
            "read_only": True,
            "pii_class": "internal",
        },
        "purpose": "Demo: contar pedidos previos del cliente sin exponer PII.",
        "resource_ref": "bodega/orders",
        "column_types": {
            "order_number": "string",
            "status": "string",
            "total": "number",
            "currency": "string",
            "created_at": "datetime",
        },
    }


def _inventory(connector_id: UUID, action: str) -> dict:
    return {
        "connector_id": str(connector_id),
        "action": action,
        "write": True,
        "max_quantity": 100,
    }


async def _writer_connector(org: UUID, workspace: UUID):
    repo = PostgresConnectorRepository()
    existing = await repo.list_connectors(org, workspace_id=workspace)
    for connector in existing:
        if connector.name == WRITER_NAME:
            return connector
    connector = await repo.create_connector(
        org,
        WRITER_NAME,
        "postgres",
        workspace_id=workspace,
        config_json={
            "host": _env("P19_EXTERNAL_HOST", "host.docker.internal"),
            "port": int(_env("P19_EXTERNAL_PORT", "55432")),
            "database": _env("P19_EXTERNAL_DB", "zent_external_mvp"),
            "user": _env("P19_WRITER_USER", "p19_writer"),
            "ssl": False,
            "managed": False,
            "write": True,
            "ssrf_allowlist": ["host.docker.internal"],
        },
    )
    await get_secret_store().put(
        org,
        connector.id,
        {"password": _env("P19_WRITER_PASSWORD", "p19_writer_dev_2026")},
    )
    return connector


async def _reader_connector(org: UUID, workspace: UUID):
    repo = PostgresConnectorRepository()
    for connector in await repo.list_connectors(org, workspace_id=workspace):
        cfg = connector.config_json if isinstance(connector.config_json, dict) else {}
        if (
            connector.type in ("postgres", "postgresql")
            and str(cfg.get("user") or "") in ("p19_reader", "p19_admin")
            and not cfg.get("write")
        ):
            return connector
    raise SystemExit("No encontré el conector lector de P19 en el workspace.")


async def _ensure_template() -> None:
    row = template_row()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_templates "
                "(id, slug, name, description, category, trigger_type, steps, "
                "trigger_config, package, graph) "
                "VALUES (gen_random_uuid(), :slug, :name, :description, :category, "
                ":trigger_type, CAST(:steps AS jsonb), CAST(:trigger_config AS jsonb), "
                "CAST(:package AS jsonb), CAST(:graph AS jsonb)) "
                "ON CONFLICT (slug) DO UPDATE SET "
                "name = EXCLUDED.name, description = EXCLUDED.description, "
                "category = EXCLUDED.category, trigger_type = EXCLUDED.trigger_type, "
                "package = EXCLUDED.package, graph = EXCLUDED.graph"
            ),
            {
                "slug": row["slug"],
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
                "trigger_type": row["trigger_type"],
                "steps": json.dumps(row["steps"]),
                "trigger_config": json.dumps(row["trigger_config"]),
                "package": json.dumps(row["package"]),
                "graph": json.dumps(row["graph"]),
            },
        )
        await session.commit()
    finally:
        await session.close()


async def _ensure_workflow(org: UUID, workspace: UUID, created_by: UUID | None) -> str:
    existing = await list_workflows(org, workspace_id=workspace)
    for workflow in existing.get("workflows", []):
        if workflow.get("name") == WORKFLOW_NAME:
            await update_workflow(
                org,
                UUID(str(workflow["id"])),
                graph=build_graph(),
                workflow_version=2,
            )
            return str(workflow["id"])
    out = await create_workflow(
        org,
        WORKFLOW_NAME,
        trigger_type="webhook",
        trigger_config={},
        description=(
            "Demo: pedido, historial del cliente, delivery o recojo y pago "
            "simulado con aprobación humana."
        ),
        created_by=created_by,
        workspace_id=workspace,
        graph=build_graph(),
        workflow_version=2,
    )
    return str(out["workflow_id"])


async def main() -> None:
    org = UUID(_env("ORG_ID", "e42d1f42-b87d-4baf-88dc-ec3da1541239"))
    workspace = UUID(_env("WORKSPACE_ID", "074a851b-f056-4d16-9ccd-ceaddc387305"))
    created_by_raw = os.environ.get("CREATED_BY") or "ddbe826b-d7fc-4fa0-8c34-53a7e49357fc"
    try:
        created_by = UUID(created_by_raw)
    except ValueError:
        created_by = None

    reader = await _reader_connector(org, workspace)
    writer = await _writer_connector(org, workspace)

    await upsert_binding(
        org,
        "bodega.product.get",
        "connected_db",
        config=_product_plan(reader.id),
        workspace_id=workspace,
        created_by=created_by,
    )
    await upsert_binding(
        org,
        "p19.customer.orders",
        "connected_db",
        config=_history_plan(reader.id),
        workspace_id=workspace,
        created_by=created_by,
    )
    for ref, action in (
        ("bodega.order.create", "create_order"),
        ("bodega.stock.reserve_batch", "reserve_stock_batch"),
        ("bodega.stock.commit_batch", "commit_order_stock"),
        ("bodega.stock.release_batch", "release_order_stock"),
    ):
        await upsert_binding(
            org,
            ref,
            "inventory",
            config=_inventory(writer.id, action),
            workspace_id=workspace,
            created_by=created_by,
        )

    await _ensure_template()
    workflow_id = await _ensure_workflow(org, workspace, created_by)

    print(f"reader_connector_id={reader.id}")  # noqa: T201
    print(f"writer_connector_id={writer.id}")  # noqa: T201
    print(f"template_slug={TEMPLATE_SLUG}")  # noqa: T201
    print(f"workflow_id={workflow_id}")  # noqa: T201
    print("demo_payload=" + json.dumps(demo_payload(), ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
