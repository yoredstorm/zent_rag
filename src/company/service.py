# =============================================================================
# Company Intelligence — Domain Service + Source Authority (Fase Company)
# =============================================================================
# CompanyGraphService: query, validación, provenance, transiciones de estado,
# filtros temporales, authority. La lógica de negocio vive aquí, NO en el
# repository (el repository solo persiste y navega).
#
# Leyes:
#   - AUTO_CONFIRMED solo para relaciones estructuralmente verificables
#     (AUTO_CONFIRMABLE_PAIRS): schema confirma Table CONTAINS Field, pero
#     un LLM que infiere Field MEANS concepto NUNCA auto-confirma.
#   - Niveles de authority: mapeo desde catalog_authority existente
#     (authoritative/approved/informational/external) a los 5 del spec.
#   - Source authority configurable por tenant (tabla
#     company_source_authority, migración 129). Sin ranking global único:
#     la autoridad se resuelve por (dominio, concepto).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
    ProvenanceRef,
    SourceAuthorityLevel,
    is_valid_at,
    normalize_relationship_type,
)
from src.core.ports.company_graph import (
    CompanyGraphRepository,
    GraphNeighborhood,
    GraphPath,
    GraphTraversalLimits,
    ImpactResult,
    RelationshipFilter,
)
from src.infrastructure.postgres.session import get_async_session


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auto-confirmación estructural (cerrado por diseño)
# ---------------------------------------------------------------------------

# Pares (from_type, relationship, to_type) verificables contra estructura
# física (schema/tabla/campo descubiertos), no contra inferencia LLM.
AUTO_CONFIRMABLE_PAIRS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("database", "CONTAINS", "table"),
        ("table", "CONTAINS", "field"),
        ("dataset", "CONTAINS", "table"),
        ("dataset", "CONTAINS", "field"),
        ("system", "CONTAINS", "database"),
        ("system", "CONTAINS", "service"),
        ("service", "CONTAINS", "api"),
        ("api", "CONTAINS", "field"),
        ("organization", "CONTAINS", "team"),
        ("team", "CONTAINS", "person"),
        ("team", "CONTAINS", "role"),
        ("domain", "CONTAINS", "concept"),
    }
)

# Tipos de relación que NUNCA pueden auto-confirmarse (requieren semántica).
NEVER_AUTO_CONFIRM: frozenset[str] = frozenset(
    {
        "MAPS_TO",
        "DESCRIBES",
        "MEANS",
        "SUPPORTS",
        "CONTRADICTS",
        "GOVERNED_BY",
        "AFFECTS",
        "RELATED_TO",
    }
)


def is_structurally_verifiable(
    from_type: str, relationship_type: str, to_type: str
) -> bool:
    rel = normalize_relationship_type(relationship_type)
    if rel in NEVER_AUTO_CONFIRM:
        return False
    return (
        from_type.strip().lower(),
        rel,
        to_type.strip().lower(),
    ) in AUTO_CONFIRMABLE_PAIRS


# ---------------------------------------------------------------------------
# Mapeo de authority: catalog_authority (4 niveles) -> spec (5 niveles)
# ---------------------------------------------------------------------------

_CATALOG_TO_SPEC: dict[str, SourceAuthorityLevel] = {
    "authoritative": SourceAuthorityLevel.AUTHORITATIVE,
    "approved": SourceAuthorityLevel.PRIMARY,
    "informational": SourceAuthorityLevel.SECONDARY,
    "external": SourceAuthorityLevel.INFORMATIONAL,
}

_SPEC_RANK: dict[SourceAuthorityLevel, int] = {
    SourceAuthorityLevel.AUTHORITATIVE: 4,
    SourceAuthorityLevel.PRIMARY: 3,
    SourceAuthorityLevel.SECONDARY: 2,
    SourceAuthorityLevel.INFORMATIONAL: 1,
    SourceAuthorityLevel.UNTRUSTED: 0,
}


def catalog_level_to_spec(catalog_level: str) -> SourceAuthorityLevel:
    return _CATALOG_TO_SPEC.get(
        catalog_level.strip().lower(), SourceAuthorityLevel.INFORMATIONAL
    )


@dataclass(frozen=True, kw_only=True)
class AuthorityRule:
    organization_id: UUID
    domain: str
    concept: str
    source_name: str
    source_type: str = "connector"
    authority_level: SourceAuthorityLevel = SourceAuthorityLevel.INFORMATIONAL
    priority: int = 1
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class CompanyAuthorityService:
    """Source authority configurable por tenant y por dominio.

    Sin ranking global único: la autoridad se resuelve por
    (dominio, concepto) con filtro de vigencia y desempate por prioridad.
    Lee company_source_authority (migración 129) y mapea catalog_authority
    existente a los 5 niveles del spec."""

    async def upsert_rule(self, rule: AuthorityRule) -> AuthorityRule:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    """
                    INSERT INTO company_source_authority
                        (organization_id, domain, concept, source_name,
                         source_type, authority_level, priority,
                         effective_from, effective_to, updated_at)
                    VALUES
                        (:oid, :domain, :concept, :source_name, :source_type,
                         :level, :priority, :eff_from, :eff_to, now())
                    ON CONFLICT (organization_id, domain, concept, source_name)
                    DO UPDATE SET
                        source_type = EXCLUDED.source_type,
                        authority_level = EXCLUDED.authority_level,
                        priority = EXCLUDED.priority,
                        effective_from = EXCLUDED.effective_from,
                        effective_to = EXCLUDED.effective_to,
                        updated_at = now()
                    """
                ),
                {
                    "oid": str(rule.organization_id),
                    "domain": rule.domain.strip().lower() or "general",
                    "concept": rule.concept.strip().lower(),
                    "source_name": rule.source_name,
                    "source_type": rule.source_type,
                    "level": rule.authority_level.value,
                    "priority": rule.priority,
                    "eff_from": rule.effective_from,
                    "eff_to": rule.effective_to,
                },
            )
            await session.commit()
            return rule
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def list_rules(
        self, organization_id: UUID, domain: str | None = None
    ) -> list[AuthorityRule]:
        session = await get_async_session()
        try:
            if domain:
                result = await session.execute(
                    text(
                        "SELECT domain, concept, source_name, source_type, "
                        "authority_level, priority, effective_from, effective_to "
                        "FROM company_source_authority "
                        "WHERE organization_id = :oid AND domain = :domain "
                        "ORDER BY concept, priority, source_name"
                    ),
                    {
                        "oid": str(organization_id),
                        "domain": domain.strip().lower(),
                    },
                )
            else:
                result = await session.execute(
                    text(
                        "SELECT domain, concept, source_name, source_type, "
                        "authority_level, priority, effective_from, effective_to "
                        "FROM company_source_authority "
                        "WHERE organization_id = :oid "
                        "ORDER BY domain, concept, priority, source_name"
                    ),
                    {"oid": str(organization_id)},
                )
            return [
                AuthorityRule(
                    organization_id=organization_id,
                    domain=row.domain,
                    concept=row.concept,
                    source_name=row.source_name,
                    source_type=row.source_type,
                    authority_level=SourceAuthorityLevel(row.authority_level),
                    priority=row.priority,
                    effective_from=row.effective_from,
                    effective_to=row.effective_to,
                )
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def resolve_authority(
        self,
        organization_id: UUID,
        *,
        domain: str,
        concept: str,
        source_name: str,
        as_of: datetime | None = None,
    ) -> SourceAuthorityLevel:
        """Nivel vigente para (dominio, concepto, fuente). Sin regla vigente:
        INFORMATIONAL (nunca asumir autoridad)."""
        moment = as_of or _utcnow()
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    "SELECT authority_level FROM company_source_authority "
                    "WHERE organization_id = :oid "
                    "AND domain = :domain "
                    "AND (concept = :concept OR concept = '') "
                    "AND source_name = :source_name "
                    "AND (effective_from IS NULL OR effective_from <= :as_of) "
                    "AND (effective_to IS NULL OR effective_to > :as_of) "
                    "ORDER BY priority ASC LIMIT 1"
                ),
                {
                    "oid": str(organization_id),
                    "domain": domain.strip().lower() or "general",
                    "concept": concept.strip().lower(),
                    "source_name": source_name,
                    "as_of": moment,
                },
            )
            row = result.fetchone()
            if row is None:
                return SourceAuthorityLevel.INFORMATIONAL
            return SourceAuthorityLevel(row.authority_level)
        finally:
            await session.close()

    @staticmethod
    def rank(level: SourceAuthorityLevel) -> int:
        return _SPEC_RANK[level]


# ---------------------------------------------------------------------------
# CompanyGraphService
# ---------------------------------------------------------------------------


class CompanyGraphService:
    """Servicio de dominio del grafo. Valida creación de relaciones,
    provenance, transiciones, filtros temporales y authority. Delega la
    persistencia al puerto (storage-agnostic)."""

    def __init__(
        self,
        repo: CompanyGraphRepository,
        authority: CompanyAuthorityService | None = None,
    ) -> None:
        self._repo = repo
        self._authority = authority or CompanyAuthorityService()

    # -- Query (delegación con defaults) --------------------------------
    async def get_entity(
        self, organization_id: UUID, entity_id: UUID
    ) -> CompanyEntity | None:
        return await self._repo.get_entity(organization_id, entity_id)

    async def find_entities(self, organization_id: UUID, **kwargs) -> list[CompanyEntity]:
        return await self._repo.find_entities(organization_id, **kwargs)

    async def find_relationships(
        self, organization_id: UUID, **kwargs
    ) -> list[CompanyRelationship]:
        return await self._repo.find_relationships(organization_id, **kwargs)

    async def neighbors(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        return await self._repo.neighbors(
            organization_id,
            entity_id,
            direction=direction,
            relationship_filter=relationship_filter,
            limits=limits,
        )

    async def traverse(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        return await self._repo.traverse(
            organization_id,
            entity_id,
            direction=direction,
            relationship_filter=relationship_filter,
            limits=limits,
        )

    async def find_path(
        self,
        organization_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
        *,
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphPath | None:
        return await self._repo.find_path(
            organization_id,
            from_entity_id,
            to_entity_id,
            relationship_filter=relationship_filter,
            limits=limits,
        )

    async def impact_analysis(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> ImpactResult:
        """Grafo verificable de dependencias. Sin conclusiones LLM."""
        return await self._repo.impact_analysis(
            organization_id,
            entity_id,
            direction=direction,
            relationship_filter=relationship_filter,
            limits=limits,
        )

    async def history(
        self, organization_id: UUID, entity_id: UUID, **kwargs
    ) -> list[CompanyRelationship]:
        return await self._repo.entity_history(organization_id, entity_id, **kwargs)

    # -- Escritura validada ---------------------------------------------
    async def upsert_entity(self, entity: CompanyEntity) -> CompanyEntity:
        return await self._repo.upsert_entity(entity)

    async def propose_relationship(
        self,
        organization_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
        relationship_type: str,
        *,
        source: str = "",
        source_ref: str = "",
        evidence: tuple[ProvenanceRef, ...] = (),
        confidence: float | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        metadata: dict | None = None,
        auto_confirm_structural: bool = False,
    ) -> CompanyRelationship:
        """Valida extremos (mismo tenant), provenance no vacía para relaciones
        no triviales, y auto-confirmación solo estructural."""
        if from_entity_id == to_entity_id:
            raise ValueError("relationship must link two different entities")
        from_entity = await self._repo.get_entity(organization_id, from_entity_id)
        to_entity = await self._repo.get_entity(organization_id, to_entity_id)
        if from_entity is None or to_entity is None:
            raise ValueError(
                "both relationship endpoints must belong to the organization"
            )
        status = EntityStatus.DISCOVERED
        if auto_confirm_structural:
            if is_structurally_verifiable(
                from_entity.entity_type, relationship_type, to_entity.entity_type
            ):
                status = EntityStatus.AUTO_CONFIRMED
        relationship = CompanyRelationship(
            organization_id=organization_id,
            from_entity_id=from_entity_id,
            to_entity_id=to_entity_id,
            relationship_type=relationship_type,
            status=status,
            confidence=confidence,
            source=source,
            source_ref=source_ref,
            evidence_refs=evidence,
            metadata=metadata or {},
            valid_from=valid_from,
            valid_to=valid_to,
        )
        return await self._repo.propose_relationship(relationship)

    async def confirm_relationship(
        self,
        organization_id: UUID,
        relationship_id: UUID,
        *,
        status: EntityStatus,
    ) -> CompanyRelationship:
        if status is EntityStatus.AUTO_CONFIRMED:
            raise ValueError(
                "AUTO_CONFIRMED cannot be set manually: "
                "only structural verification assigns it"
            )
        return await self._repo.confirm_relationship(
            organization_id, relationship_id, status=status
        )

    async def deprecate_relationship(
        self, organization_id: UUID, relationship_id: UUID
    ) -> CompanyRelationship:
        return await self._repo.deprecate_relationship(
            organization_id, relationship_id
        )

    # -- Concept mappings (técnicos, estructurados) ----------------------
    async def concept_mappings(
        self,
        organization_id: UUID,
        concept_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> list[CompanyRelationship]:
        """Mappings técnicos de un concepto (MAPS_TO vigentes)."""
        moment = as_of or _utcnow()
        rels = await self._repo.find_relationships(
            organization_id,
            from_entity_id=concept_id,
            relationship_types=("MAPS_TO",),
            current_only=True,
            as_of=moment,
            limit=200,
        )
        return [
            r
            for r in rels
            if is_valid_at(r.valid_from, r.valid_to, moment)
        ]

    async def explain(
        self, organization_id: UUID, entity_id: UUID
    ) -> dict:
        """¿Por qué Zent cree esto? source + evidence estructurada."""
        entity = await self._repo.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        return {
            "id": str(entity.id),
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "status": entity.status.value,
            "confidence": entity.confidence,
            "authority_level": (
                entity.authority_level.value if entity.authority_level else None
            ),
            "source": entity.source,
            "source_ref": entity.source_ref,
            "evidence": [p.to_dict() for p in entity.evidence],
        }
