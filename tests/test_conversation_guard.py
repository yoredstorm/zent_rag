# =============================================================================
# Conversation guard — durable counter, cooldown and tenant isolation.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.workflows.conversation_guard import (
    check_guard,
    ensure_conversation_guard_table,
    record_failure,
    record_success,
    scope_digest,
)
from src.platform.workflows.nodes import _exec_conversation_guard


@pytest.mark.asyncio
async def test_guard_warns_blocks_cools_down_and_resets() -> None:
    await ensure_conversation_guard_table()
    org = uuid4()
    key = scope_digest("participant", f"test-{uuid4().hex}")
    first = await record_failure(
        org, scope_type="participant", scope_key=key, max_failures=5, warning_at=3
    )
    assert first["failures"] == 1 and first["blocked"] is False
    await record_failure(org, scope_type="participant", scope_key=key)
    third = await record_failure(
        org, scope_type="participant", scope_key=key, max_failures=5, warning_at=3
    )
    assert third["failures"] == 3
    assert third["warning"] is True
    await record_failure(org, scope_type="participant", scope_key=key)
    fifth = await record_failure(
        org,
        scope_type="participant",
        scope_key=key,
        max_failures=5,
        warning_at=3,
        cooldown_minutes=20,
    )
    assert fifth["failures"] == 5
    assert fifth["blocked"] is True
    assert fifth["cooldown_until"]

    blocked = await check_guard(
        org, scope_type="participant", scope_key=key, max_failures=5, warning_at=3
    )
    assert blocked["blocked"] is True
    assert blocked["allowed"] is False

    # Un éxito limpia contador y cooldown.
    reset = await record_success(org, scope_type="participant", scope_key=key)
    assert reset["failures"] == 0
    allowed = await check_guard(
        org, scope_type="participant", scope_key=key, max_failures=5, warning_at=3
    )
    assert allowed["allowed"] is True

    # Simula el fin del cooldown y verifica que el guard no deja residuos.
    await record_failure(org, scope_type="participant", scope_key=key)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE workflow_conversation_guards SET failures = 5, "
                "cooldown_until = NOW() - INTERVAL '1 minute' "
                "WHERE organization_id = :oid AND scope_key = :key"
            ),
            {"oid": org, "key": key},
        )
        await session.commit()
    finally:
        await session.close()
    after = await check_guard(
        org, scope_type="participant", scope_key=key, max_failures=5, warning_at=3
    )
    assert after["allowed"] is True
    assert after["failures"] == 0


@pytest.mark.asyncio
async def test_guard_is_tenant_scoped() -> None:
    await ensure_conversation_guard_table()
    key = scope_digest("participant", f"same-{uuid4().hex}")
    org_a, org_b = uuid4(), uuid4()
    await record_failure(org_a, scope_type="participant", scope_key=key, max_failures=5)
    await record_failure(org_a, scope_type="participant", scope_key=key, max_failures=5)
    check_b = await check_guard(
        org_b, scope_type="participant", scope_key=key, max_failures=5
    )
    assert check_b["allowed"] is True
    assert check_b["failures"] == 0


@pytest.mark.asyncio
async def test_guard_simulation_does_not_write_and_counts_locally() -> None:
    execution = SimpleNamespace(simulation_state={}, instance_id=None, run_id=uuid4())
    rctx = SimpleNamespace(
        node=SimpleNamespace(
            config={"mode": "failure", "max_failures": 5, "warning_at": 3},
            label="Guardia",
        ),
        trigger={"message": "mensaje sin intención", "participant_id": "demo"},
        variables={},
        execution=execution,
        organization_id=uuid4(),
        workspace_id=None,
        simulate=True,
        node_id="guard",
        node_labels={},
        node_types={},
    )
    for _ in range(3):
        outcome = await _exec_conversation_guard(rctx)
    assert outcome.output["warning"] is True
    assert outcome.output["simulated"] is True
    assert execution.simulation_state["conversation_guard"]


@pytest.mark.asyncio
async def test_guard_bypass_keyword_skips_counter() -> None:
    execution = SimpleNamespace(simulation_state={}, instance_id=None, run_id=uuid4())
    rctx = SimpleNamespace(
        node=SimpleNamespace(
            config={"mode": "check", "bypass_keywords": ["humano", "reclamo"]},
            label="Guardia",
        ),
        trigger={"message": "quiero hablar con un humano", "participant_id": "demo"},
        variables={},
        execution=execution,
        organization_id=uuid4(),
        workspace_id=None,
        simulate=True,
        node_id="guard",
        node_labels={},
        node_types={},
    )
    outcome = await _exec_conversation_guard(rctx)
    assert outcome.output["bypass"] is True
    assert outcome.output["allowed"] is True
