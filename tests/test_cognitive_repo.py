# =============================================================================
# Cognitive repository — Postgres real (Phase 3)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.cognitive import (
    AgentMessage,
    AgentMessageType,
    CognitiveScope,
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
