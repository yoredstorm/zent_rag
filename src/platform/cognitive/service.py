# =============================================================================
# Cognitive Planning Service — Phase 3
# =============================================================================
# Compone planner + persistencia. NO ejecuta especialistas: crea el run
# planificado (DAG + asignaciones + presupuesto) y lo deja consultable.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.cognitive import (
    CognitiveBudget,
    CognitiveRun,
    CognitiveScope,
    CognitiveTask,
)
from src.core.ports.cognitive import CognitiveRepository
from src.platform.cognitive.orchestrator import KnowledgeCognitiveOrchestrator


def run_to_dict(run: CognitiveRun) -> dict:
    return {
        "id": str(run.id),
        "organization_id": str(run.organization_id),
        "workspace_id": str(run.workspace_id) if run.workspace_id else None,
        "query": run.query,
        "complexity": run.complexity.value,
        "status": run.status.value,
        "budget": run.budget.to_dict(),
        "plan": run.plan,
        "created_by": str(run.created_by) if run.created_by else None,
        "created_at": run.created_at.isoformat(),
    }


def task_to_dict(task: CognitiveTask) -> dict:
    return {
        "id": str(task.id),
        "key": task.key,
        "description": task.description,
        "agent_id": task.agent_id,
        "status": task.status.value,
        "depends_on": list(task.depends_on),
        "position": task.position,
    }


class CognitivePlanningService:
    def __init__(
        self,
        repository: CognitiveRepository,
        orchestrator: KnowledgeCognitiveOrchestrator | None = None,
    ) -> None:
        self._repo = repository
        self._orchestrator = orchestrator or KnowledgeCognitiveOrchestrator()

    async def create_run(
        self,
        *,
        query: str,
        scope: CognitiveScope,
        budget: CognitiveBudget | None = None,
        created_by: UUID | None = None,
    ) -> dict:
        plan = self._orchestrator.plan(
            query=query, scope=scope, budget=budget, created_by=created_by
        )
        saved = await self._repo.create_run(plan.run)
        await self._repo.save_tasks(
            organization_id=saved.organization_id, tasks=plan.graph.tasks
        )
        return {
            "run": run_to_dict(saved),
            "tasks": [task_to_dict(task) for task in plan.graph.tasks],
            "agents": [definition.id for definition in plan.definitions],
        }

    async def get_run(
        self, organization_id: UUID, run_id: UUID
    ) -> dict | None:
        run = await self._repo.get_run(organization_id, run_id)
        if run is None:
            return None
        tasks = await self._repo.list_tasks(organization_id, run_id)
        return {"run": run, "tasks": tasks}

    async def list_tasks(
        self, organization_id: UUID, run_id: UUID
    ) -> list[dict] | None:
        run = await self._repo.get_run(organization_id, run_id)
        if run is None:
            return None
        return await self._repo.list_tasks(organization_id, run_id)

    async def list_messages(
        self, organization_id: UUID, run_id: UUID
    ) -> list[dict] | None:
        run = await self._repo.get_run(organization_id, run_id)
        if run is None:
            return None
        return await self._repo.list_messages(organization_id, run_id)
