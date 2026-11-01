# =============================================================================
# P18.5-03 — approval_ref no es autoridad; la aprobación se resuelve en DB.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.approvals import ApprovalInvalid, resolve_verified_approval
from src.platform.workflows.effective_policy import EffectiveExecutionPolicy
from src.platform.workflows.policy_enforcement import authorize_node
from src.platform.workflows.runtime import ExecutionContext
from tests.test_workflows import _create_org, _headers, _owner_session


def _policy(org: UUID, workflow_id: UUID) -> EffectiveExecutionPolicy:
    return EffectiveExecutionPolicy(
        organization_id=str(org),
        workflow_id=str(workflow_id),
        rbac_scopes=frozenset({"external_actions:execute"}),
        capability_scope=frozenset({"orders.create"}),
        approval_required=True,
        definition_source="instance",
    ).with_hash()


def _execution(org: UUID, workflow_id: UUID, run_id: UUID) -> ExecutionContext:
    return ExecutionContext(
        organization_id=org,
        workflow_id=workflow_id,
        run_id=run_id,
        actor_type="user",
        actor_id=uuid4(),
        trigger_type="manual",
        permissions=frozenset({"external_actions:execute"}),
        workspace_id=None,
        definition_source="instance",
    )


def _node(config: dict) -> SimpleNamespace:
    return SimpleNamespace(id="pay-1", type="api_call", config=config)


def _node_def() -> SimpleNamespace:
    return SimpleNamespace(capabilities=frozenset({"external_actions:execute"}))


async def _run_context(client: AsyncClient, name: str) -> tuple[UUID, UUID, UUID]:
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
    workflow_id = UUID(created.json()["workflow_id"])
    run = await client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers={**_headers(org), "Idempotency-Key": f"p185-{uuid4().hex}"},
        json={"payload": {"message": "hola"}, "simulate": False},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    run_id = UUID(str(body.get("run_id") or (body.get("run") or {}).get("run_id")))
    return UUID(org["organization_id"]), workflow_id, run_id


async def _insert_approval(
    *,
    org: UUID,
    workflow_id: UUID,
    run_id: UUID,
    expires: datetime,
    capability_ref: str | None = None,
    approval_scope: str = '{"scope_type":"run"}',
) -> UUID:
    from src.platform.workflows.context_store import ensure_context_tables

    await ensure_context_tables()
    approval_id = uuid4()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO workflow_approvals "
                "(id, run_id, workflow_id, organization_id, node_id, action, summary, "
                " status, requested_by, decided_by, expires_at, capability_ref, "
                " approval_scope) "
                "VALUES (:id, :rid, :wid, :oid, 'approval-1', 'cobrar', 'cobro', "
                "'approved', :by, :by, :exp, :cap, CAST(:scope AS jsonb))"
            ),
            {
                "id": str(approval_id),
                "rid": str(run_id),
                "wid": str(workflow_id),
                "oid": str(org),
                "by": str(uuid4()),
                "exp": expires,
                "cap": capability_ref,
                "scope": approval_scope,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return approval_id


@pytest.mark.asyncio
async def test_fake_approval_ref_is_denied_before_effect() -> None:
    org, workflow_id, run_id = uuid4(), uuid4(), uuid4()
    rctx = SimpleNamespace(
        execution=_execution(org, workflow_id, run_id),
        simulate=False,
        organization_id=org,
        permissions=frozenset({"external_actions:execute"}),
    )
    verdict = await authorize_node(
        rctx,
        _node(
            {
                "capability": "orders.create",
                "method": "POST",
                "approval_ref": "approved",  # string arbitrario
            }
        ),
        _node_def(),
        policy=_policy(org, workflow_id),
    )
    assert verdict.allowed is False
    assert verdict.code == "policy.approval_invalid"
    assert verdict.approval_required is True
    assert "aprobación" in " ".join(verdict.reasons)


@pytest.mark.asyncio
async def test_verified_approval_is_consumed_at_most_once(
    async_client: AsyncClient,
) -> None:
    org, workflow_id, run_id = await _run_context(async_client, "P18.5 approval once")
    approval_id = await _insert_approval(
        org=org,
        workflow_id=workflow_id,
        run_id=run_id,
        expires=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    execution = _execution(org, workflow_id, run_id)
    rctx = SimpleNamespace(
        execution=execution,
        simulate=False,
        idempotency_key=f"{run_id}:pay-1:1",
    )
    approval = await resolve_verified_approval(
        rctx, _node({"capability": "orders.create"}), capability_ref="orders.create"
    )
    assert approval.approval_id == str(approval_id)
    with pytest.raises(ApprovalInvalid) as exc:
        await resolve_verified_approval(
            rctx,
            _node({"capability": "orders.create"}),
            capability_ref="orders.create",
        )
    assert exc.value.code == "approval_already_consumed"

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM workflow_approval_consumptions WHERE approval_id = :aid"),
            {"aid": str(approval_id)},
        )
        await session.execute(
            text("DELETE FROM workflow_approvals WHERE id = :aid"),
            {"aid": str(approval_id)},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_expired_and_cross_workflow_approvals_are_denied(
    async_client: AsyncClient,
) -> None:
    org, workflow_id, run_id = await _run_context(async_client, "P18.5 approval expire")
    _, other_workflow_id, _ = await _run_context(async_client, "P18.5 approval other")
    expired_id = await _insert_approval(
        org=org,
        workflow_id=workflow_id,
        run_id=run_id,
        expires=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    foreign_id = await _insert_approval(
        org=org,
        workflow_id=other_workflow_id,
        run_id=run_id,
        expires=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    execution = _execution(org, workflow_id, run_id)
    rctx = SimpleNamespace(execution=execution, simulate=False)
    with pytest.raises(ApprovalInvalid) as expired:
        await resolve_verified_approval(
            rctx,
            _node({"capability": "orders.create", "approval_ref": str(expired_id)}),
            capability_ref="orders.create",
        )
    assert expired.value.code == "approval_expired"

    with pytest.raises(ApprovalInvalid) as foreign:
        await resolve_verified_approval(
            SimpleNamespace(execution=execution, simulate=False),
            _node({"capability": "orders.create", "approval_ref": str(foreign_id)}),
            capability_ref="orders.create",
        )
    assert foreign.value.code == "approval_scope_mismatch"

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM workflow_approvals WHERE organization_id = :oid"),
            {"oid": str(org)},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_approval_for_other_capability_does_not_authorize(
    async_client: AsyncClient,
) -> None:
    org, workflow_id, run_id = await _run_context(async_client, "P18.5 approval scope")
    approval_id = await _insert_approval(
        org=org,
        workflow_id=workflow_id,
        run_id=run_id,
        expires=datetime.now(timezone.utc) + timedelta(minutes=10),
        capability_ref="notify.send",
        approval_scope='{"scope_type":"capability"}',
    )
    rctx = SimpleNamespace(
        execution=_execution(org, workflow_id, run_id), simulate=False
    )
    with pytest.raises(ApprovalInvalid) as exc:
        await resolve_verified_approval(
            rctx,
            _node(
                {
                    "capability": "orders.create",
                    "approval_ref": str(approval_id),
                }
            ),
            capability_ref="orders.create",
        )
    assert exc.value.code == "approval_scope_mismatch"

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM workflow_approvals WHERE id = :aid"),
            {"aid": str(approval_id)},
        )
        await session.commit()
    finally:
        await session.close()
