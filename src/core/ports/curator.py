# =============================================================================
# Ports — Knowledge Curator suggestions (Phase 7)
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.curator import KnowledgeSuggestion, SuggestionStatus


class CuratorRepository(ABC):
    """Sugerencias gobernadas: proponer, listar, decidir (org-scoped)."""

    @abstractmethod
    async def propose(self, suggestion: KnowledgeSuggestion) -> KnowledgeSuggestion:
        """Persiste una sugerencia PROPOSED (append)."""
        ...

    @abstractmethod
    async def get(
        self, organization_id: UUID, suggestion_id: UUID
    ) -> KnowledgeSuggestion | None:
        """Sugerencia o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def list(
        self,
        organization_id: UUID,
        *,
        status: SuggestionStatus | None = None,
        run_id: UUID | None = None,
        limit: int = 100,
    ) -> list[KnowledgeSuggestion]:
        """Sugerencias filtradas (scoped)."""
        ...

    @abstractmethod
    async def decide(
        self,
        organization_id: UUID,
        suggestion_id: UUID,
        *,
        status: SuggestionStatus,
        decided_by: UUID,
        reason: str = "",
    ) -> KnowledgeSuggestion | None:
        """Aprueba/rechaza con actor humano. Solo decisiones finales."""
        ...
