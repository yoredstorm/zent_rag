#!/usr/bin/env python
"""Fusiona los JUnit de los shards de CI en un solo `junit-tests.xml`.

Los 4 jobs `test (N/4)` suben `junit-tests-shard-N.xml`. El artifact historico
`junit-ci` (consumido por `scripts/cert/fetch_ci_evidence.py`) espera un unico
`junit-tests.xml`, asi que este script reconstruye el root `<testsuites>` y
suma los contadores.

Uso:
    python scripts/cert/merge_junit_shards.py \
        --input-dir artifacts/shards --out artifacts/junit-tests.xml
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_COUNTERS = ("tests", "failures", "errors", "skipped")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    inputs = sorted(args.input_dir.glob("junit-tests-shard-*.xml"))
    if not inputs:
        raise SystemExit(f"sin JUnit de shards en {args.input_dir}")

    merged = ET.Element("testsuites", name="pytest-shards")
    totals = dict.fromkeys(_COUNTERS, 0)
    total_time = 0.0
    merged_suites = 0

    for path in inputs:
        try:
            root = ET.parse(path).getroot()  # noqa: S314 - JUnit propio del CI
        except ET.ParseError as exc:
            print(f"WARN: JUnit invalido, se omite {path.name}: {exc}", file=sys.stderr)
            continue
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for suite in suites:
            merged.append(suite)
            merged_suites += 1
            for counter in _COUNTERS:
                totals[counter] += int(float(suite.get(counter) or 0))
            total_time += float(suite.get("time") or 0.0)

    if not merged_suites:
        raise SystemExit("ningun JUnit de shard se pudo parsear")

    for counter, value in totals.items():
        merged.set(counter, str(value))
    merged.set("time", f"{total_time:.3f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(merged)
    ET.ElementTree(merged).write(args.out, encoding="utf-8", xml_declaration=True)

    print(
        f"merged={len(inputs)} suites={merged_suites} tests={totals['tests']} "
        f"failures={totals['failures']} errors={totals['errors']} "
        f"skipped={totals['skipped']} time={total_time:.1f}s out={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
