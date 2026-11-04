# =============================================================================
# Instala el workflow conversacional de bodega (idempotente).
# =============================================================================
# 1. binding `bodega.product.search` sobre el conector lector de P19;
# 2. plantilla `bodega_conversational_order`;
# 3. workflow durable con waits `conversation.message`.
#
# Uso:
#   $env:PYTHONPATH="D:\zent_RAG"
#   uv run --frozen --no-sync python ops/p19-external/create_conversational_order_workflow.py
# =============================================================================
from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresConnectorRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.commerce.conversational_order_demo import (
    TEMPLATE_NAME,
    build_graph,
    demo_conversation,
    demo_payload,
    template_row,
)
from src.platform.workflows.bindings import upsert_binding
from src.platform.workflows.engine import create_workflow, list_workflows, update_workflow

WORKFLOW_NAME = TEMPLATE_NAME


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def _search_config(connector_id: UUID) -> dict:
    return {
        "connector_id": str(connector_id),
        "action": "search_products",
        "write": False,
        "max_rows": 2,
    }


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
        trigger_type="event",
        trigger_config={"event_type": "conversation.message"},
        description=(
            "Pedido paso a paso por chat: producto, cantidad, delivery o recojo, "
            "dirección y confirmación; reserva stock y pide aprobación humana."
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
    await upsert_binding(
        org,
        "bodega.product.search",
        "inventory",
        config=_search_config(reader.id),
        workspace_id=workspace,
        created_by=created_by,
    )

    await _ensure_template()
    workflow_id = await _ensure_workflow(org, workspace, created_by)

    print(f"reader_connector_id={reader.id}")  # noqa: T201
    print("template_slug=bodega_conversational_order")  # noqa: T201
    print(f"workflow_id={workflow_id}")  # noqa: T201
    print("demo_payload=" + json.dumps(demo_payload(), ensure_ascii=False))  # noqa: T201
    print("conversation=" + json.dumps(demo_conversation(), ensure_ascii=False))  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
