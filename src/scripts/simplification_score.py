# =============================================================================
# Simplification Score — writers/readers/autoridades/flags/fallbacks (F0).
# =============================================================================
# Métricas objetivas sobre el repo, sin heurísticas opacas: cuenta ocurrencias
# reales de patrones indicadores por subsistema. Sirve de baseline y de
# comparación antes/después de cada fase de simplificación.
#
# Uso:
#   python -m src.scripts.simplification_score
#   python -m src.scripts.simplification_score --format json --out artifacts/simplification.json
# =============================================================================
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Subsistemas medidos: nombre -> directorios/archivos.
SUBSYSTEMS: dict[str, tuple[str, ...]] = {
    "agent_runtime": ("src/agents/runtime",),
    "runtime_core": ("src/runtime",),
    "decision": ("src/decision",),
    "cache": ("src/infrastructure/redis",),
    "accounting": (
        "src/runtime/run_budget.py",
        "src/runtime/run_accounting.py",
    ),
    "metrics": ("src/infrastructure/observability",),
    "retrieval": ("src/rag",),
}

_TERMINALS = "FINALIZED|ABSTAINED|BLOCKED|FAILED|LIMIT_REACHED|UNDETERMINED"
PATTERNS: dict[str, re.Pattern[str]] = {
    # Escrituras directas a la proyección legacy (fuera de _adaptive_publish).
    "adaptive_writers": re.compile(r'adaptive\["[a-z_]+"\]\s*='),
    # Transiciones terminales fuera de la política (allowlist cerrada).
    "terminal_transitions": re.compile(
        rf"phase\s*=\s*RunPhase\.(?:{_TERMINALS})"
        rf"|return\s+RunPhase\.(?:{_TERMINALS})"
        rf"|\(RunPhase\.(?:{_TERMINALS})\)"
    ),
    # Emisiones de reason_code (contrato reason-codes-1): kwargs y dicts.
    "reason_code_literals": re.compile(
        r"reason_code[\"']?\s*[:=]\s*[\"']"
    ),
    # Fallbacks declarados en código.
    "fallbacks": re.compile(r"\bfallback", re.IGNORECASE),
    # Feature flags leídos de settings.
    "settings_reads": re.compile(r"getattr\(settings,\s*[\"']([A-Z][A-Z0-9_]+)"),
    # Autoridades explícitas (menciones de AuthorityLevel / policy resolver).
    "authority_refs": re.compile(r"AuthorityLevel|FinalizationAction|authoritative"),
    # except Exception (candidatos a política explícita).
    "except_exception": re.compile(r"except Exception"),
}


def _paths(targets: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for target in targets:
        path = ROOT / target
        if path.is_dir():
            out.extend(sorted(path.rglob("*.py")))
        elif path.suffix == ".py" and path.exists():
            out.append(path)
    return [p for p in out if "__pycache__" not in p.parts]


def measure() -> dict:
    report: dict[str, dict] = {}
    for name, targets in SUBSYSTEMS.items():
        paths = _paths(targets)
        counts = {key: 0 for key in PATTERNS}
        loc = 0
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore")
            loc += len(text.splitlines())
            for key, pattern in PATTERNS.items():
                counts[key] += len(pattern.findall(text))
        report[name] = {"files": len(paths), "loc": loc, **counts}
    return report


def hotspots(limit: int = 10) -> list[dict]:
    """Archivos más largos del runtime medido (candidatos a extracción)."""
    seen: set[Path] = set()
    rows: list[dict] = []
    for targets in SUBSYSTEMS.values():
        for path in _paths(targets):
            if path in seen:
                continue
            seen.add(path)
            rows.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "loc": len(path.read_text(encoding="utf-8", errors="ignore").splitlines()),
                }
            )
    rows.sort(key=lambda item: item["loc"], reverse=True)
    return rows[:limit]


def render_markdown(report: dict) -> str:
    keys = ["files", "loc", *PATTERNS.keys()]
    header = "| Subsistema | " + " | ".join(keys) + " |"
    sep = "|---" * (len(keys) + 1) + "|"
    lines = [
        "# Simplification score — baseline",
        "",
        "Generado por `python -m src.scripts.simplification_score` (solo lectura).",
        "`adaptive_writers` fuera de la proyección debe ser 0; "
        "`terminal_transitions` vive en la allowlist cerrada.",
        "",
        header,
        sep,
    ]
    total = {key: 0 for key in keys}
    for name, counts in report.items():
        row = [str(counts.get(key, 0)) for key in keys]
        for key, value in zip(keys, row, strict=True):
            total[key] += int(value)
        lines.append(f"| {name} | " + " | ".join(row) + " |")
    lines.append(
        "| **total** | " + " | ".join(str(total[key]) for key in keys) + " |"
    )
    lines += ["", "## Hotspots (LOC)", ""]
    for item in hotspots():
        lines.append(f"- `{item['path']}` — {item['loc']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simplification score del repo")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    report = measure()
    text = (
        json.dumps({"subsystems": report, "hotspots": hotspots()}, ensure_ascii=False, indent=2)
        if args.format == "json"
        else render_markdown(report)
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"escrito: {out_path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
