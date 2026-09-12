# =============================================================================
# Ports — KnowledgeCorpus repository (Knowledge V2, Phase D slice 2)
# =============================================================================
# Un corpus es workspace-scoped + org-scoped. Toda operación exige
# organization_id; nunca se cruza tenant. Los sources se anexan vía corpus_id
# en kb_sources (overlay; V1 sigue funcionando con corpus_id NULL).
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.knowledge_v2 import KnowledgeCorpus


class KnowledgeCorpusRepository(ABC):
    """Puerto de persistencia/lectura de KnowledgeCorpus."""

    @abstractmethod
    async def create_corpus(self, corpus: KnowledgeCorpus) -> KnowledgeCorpus:
        """Crea (idempotente por organization_id + workspace_id + slug)."""
        ...

    @abstractmethod
    async def get_corpus(
        self, organization_id: UUID, corpus_id: UUID
    ) -> dict | None:
        """Metadata del corpus o None. Scoped estricto por organization_id."""
        ...

    @abstractmethod
    async def get_corpus_by_slug(
        self, organization_id: UUID, workspace_id: UUID, slug: str
    ) -> dict | None:
        """Busca por slug dentro de un workspace (scoped)."""
        ...

    @abstractmethod
    async def list_corpora(
        self,
        organization_id: UUID,
        workspace_id: UUID | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Lista corpora (opcionalmente filtrados por workspace)."""
        ...

    @abstractmethod
    async def attach_source(
        self, organization_id: UUID, source_id: UUID, corpus_id: UUID
    ) -> None:
        """Anexa un kb_source al corpus (kb_sources.corpus_id). Scoped."""
        ...

    @abstractmethod
    async def detach_source(
        self, organization_id: UUID, source_id: UUID
    ) -> None:
        """Quita la pertenencia del source a cualquier corpus."""
        ...
