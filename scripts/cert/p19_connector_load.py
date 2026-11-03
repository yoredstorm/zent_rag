# ruff: noqa: T201 - herramienta CLI: print es la salida
"""P19.1-08 - carga real: 100 lecturas concurrentes por el pool acotado."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from uuid import uuid4

from src.infrastructure.postgres.relational_db import (
    PostgresConnectorRepository,
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.secrets.secret_store_resolver import get_secret_store
from src.platform.workflows.bindings import _execute_connected_select


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("P19_EXTERNAL_HOST", "127.0.0.1"))
    parser.add_argument("--port", default=int(os.environ.get("P19_EXTERNAL_PORT", "55432")))
    parser.add_argument("--db", default=os.environ.get("P19_EXTERNAL_DB", "zent_external_mvp"))
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--out", default="artifacts/certification/connector-load.json")
    args = parser.parse_args()

    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"P19 Load {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(org.id, "Default", "default")
    connector = await PostgresConnectorRepository().create_connector(
        org.id,
        f"P19 Load {uuid4().hex[:6]}",
        "postgres",
        workspace_id=workspace.id,
        config_json={
            "host": args.host,
            "port": args.port,
            "database": args.db,
            "user": "p19_reader",
            "ssl": False,
            "connect_timeout_seconds": 5,
        },
    )
    await get_secret_store().put(org.id, connector.id, {"password": "p19_reader_dev_2026"})
    binding = {
        "id": str(uuid4()),
        "organization_id": str(org.id),
        "workspace_id": str(workspace.id),
        "capability_ref": "p19.load.price",
        "provider_kind": "connected_db",
        "config": {
            "schema": "zent.data.query.binding/v1",
            "scope": "workspace",
            "connection_ref": str(connector.id),
            "resource": {"schema": "catalog", "name": "product_prices", "kind": "table"},
            "operation": "get_one",
            "projection": ["sku", "product_name", "price", "currency"],
            "allowed_columns": ["sku", "product_name", "price", "currency", "channel"],
            "parameters": [
                {"name": "sku", "field": "sku", "operator": "eq", "type": "string", "required": True}
            ],
            "required_predicates": [
                {"field": "channel", "op": "eq", "source": "binding", "value": "retail"}
            ],
            "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
        },
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }
    sem = asyncio.Semaphore(max(1, args.concurrency))
    latencies: list[float] = []
    errors: list[str] = []

    async def _read():
        async with sem:
            started = time.perf_counter()
            try:
                result = await _execute_connected_select(
                    org.id,
                    binding,
                    {"params": {"sku": "ARR-001"}},
                    workspace_id=workspace.id,
                )
                if result.get("status") != "FOUND":
                    errors.append(str(result.get("status")))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}:{str(exc)[:120]}")
            finally:
                latencies.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*[_read() for _ in range(args.requests)])
    ordered = sorted(latencies)

    def _pct(value: float) -> float:
        if not ordered:
            return 0.0
        index = min(len(ordered) - 1, int(round((value / 100) * (len(ordered) - 1))))
        return round(ordered[index], 2)

    evidence = {
        "schema": "zent.cert.connector-load/1",
        "requests": args.requests,
        "concurrency": args.concurrency,
        "errors": errors[:10],
        "error_rate": round(len(errors) / max(1, args.requests), 4),
        "latency_ms": {
            "p50": _pct(50),
            "p95": _pct(95),
            "p99": _pct(99),
            "mean": round(statistics.mean(ordered), 2) if ordered else 0.0,
        },
        "pass": not errors,
    }
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    from pathlib import Path

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if evidence["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
