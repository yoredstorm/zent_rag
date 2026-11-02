# ruff: noqa: T201 - herramienta CLI: print es la salida
"""P20-01 - migracion idempotente/dry-run de fuentes SQL existentes.

No adjudica identidades por nombre. Solo normaliza fuentes que ya tienen un
`connector_id` unico y reporta ambiguedades para revision humana.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="default; no escribe")
    parser.add_argument("--org", default="")
    args = parser.parse_args()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id::text, organization_id::text, workspace_id::text, name, type, "
                    "status, config_json FROM kb_sources WHERE type IN ('sql','postgres','postgresql') "
                    "AND (:oid = '' OR organization_id::text = :oid) ORDER BY organization_id, name"
                ),
                {"oid": args.org},
            )
        ).fetchall()
        report = []
        for row in rows:
            config = dict(row.config_json or {})
            connector_id = str(config.get("connector_id") or "")
            item = {
                "source_id": row.id,
                "org": row.organization_id,
                "workspace": row.workspace_id,
                "name": row.name,
                "type": row.type,
                "status": row.status,
                "connector_id": connector_id or None,
                "action": "skip_no_connector",
            }
            if connector_id:
                needs_config = (
                    row.type != "sql"
                    or not config.get("source_mode")
                    or not config.get("connection_status")
                    or not config.get("catalog_status")
                )
                item["action"] = "normalize_config" if needs_config else "noop"
            else:
                item["reason"] = "legacy_sql_internal_no_connector"
            report.append(item)
            if args.apply and item["action"] == "normalize_config":
                merged = {
                    **config,
                    "source_mode": config.get("source_mode") or "schema_only",
                    "connection_status": config.get("connection_status") or "connected",
                    "catalog_status": config.get("catalog_status") or "discovered",
                    "snapshot_status": config.get("snapshot_status") or "not_supported",
                    "allowed_resources": config.get("allowed_resources") or [],
                    "revision": int(config.get("revision") or 1),
                }
                await session.execute(
                    text(
                        "UPDATE kb_sources SET type='sql', status='ready', "
                        "config_json=CAST(:cfg AS jsonb), updated_at=NOW() WHERE id=:sid"
                    ),
                    {"cfg": json.dumps(merged), "sid": row.id},
                )
        if args.apply:
            await session.commit()
        print(json.dumps({"dry_run": not args.apply, "sources": report}, ensure_ascii=False, indent=2))
        return 0
    finally:
        await session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
