# =============================================================================
# P19.1-03 - Pin de binding: hash/version antes de consultar, sin TOCTOU.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import (
    PostgresOrganizationRepository,
    PostgresWorkspaceRepository,
)
from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.bindings import (
    BindingError,
    binding_plan_hash,
    execute_binding,
    upsert_binding,
)


def _plan(table: str) -> dict:
    return {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "resource": {"schema": "public", "name": table, "kind": "table"},
        "operation": "get_one",
        "projection": ["sku", "price"],
        "allowed_columns": ["sku", "price"],
        "parameters": [
            {"name": "sku", "field": "sku", "operator": "eq", "type": "string", "required": True}
        ],
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
    }


async def _org_workspace(label: str):
    org = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"{label} {uuid4().hex[:6]}"
    )
    workspace = await PostgresWorkspaceRepository().create_workspace(org.id, "Default", "default")
    return org, workspace


@pytest.mark.asyncio
async def test_binding_drift_is_denied_before_any_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, workspace = await _org_workspace("P19.1 Drift")
    capability = f"p19.drift.{uuid4().hex[:8]}"
    first = await upsert_binding(
        org.id,
        capability,
        "managed_db",
        config=_plan("product_prices"),
        workspace_id=workspace.id,
    )
    first_hash = binding_plan_hash(first)
    assert first["plan_version"] == 1

    called = {"count": 0}

    async def _must_not_query(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("no debe ejecutar SQL con plan stale")

    monkeypatch.setattr(
        "src.platform.workflows.bindings._execute_managed_select", _must_not_query
    )

    updated = await upsert_binding(
        org.id,
        capability,
        "managed_db",
        config=_plan("loyalty_balances"),
        workspace_id=workspace.id,
    )
    assert updated["id"] == first["id"]
    assert updated["plan_version"] == 2
    assert binding_plan_hash(updated) != first_hash

    with pytest.raises(BindingError) as exc:
        await execute_binding(
            org.id,
            capability,
            {"params": {"sku": "ARR-001"}},
            workspace_id=workspace.id,
            binding_ref=UUID(first["id"]),
            expected_binding_hash=first_hash,
        )
    assert exc.value.code == "PLAN_STALE"
    assert called["count"] == 0

    session = await get_async_session()
    try:
        versions = (
            await session.execute(
                text(
                    "SELECT plan_version FROM workflow_capability_binding_revisions "
                    "WHERE binding_id = :bid ORDER BY plan_version"
                ),
                {"bid": first["id"]},
            )
        ).scalars().all()
    finally:
        await session.close()
    assert versions == [1, 2]


@pytest.mark.asyncio
async def test_matching_pin_executes_the_same_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org, workspace = await _org_workspace("P19.1 Pin")
    capability = f"p19.pin.{uuid4().hex[:8]}"
    binding = await upsert_binding(
        org.id,
        capability,
        "managed_db",
        config=_plan("product_prices"),
        workspace_id=workspace.id,
    )
    seen: list[str] = []

    async def _fake_select(organization_id, binding_row, payload, **kwargs):
        seen.append(str(binding_row["id"]))
        return {"status": "FOUND", "found": True, "record": {"sku": "ARR-001"}}

    monkeypatch.setattr(
        "src.platform.workflows.bindings._execute_managed_select", _fake_select
    )
    result = await execute_binding(
        org.id,
        capability,
        {"params": {"sku": "ARR-001"}},
        workspace_id=workspace.id,
        binding_ref=UUID(binding["id"]),
        expected_binding_hash=binding_plan_hash(binding),
    )
    assert result["output"]["status"] == "FOUND"
    assert seen == [binding["id"]]
