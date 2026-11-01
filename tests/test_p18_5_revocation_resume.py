# =============================================================================
# P18.5-04 — Revocaciones vigentes sobre el snapshot, fail-closed en outage.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.effective_policy import (
    EffectiveExecutionPolicy,
    overlay_restrictive_policy,
    resolve_effective_policy,
)
from src.platform.workflows.policy_enforcement import authorize_node
from src.platform.workflows.runtime import ExecutionContext
from tests.test_workflows import _create_org, _headers, _owner_session


def _pinned(org: UUID, workflow_id: UUID, workspace_id: UUID | None = None):
    return EffectiveExecutionPolicy(
        organization_id=str(org),
        workspace_id=str(workspace_id) if workspace_id else None,
        workflow_id=str(workflow_id),
        rbac_scopes=frozenset({"workflows:run", "external_actions:execute"}),
        capability_scope=frozenset({"orders.create"}),
        definition_source="instance",
    ).with_hash()


async def _workflow(client: AsyncClient, name: str) -> tuple[UUID, UUID | None, dict]:
    from tests.test_workflow_published_snapshot import _marker_graph

    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    created = await client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={
            "name": name,
            "trigger_type": "webhook",
            "graph": _marker_graph("A"),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    detail = await client.get(
        f"/api/v1/workflows/{body['workflow_id']}", headers=_headers(org)
    )
    workspace = detail.json().get("workspace_id")
    return (
        UUID(org["organization_id"]),
        UUID(workspace) if workspace else None,
        {"workflow_id": UUID(body["workflow_id"]), "org": org},
    )


@pytest.mark.asyncio
async def test_revocation_created_while_waiting_applies_on_overlay(
    async_client: AsyncClient,
) -> None:
    org, workspace_id, info = await _workflow(async_client, "P18.5 revoke wait")
    workflow_id = info["workflow_id"]
    pinned = _pinned(org, workflow_id, workspace_id)

    # Instancia ya iniciada: su snapshot no contiene la revocación.
    assert "orders.create" not in pinned.revoked_capabilities
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_policy_revocations "
                "(organization_id, workspace_id, scope_type, scope_id, capability_ref, "
                " reason, active) "
                "VALUES (:oid, :ws, 'workflow', :wid, 'orders.create', "
                " 'revocada durante WAIT', true)"
            ),
            {
                "oid": str(org),
                "ws": str(workspace_id) if workspace_id else None,
                "wid": str(workflow_id),
            },
        )
        await session.commit()
    finally:
        await session.close()

    resolved = await resolve_effective_policy(
        organization_id=org,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        instance_policy=pinned.to_dict(),
    )
    assert "orders.create" in resolved.revoked_capabilities
    assert resolved.policy_store_error is False
    # El hash cambió: el snapshot original no autoriza el efecto.
    assert resolved.policy_hash != pinned.policy_hash

    execution = ExecutionContext(
        organization_id=org,
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        run_id=uuid4(),
        actor_type="signal",
        trigger_type="signal",
        permissions=frozenset({"workflows:run", "external_actions:execute"}),
        definition_source="instance",
    )
    verdict = await authorize_node(
        SimpleNamespace(
            execution=execution,
            organization_id=org,
            permissions=execution.permissions,
        ),
        SimpleNamespace(
            id="pay",
            type="api_call",
            config={"capability": "orders.create", "method": "POST"},
        ),
        SimpleNamespace(capabilities=frozenset({"external_actions:execute"})),
        policy=resolved,
    )
    assert verdict.allowed is False
    assert verdict.code == "policy.revoked"

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM workflow_policy_revocations WHERE organization_id = :oid"),
            {"oid": str(org)},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_revocation_store_outage_fails_closed_for_writes(monkeypatch) -> None:
    org, workflow_id = uuid4(), uuid4()
    pinned = _pinned(org, workflow_id)

    def _broken_session():
        raise RuntimeError("postgres down")

    monkeypatch.setattr(
        "src.platform.workflows.effective_policy.get_async_session", _broken_session
    )
    overlaid = await overlay_restrictive_policy(
        pinned, organization_id=org, workspace_id=None, workflow_id=workflow_id
    )
    assert overlaid.policy_store_error is True
    assert "*" in overlaid.revoked_capabilities

    execution = ExecutionContext(
        organization_id=org,
        workflow_id=workflow_id,
        run_id=uuid4(),
        actor_type="signal",
        trigger_type="signal",
        permissions=frozenset({"external_actions:execute"}),
    )
    verdict = await authorize_node(
        SimpleNamespace(
            execution=execution, organization_id=org, permissions=execution.permissions
        ),
        SimpleNamespace(
            id="pay", type="api_call", config={"capability": "orders.create", "method": "POST"}
        ),
        SimpleNamespace(capabilities=frozenset({"external_actions:execute"})),
        policy=overlaid,
    )
    assert verdict.allowed is False
    assert verdict.code in ("policy.revocation_unavailable", "policy.revoked")


@pytest.mark.asyncio
async def test_corrupt_instance_policy_denies_instead_of_rebuilding_live() -> None:
    org, workflow_id = uuid4(), uuid4()
    resolved = await resolve_effective_policy(
        organization_id=org,
        workspace_id=None,
        workflow_id=workflow_id,
        instance_policy={"organization_id": str(org), "workflow_id": "otro", "sorpresa": 1},
    )
    assert resolved.policy_store_error is True
    assert resolved.revoked_capabilities == frozenset({"*"})
    assert resolved.capability_scope == frozenset()
