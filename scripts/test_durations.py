#!/usr/bin/env python
"""Genera `.test_durations` para pytest-split desde un JUnit de CI.

pytest-split usa el archivo para repartir tests por duración entre shards.
El JUnit de GitHub no trae el nodeid completo (solo `classname` + `name`), así
que se resuelve contra la colección actual de pytest. Los tests nuevos sin
duración reciben la mediana para no desbalancear el reparto.

Uso:
    python scripts/test_durations.py \
        --junit artifacts/certification/<sha>/ci/junit-tests.xml
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _collected_nodeids() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 5):
        sys.stderr.write(result.stderr)
        raise SystemExit(f"pytest --collect-only falló con {result.returncode}")
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    ]


def _candidates(classname: str, name: str) -> list[str]:
    """Posibles nodeids para un `classname` JUnit con o sin clases."""
    parts = [part for part in classname.split(".") if part]
    nodes: list[str] = []
    for split_at in range(len(parts), 1, -1):
        module = "/".join(parts[:split_at]) + ".py"
        classes = parts[split_at:]
        nodes.append(f"{module}::{'::'.join(classes + [name])}")
    return nodes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / ".test_durations")
    parser.add_argument(
        "--fallback",
        type=Path,
        default=None,
        help="Durations previos para tests que no aparecen en el JUnit (runs parciales).",
    )
    args = parser.parse_args()

    fallback: dict[str, float] = {}
    if args.fallback and args.fallback.exists():
        fallback = json.loads(args.fallback.read_text(encoding="utf-8"))

    collected = _collected_nodeids()
    collected_set = set(collected)
    root = ET.parse(args.junit).getroot()  # noqa: S314 - JUnit propio del CI

    durations: dict[str, float] = {}
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        if not classname or not name:
            continue
        for node in _candidates(classname, name):
            if node in collected_set:
                durations[node] = max(float(case.get("time") or 0.0), 0.0)
                break

    if not durations:
        raise SystemExit("no se pudo mapear ningún test del JUnit a la colección")

    mapped = len(durations)
    fill = statistics.median(durations.values())
    from_fallback = 0
    for node in collected:
        if node in durations:
            continue
        if node in fallback:
            durations[node] = fallback[node]
            from_fallback += 1
        else:
            durations[node] = fill

    args.out.write_text(
        json.dumps(dict(sorted(durations.items())), indent=0),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "collected": len(collected),
                "mapped_from_junit": mapped,
                "from_fallback": from_fallback,
                "tests": len(durations),
                "estimated_seconds": round(sum(durations.values()), 1),
                "median_seconds": round(fill, 3),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
