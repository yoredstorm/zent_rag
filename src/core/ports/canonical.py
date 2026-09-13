# =============================================================================
# Ports — Canonical Knowledge repository (Phase 1)
# =============================================================================
# Identidad canónica + mapping entre sistemas. organization_id es OBLIGATORIO
# en toda operación; nunca devolver ni enlazar objetos de otro tenant.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.canonical import (
    CanonicalKind,
    CanonicalLink,
    CanonicalObject,
    CanonicalRef,
)


class CanonicalKnowledgeRepository(ABC):
    """Puerto de la identidad canónica (slice 1: registro + mapping)."""

    @abstractmethod
    async def upsert_object(self, obj: CanonicalObject) -> CanonicalObject:
        """Inserta o actualiza el objeto canónico por (org, kind, natural_key).

        Idempotente: el id canónico es determinista. Devuelve el estado
        persistido (provenance/status/title/metadata actualizados).
        """
        ...

    @abstractmethod
    async def get_object(
        self, organization_id: UUID, canonical_id: UUID
    ) -> CanonicalObject | None:
        """Objeto canónico o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def get_by_natural_key(
        self, organization_id: UUID, kind: CanonicalKind, natural_key: str
    ) -> CanonicalObject | None:
        """Objeto canónico por clave natural (scoped)."""
        ...

    @abstractmethod
    async def link(
        self,
        organization_id: UUID,
        canonical_id: UUID,
        ref: CanonicalRef,
        *,
        workspace_id: UUID | None = None,
        is_primary: bool = False,
        metadata: dict | None = None,
    ) -> CanonicalLink:
        """Enlaza un objeto físico al canónico. Idempotente por ref.

        Rechaza con ValueError si el canónico no pertenece a la organización.
        """
        ...

    @abstractmethod
    async def unlink(self, organization_id: UUID, ref: CanonicalRef) -> None:
        """Elimina el mapping del ref (scoped). No falla si no existe."""
        ...

    @abstractmethod
    async def list_links(
        self, organization_id: UUID, canonical_id: UUID
    ) -> list[CanonicalLink]:
        """Mappings de un objeto canónico (scoped)."""
        ...

    @abstractmethod
    async def resolve(
        self, organization_id: UUID, ref: CanonicalRef
    ) -> CanonicalObject | None:
        """Resuelve el canónico al que apunta un objeto físico (scoped)."""
        ...
