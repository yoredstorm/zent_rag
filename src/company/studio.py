# =============================================================================
# Company Intelligence Studio — read models (§1-§22)
# =============================================================================
# Capa de composición de lectura: convierte el Company Graph (5A), los
# candidatos de descubrimiento (5B), la memoria operativa y el ciclo de
# aprendizaje en vistas que una persona puede entender.
#
# Reglas duras:
#   - Todo acotado: ninguna lectura sin límite (max_nodes/max_edges/limit).
#   - La confianza viaja con el dato: cada relación expone status, confidence
#     y provenance. Nunca se presenta DISCOVERED como si fuera CONFIRMED.
#   - Cero métricas decorativas: si un número no sale de una consulta real,
#     no aparece.
#   - Consume el PUERTO (CompanyGraphService), nunca SQL propio del grafo:
#     la migración a Neo4j no debe tocar esta capa.
# =============================================================================
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.company.service import CompanyGraphService
from src.core.domain.company_discovery import (
    CandidateKind,
    GapKind,
    ProcessCandidatePayload,
    ProcessMode,
)
from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
    is_valid_at,
    source_authority_rank,
)
from src.core.ports.company_graph import GraphTraversalLimits
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

#: Tipos de entidad que representan datos.
DATA_TYPES = frozenset({"database", "dataset", "table", "field"})
#: Tipos que representan conocimiento fuente.
KNOWLEDGE_TYPES = frozenset({"knowledge_source", "document"})
#: Tipos que representan automatización.
AUTOMATION_TYPES = frozenset({"workflow", "agent", "tool", "process"})
#: Tipos institucionales.
INSTITUTIONAL_TYPES = frozenset({"person", "role", "team"})
#: Estados que cuentan como confirmados.
CONFIRMED_STATUSES = frozenset({EntityStatus.CONFIRMED, EntityStatus.AUTO_CONFIRMED})

#: Límites por defecto de las vistas.
DEFAULT_MAX_NODES = 25
DEFAULT_MAX_EDGES = 60
MAX_IMPACT_NODES = 200
MAX_PATHS = 6


#: Etiquetas legibles por tipo de entidad (mismas que el portal).
ENTITY_TYPE_LABELS: dict[str, str] = {
    "organization": "organización",
    "domain": "dominio",
    "concept": "concepto",
    "term": "término",
    "process": "proceso",
    "policy": "política",
    "rule": "regla",
    "system": "sistema",
    "service": "servicio",
    "database": "base de datos",
    "dataset": "dataset",
    "table": "tabla",
    "field": "campo",
    "api": "API",
    "knowledge_source": "fuente de conocimiento",
    "document": "documento",
    "agent": "agente",
    "workflow": "workflow",
    "tool": "herramienta",
    "event": "evento",
    "metric": "métrica",
    "kpi": "KPI",
    "person": "persona",
    "role": "rol",
    "team": "equipo",
}


def entity_type_label(entity_type: str | None) -> str:
    if not entity_type:
        return "entidad"
    return ENTITY_TYPE_LABELS.get(entity_type, entity_type)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class RelationshipView:
    """Arista con su confianza y procedencia intactas (§10)."""

    id: str
    relationship_type: str
    direction: str
    from_id: str
    to_id: str
    from_name: str
    to_name: str
    from_type: str
    to_type: str
    status: str
    confidence: float | None
    provenance: str
    source: str
    valid_from: str | None
    valid_to: str | None
    observed: bool

    @property
    def confirmed(self) -> bool:
        return self.status in {status.value for status in CONFIRMED_STATUSES}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "relationship_type": self.relationship_type,
            "direction": self.direction,
            "from": {"id": self.from_id, "name": self.from_name, "type": self.from_type},
            "to": {"id": self.to_id, "name": self.to_name, "type": self.to_type},
            "status": self.status,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "source": self.source,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "observed": self.observed,
            "confirmed": self.confirmed,
        }


def entity_view(entity: CompanyEntity) -> dict:
    """Vista pública de una entidad. Incluye su confianza y vigencia."""
    return {
        "id": str(entity.id),
        "entity_type": entity.entity_type,
        "canonical_name": entity.canonical_name,
        "display_name": entity.display_name or entity.canonical_name,
        "description": entity.description,
        "domain": entity.domain,
        "aliases": list(entity.aliases),
        "status": entity.status.value,
        "confidence": entity.confidence,
        "authority_level": (
            entity.authority_level.value if entity.authority_level else None
        ),
        "source": entity.source,
        "source_ref": entity.source_ref,
        "evidence": [item.to_dict() for item in entity.evidence],
        "metadata": entity.metadata,
        "valid_from": entity.valid_from.isoformat() if entity.valid_from else None,
        "valid_to": entity.valid_to.isoformat() if entity.valid_to else None,
        "first_observed_at": entity.first_observed_at.isoformat(),
        "last_observed_at": entity.last_observed_at.isoformat(),
    }


class CompanyStudioService:
    """Vistas compuestas del Company Graph para la Studio."""

    def __init__(
        self,
        graph: CompanyGraphService,
        *,
        discovery=None,
        memory=None,
        learning=None,
        authority=None,
        run_steps_loader=None,
        document_versions_loader=None,
    ) -> None:
        self._graph = graph
        self._discovery = discovery
        self._memory = memory
        self._learning = learning
        self._authority = authority
        self._load_run_steps = run_steps_loader
        self._load_versions = document_versions_loader

    # ------------------------------------------------------------------
    # §2 Overview
    # ------------------------------------------------------------------
    async def overview(self, organization_id: UUID) -> dict:
        """Conteos reales del grafo. Sin números decorativos."""
        entities = await self._graph.find_entities(
            organization_id, current_only=False, limit=200
        )
        by_type: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        by_domain: dict[str, int] = defaultdict(int)
        for entity in entities:
            by_type[entity.entity_type] += 1
            by_status[entity.status.value] += 1
            by_domain[entity.domain] += 1

        relationships = await self._graph.find_relationships(
            organization_id, current_only=False, limit=200
        )
        rel_by_status: dict[str, int] = defaultdict(int)
        rel_by_type: dict[str, int] = defaultdict(int)
        for relationship in relationships:
            rel_by_status[relationship.status.value] += 1
            rel_by_type[relationship.relationship_type] += 1

        gaps = await self.knowledge_gaps(organization_id, limit=100)
        risks = await self.risks(organization_id, limit=20)
        registry = await self._discovery_stats(organization_id)

        return {
            "entities": {
                "total": len(entities),
                "by_type": dict(sorted(by_type.items())),
                "by_status": dict(sorted(by_status.items())),
                "by_domain": dict(sorted(by_domain.items())),
                "confirmed": sum(
                    count
                    for status, count in by_status.items()
                    if status in {item.value for item in CONFIRMED_STATUSES}
                ),
                "discovered": by_status.get(EntityStatus.DISCOVERED.value, 0),
                "contradicted": by_status.get(EntityStatus.CONTRADICTED.value, 0),
                "stale": by_status.get(EntityStatus.STALE.value, 0),
            },
            "relationships": {
                "total": len(relationships),
                "by_status": dict(sorted(rel_by_status.items())),
                "by_type": dict(sorted(rel_by_type.items())),
                "confirmed": sum(
                    count
                    for status, count in rel_by_status.items()
                    if status in {item.value for item in CONFIRMED_STATUSES}
                ),
            },
            "knowledge_gaps": {
                "total": len(gaps["items"]),
                "by_kind": gaps["by_kind"],
            },
            "potential_risks": len(risks),
            "discovery": registry,
            "coverage": {
                "concepts": by_type.get("concept", 0),
                "processes": by_type.get("process", 0),
                "systems": by_type.get("system", 0),
                "datasets": by_type.get("dataset", 0),
                "tables": by_type.get("table", 0),
                "rules": by_type.get("rule", 0)
                + by_type.get("policy", 0)
                + by_type.get("metric", 0),
                "agents": by_type.get("agent", 0),
                "workflows": by_type.get("workflow", 0),
                "knowledge_sources": sum(
                    count
                    for entity_type, count in by_type.items()
                    if entity_type in KNOWLEDGE_TYPES
                ),
            },
            "as_of": _utcnow().isoformat(),
        }

    # ------------------------------------------------------------------
    # §3/§4 Company Map: exploración por capas
    # ------------------------------------------------------------------
    async def map_layer(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_types: tuple[str, ...] = (),
        statuses: tuple[EntityStatus, ...] = (),
        min_confidence: float | None = None,
        as_of: datetime | None = None,
        max_nodes: int = DEFAULT_MAX_NODES,
        max_edges: int = DEFAULT_MAX_EDGES,
        max_depth: int = 1,
    ) -> dict:
        """Vecindad acotada. Nunca se renderiza el grafo completo (§24)."""
        from src.core.ports.company_graph import RelationshipFilter

        root = await self._graph.get_entity(organization_id, entity_id)
        if root is None:
            raise ValueError("entity not found for this organization")
        limits = GraphTraversalLimits(
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        relationship_filter = RelationshipFilter(
            relationship_types=tuple(relationship_types),
            statuses=tuple(statuses),
            current_only=not statuses,
            min_confidence=min_confidence,
            as_of=as_of,
        )
        neighborhood = await self._graph.neighbors(
            organization_id,
            entity_id,
            direction=direction,
            relationship_filter=relationship_filter,
            limits=limits,
        )
        entities = {root.id: root, **{item.id: item for item in neighborhood.entities}}
        views = self._relationship_views(
            organization_id, neighborhood.relationships, entities, root_id=root.id
        )
        return {
            "root": entity_view(root),
            "nodes": [
                entity_view(item)
                for item in neighborhood.entities[:max_nodes]
            ],
            "edges": [view.to_dict() for view in views[:max_edges]],
            "groups": self._group_neighbors(neighborhood.entities),
            "truncated": neighborhood.truncated,
            "limits": {
                "max_nodes": max_nodes,
                "max_edges": max_edges,
                "max_depth": max_depth,
            },
        }

    # ------------------------------------------------------------------
    # §5 Entity detail
    # ------------------------------------------------------------------
    async def entity_detail(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        max_edges: int = DEFAULT_MAX_EDGES,
        as_of: datetime | None = None,
    ) -> dict:
        entity = await self._graph.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        moment = as_of or _utcnow()

        incoming = await self._graph.find_relationships(
            organization_id,
            to_entity_id=entity_id,
            current_only=as_of is None,
            as_of=as_of,
            limit=max_edges // 2,
        )
        outgoing = await self._graph.find_relationships(
            organization_id,
            from_entity_id=entity_id,
            current_only=as_of is None,
            as_of=as_of,
            limit=max_edges // 2,
        )
        related_entities = await self._collect_entities(
            organization_id,
            [item.from_entity_id for item in incoming]
            + [item.to_entity_id for item in outgoing],
        )
        entities = {entity.id: entity, **related_entities}
        views = self._relationship_views(
            organization_id, [*incoming, *outgoing], entities, root_id=entity.id
        )

        memory = await self._memory_for_entity(organization_id, entity, limit=8)
        gaps = await self._gaps_for_entity(organization_id, entity)
        mappings = await self._mappings_for(organization_id, entity, as_of=moment)
        mapped_concepts = await self._mapped_by_concepts(organization_id, entity)
        authority = await self._authority_for(organization_id, entity)

        return {
            "entity": entity_view(entity),
            "incoming": [v.to_dict() for v in views if v.direction == "incoming"],
            "outgoing": [v.to_dict() for v in views if v.direction == "outgoing"],
            "related": self._group_neighbors(list(related_entities.values())),
            "technical_mappings": mappings,
            "mapped_by_concepts": mapped_concepts,
            "authority": authority,
            "memory": memory,
            "knowledge_gaps": gaps,
            "as_of": moment.isoformat(),
        }

    # ------------------------------------------------------------------
    # §6 Business concept
    # ------------------------------------------------------------------
    async def concept_page(
        self, organization_id: UUID, entity_id: UUID, *, as_of: datetime | None = None
    ) -> dict:
        entity = await self._graph.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        if entity.entity_type not in ("concept", "term", "domain"):
            raise ValueError("entity is not a business concept")
        moment = as_of or _utcnow()
        mappings = await self._mappings_for(organization_id, entity, as_of=moment)
        used_by = await self._usages_for(organization_id, entity, as_of=moment)
        authority = await self._authority_for(organization_id, entity)
        return {
            "concept": entity_view(entity),
            "aliases": list(entity.aliases),
            "domain": entity.domain,
            "technical_mappings": mappings,
            "used_by": used_by,
            "authority": authority,
            "confidence": entity.confidence,
            "as_of": moment.isoformat(),
        }

    # ------------------------------------------------------------------
    # §7/§8 Process intelligence y desviación
    # ------------------------------------------------------------------
    async def process_page(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        max_runs: int = 200,
    ) -> dict:
        entity = await self._graph.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        if entity.entity_type not in ("process", "workflow"):
            raise ValueError("entity is not a process")

        designed, observed = await self._process_candidates(organization_id, entity)
        relationships = await self._process_relationships(organization_id, entity)
        deviation = await self._deviation(organization_id, entity, observed, max_runs)
        memory = await self._memory_for_entity(organization_id, entity, limit=6)
        gaps = await self._gaps_for_entity(organization_id, entity)

        return {
            "process": entity_view(entity),
            "designed": designed,
            "observed": observed,
            "steps": {
                "designed": (designed or {}).get("steps", []),
                "observed": (observed or {}).get("steps", []),
            },
            "deviation": deviation,
            "systems": relationships["systems"],
            "agents": relationships["agents"],
            "rules": relationships["rules"],
            "events": relationships["events"],
            "workflows": relationships["workflows"],
            "memory": memory,
            "knowledge_gaps": gaps,
        }

    # ------------------------------------------------------------------
    # §9/§10/§11 Impact analysis
    # ------------------------------------------------------------------
    async def impact(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        max_depth: int = 3,
        max_nodes: int = MAX_IMPACT_NODES,
        as_of: datetime | None = None,
    ) -> dict:
        root = await self._graph.get_entity(organization_id, entity_id)
        if root is None:
            raise ValueError("entity not found for this organization")
        limits = GraphTraversalLimits(
            max_depth=max_depth, max_nodes=max_nodes, max_edges=max_nodes * 2
        )
        result = await self._graph.impact_analysis(
            organization_id,
            entity_id,
            direction=direction,
            limits=limits,
        )
        entities = {root.id: root, **{item.id: item for item in result.entities}}
        views = self._relationship_views(
            organization_id, list(result.relationships), entities, root_id=root.id
        )
        by_id = {str(view.id): view for view in views}
        paths = self._paths_from(
            root_id=root.id,
            entities=result.entities,
            views=views,
            by_id=by_id,
            direction=direction,
        )
        affected = self._affected_by_type(result.entities)
        return {
            "root": entity_view(root),
            "direct": self._direct_impact(views),
            "indirect": self._indirect_impact(result.entities, root.id, views),
            "affected": affected,
            "paths": paths,
            "edges": [view.to_dict() for view in views],
            "truncated": result.truncated,
            "limits": {
                "max_depth": max_depth,
                "max_nodes": max_nodes,
            },
            "as_of": (as_of or _utcnow()).isoformat(),
        }

    # ------------------------------------------------------------------
    # §13 Source of truth
    # ------------------------------------------------------------------
    async def source_of_truth(self, organization_id: UUID) -> dict:
        """Autoridad por concepto, con conflictos detectados en el Claim Ledger."""
        concepts = await self._graph.find_entities(
            organization_id, entity_type="concept", limit=100
        )
        rules = []
        if self._authority is not None:
            try:
                rules = await self._authority.list_rules(organization_id)
            except Exception as exc:  # noqa: BLE001 - vista nunca rompe
                logger.warning("studio authority failed", error=str(exc)[:150])
        by_concept: dict[str, list] = defaultdict(list)
        for rule in rules:
            by_concept[rule.concept.strip().lower()].append(rule)

        entries: list[dict] = []
        for concept in concepts:
            key = concept.canonical_name.strip().lower()
            concept_rules = by_concept.get(key, [])
            if not concept_rules:
                concept_rules = [
                    rule
                    for name, items in by_concept.items()
                    if name and (name in key or key in name)
                    for rule in items
                ]
            sources = [
                {
                    "source_name": rule.source_name,
                    "source_type": rule.source_type,
                    "authority_level": rule.authority_level.value,
                    "priority": rule.priority,
                    "effective_from": (
                        rule.effective_from.isoformat() if rule.effective_from else None
                    ),
                    "effective_to": (
                        rule.effective_to.isoformat() if rule.effective_to else None
                    ),
                }
                for rule in sorted(
                    concept_rules,
                    key=lambda item: (
                        -source_authority_rank(item.authority_level),
                        item.priority,
                    ),
                )
            ]
            entries.append(
                {
                    "concept_id": str(concept.id),
                    "concept": concept.canonical_name,
                    "domain": concept.domain,
                    "authoritative": [
                        item for item in sources if item["authority_level"] == "authoritative"
                    ],
                    "primary": [
                        item for item in sources if item["authority_level"] == "primary"
                    ],
                    "secondary": [
                        item for item in sources if item["authority_level"] == "secondary"
                    ],
                    "informational": [
                        item
                        for item in sources
                        if item["authority_level"] in ("informational", "untrusted")
                    ],
                    "sources": sources,
                    "has_authority": any(
                        item["authority_level"] == "authoritative" for item in sources
                    ),
                }
            )
        conflicts = await self._conflict_candidates(organization_id, limit=50)
        return {
            "items": entries,
            "conflicts": conflicts,
            "concepts_without_authority": [
                item["concept"] for item in entries if not item["has_authority"]
            ],
        }

    # ------------------------------------------------------------------
    # §14 Knowledge gaps
    # ------------------------------------------------------------------
    async def knowledge_gaps(
        self, organization_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> dict:
        candidates = await self._gap_candidates(
            organization_id, limit=limit, offset=offset
        )
        items = [
            {
                "id": str(candidate.id),
                "gap_kind": candidate.payload.get("gap_kind"),
                "subject": candidate.payload.get("subject"),
                "detail": candidate.payload.get("detail"),
                "frequency": candidate.payload.get("frequency"),
                "observed_runs": candidate.payload.get("observed_runs"),
                "stage": candidate.stage.value,
                "confidence": candidate.confidence,
                "source_kind": candidate.source_kind.value,
                "source_ref": candidate.source_ref,
                "evidence": [item.to_dict() for item in candidate.evidence],
                "first_observed_at": candidate.first_observed_at.isoformat(),
                "last_observed_at": candidate.last_observed_at.isoformat(),
                "origin": "discovery",
            }
            for candidate in candidates
        ]
        items.extend(await self._derived_gaps(organization_id))
        by_kind: dict[str, int] = defaultdict(int)
        for item in items:
            by_kind[str(item.get("gap_kind") or "unknown")] += 1
        return {
            "items": items,
            "by_kind": dict(sorted(by_kind.items())),
            "limit": limit,
            "offset": offset,
        }

    # ------------------------------------------------------------------
    # §15/§16 Company changes
    # ------------------------------------------------------------------
    async def changes(
        self,
        organization_id: UUID,
        *,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """Timeline real: entidades y candidatos con su marca temporal."""
        moment = since or (_utcnow() - timedelta(days=90))
        entities = await self._graph.find_entities(
            organization_id, current_only=False, limit=200
        )
        events: list[dict] = []
        for entity in entities:
            if entity.first_observed_at >= moment:
                events.append(
                    {
                        "kind": "entity_discovered",
                        "at": entity.first_observed_at.isoformat(),
                        "entity_id": str(entity.id),
                        "title": entity.canonical_name,
                        "entity_type": entity.entity_type,
                        "status": entity.status.value,
                        "detail": entity.source,
                    }
                )
            if entity.updated_at >= moment and entity.updated_at > entity.first_observed_at:
                events.append(
                    {
                        "kind": "entity_updated",
                        "at": entity.updated_at.isoformat(),
                        "entity_id": str(entity.id),
                        "title": entity.canonical_name,
                        "entity_type": entity.entity_type,
                        "status": entity.status.value,
                        "detail": entity.domain,
                    }
                )
            if entity.status is EntityStatus.DEPRECATED:
                events.append(
                    {
                        "kind": "entity_deprecated",
                        "at": entity.updated_at.isoformat(),
                        "entity_id": str(entity.id),
                        "title": entity.canonical_name,
                        "entity_type": entity.entity_type,
                        "status": entity.status.value,
                        "detail": entity.source,
                    }
                )
        if self._discovery is not None:
            candidates = await self._discovery.find_candidates(
                organization_id, limit=200, offset=offset
            )
            for candidate in candidates:
                at = candidate.first_observed_at
                if at < moment:
                    at = candidate.last_observed_at
                    if at < moment:
                        continue
                events.append(
                    {
                        "kind": f"candidate_{candidate.kind.value}",
                        "at": at.isoformat(),
                        "candidate_id": str(candidate.id),
                        "title": candidate.title,
                        "entity_type": candidate.kind.value,
                        "status": candidate.stage.value,
                        "detail": candidate.summary,
                        "confidence": candidate.confidence,
                    }
                )
        events.sort(key=lambda item: item["at"], reverse=True)
        return {
            "items": events[offset : offset + limit],
            "since": moment.isoformat(),
            "limit": limit,
            "offset": offset,
        }

    async def entity_changes(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> dict:
        """§16 ¿Qué cambió? Compara la entidad y sus relaciones contra una fecha."""
        entity = await self._graph.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        moment = as_of or (_utcnow() - timedelta(days=365))

        then_relationships = await self._graph.find_relationships(
            organization_id,
            as_of=moment,
            current_only=False,
            limit=200,
        )
        now_relationships = await self._graph.find_relationships(
            organization_id, current_only=False, limit=200
        )
        then_ids = {
            str(item.id)
            for item in then_relationships
            if item.from_entity_id == entity_id or item.to_entity_id == entity_id
        }
        now_ids = {
            str(item.id)
            for item in now_relationships
            if item.from_entity_id == entity_id or item.to_entity_id == entity_id
        }
        related = await self._collect_entities(
            organization_id,
            [
                item.to_entity_id if item.from_entity_id == entity_id else item.from_entity_id
                for item in now_relationships
                if str(item.id) in now_ids or str(item.id) in then_ids
            ],
        )
        names = {str(item.id): item.canonical_name for item in related.values()}
        history = await self._graph.history(organization_id, entity_id, limit=100)

        changed = []
        for item in [*then_relationships, *now_relationships]:
            if item.from_entity_id != entity_id and item.to_entity_id != entity_id:
                continue
            other_id = (
                item.to_entity_id if item.from_entity_id == entity_id else item.from_entity_id
            )
            changed.append(
                {
                    "relationship_type": item.relationship_type,
                    "other": names.get(str(other_id), str(other_id)),
                    "status": item.status.value,
                    "confidence": item.confidence,
                    "valid_from": item.valid_from.isoformat() if item.valid_from else None,
                    "valid_to": item.valid_to.isoformat() if item.valid_to else None,
                    "in_previous": str(item.id) in then_ids,
                    "in_current": str(item.id) in now_ids,
                }
            )
        added = [item for item in changed if item["in_current"] and not item["in_previous"]]
        removed = [item for item in changed if item["in_previous"] and not item["in_current"]]
        return {
            "entity": entity_view(entity),
            "compared_to": moment.isoformat(),
            "valid_at_previous": is_valid_at(
                entity.valid_from, entity.valid_to, moment
            ),
            "relationships_added": added,
            "relationships_removed": removed,
            "relationships_current": [
                item for item in changed if item["in_current"]
            ][:50],
            "history": [
                {
                    "id": str(item.id),
                    "relationship_type": item.relationship_type,
                    "status": item.status.value,
                    "created_at": item.created_at.isoformat(),
                    "source": item.source,
                }
                for item in history
            ],
        }

    # ------------------------------------------------------------------
    # §17 Institutional knowledge
    # ------------------------------------------------------------------
    async def institutional(
        self, organization_id: UUID, *, limit: int = 100
    ) -> dict:
        entities = await self._graph.find_entities(
            organization_id, limit=200, current_only=False
        )
        institutional = [
            entity for entity in entities if entity.entity_type in INSTITUTIONAL_TYPES
        ]
        owners: dict[str, list[dict]] = defaultdict(list)
        if institutional:
            relationships = await self._graph.find_relationships(
                organization_id,
                relationship_types=("OWNS", "GOVERNED_BY"),
                current_only=True,
                limit=200,
            )
            owner_ids = {item.from_entity_id for item in relationships}
            owned_ids = {item.to_entity_id for item in relationships}
            names = {
                str(entity.id): entity
                for entity in entities
                if entity.id in owner_ids or entity.id in owned_ids
            }
            for relationship in relationships:
                owner = names.get(str(relationship.from_entity_id))
                owned = names.get(str(relationship.to_entity_id))
                if owner is None or owned is None:
                    continue
                owners[str(owned.id)].append(
                    {
                        "owner_id": str(owner.id),
                        "owner": owner.canonical_name,
                        "owner_type": owner.entity_type,
                        "relationship_type": relationship.relationship_type,
                        "status": relationship.status.value,
                        "confidence": relationship.confidence,
                    }
                )
        processes = [
            entity
            for entity in entities
            if entity.entity_type in ("process", "workflow")
        ]
        return {
            "people": [
                entity_view(item)
                for item in institutional
                if item.entity_type == "person"
            ][:limit],
            "roles": [
                entity_view(item)
                for item in institutional
                if item.entity_type == "role"
            ][:limit],
            "teams": [
                entity_view(item)
                for item in institutional
                if item.entity_type == "team"
            ][:limit],
            "process_ownership": [
                {
                    "process_id": str(item.id),
                    "process": item.canonical_name,
                    "owners": owners.get(str(item.id), []),
                }
                for item in processes[:limit]
            ],
            "processes_without_owner": [
                item.canonical_name
                for item in processes
                if not owners.get(str(item.id))
            ],
        }

    # ------------------------------------------------------------------
    # §18 Single points of failure
    # ------------------------------------------------------------------
    async def risks(self, organization_id: UUID, *, limit: int = 50) -> list[dict]:
        """Candidatos a riesgo. Se marcan como POTENCIALES, nunca definitivos."""
        entities = await self._graph.find_entities(
            organization_id, current_only=True, limit=200
        )
        by_id = {entity.id: entity for entity in entities}
        relationships = await self._graph.find_relationships(
            organization_id, current_only=True, limit=400
        )
        risks: list[dict] = []

        dependency = defaultdict(set)
        dependents = defaultdict(set)
        for relationship in relationships:
            if relationship.relationship_type in ("USES", "DEPENDS_ON", "READS_FROM"):
                dependency[relationship.from_entity_id].add(relationship.to_entity_id)
                dependents[relationship.to_entity_id].add(relationship.from_entity_id)

        for entity in entities:
            targets = dependency.get(entity.id, set())
            if len(targets) == 1:
                target = by_id.get(next(iter(targets)))
                if target is None:
                    continue
                risks.append(
                    {
                        "risk_kind": "single_dependency",
                        "level": "potential",
                        "entity_id": str(entity.id),
                        "entity": entity.canonical_name,
                        "entity_type": entity.entity_type,
                        "detail": (
                            f"{entity.canonical_name} depends on a single "
                            f"{target.entity_type}: {target.canonical_name}"
                        ),
                        "related_id": str(target.id),
                        "related": target.canonical_name,
                    }
                )
            reverse = dependents.get(entity.id, set())
            if entity.entity_type in ("system", "api", "database") and len(reverse) >= 3:
                risks.append(
                    {
                        "risk_kind": "shared_dependency",
                        "level": "potential",
                        "entity_id": str(entity.id),
                        "entity": entity.canonical_name,
                        "entity_type": entity.entity_type,
                        "detail": (
                            f"{len(reverse)} entities depend on "
                            f"{entity.canonical_name}; if it fails, all are affected"
                        ),
                        "related_id": None,
                        "related": None,
                    }
                )
        for entity in entities:
            if entity.entity_type in ("concept", "rule", "policy"):
                authority = await self._authority_for(organization_id, entity)
                if authority and len(authority) == 1:
                    risks.append(
                        {
                            "risk_kind": "single_authority",
                            "level": "potential",
                            "entity_id": str(entity.id),
                            "entity": entity.canonical_name,
                            "entity_type": entity.entity_type,
                            "detail": (
                                f"{entity.canonical_name} has a single source of "
                                f"truth: {authority[0]['source_name']}"
                            ),
                            "related_id": None,
                            "related": authority[0]["source_name"],
                        }
                    )
        return risks[:limit]

    # ------------------------------------------------------------------
    # §19 Knowledge health
    # ------------------------------------------------------------------
    async def knowledge_health(self, organization_id: UUID) -> dict:
        """Salud del grafo, no del documento: completitud, autoridad, conflictos."""
        entities = await self._graph.find_entities(
            organization_id, current_only=False, limit=200
        )
        relationships = await self._graph.find_relationships(
            organization_id, current_only=False, limit=400
        )
        total = max(1, len(entities))
        confirmed = sum(1 for item in entities if item.status in CONFIRMED_STATUSES)
        discovered = sum(
            1 for item in entities if item.status is EntityStatus.DISCOVERED
        )
        contradicted = sum(
            1 for item in entities if item.status is EntityStatus.CONTRADICTED
        )
        stale = sum(1 for item in entities if item.status is EntityStatus.STALE)
        deprecated = sum(
            1 for item in entities if item.status is EntityStatus.DEPRECATED
        )
        stale_relationships = sum(
            1
            for item in relationships
            if item.status is EntityStatus.STALE
            or (
                item.valid_to is not None
                and item.valid_to < _utcnow()
            )
        )
        concepts = [item for item in entities if item.entity_type == "concept"]
        with_authority = 0
        for concept in concepts:
            if await self._authority_for(organization_id, concept):
                with_authority += 1
        gaps = await self.knowledge_gaps(organization_id, limit=100)
        processes = [
            item
            for item in entities
            if item.entity_type in ("process", "workflow")
        ]
        undocumented = sum(
            1
            for gap in gaps["items"]
            if gap.get("gap_kind") == GapKind.UNDOCUMENTED_STEP.value
        )
        institutional = await self.institutional(organization_id)
        components = [
            {
                "key": "graph_confirmation",
                "label": "Entidades confirmadas",
                "score": round(100.0 * confirmed / total, 2),
                "detail": f"{confirmed} de {len(entities)}",
            },
            {
                "key": "authority_coverage",
                "label": "Conceptos con fuente autoritativa",
                "score": round(100.0 * with_authority / max(1, len(concepts)), 2),
                "detail": f"{with_authority} de {len(concepts)}",
            },
            {
                "key": "conflict_rate",
                "label": "Sin contradicciones",
                "score": round(100.0 * (total - contradicted) / total, 2),
                "detail": f"{contradicted} contradichas",
            },
            {
                "key": "freshness",
                "label": "Sin obsoletos",
                "score": round(100.0 * (total - stale) / total, 2),
                "detail": f"{stale} obsoletas, {stale_relationships} relaciones vencidas",
            },
            {
                "key": "documentation",
                "label": "Procesos documentados",
                "score": round(
                    100.0
                    * max(0, len(processes) - undocumented)
                    / max(1, len(processes)),
                    2,
                ),
                "detail": f"{undocumented} huecos de documentación",
            },
            {
                "key": "ownership",
                "label": "Procesos con responsable",
                "score": round(
                    100.0
                    * max(
                        0,
                        len(processes) - len(institutional["processes_without_owner"]),
                    )
                    / max(1, len(processes)),
                    2,
                ),
                "detail": f"{len(institutional['processes_without_owner'])} sin responsable",
            },
        ]
        measured = [item["score"] for item in components]
        return {
            "components": components,
            "aggregate": round(sum(measured) / len(measured), 2) if measured else 0.0,
            "counts": {
                "entities": len(entities),
                "confirmed": confirmed,
                "discovered": discovered,
                "contradicted": contradicted,
                "stale": stale,
                "deprecated": deprecated,
                "relationships": len(relationships),
                "knowledge_gaps": gaps["total"] if "total" in gaps else len(gaps["items"]),
            },
        }

    # ------------------------------------------------------------------
    # §20/§21 Memory y conversaciones por entidad
    # ------------------------------------------------------------------
    async def entity_memory(
        self, organization_id: UUID, entity_id: UUID, *, limit: int = 20
    ) -> dict:
        entity = await self._graph.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        records = await self._memory_for_entity(organization_id, entity, limit=limit)
        findings = await self._findings_for(organization_id, entity)
        return {
            "entity_id": str(entity.id),
            "entity": entity.canonical_name,
            "patterns": records,
            "findings": findings,
        }

    async def entity_conversations(
        self, organization_id: UUID, entity_id: UUID, *, limit: int = 20
    ) -> dict:
        """Conversaciones donde la entidad fue relevante, vía memoria y runs."""
        entity = await self._graph.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found for this organization")
        conversations: dict[str, dict] = {}
        if self._memory is not None:
            try:
                records = await self._memory_records(
                    organization_id, entity, limit=limit
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("studio conversations failed", error=str(exc)[:150])
                records = []
            for record in records:
                if record.created_from_conversation_id is None:
                    continue
                key = str(record.created_from_conversation_id)
                conversations.setdefault(
                    key,
                    {
                        "conversation_id": key,
                        "memory_id": str(record.id),
                        "title": record.title,
                        "pattern_key": record.pattern_key,
                        "created_at": record.created_at.isoformat(),
                    },
                )
        return {
            "entity_id": str(entity.id),
            "entity": entity.canonical_name,
            "items": list(conversations.values())[:limit],
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    async def _collect_entities(
        self, organization_id: UUID, entity_ids: list[UUID]
    ) -> dict[UUID, CompanyEntity]:
        unique = {item for item in entity_ids if item is not None}
        entities: dict[UUID, CompanyEntity] = {}
        for entity_id in list(unique)[:200]:
            entity = await self._graph.get_entity(organization_id, entity_id)
            if entity is not None:
                entities[entity.id] = entity
        return entities

    def _relationship_views(
        self,
        organization_id: UUID,
        relationships: list[CompanyRelationship],
        entities: dict[UUID, CompanyEntity],
        *,
        root_id: UUID,
    ) -> list[RelationshipView]:
        views: list[RelationshipView] = []
        for relationship in relationships:
            if relationship.organization_id != organization_id:
                continue
            source = entities.get(relationship.from_entity_id)
            target = entities.get(relationship.to_entity_id)
            if source is None or target is None:
                continue
            if relationship.organization_id != source.organization_id:
                continue
            direction = (
                "outgoing"
                if relationship.from_entity_id == root_id
                else "incoming"
            )
            views.append(
                RelationshipView(
                    id=str(relationship.id),
                    relationship_type=relationship.relationship_type,
                    direction=direction,
                    from_id=str(source.id),
                    to_id=str(target.id),
                    from_name=source.canonical_name,
                    to_name=target.canonical_name,
                    from_type=source.entity_type,
                    to_type=target.entity_type,
                    status=relationship.status.value,
                    confidence=relationship.confidence,
                    provenance=relationship.source or relationship.metadata.get("source", ""),
                    source=relationship.source_ref,
                    valid_from=(
                        relationship.valid_from.isoformat()
                        if relationship.valid_from
                        else None
                    ),
                    valid_to=(
                        relationship.valid_to.isoformat()
                        if relationship.valid_to
                        else None
                    ),
                    observed=bool(relationship.metadata.get("observed")),
                )
            )
        return views

    @staticmethod
    def _group_neighbors(entities: list[CompanyEntity]) -> dict:
        groups: dict[str, list[dict]] = defaultdict(list)
        for entity in entities:
            group = "other"
            if entity.entity_type in DATA_TYPES:
                group = "data"
            elif entity.entity_type in KNOWLEDGE_TYPES:
                group = "knowledge"
            elif entity.entity_type in AUTOMATION_TYPES:
                group = "automation"
            elif entity.entity_type in INSTITUTIONAL_TYPES:
                group = "institutional"
            elif entity.entity_type in ("concept", "term", "domain"):
                group = "concepts"
            elif entity.entity_type in ("rule", "policy", "metric", "kpi"):
                group = "rules"
            elif entity.entity_type in ("system", "service", "api"):
                group = "systems"
            groups[group].append(entity_view(entity))
        return {key: value[:50] for key, value in sorted(groups.items())}

    def _direct_impact(self, views: list[RelationshipView]) -> list[dict]:
        return [
            {
                "kind": "direct",
                "relationship_type": view.relationship_type,
                "from": view.from_name,
                "to": view.to_name,
                "status": view.status,
                "confidence": view.confidence,
                "certainty": "will" if view.confirmed else "may",
            }
            for view in views
        ][:50]

    @staticmethod
    def _indirect_impact(
        entities: list[CompanyEntity], root_id: UUID, views: list[RelationshipView]
    ) -> list[dict]:
        direct_ids = set()
        for view in views:
            direct_ids.add(view.from_id)
            direct_ids.add(view.to_id)
        return [
            {
                "id": str(entity.id),
                "name": entity.canonical_name,
                "entity_type": entity.entity_type,
                "status": entity.status.value,
                "confidence": entity.confidence,
            }
            for entity in entities
            if entity.id != root_id and str(entity.id) not in direct_ids
        ][:100]

    @staticmethod
    def _affected_by_type(entities: list[CompanyEntity]) -> dict:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for entity in entities:
            bucket = "other"
            if entity.entity_type in DATA_TYPES:
                bucket = "data"
            elif entity.entity_type in KNOWLEDGE_TYPES:
                bucket = "knowledge"
            elif entity.entity_type in ("workflow",):
                bucket = "workflows"
            elif entity.entity_type in ("agent", "tool"):
                bucket = "agents"
            elif entity.entity_type in ("process",):
                bucket = "processes"
            elif entity.entity_type in ("system", "service", "api"):
                bucket = "systems"
            elif entity.entity_type in ("rule", "policy"):
                bucket = "rules"
            grouped[bucket].append(
                {
                    "id": str(entity.id),
                    "name": entity.canonical_name,
                    "entity_type": entity.entity_type,
                    "status": entity.status.value,
                }
            )
        return {key: value[:50] for key, value in sorted(grouped.items())}

    def _paths_from(
        self,
        *,
        root_id: UUID,
        entities: tuple[CompanyEntity, ...],
        views: list[RelationshipView],
        by_id: dict[str, RelationshipView],
        direction: str,
    ) -> list[dict]:
        """Caminos cortos desde la raíz, con la confianza del eslabón más débil.

        Se calcula sobre la vecindad ya acotada: no hay traversal nuevo.
        """
        adjacency: dict[str, list[tuple[str, RelationshipView]]] = defaultdict(list)
        for view in views:
            if direction in ("both", "out"):
                adjacency[view.from_id].append((view.to_id, view))
            if direction in ("both", "in"):
                adjacency[view.to_id].append((view.from_id, view))
        names = {str(entity.id): entity.canonical_name for entity in entities}
        names[str(root_id)] = names.get(str(root_id), "")

        paths: list[dict] = []
        seen_targets: set[str] = set()
        frontier: list[tuple[str, list[RelationshipView]]] = [(str(root_id), [])]
        depth = 0
        while frontier and depth < 3 and len(paths) < MAX_PATHS:
            next_frontier: list[tuple[str, list[RelationshipView]]] = []
            for node, trail in frontier:
                for neighbor, view in adjacency.get(node, []):
                    if any(item.id == view.id for item in trail):
                        continue
                    new_trail = [*trail, view]
                    if neighbor in seen_targets or neighbor == str(root_id):
                        continue
                    seen_targets.add(neighbor)
                    paths.append(
                        {
                            "target_id": neighbor,
                            "target": names.get(neighbor, neighbor),
                            "hops": len(new_trail),
                            "certainty": self._path_certainty(new_trail),
                            "explanation": [
                                {
                                    "from": item.from_name,
                                    "relationship_type": item.relationship_type,
                                    "to": item.to_name,
                                    "status": item.status,
                                }
                                for item in new_trail
                            ],
                        }
                    )
                    if len(paths) >= MAX_PATHS:
                        break
                    next_frontier.append((neighbor, new_trail))
            frontier = next_frontier
            depth += 1
        return paths

    @staticmethod
    def _path_certainty(trail: list[RelationshipView]) -> str:
        """§11: 'may' si algún eslabón no está confirmado."""
        return "will" if all(item.confirmed for item in trail) else "may"

    async def _mappings_for(
        self, organization_id: UUID, entity: CompanyEntity, *, as_of: datetime
    ) -> list[dict]:
        try:
            relationships = await self._graph.concept_mappings(
                organization_id, entity.id, as_of=as_of
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio mappings failed", error=str(exc)[:150])
            return []
        targets = await self._collect_entities(
            organization_id, [item.to_entity_id for item in relationships]
        )
        return [
            {
                "id": str(relationship.id),
                "target_id": str(relationship.to_entity_id),
                "target": (
                    targets[relationship.to_entity_id].canonical_name
                    if relationship.to_entity_id in targets
                    else ""
                ),
                "target_type": (
                    targets[relationship.to_entity_id].entity_type
                    if relationship.to_entity_id in targets
                    else ""
                ),
                "values": list(relationship.metadata.get("values") or ())[:8],
                "predicate": relationship.metadata.get("predicate", ""),
                "status": relationship.status.value,
                "confidence": relationship.confidence,
            }
            for relationship in relationships
        ]

    async def _mapped_by_concepts(
        self, organization_id: UUID, entity: CompanyEntity
    ) -> list[dict]:
        """Conceptos de negocio que mapean HACIA esta entidad técnica.

        Un campo no "se mapea a" conceptos: los conceptos se mapean a él. Sin
        esto, abrir un campo no muestra de qué concepto de negocio forma parte.
        """
        if entity.entity_type not in DATA_TYPES and entity.entity_type not in (
            "api",
            "service",
        ):
            return []
        relationships = await self._graph.find_relationships(
            organization_id,
            to_entity_id=entity.id,
            relationship_types=("MAPS_TO",),
            current_only=True,
            limit=50,
        )
        sources = await self._collect_entities(
            organization_id, [item.from_entity_id for item in relationships]
        )
        return [
            {
                "id": str(relationship.id),
                "concept_id": str(relationship.from_entity_id),
                "concept": (
                    sources[relationship.from_entity_id].canonical_name
                    if relationship.from_entity_id in sources
                    else ""
                ),
                "values": list(relationship.metadata.get("values") or ())[:8],
                "predicate": relationship.metadata.get("predicate", ""),
                "status": relationship.status.value,
                "confidence": relationship.confidence,
            }
            for relationship in relationships
        ]

    async def _usages_for(
        self, organization_id: UUID, entity: CompanyEntity, *, as_of: datetime
    ) -> dict:
        """Quién usa el concepto: agentes, workflows, procesos, queries."""
        relationships = await self._graph.find_relationships(
            organization_id,
            to_entity_id=entity.id,
            current_only=as_of is None,
            as_of=as_of,
            limit=100,
        )
        sources = await self._collect_entities(
            organization_id, [item.from_entity_id for item in relationships]
        )
        grouped: dict[str, list[dict]] = defaultdict(list)
        for relationship in relationships:
            source = sources.get(relationship.from_entity_id)
            if source is None:
                continue
            bucket = (
                "agents"
                if source.entity_type == "agent"
                else "workflows"
                if source.entity_type in ("workflow", "tool")
                else "processes"
                if source.entity_type == "process"
                else "other"
            )
            grouped[bucket].append(
                {
                    "id": str(source.id),
                    "name": source.canonical_name,
                    "relationship_type": relationship.relationship_type,
                    "status": relationship.status.value,
                }
            )
        return dict(grouped)

    async def _authority_for(
        self, organization_id: UUID, entity: CompanyEntity
    ) -> list[dict]:
        if self._authority is None:
            return []
        try:
            rules = await self._authority.list_rules(organization_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio authority failed", error=str(exc)[:150])
            return []
        key = entity.canonical_name.strip().lower()
        matched = [
            rule
            for rule in rules
            if rule.concept.strip().lower() == key
            or (rule.concept and rule.concept.strip().lower() in key)
        ]
        return [
            {
                "source_name": rule.source_name,
                "source_type": rule.source_type,
                "authority_level": rule.authority_level.value,
                "priority": rule.priority,
                "domain": rule.domain,
            }
            for rule in sorted(
                matched,
                key=lambda item: (-source_authority_rank(item.authority_level), item.priority),
            )
        ][:8]

    async def _memory_for_entity(
        self, organization_id: UUID, entity: CompanyEntity, *, limit: int
    ) -> list[dict]:
        """Memoria relacionada con la entidad.

        El store de memoria indexa por patrón de comportamiento, no por entidad:
        se consulta primero por nombre (camino SQL) y se completa con las
        memorias recientes cuyo patrón, título o descripción mencionan la
        entidad o sus aliases. Todo acotado.
        """
        records = await self._memory_records(organization_id, entity, limit=limit)
        return [record.to_public_dict() for record in records[:limit]]

    async def _memory_records(
        self, organization_id: UUID, entity: CompanyEntity, *, limit: int
    ) -> list:
        if self._memory is None:
            return []
        needles = {
            entity.canonical_name.strip().lower(),
            entity.display_name.strip().lower(),
            *{alias.strip().lower() for alias in entity.aliases},
        }
        needles.discard("")
        found: dict[str, object] = {}
        for needle in list(needles)[:4]:
            try:
                rows = await self._memory.list_memories(
                    organization_id, pattern=needle, limit=limit
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("studio memory failed", error=str(exc)[:150])
                rows = []
            for record in rows:
                found[str(record.id)] = record
        if len(found) >= limit:
            return list(found.values())[:limit]
        try:
            recent = await self._memory.list_memories(
                organization_id, limit=min(100, max(limit * 4, 20))
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio memory scan failed", error=str(exc)[:150])
            recent = []
        for record in recent:
            haystack = " ".join(
                [
                    str(getattr(record, "pattern_key", "")),
                    str(getattr(record, "pattern_signature", "")),
                    str(getattr(record, "title", "")),
                    str(getattr(record, "description", "")),
                ]
            ).lower()
            if any(needle in haystack for needle in needles):
                found.setdefault(str(record.id), record)
        return list(found.values())[:limit]

    async def _findings_for(
        self, organization_id: UUID, entity: CompanyEntity
    ) -> list[dict]:
        if self._learning is None:
            return []
        try:
            findings = await self._learning.list_findings(
                organization_id, limit=50
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio findings failed", error=str(exc)[:150])
            return []
        key = entity.canonical_name.strip().lower()
        return [
            finding.to_public_dict()
            for finding in findings
            if key in (finding.observed or "").lower()
            or key in (finding.pattern_key or "").lower()
            or any(key in str(item).lower() for item in finding.affected or [])
        ][:10]

    async def _process_candidates(
        self, organization_id: UUID, entity: CompanyEntity
    ) -> tuple[dict | None, dict | None]:
        if self._discovery is None:
            return None, None
        try:
            candidates = await self._discovery.find_candidates(
                organization_id, kinds=(CandidateKind.PROCESS,), limit=100
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio process candidates failed", error=str(exc)[:150])
            return None, None
        key = entity.canonical_name.strip().lower()
        designed = observed = None
        for candidate in candidates:
            payload = ProcessCandidatePayload.from_dict(candidate.payload)
            if payload.name.strip().lower() != key:
                continue
            entry = {
                "candidate_id": str(candidate.id),
                "name": payload.name,
                "mode": payload.mode.value,
                "steps": [step.to_dict() for step in payload.steps],
                "runs_observed": payload.runs_observed,
                "workflow_id": payload.workflow_id,
                "stage": candidate.stage.value,
                "confidence": candidate.confidence,
                "source_kind": candidate.source_kind.value,
            }
            if payload.mode is ProcessMode.DESIGNED and designed is None:
                designed = entry
            elif payload.mode is ProcessMode.OBSERVED and observed is None:
                observed = entry
        # El grafo también guarda los pasos observados en la metadata.
        if observed is None and entity.metadata.get("steps"):
            observed = {
                "candidate_id": None,
                "name": entity.canonical_name,
                "mode": ProcessMode.OBSERVED.value,
                "steps": list(entity.metadata.get("steps") or ()),
                "runs_observed": int(entity.metadata.get("runs_observed") or 0),
                "workflow_id": entity.metadata.get("workflow_id", ""),
                "stage": entity.status.value,
                "confidence": entity.confidence,
                "source_kind": entity.source,
            }
        return designed, observed

    async def _process_relationships(
        self, organization_id: UUID, entity: CompanyEntity
    ) -> dict:
        """Sistemas, agentes, reglas, eventos y workflows del proceso.

        Mira en AMBAS direcciones: el proceso usa sistemas (saliente) y a la
        vez es automatizado por workflows o gobernado por reglas (entrante).
        """
        outgoing = await self._graph.find_relationships(
            organization_id,
            from_entity_id=entity.id,
            current_only=True,
            limit=100,
        )
        incoming = await self._graph.find_relationships(
            organization_id,
            to_entity_id=entity.id,
            current_only=True,
            limit=100,
        )
        neighbors = await self._collect_entities(
            organization_id,
            [item.to_entity_id for item in outgoing]
            + [item.from_entity_id for item in incoming],
        )
        buckets: dict[str, list[dict]] = defaultdict(list)
        seen: set[str] = set()
        for relationship, other_id, direction in [
            *[(item, item.to_entity_id, "outgoing") for item in outgoing],
            *[(item, item.from_entity_id, "incoming") for item in incoming],
        ]:
            target = neighbors.get(other_id)
            if target is None:
                continue
            key = f"{relationship.id}:{direction}"
            if key in seen:
                continue
            seen.add(key)
            bucket = (
                "systems"
                if target.entity_type in ("system", "service", "database", "api")
                else "agents"
                if target.entity_type in ("agent", "tool")
                else "rules"
                if target.entity_type in ("rule", "policy")
                else "events"
                if target.entity_type == "event"
                else "workflows"
                if target.entity_type == "workflow"
                else "other"
            )
            buckets[bucket].append(
                {
                    "id": str(target.id),
                    "name": target.canonical_name,
                    "entity_type": target.entity_type,
                    "relationship_type": relationship.relationship_type,
                    "direction": direction,
                    "status": relationship.status.value,
                    "confidence": relationship.confidence,
                }
            )
        return {
            "systems": buckets.get("systems", []),
            "agents": buckets.get("agents", []),
            "rules": buckets.get("rules", []),
            "events": buckets.get("events", []),
            "workflows": buckets.get("workflows", []),
        }

    async def _deviation(
        self,
        organization_id: UUID,
        entity: CompanyEntity,
        observed: dict | None,
        max_runs: int,
    ) -> dict:
        """§8: detecta rework real en las secuencias observadas.

        Compara cada corrida contra la secuencia más frecuente y reporta la
        proporción de corridas con repetición. No afirma causalidad.
        """
        workflow_id = (observed or {}).get("workflow_id") or entity.metadata.get(
            "workflow_id", ""
        )
        if not workflow_id or self._load_run_steps is None:
            return {"available": False, "reason": "no_observed_runs"}
        try:
            rows = await self._load_run_steps(organization_id, max_runs * 5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio run steps failed", error=str(exc)[:150])
            return {"available": False, "reason": "loader_failed"}
        runs: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            if str(row.get("workflow_id")) != str(workflow_id):
                continue
            runs[str(row.get("run_id"))].append(str(row.get("node_id")))
        if not runs:
            return {"available": False, "reason": "no_runs_for_workflow"}

        sequences = [tuple(nodes) for nodes in runs.values()]
        counts: dict[tuple[str, ...], int] = defaultdict(int)
        for sequence in sequences:
            counts[sequence] += 1
        canonical = max(counts.items(), key=lambda item: item[1])[0]

        rework_runs = [sequence for sequence in sequences if _has_rework(sequence)]
        frequency = len(rework_runs) / max(1, len(sequences))
        examples = []
        for sequence in rework_runs[:3]:
            examples.append(
                {
                    "sequence": list(sequence),
                    "repeated": [node for node in sequence if sequence.count(node) > 1],
                }
            )
        return {
            "available": True,
            "runs": len(sequences),
            "canonical_sequence": list(canonical),
            "rework_runs": len(rework_runs),
            "rework_frequency": round(frequency, 4),
            "examples": examples,
            "note": "rework detected from observed order; no causation claimed",
        }

    async def _gap_candidates(self, organization_id: UUID, *, limit: int, offset: int = 0):
        if self._discovery is None:
            return []
        try:
            return await self._discovery.find_candidates(
                organization_id,
                kinds=(CandidateKind.KNOWLEDGE_GAP,),
                limit=limit,
                offset=offset,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio gaps failed", error=str(exc)[:150])
            return []

    async def _conflict_candidates(self, organization_id: UUID, *, limit: int) -> list[dict]:
        candidates = await self._gap_candidates(organization_id, limit=limit)
        return [
            {
                "id": str(candidate.id),
                "subject": candidate.payload.get("subject"),
                "detail": candidate.payload.get("detail"),
                "evidence": [item.to_dict() for item in candidate.evidence],
                "stage": candidate.stage.value,
            }
            for candidate in candidates
            if candidate.payload.get("gap_kind")
            == GapKind.CONTRADICTORY_DEFINITION.value
        ]

    async def _gaps_for_entity(
        self, organization_id: UUID, entity: CompanyEntity
    ) -> list[dict]:
        candidates = await self._gap_candidates(organization_id, limit=100)
        key = entity.canonical_name.strip().lower()
        return [
            {
                "id": str(candidate.id),
                "gap_kind": candidate.payload.get("gap_kind"),
                "subject": candidate.payload.get("subject"),
                "detail": candidate.payload.get("detail"),
                "stage": candidate.stage.value,
                "confidence": candidate.confidence,
            }
            for candidate in candidates
            if key in str(candidate.payload.get("subject") or "").lower()
        ][:10]

    async def _derived_gaps(self, organization_id: UUID) -> list[dict]:
        """Huecos derivados del grafo: sin autoridad, sin responsable, vencidas."""
        gaps: list[dict] = []
        truth = await self.source_of_truth(organization_id)
        for name in truth["concepts_without_authority"][:20]:
            gaps.append(
                {
                    "gap_kind": GapKind.NO_AUTHORITATIVE_DEFINITION.value,
                    "subject": name,
                    "detail": f"{name} has no authoritative source configured",
                    "stage": "discovered",
                    "confidence": None,
                    "origin": "graph",
                }
            )
        institutional = await self.institutional(organization_id)
        for name in institutional["processes_without_owner"][:20]:
            gaps.append(
                {
                    "gap_kind": "missing_process_owner",
                    "subject": name,
                    "detail": f"{name} has no owner relationship",
                    "stage": "discovered",
                    "confidence": None,
                    "origin": "graph",
                }
            )
        stale = await self._graph.find_relationships(
            organization_id, statuses=(EntityStatus.STALE,), current_only=False, limit=50
        )
        entities = await self._collect_entities(
            organization_id,
            [item.from_entity_id for item in stale] + [item.to_entity_id for item in stale],
        )
        for relationship in stale[:20]:
            source = entities.get(relationship.from_entity_id)
            target = entities.get(relationship.to_entity_id)
            if source is None or target is None:
                continue
            gaps.append(
                {
                    "gap_kind": "stale_relationship",
                    "subject": f"{source.canonical_name} {relationship.relationship_type} {target.canonical_name}",
                    "detail": "relationship marked stale and still in the graph",
                    "stage": relationship.status.value,
                    "confidence": relationship.confidence,
                    "origin": "graph",
                }
            )
        return gaps

    async def _discovery_stats(self, organization_id: UUID) -> dict:
        if self._discovery is None:
            return {"available": False}
        try:
            stats = await self._discovery.stats(organization_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("studio discovery stats failed", error=str(exc)[:150])
            return {"available": False}
        return {"available": True, **stats}

    @staticmethod
    def _count_gap_kinds(candidates) -> dict:
        counts: dict[str, int] = defaultdict(int)
        for candidate in candidates:
            kind = candidate.payload.get("gap_kind") or "unknown"
            counts[str(kind)] += 1
        return dict(sorted(counts.items()))


def _has_rework(sequence: tuple[str, ...]) -> bool:
    """Repetición en la secuencia observada (A B C B C D)."""
    if len(sequence) < 3:
        return False
    counts: dict[str, int] = defaultdict(int)
    for node in sequence:
        counts[node] += 1
    repeated = [node for node, count in counts.items() if count > 1]
    if not repeated:
        return False
    # Repetición consecutiva o reaparición no adyacente cuenta como retrabajo.
    return True


__all__ = [
    "AUTOMATION_TYPES",
    "CompanyStudioService",
    "CONFIRMED_STATUSES",
    "DATA_TYPES",
    "INSTITUTIONAL_TYPES",
    "KNOWLEDGE_TYPES",
    "RelationshipView",
    "entity_view",
]
