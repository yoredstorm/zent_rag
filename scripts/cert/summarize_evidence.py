# =============================================================================
# Certification: resumen legible de toda la evidencia de un SHA
# =============================================================================
#   python scripts/cert/summarize_evidence.py --sha <sha>
#
# Lee artifacts/certification/<sha>/ y artifacts/release/<sha>/ e imprime un
# resumen compacto (para pegar en el reporte) + escribe summary.json.
from __future__ import annotations

# ruff: noqa: T201 - herramienta CLI: print es la salida
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Resumen de evidencia de certificación")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    base = ROOT / "artifacts" / "certification" / args.sha
    release = ROOT / "artifacts" / "release" / args.sha
    summary: dict = {"sha": args.sha, "sections": {}}

    invariants = _read(base / "invariants" / "invariants.evidence.json")
    if invariants:
        summary["sections"]["invariants"] = {
            "result": invariants.get("result"),
            "targets": len(invariants.get("targets") or []),
            "duration_seconds": invariants.get("duration_seconds"),
        }

    battery_dir = base / "battery"
    if battery_dir.exists():
        suites = {}
        for path in sorted(battery_dir.glob("*.json")):
            data = _read(path) or {}
            suites[data.get("suite", path.stem)] = {
                "scenarios": data.get("summary"),
                "tests": data.get("totals"),
                "not_demonstrated": [
                    s["id"]
                    for s in data.get("scenarios", [])
                    if s.get("status") == "not_demonstrated"
                ],
            }
        summary["sections"]["battery"] = suites

    perf_dir = base / "perf"
    if perf_dir.exists():
        runs = {}
        for path in sorted(perf_dir.glob("cert-*.json")):
            data = _read(path) or {}
            runs[path.stem] = data.get("summary") or data
        probe = _read(perf_dir / "http-probe.json")
        matrix = _read(perf_dir / "matrix.json")
        summary["sections"]["perf"] = {
            "runs": runs,
            "http_probe": probe,
            "matrix_runs": (matrix or {}).get("runs"),
        }

    migrations = _read(base / "migrations.json")
    if migrations:
        summary["sections"]["migrations"] = {
            step: {"exit": data.get("exit"), "seconds": data.get("seconds")}
            for step, data in (migrations.get("steps") or {}).items()
        }

    rehearsal = _read(base / "rollback" / "rehearsal.json")
    if rehearsal:
        summary["sections"]["rollback"] = {
            "passed": rehearsal.get("passed"),
            "rollback_seconds": rehearsal.get("rollback_seconds"),
            "steps": [
                {"step": s.get("step"), "seconds": s.get("seconds")}
                for s in rehearsal.get("steps") or []
            ],
        }

    manifest = _read(release / "manifest.json")
    if manifest:
        summary["sections"]["manifest"] = {
            "decision": (manifest.get("release_decision") or {}).get("decision"),
            "tests": {
                name: (data.get("status") if isinstance(data, dict) else data)
                for name, data in (manifest.get("tests") or {}).items()
            },
            "migration_head": (manifest.get("migrations") or {}).get("migration_head"),
            "sbom_components": None,
        }
        sbom = _read(ROOT / "artifacts" / "release" / args.sha / "sbom.json")
        if sbom:
            summary["sections"]["manifest"]["sbom_components"] = len(sbom.get("components") or [])

    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    out = Path(args.out) if args.out else base / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(rendered)
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
