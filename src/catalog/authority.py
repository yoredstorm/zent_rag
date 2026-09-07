# =============================================================================
# Source Authority — fuentes autoritativas por dominio/concepto
# =============================================================================
# El catálogo almacena domain, concept, source, authority_level, priority,
# effective_dates. Alimenta al Answerability Gate (authoritative_source)
# para resolver SOURCE_CONFLICT sin elegir fuentes arbitrariamente.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from src.catalog.lineage import LineageService
from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import CatalogAuthority
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


class AuthorityService:
    """Registro de fuentes autoritativas."""

    def __init__(self, store: PostgresCatalogStore) -> None:
        self._store = store
        self._lineage = LineageService(store)

    async def list(self, organization_id: UUID) -> list[dict]:
        return await self._store.list_authority(organization_id)

    async def upsert(
        self,
        *,
        organization_id: UUID,
        domain: str,
        concept: str,
        source_name: str,
        source_type: str = "connector",
        connector_id: UUID | None = None,
        authority_level: str = "authoritative",
        priority: int = 1,
        effective_from=None,
        effective_to=None,
        created_by: UUID | None = None,
    ) -> dict:
        authority = CatalogAuthority(
            id=uuid4(),
            organization_id=organization_id,
            domain=domain.strip().lower() or "general",
            concept=concept.strip().lower(),
            source_name=source_name,
            source_type=source_type,
            connector_id=connector_id,
            authority_level=authority_level,
            priority=priority,
            effective_from=effective_from,
            effective_to=effective_to,
            created_by=created_by,
        )
        await self._store.upsert_authority(authority)
        await self._lineage.record_authority(
            organization_id=organization_id,
            concept=authority.concept,
            source_name=authority.source_name,
        )
        return {
            "id": str(authority.id),
            "domain": authority.domain,
            "concept": authority.concept,
            "source_name": authority.source_name,
            "source_type": authority.source_type,
            "authority_level": authority.authority_level,
            "priority": authority.priority,
        }

    async def authoritative_source(
        self, organization_id: UUID, concepts: list[str], domain: str = "general"
    ) -> str | None:
        """Mejor fuente autoritativa activa para los conceptos dados."""
        rows = await self._store.get_authority_for_concepts(
            organization_id, concepts, domain=domain
        )
        if not rows:
            return None
        return rows[0]["source_name"]
