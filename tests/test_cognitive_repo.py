# =============================================================================
# Cognitive repository — Postgres real (Phase 3)
# =============================================================================
from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest

from src.core.domain.cognitive import (
    AgentExecution,
    AgentMessage,
    AgentMessageType,
    CognitiveRunStatus,
    CognitiveScope,
    CognitiveTaskStatus,
    ExecutionStatus,
)
from src.infrastructure.postgres.cognitive import PostgresCognitiveRepository
from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.platform.cognitive.orchestrator import KnowledgeCognitiveOrchestrator


@pytest.fixture
async def org():
    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Cognitive Org {uuid4().hex[:6]}")


@pytest.mark.asyncio
async def test_cognitive_repository_roundtrip_and_isolation(org) -> None:
    plan = KnowledgeCognitiveOrchestrator().plan(
        query="¿Dónde aparece la política de vacaciones?",
        scope=CognitiveScope(organization_id=org.id),
    )
    repo = PostgresCognitiveRepository()
    saved = await repo.create_run(plan.run)
    await repo.save_tasks(organization_id=org.id, tasks=plan.graph.tasks)

    fetched = await repo.get_run(org.id, saved.id)
    assert fetched is not None
    assert fetched["complexity"] == "L1"
    assert fetched["status"] == "planned"

    tasks = await repo.list_tasks(org.id, saved.id)
    assert len(tasks) == len(plan.graph.tasks)
    assert [t["task_key"] for t in tasks] == [
        t.key for t in plan.graph.tasks
    ]

    # aislamiento por tenant
    assert await repo.get_run(uuid4(), saved.id) is None
    assert await repo.list_tasks(uuid4(), saved.id) == []

    message = AgentMessage(
        run_id=saved.id,
        type=AgentMessageType.FINDING,
        from_agent="librarian",
        text="Fuente localizada: manual de RRHH",
    )
    appended = await repo.append_message(org.id, message)
    assert appended.id == message.id
    messages = await repo.list_messages(org.id, saved.id)
    assert [m["from_agent"] for m in messages] == ["librarian"]
    assert messages[0]["message_type"] == "finding"
    assert await repo.list_messages(uuid4(), saved.id) == []


@pytest.mark.asyncio
async def test_cognitive_execution_roundtrip_and_isolation(org) -> None:
    plan = KnowledgeCognitiveOrchestrator().plan(
        query="¿Dónde aparece la política de vacaciones?",
        scope=CognitiveScope(organization_id=org.id),
    )
    repo = PostgresCognitiveRepository()
    saved = await repo.create_run(plan.run)
    await repo.save_tasks(organization_id=org.id, tasks=plan.graph.tasks)

    await repo.update_run_status(org.id, saved.id, CognitiveRunStatus.RUNNING)
    task = plan.graph.tasks[0]
    await repo.update_task_status(org.id, task.id, CognitiveTaskStatus.RUNNING)

    execution = AgentExecution(
        run_id=saved.id, task_id=task.id, agent_id=task.agent_id
    )
    await repo.save_execution(org.id, execution)
    finished = replace(
        execution,
        status=ExecutionStatus.COMPLETED,
        latency_ms=12.5,
        llm_calls=1,
        tokens=42,
        cost_usd=0.01,
        result={"ok": True},
    )
    saved_execution = await repo.save_execution(org.id, finished)
    assert saved_execution.status is ExecutionStatus.COMPLETED

    executions = await repo.list_executions(org.id, saved.id)
    assert len(executions) == 1
    assert executions[0]["status"] == "completed"
    assert executions[0]["tokens"] == 42

    tasks = await repo.list_tasks(org.id, saved.id)
    assert tasks[0]["status"] == "running"

    await repo.update_run_status(
        org.id,
        saved.id,
        CognitiveRunStatus.COMPLETED,
        plan_patch={"final_answer": "ok"},
    )
    run = await repo.get_run(org.id, saved.id)
    assert run["status"] == "completed"
    assert run["plan"]["final_answer"] == "ok"

    # aislamiento por tenant
    assert await repo.list_executions(uuid4(), saved.id) == []
