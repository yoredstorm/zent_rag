#!/usr/bin/env python
# =============================================================================
# Company Intelligence demo seed — escenario "Fare Audit" (§26)
#
# Uso:
#   python -m src.scripts.company_demo_seed --org <uuid>
#   python -m src.scripts.company_demo_seed --list
#   python -m src.scripts.company_demo_seed --org <uuid> --with-candidates
#
# Idempotente: las entidades tienen id determinista, correrlo dos veces no
# duplica nada. Sirve para demos, capturas y pruebas manuales de la Studio.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from sqlalchemy import text

from src.company.demo_seed import seed_demo_candidates, seed_fare_audit_demo
from src.infrastructure.postgres.session import get_async_session


def _print(line: str) -> None:
    print(line)  # noqa: T201 (CLI)


async def list_organizations() -> list[tuple[UUID, str]]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text("SELECT id, name FROM organizations ORDER BY created_at")
            )
        ).fetchall()
        return [(row.id, row.name) for row in rows]
    finally:
        await session.close()


async def _main(args: argparse.Namespace) -> int:
    if args.list:
        organizations = await list_organizations()
        if not organizations:
            _print("No hay organizaciones.")
            return 0
        for organization_id, name in organizations:
            _print(f"{organization_id}  {name}")
        return 0

    if not args.org:
        _print("Falta --org <uuid> (o usá --list para ver las disponibles).")
        return 2

    organization_id = UUID(args.org)
    result = await seed_fare_audit_demo(
        organization_id, with_learning=not args.skip_learning
    )
    _print("Escenario Fare Audit sembrado:")
    for key, value in result.to_dict().items():
        _print(f"  {key}: {value}")

    if args.with_candidates:
        created = await seed_demo_candidates(organization_id)
        _print(f"  candidatos de descubrimiento: {created}")

    _print("")
    _print("Abrí el portal en /company-intelligence para recorrerlo.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Siembra el demo de Company Intelligence")
    parser.add_argument("--org", help="UUID de la organización")
    parser.add_argument("--list", action="store_true", help="Listar organizaciones")
    parser.add_argument(
        "--skip-learning",
        action="store_true",
        help="No sembrar Finding ni Experiment del Learning Engine",
    )
    parser.add_argument(
        "--with-candidates",
        action="store_true",
        help="Sembrar también un candidato de hueco de conocimiento",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args)))


if __name__ == "__main__":
    sys.exit(main())
