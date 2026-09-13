# =============================================================================
# Ports — Shadow evaluation (Phase 8)
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.shadow import ShadowComparison


class ShadowRepository(ABC):
    """Comparaciones shadow baseline vs cognitive (org-scoped)."""

    @abstractmethod
    async def save(self, comparison: ShadowComparison) -> ShadowComparison:
        """Persiste la comparación (idempotente por id)."""
        ...

    @abstractmethod
    async def list(
        self, organization_id: UUID, limit: int = 50
    ) -> list[ShadowComparison]:
        """Comparaciones de la organización, más recientes primero."""
        ...
