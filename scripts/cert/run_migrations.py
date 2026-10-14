# =============================================================================
# Certification: evidencia de migraciones (forward + rollback) en DB scratch
# =============================================================================
#   python scripts/cert/run_migrations.py --database rag_cert_mig
#
# Mide:
#   - upgrade head desde cero (duración)
#   - downgrade -1 y upgrade head de nuevo (rollback de la última revisión)
#   - lock risk de las últimas N revisiones (DDL bloqueante sin CONCURRENTLY)
# Escribe evidence JSON.
from __future__ import annotations

# ruff: noqa: T201, S603, S607 - herramienta CLI; subprocess con args fijos
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "src" / "infrastructure" / "db_init" / "versions"


def _alembic(args: list[str], database: str) -> tuple[int, str, float]:
    env = {**os.environ, "RAG_POSTGRES_DB": database, "PYTHONPATH": str(ROOT)}
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    return (
        completed.returncode,
        (completed.stdout + completed.stderr).strip()[-400:],
        round(time.perf_counter() - started, 2),
    )


def _recent_revisions(limit: int = 10) -> list[dict]:
    files = sorted(VERSIONS.glob("*.py"), key=lambda p: p.stat().st_mtime)
    findings = []
    for path in files[-limit:]:
        text = path.read_text(encoding="utf-8", errors="replace")
        revision = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', text, re.M)
        blocking = []
        if re.search(r"CREATE INDEX(?!\s+CONCURRENTLY)", text):
            blocking.append("CREATE INDEX sin CONCURRENTLY")
        if re.search(r"ALTER TABLE[^;]*ADD COLUMN[^;]*NOT NULL(?!\s+DEFAULT)", text):
            blocking.append("ADD COLUMN NOT NULL sin DEFAULT")
        if re.search(r"ALTER TABLE[^;]*DROP COLUMN", text):
            blocking.append("DROP COLUMN (destructivo)")
        if re.search(r"def downgrade", text) is None:
            blocking.append("sin downgrade")
        findings.append(
            {
                "revision": revision.group(1) if revision else path.stem,
                "file": str(path.relative_to(ROOT)),
                "blocking_ddl": blocking,
            }
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidencia de migraciones")
    parser.add_argument("--database", default="rag_cert_mig")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    out = Path(args.out) if args.out else ROOT / "artifacts" / "certification" / sha / "migrations.json"

    results: dict = {
        "schema": "zent.cert.migrations/1",
        "git_sha": sha,
        "database": args.database,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "recent_revisions": _recent_revisions(),
        "versions_total": len(list(VERSIONS.glob("*.py"))),
        "versions_with_downgrade": sum(
            1 for p in VERSIONS.glob("*.py") if "def downgrade" in p.read_text(encoding="utf-8", errors="replace")
        ),
    }
    code, tail, seconds = _alembic(["upgrade", "head"], args.database)
    results["steps"]["upgrade_head"] = {"exit": code, "seconds": seconds, "tail": tail}

    code, tail, seconds = _alembic(["current"], args.database)
    results["steps"]["current"] = {"exit": code, "seconds": seconds, "tail": tail}

    code, tail, seconds = _alembic(["downgrade", "-1"], args.database)
    results["steps"]["downgrade_minus_one"] = {"exit": code, "seconds": seconds, "tail": tail}

    code, tail, seconds = _alembic(["upgrade", "head"], args.database)
    results["steps"]["upgrade_head_again"] = {"exit": code, "seconds": seconds, "tail": tail}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failures = [k for k, v in results["steps"].items() if v["exit"] != 0]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
