#!/usr/bin/env python
"""Planifica shards de pytest agrupando archivos completos por duracion.

`pytest-split --splitting-algorithm least_duration` balancea tests individuales,
pero puede separar tests del mismo archivo. Eso rompe fixtures de modulo,
estado compartido y tests que dependen del orden interno del archivo. Este
planificador hace LPT (longest processing time) sobre la duracion total de cada
archivo y asigna archivos completos a cada shard: mismo balance, sin romper la
unidad de aislamiento.

Uso (una invocacion por shard; la asignacion es determinista):
    python scripts/ci/shard_plan.py --splits 6 --group 3 \
        --durations-path .test_durations \
        --exclude-file /tmp/invariant-files.txt \
        --exclude-dir tests/certification/workflows
"""

from __future__ import annotations

import argparse
import heapq
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _test_files(root: str) -> list[str]:
    result = subprocess.run(  # noqa: S603,S607 - git del repo con argumentos fijos
        ["git", "ls-files", root],  # noqa: S607 - git resuelto por PATH en CI/local
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git ls-files fallo: {result.stderr}")
    return sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if line.endswith(".py")
        and (Path(line).name.startswith("test_") or Path(line).name.endswith("_test.py"))
    )


def _excluded_files(path: Path) -> set[str]:
    if not path.is_file():
        raise SystemExit(f"no existe --exclude-file: {path}")
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--splits", required=True, type=int)
    parser.add_argument("--group", required=True, type=int)
    parser.add_argument("--durations-path", type=Path, default=ROOT / ".test_durations")
    parser.add_argument("--tests-root", default="tests")
    parser.add_argument("--exclude-file", type=Path, default=None)
    parser.add_argument("--exclude-dir", action="append", default=[])
    args = parser.parse_args()
    if args.splits < 1 or not 1 <= args.group <= args.splits:
        raise SystemExit("--splits >= 1 y 1 <= --group <= --splits")

    excluded = _excluded_files(args.exclude_file) if args.exclude_file else set()
    exclude_dirs = tuple(args.exclude_dir) + ("tests/certification/workflows",)
    files = [
        f
        for f in _test_files(args.tests_root)
        if f not in excluded and not any(f.startswith(prefix) for prefix in exclude_dirs)
    ]
    if not files:
        raise SystemExit("no quedaron archivos de test para planificar")

    durations: dict[str, float] = json.loads(args.durations_path.read_text(encoding="utf-8"))
    per_file: dict[str, float] = {f: 0.0 for f in files}
    tests_per_file: dict[str, int] = {f: 0 for f in files}
    for nodeid, seconds in durations.items():
        path = nodeid.split("::", 1)[0]
        if path in per_file:
            per_file[path] += max(float(seconds), 0.0)
            tests_per_file[path] += 1
    observed = [value for value in per_file.values() if value > 0]
    fallback = statistics.median(observed) if observed else 0.5
    for path, value in per_file.items():
        if value <= 0:
            per_file[path] = fallback

    items = sorted(files, key=lambda path: (-per_file[path], path))
    groups: list[list[str]] = [[] for _ in range(args.splits)]
    totals = [0.0] * args.splits
    heap = [(0.0, index) for index in range(args.splits)]
    heapq.heapify(heap)
    for path in items:
        current, index = heapq.heappop(heap)
        groups[index].append(path)
        totals[index] = current + per_file[path]
        heapq.heappush(heap, (totals[index], index))

    selected = sorted(groups[args.group - 1])
    print(
        f"shard {args.group}/{args.splits}: files={len(selected)} "
        f"tests~{sum(tests_per_file[f] for f in selected)} "
        f"estimated={totals[args.group - 1]:.1f}s",
        file=sys.stderr,
    )
    for path in selected:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
