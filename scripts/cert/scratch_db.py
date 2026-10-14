# ruff: noqa: T201 - herramienta CLI: print es la salida del comando
# =============================================================================
# Certification: base de datos scratch (paridad con CI)
# =============================================================================
# El DB de desarrollo local acumula drift (datos de tests, seeds viejos), y los
# tests que dependen de estado sembrado fallan por datos, no por código. CI crea
# una base limpia por run: este script replica esa condición.
#
#   python scripts/cert/scratch_db.py create --name rag_cert
#   python scripts/cert/scratch_db.py init   --name rag_cert
#   python scripts/cert/scratch_db.py drop   --name rag_cert
#
# `init` aplica los mismos pasos que .github/workflows/ci.yml (job test):
#   1. scripts src/infrastructure/db_init/[0-9][0-9]-*.sql
#   2. seed del dev key (mismo INSERT que CI)
#   3. alembic upgrade head
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DEV_KEY_SQL = (
    "INSERT INTO api_keys (id, organization_id, key_hash, key_prefix, name, scopes) "
    "SELECT '30000000-0000-0000-0000-000000000001',"
    "'00000000-0000-0000-0000-000000000001',"
    "encode(sha256('rag_test_dev_token_for_local_testing_123'::bytea),'hex'),"
    "'rag_test_','Dev Token','[\"rag:query\",\"rag:ingest\",\"admin:*\"]'::jsonb "
    "WHERE EXISTS (SELECT 1 FROM organizations WHERE id='00000000-0000-0000-0000-000000000001') "
    "AND NOT EXISTS (SELECT 1 FROM api_keys WHERE organization_id='00000000-0000-0000-0000-000000000001');"
)


def _dsn(database: str = "postgres") -> dict:
    from src.core.config import get_settings

    settings = get_settings()
    return {
        "host": settings.POSTGRES_HOST,
        "port": int(settings.POSTGRES_PORT),
        "user": settings.POSTGRES_USER,
        "password": settings.POSTGRES_PASSWORD.get_secret_value()
        if hasattr(settings.POSTGRES_PASSWORD, "get_secret_value")
        else settings.POSTGRES_PASSWORD,
        "database": database,
    }


async def _create(name: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(**_dsn())
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists:
            print(f"db {name} ya existe")
            return
        await conn.execute(f'CREATE DATABASE "{name}"')
        print(f"db {name} creada")
    finally:
        await conn.close()


async def _drop(name: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(**_dsn())
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        print(f"db {name} eliminada")
    finally:
        await conn.close()


async def _init(name: str, out_dir: Path) -> int:
    import asyncpg

    started = time.perf_counter()
    sql_files = sorted((ROOT / "src" / "infrastructure" / "db_init").glob("[0-9][0-9]-*.sql"))
    conn = await asyncpg.connect(**_dsn(name))
    applied: list[str] = []
    try:
        for path in sql_files:
            try:
                await conn.execute(path.read_text(encoding="utf-8"))
                applied.append(path.name)
            except Exception as exc:  # noqa: BLE001 - reportar y cortar
                print(f"FAIL {path.name}: {type(exc).__name__}: {exc}")
                return 1
        await conn.execute(DEV_KEY_SQL)
        applied.append("dev-key-seed")
    finally:
        await conn.close()

    env = {**__import__("os").environ, "RAG_POSTGRES_DB": name, "PYTHONPATH": str(ROOT)}
    alembic = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    head = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    ).stdout.strip()

    payload = {
        "schema": "zent.cert.scratch-db/1",
        "database": name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sql_files_applied": applied,
        "alembic_exit_code": alembic.returncode,
        "alembic_head": head,
        "duration_seconds": round(time.perf_counter() - started, 1),
        "source": "mirrors .github/workflows/ci.yml job `test`",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "scratch-db.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if alembic.returncode == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Base de datos scratch de certificación")
    parser.add_argument("action", choices=["create", "init", "drop"])
    parser.add_argument("--name", default="rag_cert")
    parser.add_argument("--out-dir", default="artifacts/certification/scratch-db")
    args = parser.parse_args()
    if args.action == "create":
        asyncio.run(_create(args.name))
        return 0
    if args.action == "drop":
        asyncio.run(_drop(args.name))
        return 0
    return asyncio.run(_init(args.name, ROOT / args.out_dir))


if __name__ == "__main__":
    raise SystemExit(main())
