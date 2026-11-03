# =============================================================================
# P20-11 — snapshot congelado del checkout manual.
# =============================================================================
from __future__ import annotations

import ast
import json
from pathlib import Path

from src.platform.commerce import checkout_manual
from src.platform.workflows.packages import validate_graph_from_dict

ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = (
    ROOT
    / "src"
    / "infrastructure"
    / "db_init"
    / "seeds"
    / "retail_checkout_manual.json"
)
MIGRATION = (
    ROOT
    / "src"
    / "infrastructure"
    / "db_init"
    / "versions"
    / "181_retail_checkout_manual.py"
)


def test_checkout_snapshot_matches_live_definition() -> None:
    frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert frozen == checkout_manual.snapshot_payload()


def test_checkout_graph_is_valid_and_uses_manual_payment() -> None:
    graph = checkout_manual.build_graph()
    validate_graph_from_dict(graph)
    types = {node["type"] for node in graph["nodes"]}
    assert "manual_payment_validation" in types
    assert "business_result" in types
    assert graph["metadata"]["temporary_manual_payment"] is True
    assert len(graph["nodes"]) >= 12


def test_checkout_migration_reads_snapshot_without_platform_import() -> None:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not [mod for mod in imported if mod.startswith("src.platform")]
    assert SNAPSHOT.exists()
