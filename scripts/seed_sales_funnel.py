"""Refresca el snapshot del embudo y re-siembra plantilla + producto.

Flujo:

1. Genera `src/infrastructure/db_init/seeds/retail_sales_funnel.json` desde la
   definición viva (`src/platform/commerce/sales_funnel.py::snapshot_payload`).
   La migración 158 lee ese JSON porque infrastructure no puede importar la capa
   de plataforma (invariante de arquitectura).
2. Ejecuta las sentencias de la migración 158 (contratos de capacidades y
   eventos, addon de mensajería, plantilla y producto de marketplace).

Las instancias vivas conservan su snapshot congelado: re-sembrar la plantilla no
toca procesos en curso.

Uso:
    python scripts/seed_sales_funnel.py            # refresca y siembra
    python scripts/seed_sales_funnel.py --check    # solo verifica el snapshot
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_MIGRATION = "src.infrastructure.db_init.versions.158_commerce_sales_funnel"
SNAPSHOT_PATH = _ROOT / "src" / "infrastructure" / "db_init" / "seeds" / "retail_sales_funnel.json"


def build_snapshot() -> dict:
    from src.platform.commerce.sales_funnel import snapshot_payload

    return snapshot_payload()


def write_snapshot() -> Path:
    SNAPSHOT_PATH.write_text(
        json.dumps(build_snapshot(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return SNAPSHOT_PATH


def load_snapshot() -> dict:
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


async def _seed() -> None:
    from src.core.config import Settings

    migration = importlib.import_module(_MIGRATION)
    engine = create_async_engine(Settings().POSTGRES_DSN, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            for statement in migration.seed_statements():
                await connection.execute(statement)
            await connection.commit()
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args and args[0] == "--check":
        if build_snapshot() != load_snapshot():
            print("SNAPSHOT DESACTUALIZADO: corre el script sin --check y commitea el JSON")
            return 1
        print("snapshot OK")
        return 0
    path = write_snapshot()
    print(f"snapshot refrescado en {path}")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_seed())
    print("Plantilla retail_sales_funnel y producto retail-sales-funnel publicados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
