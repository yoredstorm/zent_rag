# =============================================================================
# Migration and contract checks for the universal role/solution slice.
# =============================================================================
from __future__ import annotations

import importlib.util
from pathlib import Path

from src.platform.studio.contracts import RoleProfileV1, SolutionV1

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "src" / "infrastructure" / "db_init" / "versions"


def _load_migration(name: str):
    path = VERSIONS / name
    spec = importlib.util.spec_from_file_location(f"migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_163_is_aditive_and_chained() -> None:
    module = _load_migration("163_role_profiles_and_solutions.py")
    assert module.revision == "163"
    assert module.down_revision == "162"
    source = (VERSIONS / "163_role_profiles_and_solutions.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS role_profiles" in source
    assert "CREATE TABLE IF NOT EXISTS role_profile_versions" in source
    assert "CREATE TABLE IF NOT EXISTS studio_solutions" in source
    assert "CREATE TABLE IF NOT EXISTS studio_solution_versions" in source
    assert "ALTER TABLE agents ADD COLUMN IF NOT EXISTS role_profile_id UUID" in source
    assert "fk_agents_role_profile_id" in source
    assert "ON DELETE SET NULL" in source
    # No second agents/assistants registry.
    assert "CREATE TABLE IF NOT EXISTS agents" not in source
    assert "CREATE TABLE IF NOT EXISTS assistants" not in source


def test_latest_migration_is_169() -> None:
    numbers = sorted(
        int(path.stem.split("_", 1)[0])
        for path in VERSIONS.glob("*.py")
        if path.stem.split("_", 1)[0].isdigit()
    )
    assert numbers[-1] == 169


def test_migration_169_persists_test_reports_only() -> None:
    module = _load_migration("169_workflow_test_reports.py")
    assert module.revision == "169"
    assert module.down_revision == "168"
    source = (VERSIONS / "169_workflow_test_reports.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS workflow_test_reports" in source
    assert "graph_hash" in source
    assert "role_hash" in source
    assert "binding_hash" in source
    assert "CREATE TABLE IF NOT EXISTS workflow_certificates" not in source


def test_migration_168_adds_memory_scope_without_recreating_tables() -> None:
    module = _load_migration("168_memory_scope_consent.py")
    assert module.revision == "168"
    assert module.down_revision == "167"
    source = (VERSIONS / "168_memory_scope_consent.py").read_text()
    assert "ADD COLUMN IF NOT EXISTS workspace_id" in source
    assert "ADD COLUMN IF NOT EXISTS subject_id" in source
    assert "ADD COLUMN IF NOT EXISTS scope" in source
    assert "ADD COLUMN IF NOT EXISTS consent_at" in source
    assert "ADD COLUMN IF NOT EXISTS expires_at" in source
    assert "ADD COLUMN IF NOT EXISTS deleted_at" in source
    assert "CREATE TABLE IF NOT EXISTS memory_records" not in source


def test_role_contract_json_roundtrip_has_no_tenant_or_secret_fields() -> None:
    from src.platform.studio.templates import role_template

    role = role_template("mentor")
    assert role is not None
    dumped = role.model_dump(by_alias=True)
    assert dumped["schema"] == "zent.role/v1"
    assert "record_id" not in dumped
    assert "organization_id" not in dumped
    assert "workspace_id" not in dumped
    RoleProfileV1.model_validate(dumped)


def test_solution_contract_json_roundtrip_has_logical_refs_only() -> None:
    import json

    example = (
        ROOT
        / "docs"
        / "architecture"
        / "universal-roles"
        / "examples"
        / "audit-solution.json"
    )
    solution = SolutionV1.model_validate(json.loads(example.read_text(encoding="utf-8")))
    dumped = solution.model_dump(by_alias=True)
    assert dumped["schema"] == "zent.solution/v1"
    assert "record_id" not in dumped
    assert all("organization_id" not in ref for ref in dumped["roles"])
    assert dumped["workflows"][1]["agent_refs"] == ["mentor_agent", "auditor_agent"]
