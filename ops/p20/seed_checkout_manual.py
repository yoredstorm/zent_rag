"""Publica la plantilla `retail_checkout_manual` en la base local/tenant.

Uso:
    python ops/p20/seed_checkout_manual.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.infrastructure.postgres.session import get_async_session  # noqa: E402
from src.platform.commerce.checkout_manual import (  # noqa: E402
    snapshot_payload,
)


async def main() -> None:
    payload = snapshot_payload()
    row = payload["template"]
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_templates "
                "(slug, name, description, category, trigger_type, steps, "
                "trigger_config, package, graph) "
                "VALUES (:slug, :name, :descr, :cat, :trigger, '[]'::jsonb, "
                "CAST(:tcfg AS jsonb), CAST(:pkg AS jsonb), CAST(:graph AS jsonb)) "
                "ON CONFLICT (slug) DO UPDATE SET "
                "name = EXCLUDED.name, description = EXCLUDED.description, "
                "category = EXCLUDED.category, trigger_type = EXCLUDED.trigger_type, "
                "trigger_config = EXCLUDED.trigger_config, "
                "package = EXCLUDED.package, graph = EXCLUDED.graph"
            ),
            {
                "slug": row["slug"],
                "name": row["name"],
                "descr": row["description"],
                "cat": row["category"],
                "trigger": row["trigger_type"],
                "tcfg": json.dumps(row["trigger_config"], ensure_ascii=False),
                "pkg": json.dumps(row["package"], ensure_ascii=False),
                "graph": json.dumps(row["graph"], ensure_ascii=False),
            },
        )
        await session.commit()
    finally:
        await session.close()
    print(f"template={row['slug']} nodes={len(row['graph']['nodes'])}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
