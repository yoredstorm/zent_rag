# =============================================================================
# P20-11 MVP - nodo temporal de validación manual de pago.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.platform.workflows.approvals import ApprovalInvalid, VerifiedApproval
from src.platform.workflows.manual_payment import (
    MANUAL_PAYMENT_CAPABILITY,
    execute_manual_payment_validation,
)
from src.platform.workflows.nodes import NodeContext, registry


def _rctx(*, simulate: bool = False, config: dict | None = None) -> NodeContext:
    execution = SimpleNamespace(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        run_id=uuid4(),
        workflow_id=uuid4(),
        actor_id=uuid4(),
        workflow_version=1,
        graph_hash="graph-hash",
    )
    node = SimpleNamespace(
        id="pago_manual",
        label="Validación manual",
        config={
            "order_id": "BOD-1001",
            "amount": "9.60",
            "currency": "PEN",
            "payment_reference": "SIM-001",
            **(config or {}),
        },
    )
    return NodeContext(
        execution=execution,
        node=node,
        node_type=registry.require("manual_payment_validation"),
        node_id="pago_manual",
        inputs={},
        trigger={},
        payload={},
        variables={},
        node_outputs={},
        idempotency_key="manual-payment:BOD-1001",
        simulate=simulate,
    )


def test_node_is_registered_as_temporary() -> None:
    node = registry.get("manual_payment_validation")
    assert node is not None
    assert "temporal" in node.label.lower()
    assert node.risk_level == "critical"
    assert node.business_name


@pytest.mark.asyncio
async def test_manual_payment_simulation_waits_for_approval() -> None:
    result = await execute_manual_payment_validation(_rctx(simulate=True))

    assert result.simulated is True
    assert result.control == "wait_approval"
    assert result.output["status"] == "pending"
    assert result.output["temporary"] is True
    assert result.output["mode"] == "manual_mvp"
    assert result.output["amount"] == "9.60"
    assert result.output["currency"] == "PEN"


@pytest.mark.asyncio
async def test_manual_payment_without_approval_creates_request(monkeypatch) -> None:
    async def _no_approval(*_args, **_kwargs):
        raise ApprovalInvalid("approval_required", "no hay aprobación")

    async def _create(*_args, **_kwargs):
        return uuid4()

    monkeypatch.setattr(
        "src.platform.workflows.approvals.resolve_verified_approval",
        _no_approval,
    )
    monkeypatch.setattr("src.platform.workflows.nodes._create_approval", _create)

    result = await execute_manual_payment_validation(_rctx())

    assert result.control == "wait_approval"
    assert result.output["status"] == "pending"
    assert result.output["approval_id"]
    assert result.output["order_id"] == "BOD-1001"


@pytest.mark.asyncio
async def test_manual_payment_with_verified_approval_marks_paid(monkeypatch) -> None:
    async def _approved(*_args, **_kwargs):
        return VerifiedApproval(
            approval_id=str(uuid4()),
            run_id=str(uuid4()),
            instance_id=str(uuid4()),
            workflow_id=str(uuid4()),
            node_id="pago_manual",
            capability_ref=MANUAL_PAYMENT_CAPABILITY,
            target_node_id="pago_manual",
            scope={"scope_type": "node"},
            decided_by=str(uuid4()),
            expires_at=None,
        )

    monkeypatch.setattr(
        "src.platform.workflows.approvals.resolve_verified_approval",
        _approved,
    )

    result = await execute_manual_payment_validation(_rctx())

    assert result.control is None
    assert result.output["status"] == "paid"
    assert result.output["provider"] == "manual_mvp"
    assert result.output["payment_reference"] == "SIM-001"
    assert result.output["verified_by"]
    assert result.output["temporary"] is True


@pytest.mark.asyncio
async def test_manual_payment_is_blocked_in_production(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.core.config.get_settings",
        lambda: SimpleNamespace(ENVIRONMENT="production"),
    )

    result = await execute_manual_payment_validation(_rctx(simulate=True))

    assert result.error is not None
    assert result.error.startswith("MANUAL_PAYMENT_DISABLED_IN_PRODUCTION")


@pytest.mark.asyncio
async def test_manual_payment_requires_order_id() -> None:
    result = await execute_manual_payment_validation(
        _rctx(simulate=True, config={"order_id": ""})
    )

    assert result.error is not None
    assert result.error.startswith("MANUAL_PAYMENT_ORDER_REQUIRED")
