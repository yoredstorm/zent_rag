# =============================================================================
# Ports — CompanyGraphRepository (GRAPH-FIRST, STORAGE-AGNOSTIC)
# =============================================================================
# Puerto de dominio independiente del almacenamiento. El dominio y el
# servicio solo conocen esta interfaz: nunca SQLAlchemy específico, nunca
# Neo4j. organization_id es OBLIGATORIO en toda operación.
#
# Backends:
#   - PostgresCompanyGraphRepository (implementado, adapter inicial)
#   - Neo4jCompanyGraphRepository (stub futuro: agregar sin tocar capas
#     superiores, solo registrando la implementación en el wiring)
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
)


@dataclass(frozen=True, kw_only=True)
class GraphTraversalLimits:
    """Guardarraíles de traversal. Evitan consultas sin límites."""

    max_depth: int = 4
    max_nodes: int = 200
    max_edges: int = 500

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= 10:
            raise ValueError("max_depth must be within [1, 10]")
        if not 1 <= self.max_nodes <= 5000:
            raise ValueError("max_nodes must be within [1, 5000]")
        if not 1 <= self.max_edges <= 10000:
            raise ValueError("max_edges must be within [1, 10000]")


@dataclass(frozen=True, kw_only=True)
class RelationshipFilter:
    """Filtros de arista para neighbors/traverse/path/impact."""

    relationship_types: tuple[str, ...] = ()
    statuses: tuple[EntityStatus, ...] = ()
    current_only: bool = True
    min_confidence: float | None = None
    as_of: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class GraphNeighborhood:
    """Resultado de neighbors()/traverse()."""

    entities: tuple[CompanyEntity, ...] = ()
    relationships: tuple[CompanyRelationship, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, kw_only=True)
class GraphPath:
    """Un camino dirigido entre dos entidades."""

    entities: tuple[CompanyEntity, ...] = ()
    relationships: tuple[CompanyRelationship, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ImpactResult:
    """Grafo verificable de dependencias afectadas. Sin conclusiones LLM:
    el servicio devuelve hechos navegación, el reasoning los interpreta."""

    root: CompanyEntity | None = None
    entities: tuple[CompanyEntity, ...] = ()
    relationships: tuple[CompanyRelationship, ...] = ()
    by_type: dict = field(default_factory=dict)
    truncated: bool = False


class CompanyGraphRepository(ABC):
    """Puerto del grafo de compañía. Todo scoped por organization_id."""

    # -- Lectura ------------------------------------------------------
    @abstractmethod
    async def get_entity(
        self, organization_id: UUID, entity_id: UUID
    ) -> CompanyEntity | None:
        """Entidad o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def find_entities(
        self,
        organization_id: UUID,
        *,
        entity_type: str | None = None,
        query: str | None = None,
        statuses: tuple[EntityStatus, ...] = (),
        current_only: bool = True,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyEntity]:
        """Búsqueda paginada de entidades (scoped, con filtros)."""
        ...

    @abstractmethod
    async def find_relationships(
        self,
        organization_id: UUID,
        *,
        from_entity_id: UUID | None = None,
        to_entity_id: UUID | None = None,
        relationship_types: tuple[str, ...] = (),
        statuses: tuple[EntityStatus, ...] = (),
        current_only: bool = True,
        as_of: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyRelationship]:
        """Búsqueda paginada de relaciones (scoped, con filtros)."""
        ...

    @abstractmethod
    async def neighbors(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        """Vecinos a un salto (one-hop)."""
        ...

    @abstractmethod
    async def traverse(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        """Traversal multi-hop limitado (BFS con max_depth/max_nodes)."""
        ...

    @abstractmethod
    async def find_path(
        self,
        organization_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
        *,
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphPath | None:
        """Camino dirigido entre dos entidades (BFS). None si no existe."""
        ...

    @abstractmethod
    async def impact_analysis(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> ImpactResult:
        """Dependencias directas e indirectas agrupadas por tipo."""
        ...

    # -- Escritura ----------------------------------------------------
    @abstractmethod
    async def upsert_entity(self, entity: CompanyEntity) -> CompanyEntity:
        """Inserta o actualiza por (org, tipo, nombre). Idempotente."""
        ...

    @abstractmethod
    async def propose_relationship(
        self, relationship: CompanyRelationship
    ) -> CompanyRelationship:
        """Propone una relación en DISCOVERED. Valida tenant de extremos."""
        ...

    @abstractmethod
    async def confirm_relationship(
        self,
        organization_id: UUID,
        relationship_id: UUID,
        *,
        status: EntityStatus,
    ) -> CompanyRelationship:
        """Transiciona estado validando la ley de transiciones."""
        ...

    @abstractmethod
    async def deprecate_relationship(
        self, organization_id: UUID, relationship_id: UUID
    ) -> CompanyRelationship:
        """Marca DEPRECATED (las vistas current la excluyen)."""
        ...

    @abstractmethod
    async def entity_history(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CompanyRelationship]:
        """Historial de relaciones de la entidad (incluye deprecated)."""
        ...


class Neo4jCompanyGraphRepository(CompanyGraphRepository):
    """Stub de readiness futura. Implementar contra el driver de Neo4j sin
    modificar dominio, servicio ni API: basta con heredar y registrar en el
    wiring. Cada método levanta NotImplementedError hasta entonces."""

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "Neo4jCompanyGraphRepository is a future adapter: "
            "PostgresCompanyGraphRepository is the current backend. "
            "Implement this class against the Neo4j driver when the "
            "dependency is justified; no upper layer needs changes."
        )

    async def get_entity(self, organization_id: UUID, entity_id: UUID):  # type: ignore[override]
        raise NotImplementedError

    async def find_entities(self, organization_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def find_relationships(self, organization_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def neighbors(self, organization_id: UUID, entity_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def traverse(self, organization_id: UUID, entity_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def find_path(self, organization_id: UUID, from_entity_id: UUID, to_entity_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def impact_analysis(self, organization_id: UUID, entity_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def upsert_entity(self, entity: CompanyEntity):  # type: ignore[override]
        raise NotImplementedError

    async def propose_relationship(self, relationship: CompanyRelationship):  # type: ignore[override]
        raise NotImplementedError

    async def confirm_relationship(self, organization_id: UUID, relationship_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError

    async def deprecate_relationship(self, organization_id: UUID, relationship_id: UUID):  # type: ignore[override]
        raise NotImplementedError

    async def entity_history(self, organization_id: UUID, entity_id: UUID, **kwargs):  # type: ignore[override]
        raise NotImplementedError
