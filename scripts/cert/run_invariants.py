# ruff: noqa: T201, S603, S607 - herramienta CLI: print es la salida; git/pytest del PATH con args fijos
# =============================================================================
# Certification: invariantes de arquitectura con la lista EXACTA de CI
# =============================================================================
# Extrae la lista de tests del paso "Architecture invariants (fast, required)"
# de .github/workflows/ci.yml (así la evidencia no puede divergir de CI) y los
# corre con junitxml + evidencia JSON.
#
#   python scripts/cert/run_invariants.py [--out-dir artifacts/certification/<sha>/invariants]
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def invariant_targets() -> list[str]:
    text = CI_YML.read_text(encoding="utf-8")
    match = re.search(
        r"Architecture invariants \(fast, required\).*?pytest \\\n(.*?)-q --no-header",
        text,
        re.S,
    )
    if not match:
        raise SystemExit("no pude extraer la lista de invariantes de ci.yml")
    return re.findall(r"(tests/[\w./]+\.py)", match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Invariantes de arquitectura (lista CI)")
    parser.add_argument("--out-dir", default="")
    args = parser.parse_args()

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "artifacts" / "certification" / sha / "invariants"
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = invariant_targets()
    junit = out_dir / "junit-invariants.xml"
    log = out_dir / "pytest-invariants.log"
    command = [sys.executable, "-m", "pytest", *targets, "-q", "--no-header", f"--junitxml={junit}"]

    started = datetime.now(timezone.utc)
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    finished = datetime.now(timezone.utc)
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")

    payload = {
        "schema": "zent.cert.invariants/1",
        "generated_at": finished.isoformat(),
        "git_sha": sha,
        "git_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
            ).stdout.strip()
        ),
        "source": ".github/workflows/ci.yml -> 'Architecture invariants (fast, required)'",
        "targets": targets,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "result": "pass" if completed.returncode == 0 else "fail",
        "duration_seconds": round((finished - started).total_seconds(), 1),
        "junit": str(junit),
        "log": str(log),
    }
    (out_dir / "invariants.evidence.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
