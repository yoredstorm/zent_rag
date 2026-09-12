#!/usr/bin/env python
# =============================================================================
# Knowledge V2 status — readiness operativo del cutover (Phase H)
#
# Uso:
#   python -m src.scripts.knowledge_v2_status --org <uuid>
#   python -m src.scripts.knowledge_v2_status               (todas las orgs)
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.knowledge.cutover import assess_v2_readiness


def _print(line: str) -> None:
    print(line)  # noqa: T201 (CLI)


async def list_organizations() -> list[UUID]:
    session = await get_async_session()
    try:
        rows = (await session.execute(text("SELECT id FROM organizations ORDER BY created_at"))).fetchall()
        return [row.id for row in rows]
    finally:
        await session.close()


async def _main(args: argparse.Namespace) -> None:
    orgs: list[UUID]
    if args.org:
        orgs = [UUID(args.org)]
    else:
        orgs = await list_organizations()
    _print(f"CUTOVER READINESS — organizaciones: {len(orgs)}")
    for org in orgs:
        status = await assess_v2_readiness(org)
        _print(
            f"[{status['organization_id']}] ready={status['ready']} "
            f"docs={status['counts']['structured_documents']} "
            f"blocks={status['counts']['structured_blocks']} "
            f"corpora={status['counts']['knowledge_corpora']} "
            f"flags={status['flags']}"
        )
        _print("  gate: " + status["gate"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge V2 cutover status")
    parser.add_argument("--org", help="Organization UUID (default: todas)")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
