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

from src.core.domain.cognitive import AgentMessage, CognitiveRun, CognitiveTask


class CognitiveRepository(ABC):
    """Puerto de persistencia del Cognitive OS (planning runs)."""

    @abstractmethod
    async def create_run(self, run: CognitiveRun) -> CognitiveRun:
        """Persiste el run (idempotente por id)."""
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
