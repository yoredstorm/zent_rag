# =============================================================================
# Ports — Structured Document repository (Knowledge V2, Phase B)
# =============================================================================
# Persiste el árbol StructuredDocument (structured_documents + blocks) con el
# MISMO contrato de aislamiento que el resto de la plataforma:
# organization_id es OBLIGATORIO en toda operación. Nunca devolver un
# documento cuyo organization_id no coincide con el solicitante.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument


class StructuredDocumentRepository(ABC):
    """Puerto para persistir el modelo de conocimiento V2 (Phase B)."""

    @abstractmethod
    async def upsert_document(self, document: StructuredDocument) -> str:
        """Reemplaza el documento (y su árbol de blocks) por
        (organization_id, source_id, external_id). Idempotente y scoped.

        Retorna el change_kind detectado por content_hash
        ('created' | 'unchanged' | 'updated' — ver DocumentChangeKind).
        """
        ...

    @abstractmethod
    async def get_document(
        self, organization_id: UUID, document_id: UUID
    ) -> dict | None:
        """Metadata del documento o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def list_documents(
        self,
        organization_id: UUID,
        source_id: UUID,
        limit: int = 100,
    ) -> list[dict]:
        """Lista metadata de documentos de una fuente (scoped)."""
        ...

    @abstractmethod
    async def delete_for_source(self, organization_id: UUID, source_id: UUID) -> None:
        """Elimina documentos y blocks de la fuente (scoped, cascade)."""
        ...
