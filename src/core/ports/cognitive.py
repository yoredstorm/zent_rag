# =============================================================================
# Ports — Cognitive OS repository (Phase 3)
# =============================================================================
# Runs, tasks y mensajes del supervisor cognitivo. organization_id es
# OBLIGATORIO en toda operación (tenant isolation).
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from src.core.domain.cognitive import (
    AgentExecution,
    AgentMessage,
    CognitiveRun,
    CognitiveRunStatus,
    CognitiveTask,
    CognitiveTaskStatus,
)


class CognitiveRepository(ABC):
    """Puerto de persistencia del Cognitive OS (planning + execution)."""

    @abstractmethod
    async def create_run(self, run: CognitiveRun) -> CognitiveRun:
        """Persiste el run (idempotente por id)."""
        ...

    @abstractmethod
    async def update_run_status(
        self,
        organization_id: UUID,
        run_id: UUID,
        status: CognitiveRunStatus,
        *,
        plan_patch: dict | None = None,
    ) -> None:
        """Actualiza estado del run y mergea un patch en `plan` (scoped)."""
        ...

    @abstractmethod
    async def update_task_status(
        self,
        organization_id: UUID,
        task_id: UUID,
        status: CognitiveTaskStatus,
        *,
        result: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Actualiza estado/resultado de una tarea (scoped)."""
        ...

    @abstractmethod
    async def save_execution(
        self, organization_id: UUID, execution: AgentExecution
    ) -> AgentExecution:
        """Persiste/actualiza una ejecución de especialista (scoped)."""
        ...

    @abstractmethod
    async def list_executions(
        self, organization_id: UUID, run_id: UUID
    ) -> list[dict]:
        """Ejecuciones del run (scoped, orden cronológico)."""
        ...

    @abstractmethod
    async def save_tasks(
        self, *, organization_id: UUID, tasks: Sequence[CognitiveTask]
    ) -> None:
        """Persiste el task graph planificado (idempotente por run+key)."""
        ...

    @abstractmethod
    async def get_run(
        self, organization_id: UUID, run_id: UUID
    ) -> dict | None:
        """Run o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def list_tasks(
        self, organization_id: UUID, run_id: UUID
    ) -> list[dict]:
        """Tareas del run en orden de planificación (scoped)."""
        ...

    @abstractmethod
    async def append_message(
        self, organization_id: UUID, message: AgentMessage
    ) -> AgentMessage:
        """Registra un AgentMessage (append-only, org-scoped)."""
        ...

    @abstractmethod
    async def list_messages(
        self, organization_id: UUID, run_id: UUID, limit: int = 200
    ) -> list[dict]:
        """Mensajes del run (scoped, orden cronológico)."""
        ...
