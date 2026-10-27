"""P17-00 — snapshot de invariantes del Knowledge OS.

Solo lectura. Cuenta filas y calcula hashes de IDs/estado para comparar antes y
después de cada fase UX. No incluye contenido documental ni credenciales.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.infrastructure.postgres.session import get_async_session

DEFAULT_OUT = Path("artifacts/certification/p17/invariants.json")

TABLES: tuple[str, ...] = (
    "knowledge_bases",
    "kb_sources",
    "source_documents",
    "structured_documents",
    "ingestion_jobs",
    "knowledge_corpora",
    "knowledge_canonical_objects",
    "knowledge_assertions",
    "knowledge_edges",
    "knowledge_conflicts",
    "context_gaps",
    "knowledge_learning_sessions",
    "knowledge_compilations",
    "evidence_ledger",
    "workflows",
    "agents",
)

STATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "kb_sources": ("status", "workspace_id"),
    "knowledge_assertions": ("status",),
    "knowledge_conflicts": ("status",),
    "context_gaps": ("status",),
    "ingestion_jobs": ("status",),
    "knowledge_learning_sessions": ("status",),
    "workflows": ("status",),
}


def git_head() -> str:
    git = shutil.which("git")
    if not git:
        return ""
    try:
        return subprocess.check_output(  # noqa: S603 — ruta resuelta por shutil.which
            [git, "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return ""


async def table_snapshot(session, table: str) -> dict[str, Any]:
    exists = (
        await session.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"})
    ).scalar()
    if exists is None:
        return {"exists": False, "count": None, "hash": None}
    count = int(
        (await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar() or 0  # noqa: S608
    )
    columns = STATE_COLUMNS.get(table, ())
    state_parts = ["id::text", *[f"{column}::text" for column in columns]]
    state_expr = " || ':' || ".join(f"COALESCE({part}, '')" for part in state_parts)
    try:
        digest = (
            await session.execute(
                text(
                    f"SELECT md5(COALESCE(string_agg({state_expr}, ',' ORDER BY id), '')) "  # noqa: S608
                    f"FROM {table}"  # noqa: S608
                )
            )
        ).scalar()
    except Exception:  # noqa: BLE001 — columna opcional ausente en una versión previa
        await session.rollback()
        digest = (
            await session.execute(
                text(
                    f"SELECT md5(COALESCE(string_agg(id::text, ',' ORDER BY id), '')) "  # noqa: S608
                    f"FROM {table}"  # noqa: S608
                )
            )
        ).scalar()
    return {
        "exists": True,
        "count": count,
        "hash": hashlib.sha256(str(digest or "").encode()).hexdigest()[:16],
        "state_columns": list(columns),
    }


async def snapshot() -> dict[str, Any]:
    session = await get_async_session()
    try:
        tables = {}
        for table in TABLES:
            tables[table] = await table_snapshot(session, table)
    finally:
        await session.close()
    return {
        "schema": "zent.p17.invariants/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "head": git_head(),
        "tables": tables,
        "note": (
            "Read-only counts and deterministic ID/state hashes. Compare before and "
            "after a UX phase; no document content or secrets are stored."
        ),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    payload = await snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "tables": len(payload["tables"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
