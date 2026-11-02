# ruff: noqa: T201 - herramienta CLI: print es la salida
"""P19.1-07 - barrido periodico de reservas de inventario expiradas.

Uso:
  python -m src.scripts.expire_inventory_reservations \
    --org <uuid> --workspace <uuid> --capability bodega.stock.reserve

El scheduler externo (cron/worker) debe ejecutarlo con lock de lider; el
adaptador usa pg_try_advisory_xact_lock y SKIP LOCKED para no duplicar trabajo.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from src.platform.workflows.bindings import resolve_binding
from src.platform.workflows.inventory_adapter import expire_inventory_reservations


async def _run(args: argparse.Namespace) -> int:
    binding = await resolve_binding(args.org, args.capability, args.workspace)
    if binding is None:
        print(json.dumps({"status": "NOT_CONFIGURED", "capability": args.capability}))
        return 2
    result = await expire_inventory_reservations(
        args.org,
        binding,
        workspace_id=args.workspace,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Expirar reservas de inventario")
    parser.add_argument("--org", required=True, type=UUID)
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--capability", default="bodega.stock.reserve")
    parser.add_argument("--batch-size", type=int, default=500)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
