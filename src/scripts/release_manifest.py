# =============================================================================
# Release Evidence Manifest — artifact machine-readable + human-readable
# =============================================================================
# Ligado al SHA: registra build, dependencias, migraciones, resultados de tests,
# invariantes, checks de seguridad, digests de imagen, evidencia de
# performance/load/chaos/seguridad/contabilidad, warnings conocidos, riesgos
# aceptados y la decisión de release.
#
# Reglas:
#   - Se GENERA desde evidencia real (nunca se escribe a mano).
#   - NUNCA guarda secretos: solo nombres de variables y fingerprints.
#   - Lo que falta se registra como `not_available` (jamás como verde).
#
# Uso:
#   python -m src.scripts.release_manifest \
#     --sha <sha> --decision READY_FOR_INTERNAL \
#     --suite <evidence.json> ... --invariants <evidence.json> ... \
#     --battery-dir artifacts/certification/<sha>/battery \
#     --evidence perf=artifacts/perf/x.json --evidence load=artifacts/load/y.json \
#     --check "ruff=pass" --check "gitleaks=pass" \
#     --image-digest sha256:... --out-dir artifacts/release/<sha>
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DECISIONS = (
    "NO_GO",
    "READY_FOR_INTERNAL",
    "READY_FOR_CANARY",
    "READY_FOR_PRODUCTION",
)


def _sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(args: list[str]) -> str:
    """Comando fijo del propio tooling (git/uv/alembic del PATH)."""
    try:
        return subprocess.run(  # noqa: S603 - lista de args construida acá
            args, cwd=ROOT, capture_output=True, text=True, timeout=60
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - la evidencia no rompe la generación
        return ""


def _dependency_fingerprints() -> dict:
    files = {
        "uv_lock": "uv.lock",
        "pyproject": "pyproject.toml",
        "python_version": ".python-version",
        "portal_lock": "portal/package-lock.json",
        "portal_package": "portal/package.json",
        "sdk_node_lock": "sdk/node/package-lock.json",
        "dockerfile_api": "Dockerfile.api",
        "dockerfile_portal": "portal/Dockerfile",
        "compose_prod": "docker-compose.prod.yml",
    }
    return {
        name: {"path": rel, "sha256": _sha256(ROOT / rel)}
        for name, rel in files.items()
    }


def _alembic_head() -> dict:
    """Head real del grafo de revisiones (usa el ScriptDirectory de Alembic).

    Fallback: parser de `revision`/`down_revision` (soporta anotaciones de tipo
    y tuplas de merge).
    """
    versions = ROOT / "src" / "infrastructure" / "db_init" / "versions"
    head = ""
    total = len(list(versions.glob("*.py")))
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        head = heads[0] if heads else ""
    except Exception:  # noqa: BLE001 - fallback a parser propio
        revisions: dict[str, list[str]] = {}
        for path in versions.glob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            revision = re.search(
                r'^revision(?:\s*:[^=]+)?\s*=\s*["\']([^"\']+)["\']', text, re.M
            )
            down = re.search(r"^down_revision(?:\s*:[^=]+)?\s*=\s*([^\n]+)", text, re.M)
            if not revision:
                continue
            parents = re.findall(r'["\']([^"\']+)["\']', down.group(1)) if down else []
            revisions[revision.group(1)] = parents
        referenced = {parent for parents in revisions.values() for parent in parents}
        heads = sorted(rev for rev in revisions if rev not in referenced)
        head = heads[-1] if heads else ""
    return {
        "migration_head": head,
        "revisions": total,
        "source": "alembic ScriptDirectory (script_location=src/infrastructure/db_init)",
        "applied_head_at_evidence_time": _run(
            [sys.executable, "-m", "alembic", "heads"]
        ).splitlines()[-1:] or [""],
    }


def _junit_summary(path: Path) -> dict:
    import xml.etree.ElementTree as ET

    if not path.exists():
        return {"status": "not_available", "path": str(path)}
    tree = ET.parse(path)  # noqa: S314 - junit escrito por nuestro pytest
    root = tree.getroot()
    suites = list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            totals[key] += int(float(suite.get(key) or 0))
    failed = [
        f"{case.get('classname')}::{case.get('name')}"
        for case in root.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    ]
    return {
        "status": "pass" if totals["failures"] == 0 and totals["errors"] == 0 else "fail",
        "path": str(path),
        "sha256": _sha256(path),
        **totals,
        "failed_tests": failed[:20],
    }


def _suite_evidence(path: Path) -> dict:
    if not path.exists():
        return {"status": "not_available", "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "status": data.get("result", "unknown"),
        "path": str(path),
        "sha256": _sha256(path),
        "label": data.get("label"),
        "git_sha": data.get("git_sha"),
        "environment": data.get("environment"),
        "database": data.get("database"),
        "duration_seconds": data.get("duration_seconds"),
        "exit_code": data.get("exit_code"),
        "junit": _junit_summary(Path(data.get("junit", ""))),
    }


def _battery_evidence(directory: Path) -> dict:
    if not directory.exists():
        return {"status": "not_available", "path": str(directory)}
    suites = {}
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        suites[data.get("suite", path.stem)] = {
            "status": (
                "pass"
                if data.get("summary", {}).get("fail", 0) == 0
                and data.get("summary", {}).get("not_demonstrated", 0) == 0
                and data.get("totals", {}).get("fail", 0) == 0
                and data.get("totals", {}).get("error", 0) == 0
                else "fail"
            ),
            "path": str(path),
            "sha256": _sha256(path),
            "scenarios": data.get("summary"),
            "tests": data.get("totals"),
            "not_demonstrated": [
                f"{s['id']} {s['title']}"
                for s in data.get("scenarios", [])
                if s.get("status") == "not_demonstrated"
            ],
            "failures": [
                f"{s['id']} {s['title']}"
                for s in data.get("scenarios", [])
                if s.get("status") == "fail"
            ],
        }
    if not suites:
        status = "not_available"
    else:
        status = "pass" if all(s["status"] == "pass" for s in suites.values()) else "fail"
    return {"status": status, "path": str(directory), "suites": suites}


def _perf_evidence(path: Path) -> dict:
    if not path.exists():
        return {"status": "not_available", "path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary") or data
    return {
        "status": "measured",
        "path": str(path),
        "sha256": _sha256(path),
        "label": data.get("label"),
        "generated_at": data.get("generated_at"),
        "queries_file": data.get("queries_file"),
        "iterations": data.get("iterations"),
        "summary": summary,
    }


def _load_risks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yml", ".yaml"}:
        import yaml

        data = yaml.safe_load(text) or {}
        return list(data.get("risks") or [])
    data = json.loads(text)
    return list(data.get("risks") or data if isinstance(data, dict) else data)


def build_manifest(args: argparse.Namespace) -> dict:
    sha = args.sha or _run(["git", "rev-parse", "HEAD"])
    evidence = {}
    for item in args.evidence or []:
        name, _, raw_path = item.partition("=")
        path = Path(raw_path)
        evidence[name] = _perf_evidence(path) if "perf" in name or "load" in name else _perf_evidence(path)

    checks = {}
    for item in args.check or []:
        name, _, result = item.partition("=")
        checks[name] = result or "unknown"

    return {
        "schema": "zent.release-evidence/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "src/scripts/release_manifest.py",
        "git": {
            "sha": sha,
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            "tag": _run(["git", "describe", "--tags", "--always"]),
            "dirty": bool(_run(["git", "status", "--porcelain"])),
            "subject": _run(["git", "log", "-1", "--format=%s"]),
        },
        "build": {
            "identifier": args.build_id
            or f"local-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            "ci_run": args.ci_run or "not_available",
            "python": sys.version.split()[0],
            "uv": _run(["uv", "--version"]).split(" ")[1] if _run(["uv", "--version"]) else "",
            "platform": platform.platform(),
        },
        "dependencies": _dependency_fingerprints(),
        "sbom": {
            "path": args.sbom or "not_available",
            "sha256": _sha256(Path(args.sbom)) if args.sbom else "",
        },
        "migrations": _alembic_head(),
        "frontend": {
            "artifact": args.frontend_artifact or "not_built_in_this_run",
            "package_version": _portal_version(),
        },
        "containers": {
            "image": args.image or "not_available",
            "image_id": args.image_id or "not_available",
            "base_images_pinned_by_digest": False,
        },
        "checks": checks,
        "tests": {
            "full_suite": _suite_evidence(Path(args.suite)) if args.suite else {"status": "not_available"},
            "invariants": _suite_evidence(Path(args.invariants)) if args.invariants else {"status": "not_available"},
            "battery": _battery_evidence(Path(args.battery_dir)) if args.battery_dir else {"status": "not_available"},
        },
        "evidence": evidence,
        "known_warnings": _load_lines(Path(args.warnings)) if args.warnings else [],
        "accepted_risks": _load_risks(Path(args.risks)) if args.risks else [],
        "release_decision": {
            "decision": args.decision,
            "reason": args.decision_reason or "",
            "environment": args.environment or "local-workstation",
            "certified_by": args.certified_by or "automated certification run",
        },
    }


def _portal_version() -> str:
    path = ROOT / "portal" / "package.json"
    if not path.exists():
        return ""
    return str(json.loads(path.read_text(encoding="utf-8")).get("version") or "")


def _load_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_markdown(manifest: dict) -> str:
    git = manifest["git"]
    decision = manifest["release_decision"]
    lines = [
        "# Release Evidence Manifest",
        "",
        f"- SHA: `{git['sha']}` ({git['branch']}, dirty={git['dirty']})",
        f"- Generado: {manifest['generated_at']} por `{manifest['generated_by']}`",
        f"- Build: `{manifest['build']['identifier']}` (CI run: {manifest['build']['ci_run']})",
        f"- Runtime: Python {manifest['build']['python']} / uv {manifest['build']['uv']}"
        f" / {manifest['build']['platform']}",
        f"- Migración head: `{manifest['migrations']['migration_head']}`",
        f"- **Decisión: {decision['decision']}** ({decision['environment']})",
        f"- Motivo: {decision['reason'] or 'n/a'}",
        "",
        "## Tests",
        "",
        "| Suite | Estado | Detalle |",
        "|---|---|---|",
    ]
    for name, data in manifest["tests"].items():
        if name == "battery":
            suites = data.get("suites") or {}
            detail = ", ".join(f"{key}:{value.get('status')}" for key, value in suites.items())
            lines.append(f"| battery | {data.get('status')} | {detail or 'sin suites'} |")
            continue
        junit = data.get("junit") or {}
        lines.append(
            f"| {name} | {data.get('status')} | "
            f"tests={junit.get('tests', 'n/a')} fail={junit.get('failures', 'n/a')} "
            f"err={junit.get('errors', 'n/a')} skip={junit.get('skipped', 'n/a')} |"
        )
    lines += ["", "## Checks", "", "| Check | Resultado |", "|---|---|"]
    for name, result in (manifest["checks"] or {}).items():
        lines.append(f"| {name} | {result} |")
    lines += ["", "## Evidencia externa", "", "| Evidencia | Estado | Archivo |", "|---|---|---|"]
    for name, data in (manifest["evidence"] or {}).items():
        lines.append(f"| {name} | {data.get('status')} | `{data.get('path')}` |")
    lines += ["", "## Dependencias (fingerprints)", "", "| Archivo | sha256 |", "|---|---|"]
    for _name, data in manifest["dependencies"].items():
        lines.append(f"| {data['path']} | `{data['sha256'][:16]}…` |")
    if manifest["known_warnings"]:
        lines += ["", "## Warnings conocidos", ""] + [
            f"- {item}" for item in manifest["known_warnings"]
        ]
    if manifest["accepted_risks"]:
        lines += ["", "## Riesgos aceptados", ""]
        for risk in manifest["accepted_risks"]:
            lines.append(
                f"- [{risk.get('severity', '?')}] {risk.get('title', '?')} — "
                f"owner: {risk.get('owner', '?')} — {risk.get('mitigation', '')}"
            )
    lines += [
        "",
        "> Este manifest se genera desde evidencia real. Cualquier resultado "
        "`not_available` significa NO DEMOSTRADO, nunca verde. Si el código "
        "cambia, este archivo caduca: regenerar antes de promover.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Release Evidence Manifest")
    parser.add_argument("--sha", default="")
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--decision", default="NO_GO", choices=DECISIONS)
    parser.add_argument("--decision-reason", default="")
    parser.add_argument("--environment", default="")
    parser.add_argument("--certified-by", default="")
    parser.add_argument("--suite", default="")
    parser.add_argument("--invariants", default="")
    parser.add_argument("--battery-dir", default="")
    parser.add_argument(
        "--evidence",
        action="append",
        default=[],
        help="nombre=ruta (repetible): evidencia externa (perf, load, chaos, ...)",
    )
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        help="nombre=resultado (repetible): check ejecutado por el runner",
    )
    parser.add_argument("--sbom", default="")
    parser.add_argument("--image", default="")
    parser.add_argument("--image-id", default="")
    parser.add_argument("--frontend-artifact", default="")
    parser.add_argument("--build-id", default="")
    parser.add_argument("--ci-run", default="")
    parser.add_argument("--warnings", default="")
    parser.add_argument("--risks", default="")
    args = parser.parse_args()

    manifest = build_manifest(args)
    sha = manifest["git"]["sha"]
    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "artifacts" / "release" / sha
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "manifest.json"
    md_path = out_dir / "manifest.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(manifest), encoding="utf-8")
    print(
        json.dumps(
            {
                "json": str(json_path),
                "md": str(md_path),
                "decision": manifest["release_decision"]["decision"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
