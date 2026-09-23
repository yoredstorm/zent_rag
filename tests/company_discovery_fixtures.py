# =============================================================================
# Fixtures de Company Discovery — grafo en memoria y filas falsas
# =============================================================================
# Permiten testear el motor, la resolución y el compilador de contexto sin
# base de datos, de forma determinista. Los escenarios reflejan lo que el
# descubrimiento produce en una compañía real (conceptos, mappings, procesos,
# authority y versiones temporales).
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from src.core.domain.company_discovery import (
    CandidateKind,
    CandidateSupport,
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoverySourceKind,
    DiscoveryStage,
    EntityCandidatePayload,
    EntityRef,
    MappingCandidatePayload,
    ProcessCandidatePayload,
    ProcessMode,
    ProcessStep,
    RelationshipCandidatePayload,
)
from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
    SourceAuthorityLevel,
)
from src.core.ports.company_graph import (
    GraphNeighborhood,
    GraphPath,
    GraphTraversalLimits,
    ImpactResult,
    RelationshipFilter,
)

ORG = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Grafo en memoria (mismo contrato que CompanyGraphService)
# ---------------------------------------------------------------------------


class FakeGraphService:
    """Servicio de grafo en memoria: mismos métodos que usa el compilador."""

    def __init__(
        self,
        entities: list[CompanyEntity] | None = None,
        relationships: list[CompanyRelationship] | None = None,
    ) -> None:
        self.entities: dict[UUID, CompanyEntity] = {
            entity.id: entity for entity in entities or []
        }
        self.relationships: list[CompanyRelationship] = list(relationships or [])

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
        moment = as_of or NOW
        results = []
        for entity in self.entities.values():
            if entity.organization_id != organization_id:
                continue
            if entity_type and entity.entity_type != entity_type:
                continue
            if current_only and entity.status in (
                EntityStatus.DEPRECATED,
                EntityStatus.REJECTED,
            ):
                continue
            if as_of is not None:
                if entity.valid_from and moment < entity.valid_from:
                    continue
                if entity.valid_to and moment >= entity.valid_to:
                    continue
            results.append(entity)
        results.sort(key=lambda item: item.canonical_name)
        return results[offset : offset + limit]

    async def get_entity(
        self, organization_id: UUID, entity_id: UUID
    ) -> CompanyEntity | None:
        entity = self.entities.get(entity_id)
        if entity is None or entity.organization_id != organization_id:
            return None
        return entity

    async def concept_mappings(
        self, organization_id: UUID, concept_id: UUID, *, as_of: datetime | None = None
    ) -> list[CompanyRelationship]:
        moment = as_of or NOW
        results = []
        for relationship in self.relationships:
            if relationship.organization_id != organization_id:
                continue
            if relationship.from_entity_id != concept_id:
                continue
            if relationship.relationship_type != "MAPS_TO":
                continue
            if relationship.valid_from and moment < relationship.valid_from:
                continue
            if relationship.valid_to and moment >= relationship.valid_to:
                continue
            results.append(relationship)
        return results

    async def neighbors(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter: RelationshipFilter | None = None,
        limits: GraphTraversalLimits | None = None,
    ) -> GraphNeighborhood:
        limits = limits or GraphTraversalLimits()
        relations = [
            relationship
            for relationship in self.relationships
            if relationship.organization_id == organization_id
            and (
                relationship.from_entity_id == entity_id
                or relationship.to_entity_id == entity_id
            )
        ][: limits.max_edges]
        neighbor_ids = {item.from_entity_id for item in relations} | {
            item.to_entity_id for item in relations
        }
        neighbor_ids.discard(entity_id)
        entities = [
            self.entities[item] for item in sorted(neighbor_ids) if item in self.entities
        ][: limits.max_nodes]
        return GraphNeighborhood(
            entities=tuple(entities), relationships=tuple(relations)
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
        """BFS acotado, mismo contrato que el adapter Postgres."""
        limits = limits or GraphTraversalLimits()
        visited: dict[UUID, CompanyEntity] = {}
        relations: list[CompanyRelationship] = []
        frontier = [entity_id]
        seen: set[UUID] = {entity_id}
        for _depth in range(limits.max_depth):
            next_frontier: list[UUID] = []
            for node in frontier:
                hood = await self.neighbors(
                    organization_id,
                    node,
                    direction=direction,
                    relationship_filter=relationship_filter,
                    limits=limits,
                )
                for relationship in hood.relationships:
                    if relationship not in relations:
                        relations.append(relationship)
                for entity in hood.entities:
                    if entity.id in seen:
                        continue
                    seen.add(entity.id)
                    visited[entity.id] = entity
                    next_frontier.append(entity.id)
                    if len(visited) >= limits.max_nodes:
                        break
                if len(visited) >= limits.max_nodes:
                    break
            frontier = next_frontier
            if not frontier or len(visited) >= limits.max_nodes:
                break
        return GraphNeighborhood(
            entities=tuple(visited.values())[: limits.max_nodes],
            relationships=tuple(relations)[: limits.max_edges],
            truncated=len(visited) >= limits.max_nodes,
        )

    async def find_path(self, *args, **kwargs) -> GraphPath | None:
        return None

    async def impact_analysis(self, *args, **kwargs) -> ImpactResult:
        return ImpactResult()

    async def upsert_entity(self, entity: CompanyEntity) -> CompanyEntity:
        self.entities[entity.id] = entity
        return entity

    async def explain(self, organization_id: UUID, entity_id: UUID) -> dict:
        entity = await self.get_entity(organization_id, entity_id)
        if entity is None:
            raise ValueError("entity not found")
        return {"id": str(entity.id), "canonical_name": entity.canonical_name}


class FakeAuthorityService:
    """Authority configurable en memoria (mismo contrato que el servicio real)."""

    def __init__(self, rules: list | None = None) -> None:
        self.rules = list(rules or [])

    async def list_rules(self, organization_id: UUID, domain: str | None = None):
        return [
            rule
            for rule in self.rules
            if rule.organization_id == organization_id
            and (domain is None or rule.domain == domain)
        ]

    async def resolve_authority(
        self, organization_id: UUID, *, domain: str, concept: str, source_name: str, as_of=None
    ):
        for rule in self.rules:
            if (
                rule.organization_id == organization_id
                and rule.domain == domain
                and rule.concept == concept
                and rule.source_name == source_name
            ):
                return rule.authority_level
        return SourceAuthorityLevel.INFORMATIONAL

    async def upsert_rule(self, rule):
        self.rules.append(rule)
        return rule


class FakeMemoryRecall:
    """Recall de memoria en memoria."""

    def __init__(self, records: list | None = None) -> None:
        self.records = list(records or [])
        self.queries: list = []

    async def recall(self, query) -> list:
        self.queries.append(query)
        return self.records


# ---------------------------------------------------------------------------
# Grafo demo (escenarios golden)
# ---------------------------------------------------------------------------


def build_demo_graph() -> FakeGraphService:
    """Compañía demo: conceptos, mappings, procesos, systems y versiones."""
    graph = FakeGraphService()

    def entity(
        entity_type: str,
        name: str,
        *,
        aliases: tuple[str, ...] = (),
        description: str = "",
        domain: str = "business",
        confidence: float = 0.8,
        authority: SourceAuthorityLevel | None = None,
        metadata: dict | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        status: EntityStatus = EntityStatus.SUPPORTED,
    ) -> CompanyEntity:
        item = CompanyEntity(
            organization_id=ORG,
            entity_type=entity_type,
            canonical_name=name,
            display_name=name,
            description=description,
            domain=domain,
            aliases=aliases,
            status=status,
            confidence=confidence,
            authority_level=authority,
            metadata=metadata or {},
            valid_from=valid_from,
            valid_to=valid_to,
            last_observed_at=NOW - timedelta(days=1),
        )
        graph.entities[item.id] = item
        return item

    def relate(
        from_entity: CompanyEntity,
        to_entity: CompanyEntity,
        relationship_type: str,
        *,
        metadata: dict | None = None,
        status: EntityStatus = EntityStatus.CONFIRMED,
    ) -> CompanyRelationship:
        relationship = CompanyRelationship(
            organization_id=ORG,
            from_entity_id=from_entity.id,
            to_entity_id=to_entity.id,
            relationship_type=relationship_type,
            status=status,
            confidence=0.9,
            metadata=metadata or {},
        )
        graph.relationships.append(relationship)
        return relationship

    pending = entity(
        "concept",
        "Pending Transaction",
        aliases=("pending", "pendiente", "sin procesar"),
        description="Transacción aún no procesada por el sistema",
    )
    pending_field = entity(
        "field",
        "A1672STO0",
        domain="data",
        metadata={"technical_identifiers": ["PXSAUDIT.A1672.A1672STO0"]},
    )
    ticket = entity("concept", "Ticket", aliases=("tickets", "documento"))
    ticket_table = entity("table", "PXSAUDIT.A1672", domain="data")
    system = entity("system", "PXSAUDIT", domain="data", confidence=0.9)
    reconciliation = entity(
        "process",
        "Reconciliation",
        domain="operations",
        metadata={"mode": "observed"},
    )
    workflow = entity("workflow", "invoice-wf", domain="automation")
    api = entity("api", "/transactions", domain="data")
    policy_v1 = entity(
        "policy",
        "Refund Policy v1",
        domain="business",
        aliases=("política de reembolso v1", "politica de reembolso v1"),
        valid_from=_utc(2024, 1, 1),
        valid_to=_utc(2025, 6, 30),
    )
    policy_v2 = entity(
        "policy",
        "Refund Policy v2",
        domain="business",
        aliases=("política de reembolso v2", "politica de reembolso v2"),
        valid_from=_utc(2025, 7, 1),
    )

    relate(
        pending,
        pending_field,
        "MAPS_TO",
        metadata={"values": ["0", ""], "predicate": "A1672STO0 IN ('0', '')"},
    )
    relate(ticket, ticket_table, "MAPS_TO", metadata={"values": ["A1672"]})
    relate(ticket_table, pending_field, "CONTAINS")
    relate(reconciliation, system, "USES")
    relate(system, ticket_table, "CONTAINS")
    relate(workflow, api, "USES")
    relate(policy_v1, policy_v2, "SUPERSEDED_BY")
    return graph


def demo_authority_rules(org: UUID = ORG) -> list:
    from src.company.service import AuthorityRule

    return [
        AuthorityRule(
            organization_id=org,
            domain="data",
            concept="ticket",
            source_name="PXSAUDIT",
            source_type="database",
            authority_level=SourceAuthorityLevel.AUTHORITATIVE,
            priority=1,
        ),
        AuthorityRule(
            organization_id=org,
            domain="business",
            concept="refund policy v2",
            source_name="official-docs",
            source_type="document",
            authority_level=SourceAuthorityLevel.PRIMARY,
            priority=1,
        ),
    ]


# ---------------------------------------------------------------------------
# Filas falsas para las fuentes (mismas claves que los loaders Postgres)
# ---------------------------------------------------------------------------


def fake_schema_rows() -> tuple[list[dict], list[dict]]:
    tables = [
        {
            "id": "t-1",
            "source_id": "s-1",
            "schema_name": "PXSAUDIT",
            "table_name": "A1672",
            "table_comment": "Transaction audit",
            "source_name": "prod-db",
            "engine": "postgres",
        }
    ]
    columns = [
        {
            "id": "c-1",
            "table_id": "t-1",
            "column_name": "A1672STO0",
            "data_type": "character",
            "is_primary_key": False,
            "column_comment": "status",
        },
        {
            "id": "c-2",
            "table_id": "t-1",
            "column_name": "A1672DOC",
            "data_type": "character",
            "is_primary_key": True,
            "column_comment": "document type",
        },
    ]
    return tables, columns


def fake_sql_rows() -> list[dict]:
    """El ejemplo del spec: "pending" y A1672STO0 IN ('0','').

    Incluye también un término frecuente SIN mapeo técnico (revenue neto) para
    que el descubrimiento produzca un Knowledge Gap real.
    """
    rows = []
    for index, actor in enumerate(("u-1", "u-2", "u-1", "u-3")):
        rows.append(
            {
                "id": f"sql-{index}",
                "question": "¿cuántas transacciones pending hay?",
                "generated_sql": (
                    "SELECT COUNT(*) FROM PXSAUDIT.A1672 "
                    "WHERE A1672STO0 IN ('0','')"
                ),
                "tables": ["PXSAUDIT.A1672"],
                "user_id": actor,
                "status": "success",
            }
        )
    for index, actor in enumerate(("u-1", "u-2", "u-3")):
        rows.append(
            {
                "id": f"sql-rev-{index}",
                "question": "¿cuál es el revenue neto del período?",
                "generated_sql": "SELECT SUM(1)",
                "tables": ["PXSAUDIT.A1672"],
                "user_id": actor,
                "status": "success",
            }
        )
    return rows


def fake_run_step_rows() -> list[dict]:
    """Secuencia observada: Load -> Validate -> Match -> Reconcile."""
    steps = ["load", "validate", "match", "reconcile", "notify"]
    rows = []
    for run_index in range(4):
        workflow_id = "wf-1" if run_index < 3 else "wf-2"
        run_id = f"run-{run_index}"
        for position, node in enumerate(steps):
            # 'notify' sólo aparece en algunas corridas del wf-1.
            if node == "notify" and run_index != 0:
                continue
            rows.append(
                {
                    "run_id": run_id,
                    "step_index": position,
                    "node_id": node,
                    "node_type": "llm",
                    "status": "succeeded",
                    "workflow_id": workflow_id,
                    "run_status": "succeeded",
                    "workflow_name": "invoice-wf" if workflow_id == "wf-1" else "other-wf",
                }
            )
    return rows


def fake_document_rows() -> tuple[list[dict], list[dict]]:
    documents = [
        {"id": "d-1", "title": "Operations Runbook", "document_type": "runbook"},
        {"id": "d-2", "title": "Billing Policy", "document_type": "policy"},
    ]
    blocks = [
        {
            "id": "b-1",
            "document_id": "d-1",
            "node_type": "block",
            "text": (
                "Pending Transaction means a transaction that has not been "
                "processed by the audit system yet."
            ),
            "order_index": 0,
        },
        {
            "id": "b-2",
            "document_id": "d-1",
            "node_type": "block",
            "text": (
                "Pending Transaction se define como una transacción sin procesar "
                "que espera validación."
            ),
            "order_index": 1,
        },
        {
            "id": "b-3",
            "document_id": "d-2",
            "node_type": "block",
            "text": (
                "The status lives in PXSAUDIT.A1672.A1672STO0 with value 0 meaning "
                "pending."
            ),
            "order_index": 0,
        },
        {
            "id": "b-4",
            "document_id": "d-2",
            "node_type": "block",
            "text": "Refund Policy effective from 2025-07-01 applies to tickets.",
            "order_index": 1,
        },
    ]
    return documents, blocks


def make_candidate(
    *,
    kind: CandidateKind = CandidateKind.ENTITY,
    payload: dict,
    organization_id: UUID = ORG,
    stage: DiscoveryStage = DiscoveryStage.DISCOVERED,
    support: CandidateSupport | None = None,
    source_kind: DiscoverySourceKind = DiscoverySourceKind.DATABASE_SCHEMA,
) -> DiscoveryCandidate:
    from src.core.domain.company_discovery import candidate_key

    return DiscoveryCandidate(
        organization_id=organization_id,
        kind=kind,
        natural_key=candidate_key(kind, payload),
        title=str(payload.get("canonical_name") or payload.get("name") or "candidate"),
        payload=payload,
        source_kind=source_kind,
        stage=stage,
        support=support or CandidateSupport(observations=1, structural=True),
    )


__all__ = [
    "FakeAuthorityService",
    "FakeGraphService",
    "FakeMemoryRecall",
    "ORG",
    "build_demo_graph",
    "demo_authority_rules",
    "EntityCandidatePayload",
    "EntityRef",
    "MappingCandidatePayload",
    "ProcessCandidatePayload",
    "ProcessMode",
    "ProcessStep",
    "RelationshipCandidatePayload",
    "DiscoveryEvidence",
    "make_candidate",
    "fake_document_rows",
    "fake_run_step_rows",
    "fake_schema_rows",
    "fake_sql_rows",
    "uuid4",
]
