"""Audita el puntero publicado de P13. Read-only; sale 1 si hay brechas."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from src.infrastructure.postgres.session import get_async_session  # noqa: E402


async def run() -> int:
    session = await get_async_session()
    try:
        active_missing = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflows "
                    "WHERE status = 'active' AND published_version_id IS NULL"
                )
            )
        ).scalar()
        duplicate_production = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "SELECT workflow_id FROM workflow_versions WHERE status = 'production' "
                    "GROUP BY workflow_id HAVING COUNT(*) > 1) dup"
                )
            )
        ).scalar()
        legacy = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflow_versions WHERE legacy_baseline = true"
                )
            )
        ).scalar()
        hash_mismatch = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM workflows w JOIN workflow_versions v "
                    "ON v.id = w.published_version_id "
                    "WHERE w.published_graph_hash IS NOT NULL "
                    "AND v.graph_hash IS NOT NULL AND w.published_graph_hash <> v.graph_hash"
                )
            )
        ).scalar()
    finally:
        await session.close()
    report = {
        "active_missing_pointer": int(active_missing or 0),
        "duplicate_production": int(duplicate_production or 0),
        "legacy_baselines": int(legacy or 0),
        "published_hash_mismatch": int(hash_mismatch or 0),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if (
        report["active_missing_pointer"]
        or report["duplicate_production"]
        or report["published_hash_mismatch"]
    ) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoría P13 de punteros publicados")
    parser.parse_args()
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
