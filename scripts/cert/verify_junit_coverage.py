#!/usr/bin/env python
"""Verifica que el JUnit fusionado cubra exactamente la coleccion de pytest.

El merge estricto detecta XML invalidos, shards faltantes y duplicados, pero no
puede saber si un test desaparecio del JUnit. Este chequeo recolecta la suite
con el mismo alcance que CI y compara los nodeids contra los testcases del
artifact. Falla si falta un test, si sobra uno o si hay IDs sin mapear.

Uso (CI, despues del merge):
    python scripts/cert/verify_junit_coverage.py \
        --junit artifacts/junit-tests.xml
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _collected_nodeids() -> list[str]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/",
            "--ignore=tests/certification/workflows",
            "--collect-only",
            "-q",
            "--no-header",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
    )
    if result.returncode not in (0, 5):
        sys.stderr.write(result.stderr)
        raise SystemExit(f"pytest --collect-only fallo con {result.returncode}")
    return [
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    ]


def _candidates(classname: str, name: str) -> list[str]:
    parts = [part for part in classname.split(".") if part]
    nodes: list[str] = []
    for split_at in range(len(parts), 1, -1):
        module = "/".join(parts[:split_at]) + ".py"
        classes = parts[split_at:]
        nodes.append(f"{module}::{'::'.join(classes + [name])}")
    return nodes


def _manifest_nodeids(manifests_dir: Path, splits: int) -> set[str]:
    expected_files = [
        manifests_dir / f"nodeids-shard-{n}.txt" for n in range(1, splits + 1)
    ]
    expected_files.append(manifests_dir / "nodeids-invariants.txt")
    ids: set[str] = set()
    for path in expected_files:
        if not path.is_file():
            raise SystemExit(f"falta el manifiesto de nodeids: {path}")
        lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}
        if not lines:
            raise SystemExit(f"manifiesto vacio: {path}")
        overlap = ids & lines
        if overlap:
            raise SystemExit(f"nodeids duplicados entre manifiestos: {sorted(overlap)[:5]}")
        ids |= lines
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument(
        "--manifests-dir",
        type=Path,
        default=None,
        help="Directorio con nodeids-shard-N.txt y nodeids-invariants.txt (recomendado en CI).",
    )
    parser.add_argument("--splits", type=int, default=None)
    args = parser.parse_args()

    if args.manifests_dir is not None:
        if args.splits is None:
            raise SystemExit("--manifests-dir requiere --splits")
        collected = sorted(_manifest_nodeids(args.manifests_dir, args.splits))
    else:
        collected = _collected_nodeids()
    collected_set = set(collected)
    if len(collected) != len(collected_set):
        raise SystemExit("la coleccion de pytest contiene nodeids duplicados")

    root = ET.parse(args.junit).getroot()  # noqa: S314 - JUnit propio del CI
    junit_ids: set[str] = set()
    mapped_ids: set[str] = set()
    unmapped: list[str] = []
    duplicates: list[str] = []
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        cid = f"{classname}::{name}"
        if cid in junit_ids:
            duplicates.append(cid)
            continue
        junit_ids.add(cid)
        node = next((n for n in _candidates(classname, name) if n in collected_set), None)
        if node is None:
            unmapped.append(cid)
        else:
            mapped_ids.add(node)

    missing = sorted(collected_set - mapped_ids)
    extra = sorted(mapped_ids - collected_set)

    print(f"collected={len(collected_set)} junit={len(junit_ids)} mapped={len(mapped_ids)}")
    if duplicates:
        print(f"duplicados={len(duplicates)} (primeros 5: {duplicates[:5]})", file=sys.stderr)
    if unmapped:
        print(f"sin mapear={len(unmapped)} (primeros 5: {unmapped[:5]})", file=sys.stderr)
    if missing:
        print(f"faltan en JUnit={len(missing)} (primeros 5: {missing[:5]})", file=sys.stderr)
    if extra:
        print(f"sobran en JUnit={len(extra)} (primeros 5: {extra[:5]})", file=sys.stderr)

    return 0 if not (duplicates or unmapped or missing or extra) else 1


if __name__ == "__main__":
    raise SystemExit(main())
