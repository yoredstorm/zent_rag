#!/usr/bin/env python
"""Fusiona los JUnit de los shards de CI en un solo `junit-tests.xml`.

Los N jobs `test (i/N)` suben `junit-tests-shard-i.xml`; el shard 1 agrega
`junit-invariants.xml`. El artifact historico `junit-ci` (consumido por
`scripts/cert/fetch_ci_evidence.py`) espera un unico `junit-tests.xml` con la
suite completa, asi que este script reconstruye el root `<testsuites>`, suma
los contadores e incluye los invariantes una sola vez.

La fusion es estricta a proposito: si falta un shard, un XML es invalido, un
shard no tiene tests o un test aparece dos veces, el job falla. Un artifact
incompleto nunca debe parecer evidencia valida.

Uso:
    python scripts/cert/merge_junit_shards.py \
        --input-dir artifacts/shards --splits 6 \
        --invariants artifacts/shards/junit-invariants.xml \
        --out artifacts/junit-tests.xml
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

_COUNTERS = ("tests", "failures", "errors", "skipped")


def _load_xml(path: Path) -> ET.Element:
    try:
        return ET.parse(path).getroot()  # noqa: S314 - JUnit propio del CI
    except (ET.ParseError, OSError) as exc:
        raise SystemExit(f"JUnit invalido o ilegible: {path}: {exc}") from exc


def _test_ids(root: ET.Element) -> set[str]:
    ids: set[str] = set()
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        if not name:
            raise SystemExit("testcase sin atributo name en el JUnit")
        ids.add(f"{classname}::{name}")
    return ids


def _suites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuite":
        return [root]
    if root.tag != "testsuites":
        raise SystemExit(f"root JUnit inesperado: <{root.tag}>")
    return list(root.iter("testsuite"))


def _append_suites(
    merged: ET.Element,
    suites: list[ET.Element],
    totals: dict[str, int],
    seen: dict[str, str],
    origin: str,
) -> tuple[int, float]:
    merged_suites = 0
    total_time = 0.0
    for suite in suites:
        cases = list(suite.iter("testcase"))
        if not cases:
            raise SystemExit(f"suite vacia en {origin}: <{suite.get('name')}>")
        for case in cases:
            cid = f"{case.get('classname') or ''}::{case.get('name') or ''}"
            if cid in seen:
                raise SystemExit(f"test duplicado entre {seen[cid]} y {origin}: {cid}")
            seen[cid] = origin
        merged.append(suite)
        merged_suites += 1
        for counter in _COUNTERS:
            totals[counter] += int(float(suite.get(counter) or 0))
        total_time += float(suite.get("time") or 0.0)
    return merged_suites, total_time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--splits", required=True, type=int)
    parser.add_argument(
        "--invariants",
        type=Path,
        default=None,
        help="JUnit de invariantes que se incluye en junit-tests.xml (se ejecuta una sola vez).",
    )
    args = parser.parse_args()
    if args.splits < 1:
        raise SystemExit("--splits debe ser >= 1")

    expected = [args.input_dir / f"junit-tests-shard-{n}.xml" for n in range(1, args.splits + 1)]
    missing = [path.name for path in expected if not path.is_file()]
    if missing:
        raise SystemExit(f"faltan shards esperados en {args.input_dir}: {', '.join(missing)}")

    unexpected = sorted(
        path.name
        for path in args.input_dir.glob("junit-tests-shard-*.xml")
        if path not in expected
    )
    if unexpected:
        raise SystemExit(
            f"hay shards no esperados para --splits {args.splits}: {', '.join(unexpected)}"
        )

    merged = ET.Element("testsuites", name="pytest-shards")
    totals = dict.fromkeys(_COUNTERS, 0)
    total_time = 0.0
    merged_suites = 0
    seen: dict[str, str] = {}

    for path in expected:
        root = _load_xml(path)
        ids = _test_ids(root)
        if not ids:
            raise SystemExit(f"shard sin testcases: {path.name}")
        suites, seconds = _append_suites(
            merged, _suites(root), totals, seen, path.name
        )
        merged_suites += suites
        total_time += seconds
        print(f"{path.name}: tests={len(ids)} suites={suites} time={seconds:.1f}s")

    if args.invariants is not None:
        if not args.invariants.is_file():
            raise SystemExit(f"falta el JUnit de invariantes: {args.invariants}")
        root = _load_xml(args.invariants)
        ids = _test_ids(root)
        if not ids:
            raise SystemExit("junit-invariants.xml no contiene testcases")
        suites, seconds = _append_suites(
            merged, _suites(root), totals, seen, args.invariants.name
        )
        merged_suites += suites
        total_time += seconds
        print(f"{args.invariants.name}: tests={len(ids)} suites={suites} time={seconds:.1f}s")

    if merged_suites == 0:
        raise SystemExit("ningun JUnit se pudo fusionar")

    counted = sum(1 for _ in merged.iter("testcase"))
    if counted != totals["tests"]:
        raise SystemExit(
            f"contador inconsistente: testcases={counted} tests={totals['tests']}"
        )
    if len(seen) != counted:
        raise SystemExit(f"ids unicos={len(seen)} testcases={counted}")

    for counter, value in totals.items():
        merged.set(counter, str(value))
    merged.set("time", f"{total_time:.3f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged)
    ET.ElementTree(merged).write(args.out, encoding="utf-8", xml_declaration=True)

    print(
        f"merged={args.splits} suites={merged_suites} tests={totals['tests']} "
        f"failures={totals['failures']} errors={totals['errors']} "
        f"skipped={totals['skipped']} time={total_time:.1f}s out={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
