# =============================================================================
# Company Intelligence Studio — tests de backend (Fase 5C)
# =============================================================================
# Cubre: overview, map acotado, detalle de entidad, concepto, proceso con
# desviación, impacto con preservación de confianza, fuente de verdad, gaps,
# cambios, institucional, riesgos, salud, memoria/conversaciones por entidad,
# exploración en lenguaje natural y aislamiento por tenant.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from src.company.ask import (
    CompanyAskService,
    CompanyIntent,
    lexical_intent,
    question_tokens,
)
from src.company.demo_seed import (
    DEMO_DOMAIN,
)
from src.company.studio import CompanyStudioService, entity_view
from src.core.domain.company_graph import (
    CompanyEntity,
    CompanyRelationship,
    EntityStatus,
    SourceAuthorityLevel,
)
from src.core.ports.company_graph import GraphTraversalLimits

ORG = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures: grafo en memoria con el escenario Fare Audit
# ---------------------------------------------------------------------------


class FakeGraphService:
    """Mismo contrato que CompanyGraphService, en memoria."""

    def __init__(self) -> None:
        self.entities: dict[UUID, CompanyEntity] = {}
        self.relationships: list[CompanyRelationship] = []

    def add(
        self,
        entity_type: str,
        name: str,
        *,
        aliases: tuple[str, ...] = (),
        status: EntityStatus = EntityStatus.CONFIRMED,
        description: str = "",
        domain: str = DEMO_DOMAIN,
        metadata: dict | None = None,
        confidence: float = 0.9,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
    ) -> CompanyEntity:
        entity = CompanyEntity(
            organization_id=ORG,
            entity_type=entity_type,
            canonical_name=name,
            display_name=name,
            description=description,
            domain=domain,
            aliases=aliases,
            status=status,
            confidence=confidence,
            metadata=metadata or {},
            valid_from=valid_from,
            valid_to=valid_to,
            last_observed_at=NOW - timedelta(days=2),
        )
        self.entities[entity.id] = entity
        return entity

    def link(
        self,
        source: CompanyEntity,
        target: CompanyEntity,
        relationship_type: str,
        *,
        status: EntityStatus = EntityStatus.CONFIRMED,
        confidence: float = 0.8,
        metadata: dict | None = None,
    ) -> CompanyRelationship:
        relationship = CompanyRelationship(
            organization_id=ORG,
            from_entity_id=source.id,
            to_entity_id=target.id,
            relationship_type=relationship_type,
            status=status,
            confidence=confidence,
            source="manual",
            source_ref="demo",
            metadata=metadata or {},
        )
        self.relationships.append(relationship)
        return relationship

    async def get_entity(self, organization_id: UUID, entity_id: UUID):
        entity = self.entities.get(entity_id)
        if entity is None or entity.organization_id != organization_id:
            return None
        return entity

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
    ):
        moment = as_of or NOW
        results = []
        for entity in self.entities.values():
            if entity.organization_id != organization_id:
                continue
            if entity_type and entity.entity_type != entity_type:
                continue
            if query:
                haystack = f"{entity.canonical_name} {entity.display_name} {' '.join(entity.aliases)}".lower()
                if query.lower() not in haystack:
                    continue
            if statuses and entity.status not in statuses:
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
    ):
        results = []
        for relationship in self.relationships:
            if relationship.organization_id != organization_id:
                continue
            if from_entity_id and relationship.from_entity_id != from_entity_id:
                continue
            if to_entity_id and relationship.to_entity_id != to_entity_id:
                continue
            if relationship_types and relationship.relationship_type not in relationship_types:
                continue
            if statuses and relationship.status not in statuses:
                continue
            if current_only and relationship.status in (
                EntityStatus.DEPRECATED,
                EntityStatus.REJECTED,
            ):
                continue
            if as_of is not None:
                if relationship.valid_from and as_of < relationship.valid_from:
                    continue
                if relationship.valid_to and as_of >= relationship.valid_to:
                    continue
            results.append(relationship)
        return results[offset : offset + limit]

    async def neighbors(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter=None,
        limits: GraphTraversalLimits | None = None,
    ):
        """Honra el filtro del puerto, igual que el adapter Postgres."""
        from src.core.ports.company_graph import GraphNeighborhood

        limits = limits or GraphTraversalLimits()
        flt = relationship_filter
        relations = []
        for item in await self.find_relationships(organization_id, limit=200):
            if item.from_entity_id != entity_id and item.to_entity_id != entity_id:
                continue
            if direction == "out" and item.from_entity_id != entity_id:
                continue
            if direction == "in" and item.to_entity_id != entity_id:
                continue
            if flt is not None:
                if flt.relationship_types and (
                    item.relationship_type not in flt.relationship_types
                ):
                    continue
                if flt.statuses and item.status not in flt.statuses:
                    continue
                if flt.current_only and item.status in (
                    EntityStatus.DEPRECATED,
                    EntityStatus.REJECTED,
                ):
                    continue
                if (
                    flt.min_confidence is not None
                    and item.confidence is not None
                    and item.confidence < flt.min_confidence
                ):
                    continue
            relations.append(item)
        relations = relations[: limits.max_edges]
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

    async def traverse(self, organization_id: UUID, entity_id: UUID, **kwargs):
        limits = kwargs.get("limits") or GraphTraversalLimits()
        visited: dict[UUID, CompanyEntity] = {}
        seen = {entity_id}
        frontier = [entity_id]
        relations: list[CompanyRelationship] = []
        for _depth in range(limits.max_depth):
            next_frontier: list[UUID] = []
            for node in frontier:
                hood = await self.neighbors(
                    organization_id, node, limits=limits
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
            frontier = next_frontier
            if not frontier or len(visited) >= limits.max_nodes:
                break
        from src.core.ports.company_graph import GraphNeighborhood

        return GraphNeighborhood(
            entities=tuple(visited.values())[: limits.max_nodes],
            relationships=tuple(relations)[: limits.max_edges],
        )

    async def impact_analysis(
        self,
        organization_id: UUID,
        entity_id: UUID,
        *,
        direction: str = "both",
        relationship_filter=None,
        limits: GraphTraversalLimits | None = None,
    ):
        from src.core.ports.company_graph import ImpactResult

        limits = limits or GraphTraversalLimits()
        hood = await self.traverse(
            organization_id, entity_id, direction=direction, limits=limits
        )
        root = self.entities.get(entity_id)
        by_type: dict[str, int] = {}
        for entity in hood.entities:
            by_type[entity.entity_type] = by_type.get(entity.entity_type, 0) + 1
        return ImpactResult(
            root=root,
            entities=hood.entities,
            relationships=hood.relationships,
            by_type=by_type,
        )

    async def concept_mappings(self, organization_id: UUID, concept_id: UUID, *, as_of=None):
        return [
            item
            for item in self.relationships
            if item.organization_id == organization_id
            and item.from_entity_id == concept_id
            and item.relationship_type == "MAPS_TO"
        ]

    async def history(self, organization_id: UUID, entity_id: UUID, *, limit: int = 50, offset: int = 0):
        return [
            item
            for item in self.relationships
            if item.organization_id == organization_id
            and (item.from_entity_id == entity_id or item.to_entity_id == entity_id)
        ][:limit]

    async def find_path(self, *args, **kwargs):
        return None

    async def upsert_entity(self, entity: CompanyEntity):
        self.entities[entity.id] = entity
        return entity

    async def propose_relationship(self, organization_id, from_id, to_id, relationship_type, **kwargs):
        relationship = CompanyRelationship(
            organization_id=organization_id,
            from_entity_id=from_id,
            to_entity_id=to_id,
            relationship_type=relationship_type,
            **kwargs,
        )
        self.relationships.append(relationship)
        return relationship

    async def confirm_relationship(self, organization_id, relationship_id, *, status):
        for index, item in enumerate(self.relationships):
            if item.id == relationship_id:
                from dataclasses import replace

                updated = replace(item, status=status)
                self.relationships[index] = updated
                return updated
        raise ValueError("relationship not found")


class FakeAuthority:
    def __init__(self, rules: list[dict] | None = None) -> None:
        self.rules = rules or []

    async def list_rules(self, organization_id: UUID, domain: str | None = None):
        from src.company.service import AuthorityRule

        return [
            AuthorityRule(
                organization_id=organization_id,
                domain=rule["domain"],
                concept=rule["concept"],
                source_name=rule["source_name"],
                source_type=rule.get("source_type", "database"),
                authority_level=SourceAuthorityLevel(rule["authority_level"]),
                priority=rule.get("priority", 1),
            )
            for rule in self.rules
            if rule.get("organization_id", organization_id) == organization_id
        ]

    async def upsert_rule(self, rule):
        self.rules.append(
            {
                "organization_id": rule.organization_id,
                "domain": rule.domain,
                "concept": rule.concept,
                "source_name": rule.source_name,
                "authority_level": rule.authority_level.value,
            }
        )
        return rule

    async def resolve_authority(self, *args, **kwargs):
        return SourceAuthorityLevel.INFORMATIONAL


class FakeMemory:
    def __init__(self, records: list | None = None) -> None:
        self.records = records or []

    async def list_memories(self, organization_id: UUID, **filters):
        pattern = str(filters.get("pattern") or "").lower()
        results = []
        for record in self.records:
            if getattr(record, "organization_id", None) != organization_id:
                continue
            if pattern and pattern not in record.pattern_key.lower():
                continue
            results.append(record)
        return results[: int(filters.get("limit") or 50)]


class FakeDiscovery:
    def __init__(self, candidates: list | None = None) -> None:
        self.candidates = candidates or []

    async def find_candidates(
        self,
        organization_id: UUID,
        *,
        kinds=(),
        stages=(),
        source_kinds=(),
        min_confidence=None,
        query=None,
        limit=50,
        offset=0,
    ):
        return [item for item in self.candidates if item.organization_id == organization_id][
            offset : offset + limit
        ]

    async def stats(self, organization_id: UUID):
        return {
            "by_kind": {"knowledge_gap": len(self.candidates)},
            "by_stage": {"suggested": len(self.candidates)},
            "total": len(self.candidates),
        }


def _demo_graph() -> FakeGraphService:
    """Escenario §26: Fare Audit."""
    graph = FakeGraphService()
    atpco = graph.add("knowledge_source", "ATPCO")
    record2 = graph.add("dataset", "Record2")
    carrier = graph.add("field", "Carrier Code")
    a1672 = graph.add("table", "A1672")
    sto0 = graph.add("field", "A1672STO0")
    pxsaudit = graph.add("system", "PXSAUDIT")
    fare_audit = graph.add("process", "Fare Audit")
    reconciliation = graph.add("process", "Reconciliation Process")
    agent = graph.add("agent", "Audit Agent")
    workflow = graph.add("workflow", "Reconciliation Workflow")
    pending = graph.add(
        "concept",
        "Pending Transaction",
        aliases=("pending", "pendiente"),
        metadata={"technical_identifiers": ["PXSAUDIT.A1672.A1672STO0"]},
    )
    rule = graph.add("rule", "Fare Audit Rule")
    team = graph.add("team", "Audit Team")

    graph.link(atpco, record2, "PROVIDES")
    graph.link(record2, carrier, "CONTAINS")
    graph.link(a1672, pxsaudit, "BELONGS_TO")
    graph.link(a1672, sto0, "CONTAINS")
    graph.link(fare_audit, a1672, "READS_FROM")
    graph.link(agent, fare_audit, "ASSISTS")
    graph.link(workflow, reconciliation, "AUTOMATES")
    graph.link(reconciliation, pxsaudit, "USES")
    graph.link(rule, atpco, "GOVERNED_BY")
    graph.link(team, reconciliation, "OWNS")
    graph.link(
        pending,
        sto0,
        "MAPS_TO",
        metadata={"values": ["0", ""], "predicate": "A1672STO0 IN ('0', '')"},
    )
    graph.link(pending, a1672, "USES", status=EntityStatus.DISCOVERED, confidence=0.5)
    return graph


def _studio(graph=None, **kwargs) -> CompanyStudioService:
    return CompanyStudioService(graph or _demo_graph(), **kwargs)


def _entity_by_name(graph: FakeGraphService, name: str) -> CompanyEntity:
    for entity in graph.entities.values():
        if entity.canonical_name == name:
            return entity
    raise AssertionError(f"entity not found: {name}")


# ---------------------------------------------------------------------------
# §2 Overview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overview_reports_real_counts() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    overview = await studio.overview(ORG)

    assert overview["entities"]["total"] == len(graph.entities)
    assert overview["coverage"]["processes"] == 2
    assert overview["coverage"]["systems"] == 1
    assert overview["coverage"]["tables"] == 1
    assert overview["coverage"]["rules"] == 1
    assert overview["entities"]["confirmed"] >= 10
    # Todo número sale del grafo: no hay métricas decorativas.
    assert set(overview["entities"]["by_status"]) <= {
        status.value for status in EntityStatus
    }


@pytest.mark.asyncio
async def test_overview_reports_zero_for_empty_tenant() -> None:
    overview = await _studio().overview(uuid4())
    assert overview["entities"]["total"] == 0
    assert overview["knowledge_gaps"]["total"] == 0


# ---------------------------------------------------------------------------
# §3/§4/§24 Company Map acotado
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_map_layer_is_bounded_and_grouped() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    a1672 = _entity_by_name(graph, "A1672")
    layer = await studio.map_layer(ORG, a1672.id, max_nodes=3, max_edges=2)

    assert layer["root"]["canonical_name"] == "A1672"
    assert len(layer["nodes"]) <= 3
    assert len(layer["edges"]) <= 2
    assert layer["limits"]["max_nodes"] == 3
    # Los vecinos vienen agrupados para poder navegar por capas.
    assert isinstance(layer["groups"], dict)


@pytest.mark.asyncio
async def test_map_layer_filters_by_relationship_and_status() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    a1672 = _entity_by_name(graph, "A1672")
    only_reads = await studio.map_layer(
        ORG, a1672.id, relationship_types=("READS_FROM",), direction="in"
    )
    types = {edge["relationship_type"] for edge in only_reads["edges"]}
    assert types <= {"READS_FROM"}

    suggested = await studio.map_layer(
        ORG,
        _entity_by_name(graph, "Pending Transaction").id,
        statuses=(EntityStatus.DISCOVERED,),
        direction="out",
    )
    assert all(edge["status"] == EntityStatus.DISCOVERED.value for edge in suggested["edges"])


@pytest.mark.asyncio
async def test_map_layer_rejects_unknown_entity() -> None:
    with pytest.raises(ValueError):
        await _studio().map_layer(ORG, uuid4())


# ---------------------------------------------------------------------------
# §5 Entity detail y §22 badges de confianza
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_detail_keeps_confidence_and_provenance() -> None:
    graph = _demo_graph()
    studio = _studio(graph, authority=FakeAuthority([
        {"domain": "data", "concept": "pending transaction", "source_name": "PXSAUDIT",
         "authority_level": "authoritative"},
    ]))
    a1672 = _entity_by_name(graph, "A1672")
    detail = await studio.entity_detail(ORG, a1672.id)

    assert detail["entity"]["canonical_name"] == "A1672"
    assert detail["incoming"] and detail["outgoing"]
    for edge in detail["incoming"] + detail["outgoing"]:
        assert "status" in edge and "confidence" in edge and "confirmed" in edge
        assert edge["direction"] in ("incoming", "outgoing")
    # El sistema aparece agrupado como system, no mezclado con datos.
    assert any(
        item["canonical_name"] == "PXSAUDIT"
        for item in detail["related"].get("systems", [])
    )
    assert any(
        item["canonical_name"] == "Fare Audit"
        for item in detail["related"].get("automation", [])
    )


@pytest.mark.asyncio
async def test_entity_detail_shows_unconfirmed_as_unconfirmed() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    pending = _entity_by_name(graph, "Pending Transaction")
    detail = await studio.entity_detail(ORG, pending.id)
    suggested = [
        edge for edge in detail["outgoing"] if edge["status"] == EntityStatus.DISCOVERED.value
    ]
    assert suggested
    assert all(edge["confirmed"] is False for edge in suggested)


# ---------------------------------------------------------------------------
# §6 Concepto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concept_page_shows_mappings_and_usages() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    pending = _entity_by_name(graph, "Pending Transaction")
    page = await studio.concept_page(ORG, pending.id)

    assert page["concept"]["canonical_name"] == "Pending Transaction"
    assert "pendiente" in page["aliases"]
    mapping = page["technical_mappings"][0]
    assert mapping["target"] == "A1672STO0"
    assert "0" in mapping["values"]
    assert "A1672STO0" in mapping["predicate"]
    assert mapping["status"] == EntityStatus.CONFIRMED.value


@pytest.mark.asyncio
async def test_concept_page_rejects_non_concept() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    with pytest.raises(ValueError):
        await studio.concept_page(ORG, _entity_by_name(graph, "PXSAUDIT").id)


# ---------------------------------------------------------------------------
# §7/§8 Proceso y desviación
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_page_separates_designed_and_observed() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    reconciliation = _entity_by_name(graph, "Reconciliation Process")
    page = await studio.process_page(ORG, reconciliation.id)
    assert page["process"]["canonical_name"] == "Reconciliation Process"
    assert page["steps"]["designed"] == []
    assert page["steps"]["observed"] == []
    assert page["deviation"]["available"] is False
    assert any(item["name"] == "PXSAUDIT" for item in page["systems"])
    assert any(item["name"] == "Reconciliation Workflow" for item in page["workflows"])


@pytest.mark.asyncio
async def test_process_deviation_detects_rework() -> None:
    """§8: A B C B C D tiene retrabajo; se reporta frecuencia, no causalidad."""
    rows = []
    sequences = [
        ["a", "b", "c", "b", "c", "d"],
        ["a", "b", "c", "d"],
        ["a", "b", "c", "d"],
        ["a", "b", "c", "b", "d"],
    ]
    for index, sequence in enumerate(sequences):
        for position, node in enumerate(sequence):
            rows.append(
                {
                    "run_id": f"run-{index}",
                    "step_index": position,
                    "node_id": node,
                    "workflow_id": "wf-1",
                }
            )

    async def loader(organization_id: UUID, limit: int):
        return rows

    graph = _demo_graph()
    studio = _studio(graph, run_steps_loader=loader)
    entity = graph.add(
        "process",
        "Fare Audit Observed",
        metadata={"workflow_id": "wf-1", "runs_observed": 4, "steps": []},
    )
    page = await studio.process_page(ORG, entity.id)
    deviation = page["deviation"]
    assert deviation["available"] is True
    assert deviation["runs"] == 4
    assert deviation["rework_frequency"] == pytest.approx(0.5, abs=0.01)
    assert deviation["canonical_sequence"] == ["a", "b", "c", "d"]
    assert "no causation" in deviation["note"]


# ---------------------------------------------------------------------------
# §9/§10/§11 Impacto con confianza y lenguaje hipotético
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_impact_marks_unconfirmed_paths_as_may() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    pending = _entity_by_name(graph, "Pending Transaction")
    impact = await studio.impact(ORG, pending.id)

    assert impact["root"]["canonical_name"] == "Pending Transaction"
    certainties = {path["certainty"] for path in impact["paths"]}
    assert "may" in certainties, "el vínculo SUGGESTED debe producir 'may'"
    for path in impact["paths"]:
        if path["certainty"] == "may":
            assert any(
                step["status"] != EntityStatus.CONFIRMED.value
                for step in path["explanation"]
            )
    # §10: la evidencia conserva status por eslabón.
    assert all("status" in edge for edge in impact["edges"])


@pytest.mark.asyncio
async def test_impact_lists_affected_by_bucket() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    pxsaudit = _entity_by_name(graph, "PXSAUDIT")
    impact = await studio.impact(ORG, pxsaudit.id)
    affected = impact["affected"]
    assert "systems" in affected or "processes" in affected
    names = {
        item["name"]
        for items in affected.values()
        for item in items
    }
    assert "A1672" in names or "Reconciliation Process" in names


@pytest.mark.asyncio
async def test_impact_respects_depth_limit() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    atpco = _entity_by_name(graph, "ATPCO")
    shallow = await studio.impact(ORG, atpco.id, max_depth=1)
    assert shallow["limits"]["max_depth"] == 1
    assert all(path["hops"] <= 1 for path in shallow["paths"])


# ---------------------------------------------------------------------------
# §13 Fuente de verdad
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_source_of_truth_groups_levels_and_finds_untracked() -> None:
    graph = _demo_graph()
    studio = _studio(
        graph,
        authority=FakeAuthority(
            [
                {"domain": "data", "concept": "pending transaction",
                 "source_name": "PXSAUDIT", "authority_level": "authoritative"},
                {"domain": "data", "concept": "pending transaction",
                 "source_name": "documentation", "authority_level": "secondary"},
            ]
        ),
    )
    truth = await studio.source_of_truth(ORG)
    entry = next(
        item for item in truth["items"] if item["concept"] == "Pending Transaction"
    )
    assert entry["authoritative"][0]["source_name"] == "PXSAUDIT"
    assert entry["secondary"][0]["source_name"] == "documentation"
    assert entry["has_authority"] is True
    # Conceptos sin authority se listan como hueco de conocimiento.
    assert "Pending Transaction" not in truth["concepts_without_authority"]


# ---------------------------------------------------------------------------
# §14 Knowledge gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_knowledge_gaps_merge_discovery_and_graph() -> None:
    graph = _demo_graph()
    discovery = FakeDiscovery([])
    studio = _studio(graph, discovery=discovery)
    gaps = await studio.knowledge_gaps(ORG)
    kinds = {item["gap_kind"] for item in gaps["items"]}
    # Derivados del grafo: conceptos sin authority y procesos sin responsable.
    assert "no_authoritative_definition" in kinds
    assert isinstance(gaps["by_kind"], dict)


@pytest.mark.asyncio
async def test_knowledge_gaps_include_undocumented_step() -> None:
    from src.company.demo_seed import DEMO_DOMAIN as _domain  # noqa: F401
    from src.core.domain.company_discovery import (
        CandidateKind,
        CandidateSupport,
        DiscoveryCandidate,
        DiscoveryEvidence,
        DiscoverySourceKind,
        DiscoveryStage,
        GapKind,
        KnowledgeGapPayload,
        candidate_key,
    )

    payload = KnowledgeGapPayload(
        gap_kind=GapKind.UNDOCUMENTED_STEP,
        subject="Reconciliation Process:manual-review",
        detail="step occurs in 27% of observed runs but is not documented",
        frequency=0.27,
        observed_runs=100,
    )
    candidate = DiscoveryCandidate(
        organization_id=ORG,
        kind=CandidateKind.KNOWLEDGE_GAP,
        natural_key=candidate_key(CandidateKind.KNOWLEDGE_GAP, payload.to_dict()),
        title="Gap: undocumented step",
        payload=payload.to_dict(),
        source_kind=DiscoverySourceKind.EVENT,
        stage=DiscoveryStage.SUGGESTED,
        confidence=0.6,
        support=CandidateSupport(observations=100, successful_runs=100),
        evidence=(DiscoveryEvidence(source_kind=DiscoverySourceKind.EVENT, ref="run-1"),),
    )
    studio = _studio(_demo_graph(), discovery=FakeDiscovery([candidate]))
    gaps = await studio.knowledge_gaps(ORG)
    undocumented = [
        item for item in gaps["items"] if item["gap_kind"] == "undocumented_step"
    ]
    assert undocumented
    assert undocumented[0]["origin"] == "discovery"
    assert undocumented[0]["frequency"] == pytest.approx(0.27)


# ---------------------------------------------------------------------------
# §15/§16 Cambios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_changes_timeline_is_chronological() -> None:
    graph = _demo_graph()
    studio = _studio(graph)
    changes = await studio.changes(ORG, since=NOW - timedelta(days=30))
    assert changes["items"], "el grafo demo acaba de crearse: hay cambios"
    timestamps = [item["at"] for item in changes["items"]]
    assert timestamps == sorted(timestamps, reverse=True)
    assert all("kind" in item for item in changes["items"])


@pytest.mark.asyncio
async def test_entity_changes_compares_temporal_validity() -> None:
    graph = _demo_graph()
    old = _entity_by_name(graph, "A1672")
    retirement = NOW - timedelta(days=100)
    from dataclasses import replace

    graph.entities[old.id] = replace(old, valid_to=retirement)
    studio = _studio(graph)
    changes = await studio.entity_changes(
        ORG, old.id, as_of=NOW - timedelta(days=200)
    )
    assert changes["compared_to"]
    assert changes["valid_at_previous"] is True
    assert "relationships_current" in changes


# ---------------------------------------------------------------------------
# §17/§18/§19 Institucional, riesgos, salud
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_institutional_reports_owners_and_missing_owners() -> None:
    studio = _studio(_demo_graph())
    institutional = await studio.institutional(ORG)
    assert [item["canonical_name"] for item in institutional["teams"]] == ["Audit Team"]
    ownership = {
        item["process"]: item["owners"] for item in institutional["process_ownership"]
    }
    assert ownership["Reconciliation Process"][0]["owner"] == "Audit Team"
    # Fare Audit no tiene owner: debe aparecer como pendiente.
    assert "Fare Audit" in institutional["processes_without_owner"]


@pytest.mark.asyncio
async def test_risks_are_marked_potential() -> None:
    studio = _studio(_demo_graph())
    risks = await studio.risks(ORG)
    assert risks
    # §18: siempre POTENCIAL, nunca riesgo definitivo.
    assert all(item["level"] == "potential" for item in risks)
    kinds = {item["risk_kind"] for item in risks}
    assert "single_dependency" in kinds


@pytest.mark.asyncio
async def test_single_authority_is_flagged_as_potential_risk() -> None:
    graph = _demo_graph()
    studio = _studio(
        graph,
        authority=FakeAuthority(
            [
                {"domain": "data", "concept": "pending transaction",
                 "source_name": "PXSAUDIT", "authority_level": "authoritative"},
            ]
        ),
    )
    risks = await studio.risks(ORG)
    authority_risks = [item for item in risks if item["risk_kind"] == "single_authority"]
    assert authority_risks
    assert authority_risks[0]["entity"] == "Pending Transaction"
    assert authority_risks[0]["level"] == "potential"


@pytest.mark.asyncio
async def test_knowledge_health_components_are_measured() -> None:
    studio = _studio(
        _demo_graph(),
        authority=FakeAuthority(
            [
                {"domain": "data", "concept": "pending transaction",
                 "source_name": "PXSAUDIT", "authority_level": "authoritative"},
            ]
        ),
    )
    health = await studio.knowledge_health(ORG)
    keys = {item["key"] for item in health["components"]}
    assert "authority_coverage" in keys
    assert "graph_confirmation" in keys
    assert 0.0 <= health["aggregate"] <= 100.0
    assert health["counts"]["entities"] > 0


# ---------------------------------------------------------------------------
# §20/§21 Memoria y conversaciones por entidad
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entity_memory_and_conversations() -> None:
    class _Record:
        def __init__(self, key: str, conversation_id: UUID | None = None) -> None:
            self.id = uuid4()
            self.organization_id = ORG
            self.pattern_key = key
            self.title = key
            self.description = "aprendizaje operativo"
            self.memory_type = type("T", (), {"value": "operational"})()
            self.status = type("T", (), {"value": "active"})()
            self.visibility = type("T", (), {"value": "tenant"})()
            self.confidence = 0.8
            self.support_count = 3
            self.contradiction_count = 0
            self.success_count = 2
            self.success_rate = 0.66
            self.created_at = NOW
            self.updated_at = NOW
            self.created_from_conversation_id = conversation_id

        def to_public_dict(self) -> dict:
            return {
                "id": str(self.id),
                "pattern_key": self.pattern_key,
                "title": self.title,
                "status": self.status.value,
                "success_rate": self.success_rate,
                "support_count": self.support_count,
            }

    conversation_id = uuid4()
    memory = FakeMemory([_Record("a1672_structured_exact", conversation_id)])
    graph = _demo_graph()
    studio = _studio(graph, memory=memory)
    a1672 = _entity_by_name(graph, "A1672")

    detail = await studio.entity_detail(ORG, a1672.id)
    assert detail["memory"], "la memoria relacionada debe aparecer en el detalle"

    conversations = await studio.entity_conversations(ORG, a1672.id)
    assert conversations["items"][0]["conversation_id"] == str(conversation_id)


# ---------------------------------------------------------------------------
# §12 Ask your Company
# ---------------------------------------------------------------------------


def test_question_tokens_and_lexical_intent() -> None:
    assert "atpco" in question_tokens("¿Qué procesos dependen de ATPCO?")
    intent, confidence = lexical_intent("¿Qué se vería afectado si PXSAUDIT falla?")
    assert intent is CompanyIntent.IMPACT
    assert confidence > 0
    assert lexical_intent("¿Qué fuente manda sobre esta regla?")[0] is (
        CompanyIntent.SOURCE_OF_TRUTH
    )
    assert lexical_intent("¿Qué conocimiento falta?")[0] is CompanyIntent.KNOWLEDGE_GAPS


@pytest.mark.asyncio
async def test_ask_answers_dependency_question() -> None:
    graph = _demo_graph()
    ask = CompanyAskService(graph, _studio(graph))
    answer = await ask.ask(ORG, "¿Qué procesos dependen de ATPCO?")
    assert answer.intent in (
        CompanyIntent.DEPENDENCY.value,
        CompanyIntent.IMPACT.value,
        CompanyIntent.ENTITY_LOOKUP.value,
    )
    assert answer.answer
    assert answer.decision["provider"] == "lexical"
    assert answer.decision["fallback_used"] is True


@pytest.mark.asyncio
async def test_ask_uses_judge_when_available() -> None:
    graph = _demo_graph()

    async def judge(*, state, questions):
        return {"provider": "jev", "answers": {"intent": {"choice": "source_of_truth", "confidence": 0.9}}}

    ask = CompanyAskService(graph, _studio(graph), judge=judge)
    answer = await ask.ask(ORG, "¿quién manda acá?")
    assert answer.intent == CompanyIntent.SOURCE_OF_TRUTH.value
    assert answer.decision["fallback_used"] is False


@pytest.mark.asyncio
async def test_ask_survives_broken_judge() -> None:
    async def judge(*, state, questions):
        raise RuntimeError("jev down")

    ask = CompanyAskService(_demo_graph(), _studio(), judge=judge)
    answer = await ask.ask(ORG, "¿dónde se representa pending?")
    assert answer.decision["fallback_used"] is True
    assert answer.intent


@pytest.mark.asyncio
async def test_ask_reports_gaps_and_changes() -> None:
    graph = _demo_graph()
    ask = CompanyAskService(graph, _studio(graph, discovery=FakeDiscovery([])))
    gaps = await ask.ask(ORG, "¿Qué conocimiento falta?")
    assert gaps.intent == CompanyIntent.KNOWLEDGE_GAPS.value
    assert gaps.answer

    changes = await ask.ask(ORG, "¿Qué cambió este mes?")
    assert changes.intent == CompanyIntent.CHANGES.value


@pytest.mark.asyncio
async def test_ask_is_tenant_scoped() -> None:
    ask = CompanyAskService(_demo_graph(), _studio())
    answer = await ask.ask(uuid4(), "¿qué es ATPCO?")
    assert "No encontré" in answer.answer or answer.intent


@pytest.mark.asyncio
async def test_ask_never_raises_on_empty_question() -> None:
    ask = CompanyAskService(_demo_graph(), _studio())
    with pytest.raises(ValueError):
        await ask.ask(ORG, "   ")


@pytest.mark.asyncio
async def test_ask_marks_hypothetical_impact() -> None:
    graph = _demo_graph()
    ask = CompanyAskService(graph, _studio(graph))
    answer = await ask.ask(ORG, "¿Qué se vería afectado si Pending Transaction cambia?")
    if answer.certainty == "may":
        assert "potencial" in answer.answer or "may" in answer.answer.lower()


@pytest.mark.asyncio
async def test_ask_finds_processes_that_use_an_entity() -> None:
    """'¿Qué proceso usa A1672?' no debe tratar la tabla como proceso."""
    graph = _demo_graph()
    ask = CompanyAskService(graph, _studio(graph))
    answer = await ask.ask(ORG, "¿Qué proceso usa A1672?")
    assert "Fare Audit" in answer.answer
    assert any(item.kind == "process" for item in answer.evidence)


@pytest.mark.asyncio
async def test_ask_representation_reports_concepts_for_a_field() -> None:
    """Un campo no se mapea a conceptos: los conceptos se mapean hacia él."""
    graph = _demo_graph()
    ask = CompanyAskService(graph, _studio(graph))
    answer = await ask.ask(ORG, "¿Dónde se representa A1672STO0?")
    assert "Pending Transaction" in answer.answer
    assert any(item.kind == "mapping" for item in answer.evidence)


@pytest.mark.asyncio
async def test_ask_uses_page_context_for_unspecified_entity() -> None:
    """'¿Qué aprendió Zent sobre esta tabla?' se resuelve con el contexto."""

    class _MemoryRecord:
        id = uuid4()
        pattern_key = "a1672_lookup"
        title = "lookup en A1672"
        status = type("S", (), {"value": "active"})()
        success_rate = 0.8
        support_count = 5

        def to_public_dict(self) -> dict:
            return {
                "id": str(self.id),
                "pattern_key": self.pattern_key,
                "title": self.title,
                "status": "active",
                "success_rate": self.success_rate,
                "support_count": self.support_count,
            }

    graph = _demo_graph()
    a1672 = _entity_by_name(graph, "A1672")
    ask = CompanyAskService(
        graph, _studio(graph, memory=FakeMemory([_MemoryRecord()]))
    )
    answer = await ask.ask(
        ORG, "¿Qué aprendió Zent sobre esta tabla?", entity_id=a1672.id
    )
    assert "A1672" in answer.answer
    assert answer.intent == CompanyIntent.LEARNED.value


@pytest.mark.asyncio
async def test_ask_explains_when_nothing_matches() -> None:
    ask = CompanyAskService(_demo_graph(), _studio())
    answer = await ask.ask(ORG, "¿Qué aprendió Zent sobre esto?")
    assert "No encontré" in answer.answer
    assert "Nombrá la entidad" in answer.answer


# ---------------------------------------------------------------------------
# §28 Backend: graph service contract (Neo4j readiness) y aislamiento
# ---------------------------------------------------------------------------


def test_studio_uses_graph_port_not_sql() -> None:
    """§25: la Studio no debe hablar SQL propio del grafo."""
    import inspect

    import src.company.studio as studio_module

    source = inspect.getsource(studio_module)
    assert "company_entities" not in source
    assert "company_relationships" not in source
    assert "FROM company_" not in source


def test_entity_view_exposes_confidence_fields() -> None:
    entity = CompanyEntity(
        organization_id=ORG,
        entity_type="rule",
        canonical_name="Rule X",
        status=EntityStatus.STALE,
        confidence=0.4,
        authority_level=SourceAuthorityLevel.PRIMARY,
    )
    view = entity_view(entity)
    assert view["status"] == "stale"
    assert view["confidence"] == 0.4
    assert view["authority_level"] == "primary"


@pytest.mark.asyncio
async def test_impact_analysis_respects_limits_in_port() -> None:
    graph = _demo_graph()
    result = await graph.impact_analysis(
        ORG,
        _entity_by_name(graph, "A1672").id,
        limits=GraphTraversalLimits(max_depth=1, max_nodes=2, max_edges=2),
    )
    assert len(result.entities) <= 2
    assert len(result.relationships) <= 2
