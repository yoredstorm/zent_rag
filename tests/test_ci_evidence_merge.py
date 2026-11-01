"""Contratos de integridad del artifact JUnit fusionado de CI.

La fusion debe fallar si falta un shard, si un XML es invalido, si un shard
esta vacio o si un test aparece dos veces. Un artifact incompleto no puede
parecer evidencia valida para `scripts/cert/fetch_ci_evidence.py`.
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MERGE = ROOT / "scripts" / "cert" / "merge_junit_shards.py"
VERIFY = ROOT / "scripts" / "cert" / "verify_junit_coverage.py"


def _write_shard(path: Path, cases: list[tuple[str, str, float]]) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(
        root,
        "testsuite",
        name="pytest",
        tests=str(len(cases)),
        failures="0",
        errors="0",
        skipped="0",
        time=f"{sum(case[2] for case in cases):.3f}",
    )
    for classname, name, seconds in cases:
        ET.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=name,
            time=f"{seconds:.3f}",
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _run(input_dir: Path, splits: int, invariants: Path | None = None, out: Path | None = None):
    command = [
        sys.executable,
        str(MERGE),
        "--input-dir",
        str(input_dir),
        "--splits",
        str(splits),
        "--out",
        str(out or input_dir / "junit-tests.xml"),
    ]
    if invariants is not None:
        command.extend(["--invariants", str(invariants)])
    return subprocess.run(  # noqa: S603 - script propio, argumentos fijos del test
        command, capture_output=True, text=True, encoding="utf-8"
    )


def _write_junit_from_nodeids(path: Path, nodeids: list[str]) -> None:
    cases = []
    for nodeid in nodeids:
        parts = nodeid.split("::")
        module = parts[0].removesuffix(".py").replace("/", ".")
        cases.append((".".join([module, *parts[1:-1]]), parts[-1], 0.1))
    _write_shard(path, cases)


def _run_verify(tmp_path: Path, junit: Path, manifests: Path, splits: int):
    return subprocess.run(  # noqa: S603 - script propio, argumentos fijos del test
        [
            sys.executable,
            str(VERIFY),
            "--junit",
            str(junit),
            "--manifests-dir",
            str(manifests),
            "--splits",
            str(splits),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_verify_coverage_accepts_complete_manifests(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "nodeids-shard-1.txt").write_text(
        "tests/test_api.py::test_one\ntests/test_api.py::TestX::test_two\n", encoding="utf-8"
    )
    (manifests / "nodeids-shard-2.txt").write_text("tests/test_db.py::test_three\n", encoding="utf-8")
    (manifests / "nodeids-invariants.txt").write_text(
        "tests/test_architecture.py::test_core\n", encoding="utf-8"
    )
    junit = tmp_path / "junit-tests.xml"
    _write_junit_from_nodeids(
        junit,
        [
            "tests/test_api.py::test_one",
            "tests/test_api.py::TestX::test_two",
            "tests/test_db.py::test_three",
            "tests/test_architecture.py::test_core",
        ],
    )
    result = _run_verify(tmp_path, junit, manifests, 2)
    assert result.returncode == 0, result.stderr
    assert "collected=4 junit=4 mapped=4" in result.stdout


def test_verify_coverage_fails_when_manifest_missing(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "nodeids-shard-1.txt").write_text("tests/test_api.py::test_one\n", encoding="utf-8")
    (manifests / "nodeids-shard-2.txt").write_text("tests/test_db.py::test_three\n", encoding="utf-8")
    junit = tmp_path / "junit-tests.xml"
    _write_junit_from_nodeids(junit, ["tests/test_api.py::test_one", "tests/test_db.py::test_three"])
    result = _run_verify(tmp_path, junit, manifests, 2)
    assert result.returncode != 0
    assert "falta el manifiesto" in result.stderr


def test_verify_coverage_fails_when_test_missing(tmp_path: Path) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "nodeids-shard-1.txt").write_text("tests/test_api.py::test_one\n", encoding="utf-8")
    (manifests / "nodeids-shard-2.txt").write_text("tests/test_db.py::test_three\n", encoding="utf-8")
    (manifests / "nodeids-invariants.txt").write_text(
        "tests/test_architecture.py::test_core\n", encoding="utf-8"
    )
    junit = tmp_path / "junit-tests.xml"
    _write_junit_from_nodeids(
        junit,
        ["tests/test_api.py::test_one", "tests/test_db.py::test_three"],
    )
    result = _run_verify(tmp_path, junit, manifests, 2)
    assert result.returncode != 0
    assert "faltan en JUnit=1" in result.stderr


def _planner_files(group: int, splits: int, exclude_file: Path) -> list[str]:
    result = subprocess.run(  # noqa: S603 - script propio, argumentos fijos del test
        [
            sys.executable,
            str(ROOT / "scripts" / "ci" / "shard_plan.py"),
            "--splits",
            str(splits),
            "--group",
            str(group),
            "--durations-path",
            str(ROOT / ".test_durations"),
            "--exclude-file",
            str(exclude_file),
            "--exclude-dir",
            "tests/certification/workflows",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_shard_plan_partitions_every_test_file_exactly_once(tmp_path: Path) -> None:
    excludes = subprocess.run(  # noqa: S603 - script propio, argumentos fijos del test
        [sys.executable, str(ROOT / "scripts" / "cert" / "run_invariants.py"), "--list-ignores"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    excluded = {line.removeprefix("--ignore=") for line in excludes.splitlines() if line}
    exclude_file = tmp_path / "invariants.txt"
    exclude_file.write_text("\n".join(sorted(excluded)), encoding="utf-8")

    expected = {
        line
        for line in subprocess.run(
            ["git", "ls-files", "tests"],  # noqa: S603,S607 - git del repo, sin shell
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.splitlines()
        if line.endswith(".py")
        and (Path(line).name.startswith("test_") or Path(line).name.endswith("_test.py"))
        and line not in excluded
        and not line.startswith("tests/certification/workflows/")
    }

    assigned: list[str] = []
    for group in range(1, 7):
        assigned.extend(_planner_files(group, 6, exclude_file))

    assert len(assigned) == len(set(assigned)), "un archivo quedo en mas de un shard"
    assert set(assigned) == expected, "el plan de shards no cubre todos los archivos"


def test_merge_includes_shards_and_invariants_once(tmp_path: Path) -> None:
    inv = tmp_path / "junit-invariants.xml"
    _write_shard(inv, [("tests.test_architecture", "test_core", 0.5)])
    _write_shard(
        tmp_path / "junit-tests-shard-1.xml",
        [("tests.test_api", "test_one", 1.5), ("tests.test_api", "test_two", 2.5)],
    )
    _write_shard(
        tmp_path / "junit-tests-shard-2.xml",
        [("tests.test_db", "test_three", 3.5)],
    )
    out = tmp_path / "junit-tests.xml"
    result = _run(tmp_path, 2, inv, out)
    assert result.returncode == 0, result.stderr
    root = ET.parse(out).getroot()  # noqa: S314 - XML generado por este test
    assert root.get("tests") == "4"
    assert root.get("failures") == "0"
    assert len(list(root.iter("testcase"))) == 4
    ids = [(case.get("classname"), case.get("name")) for case in root.iter("testcase")]
    assert len(ids) == len(set(ids))


def test_merge_fails_when_expected_shard_missing(tmp_path: Path) -> None:
    _write_shard(tmp_path / "junit-tests-shard-1.xml", [("tests.test_api", "test_one", 1.0)])
    result = _run(tmp_path, 2)
    assert result.returncode != 0
    assert "faltan shards esperados" in result.stderr


def test_merge_fails_on_invalid_xml(tmp_path: Path) -> None:
    (tmp_path / "junit-tests-shard-1.xml").write_text("<testsuites><testsuite", encoding="utf-8")
    _write_shard(tmp_path / "junit-tests-shard-2.xml", [("tests.test_api", "test_one", 1.0)])
    result = _run(tmp_path, 2)
    assert result.returncode != 0
    assert "JUnit invalido" in result.stderr


def test_merge_fails_on_duplicate_test(tmp_path: Path) -> None:
    _write_shard(tmp_path / "junit-tests-shard-1.xml", [("tests.test_api", "test_one", 1.0)])
    _write_shard(tmp_path / "junit-tests-shard-2.xml", [("tests.test_api", "test_one", 1.0)])
    result = _run(tmp_path, 2)
    assert result.returncode != 0
    assert "duplicado" in result.stderr


def test_merge_fails_on_empty_shard(tmp_path: Path) -> None:
    _write_shard(tmp_path / "junit-tests-shard-1.xml", [])
    _write_shard(tmp_path / "junit-tests-shard-2.xml", [("tests.test_api", "test_one", 1.0)])
    result = _run(tmp_path, 2)
    assert result.returncode != 0
    assert "sin testcases" in result.stderr


def test_merge_fails_on_unexpected_shard(tmp_path: Path) -> None:
    _write_shard(tmp_path / "junit-tests-shard-1.xml", [("tests.test_api", "test_one", 1.0)])
    _write_shard(tmp_path / "junit-tests-shard-2.xml", [("tests.test_api", "test_two", 1.0)])
    result = _run(tmp_path, 1)
    assert result.returncode != 0
    assert "no esperados" in result.stderr
