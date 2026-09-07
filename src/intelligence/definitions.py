# =============================================================================
# Business Definition Registry — conceptos/metrícas aprobadas por organización
# =============================================================================
# Zent NO inventa definiciones empresariales: solo lo aprobado aquí cuenta
# como definido (CONTEXT_MISSING si un concepto requerido no está registrado).
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from src.core.domain.intelligence import BusinessDefinition
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)

_CACHE_KEY_PREFIX = "rag:intelligence:definitions:"
_CACHE_TTL_SECONDS = 60


class BusinessDefinitionRegistry:
    """Registro org-scoped de definiciones aprobadas (con caché opcional)."""

    def __init__(
        self,
        store: PostgresIntelligenceStore | None = None,
        cache: Any | None = None,
        ttl_seconds: int = _CACHE_TTL_SECONDS,
    ) -> None:
        self._store = store or PostgresIntelligenceStore()
        self._cache = cache
        self._ttl = ttl_seconds

    @staticmethod
    def _cache_key(organization_id: UUID) -> str:
        return f"{_CACHE_KEY_PREFIX}{organization_id}"

    async def get_all(self, organization_id: UUID) -> list[BusinessDefinition]:
        """Definiciones de la org (caché de lista, TTL corto)."""
        cache_key = self._cache_key(organization_id)
        if self._cache is not None:
            try:
                cached = await self._cache.get(cache_key)
                if cached:
                    return [
                        BusinessDefinition(**item)
                        for item in cached
                        if isinstance(item, dict)
                    ]
            except Exception as exc:  # noqa: BLE001
                logger.warning("Definitions cache read failed", error=str(exc))

        definitions = await self._store.list_definitions(organization_id)
        if self._cache is not None:
            try:
                await self._cache.set(
                    cache_key,
                    [d.__dict__ for d in definitions],
                    ttl_seconds=self._ttl,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Definitions cache write failed", error=str(exc))
        return definitions

    async def get(
        self, organization_id: UUID, concept: str
    ) -> BusinessDefinition | None:
        normalized = concept.strip().lower()
        for definition in await self.get_all(organization_id):
            if definition.concept == normalized:
                return definition
        return None

    async def resolve_concepts(
        self, organization_id: UUID, concepts: list[str]
    ) -> dict[str, bool]:
        """Mapea conceptos candidatos -> definidos (solo 'approved')."""
        if not concepts:
            return {}
        definitions = await self.get_all(organization_id)
        approved = {
            d.concept for d in definitions if d.status == "approved"
        }
        return {c.strip().lower(): c.strip().lower() in approved for c in concepts}

    async def upsert(self, definition: BusinessDefinition) -> BusinessDefinition:
        saved = await self._store.upsert_definition(
            organization_id=definition.organization_id,
            concept=definition.concept,
            definition=definition.definition,
            expression=definition.expression,
            data_type=definition.data_type,
            status=definition.status,
            authoritative_source_id=definition.authoritative_source_id,
            created_by=definition.created_by,
        )
        await self._invalidate(definition.organization_id)
        return saved

    async def delete(self, organization_id: UUID, concept: str) -> bool:
        deleted = await self._store.delete_definition(organization_id, concept)
        await self._invalidate(organization_id)
        return deleted

    async def _invalidate(self, organization_id: UUID) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.delete(self._cache_key(organization_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Definitions cache invalidation failed", error=str(exc))
