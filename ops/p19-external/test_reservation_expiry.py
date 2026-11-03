"""Prueba real de expiración de reserva (ejecutar dentro de rag-api)."""
from __future__ import annotations

import asyncio
import time
from uuid import UUID

from src.platform.workflows.bindings import BindingError, execute_binding

ORG = UUID("d7cafbf1-5764-41fe-a50e-97c8d97fc834")
WS = UUID("d28ec9d6-020f-4537-a715-dc4ff34e888d")


async def main() -> None:
    reserved = await execute_binding(
        ORG,
        "bodega.stock.reserve",
        {"order_number": "BOD-1003", "sku": "BD-QUINUA-01", "quantity": 1, "ttl_seconds": 30},
        workspace_id=WS,
    )
    print("reserve=", reserved["output"])  # noqa: T201
    time.sleep(35)
    try:
        committed = await execute_binding(
            ORG,
            "bodega.stock.commit",
            {"order_number": "BOD-1003", "sku": "BD-QUINUA-01", "quantity": 1},
            workspace_id=WS,
        )
        print("commit=", committed["output"])  # noqa: T201
    except BindingError as exc:
        print("commit_error=", exc.code, exc.message)  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main())
