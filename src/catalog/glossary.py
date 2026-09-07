# =============================================================================
# Business Glossary — términos reutilizables sobre business_definitions
# =============================================================================
# Term: name, description, synonyms, owner, status, version, effective_from/to,
# created_by, approved_by. Un término aprobado alimenta el Answerability Gate
# (business_definition_status) sin lógica duplicada.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.intelligence import BusinessDefinition
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)


class GlossaryService:
    """Gobernanza del glosario de negocio."""

    def __init__(self, store: PostgresIntelligenceStore | None = None) -> None:
        self._store = store or PostgresIntelligenceStore()

    async def list(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        definitions = await self._store.list_definitions(
            organization_id, status=status, limit=limit, offset=offset
        )
        return [_payload(d) for d in definitions]

    async def upsert(
        self,
        *,
        organization_id: UUID,
        concept: str,
        definition: str,
        expression: str | None = None,
        data_type: str = "concept",
        status: str = "approved",
        authoritative_source_id: str | None = None,
        created_by: UUID | None = None,
        synonyms: list[str] | None = None,
        owner: str | None = None,
        effective_from=None,
        effective_to=None,
    ) -> dict:
        existing = await self._store.get_definition(organization_id, concept)
        next_version = (existing.version + 1) if existing else 1
        saved = await self._store.upsert_definition(
            organization_id=organization_id,
            concept=concept,
            definition=definition,
            expression=expression,
            data_type=data_type,
            status=status,
            authoritative_source_id=authoritative_source_id,
            created_by=created_by,
            synonyms=synonyms,
            owner=owner,
            version=next_version,
            effective_from=effective_from,
            effective_to=effective_to,
            approved_by=created_by if status == "approved" else None,
            provenance=(
                "APPROVED"
                if status == "approved"
                else ("OBSERVED" if existing is None else existing.provenance)
            ),
        )
        return _payload(saved)

    async def approve(
        self,
        *,
        organization_id: UUID,
        concept: str,
        approved_by: UUID | None = None,
    ) -> dict | None:
        existing = await self._store.get_definition(organization_id, concept)
        if existing is None:
            return None
        saved = await self._store.upsert_definition(
            organization_id=organization_id,
            concept=existing.concept,
            definition=existing.definition,
            expression=existing.expression,
            data_type=existing.data_type,
            status="approved",
            authoritative_source_id=existing.authoritative_source_id,
            created_by=existing.created_by,
            synonyms=existing.synonyms,
            owner=existing.owner,
            version=existing.version,
            effective_from=existing.effective_from,
            effective_to=existing.effective_to,
            approved_by=approved_by,
            provenance="APPROVED",
        )
        return _payload(saved)

    async def delete(self, organization_id: UUID, concept: str) -> bool:
        return await self._store.delete_definition(organization_id, concept)


def _payload(d: BusinessDefinition) -> dict:
    return {
        "id": str(d.id),
        "concept": d.concept,
        "definition": d.definition,
        "expression": d.expression,
        "data_type": d.data_type,
        "status": d.status,
        "authoritative_source_id": d.authoritative_source_id,
        "synonyms": d.synonyms,
        "owner": d.owner,
        "version": d.version,
        "effective_from": d.effective_from.isoformat() if d.effective_from else None,
        "effective_to": d.effective_to.isoformat() if d.effective_to else None,
        "approved_by": str(d.approved_by) if d.approved_by else None,
        "provenance": d.provenance,
        "created_by": str(d.created_by) if d.created_by else None,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }
