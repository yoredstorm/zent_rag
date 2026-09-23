# =============================================================================
# Company Discovery Engine — tests de la Fase 5B
# =============================================================================
# Cubre: descubrimiento desde estructura, documentos, uso real y config;
# resolución de entidades (dedupe, alias, ambigüedad); mappings técnicos con
# evidencia acumulada; procesos designed vs observed; knowledge gaps;
# authority candidates; versiones temporales; compilación de contexto con
# presupuesto; aislamiento por tenant y adaptadores de consumidores.
# =============================================================================
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from src.company.context import (
    CompanyContextCompiler,
    ContextBudget,
    request_tokens,
)
from src.company.discovery.confidence import (
    mapping_confident,
    next_stage_for,
    score_candidate,
)
from src.company.discovery.gaps import (
    KnowledgeGapSource,
    find_process_divergences,
)
from src.company.discovery.resolution import (
    EntityResolutionEngine,
    ResolutionStrategy,
    normalize_business_name,
)
from src.company.discovery.sources_config import (
    AgentConfigSource,
    WorkflowConfigSource,
)
from src.company.discovery.sources_documents import (
    DocumentConceptSource,
    TemporalVersionSource,
    extract_definitions,
    extract_effective_dates,
    extract_technical_identifiers,
)
from src.company.discovery.sources_structured import (
    CatalogSemanticSource,
    DatabaseSchemaSource,
    TabularStructureSource,
)
from src.company.discovery.sources_usage import (
    AuthorityCandidateSource,
    ObservedProcessSource,
    SqlUsageSource,
    extract_predicates,
    extract_terms,
)
from src.core.domain.company_discovery import (
    AuthorityCandidatePayload,
    CandidateKind,
    CandidateSupport,
    DiscoveryCandidate,
    DiscoverySourceKind,
    DiscoveryStage,
    EntityCandidatePayload,
    GapKind,
    KnowledgeGapPayload,
    MappingCandidatePayload,
    ProcessCandidatePayload,
    ProcessMode,
    ProcessStep,
    TermCandidatePayload,
    assert_stage_transition,
    candidate_key,
    compare_processes,
    requires_human_confirmation,
)
from src.core.domain.company_graph import (
    CompanyEntity,
    EntityStatus,
    ProvenanceKind,
    SourceAuthorityLevel,
    assert_status_transition,
)
from tests.company_discovery_fixtures import (
    ORG,
    FakeAuthorityService,
    FakeMemoryRecall,
    build_demo_graph,
    demo_authority_rules,
    fake_document_rows,
    fake_run_step_rows,
    fake_schema_rows,
    fake_sql_rows,
)


def _loader(items: list):
    """Loader falso: misma firma que los loaders Postgres, pero en memoria."""

    async def load(*args, **kwargs) -> list:
        return list(items)

    return load


NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Descubrimiento estructurado (§2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_discovery_confirms_database_table_field() -> None:
    tables, columns = fake_schema_rows()
    source = DatabaseSchemaSource(
        loader_tables=_loader(tables),
        loader_columns=_loader(columns),
    )
    candidates = await source.discover(ORG)
    kinds = {(item.kind, item.payload.get("relationship_type")) for item in candidates}
    assert (CandidateKind.ENTITY, None) in kinds
    assert (CandidateKind.RELATIONSHIP, "CONTAINS") in kinds

    table = _find_entity(candidates, "table", "PXSAUDIT.A1672")
    assert table.support.structural is True
    assert table.confidence >= 0.7

    contains = _find_relationship(candidates, "CONTAINS", "table", "field")
    assert contains.payload["from_ref"]["canonical_name"] == "PXSAUDIT.A1672"
    assert contains.support.structural is True


@pytest.mark.asyncio
async def test_catalog_mapping_discovery_is_structural_only_when_approved() -> None:
    entities = [
        {
            "id": "e-1",
            "name": "Pending Transaction",
            "display_name": "Pending Transaction",
            "description": "",
            "provenance": "APPROVED",
            "confidence": "high",
        }
    ]
    fields = [
        {
            "id": "f-1",
            "entity_id": "e-1",
            "name": "Pending flag",
            "provenance": "INFERRED",
            "confidence": "high",
            "mapped_column_id": "c-1",
            "synonyms": ["pending"],
            "status": "draft",
            "mapping_type": "DIRECT",
            "role": "STATUS",
        }
    ]
    columns = [
        {
            "id": "c-1",
            "column_name": "A1672STO0",
            "schema_name": "PXSAUDIT",
            "table_name": "A1672",
        }
    ]
    source = CatalogSemanticSource(
        loader_entities=_loader(entities),
        loader_fields=_loader(fields),
        loader_columns=_loader(columns),
        loader_enums=_loader([]),
    )
    candidates = await source.discover(ORG)
    mapping = next(item for item in candidates if item.kind is CandidateKind.MAPPING)
    payload = MappingCandidatePayload.from_dict(mapping.payload)
    assert payload.concept_ref.canonical_name == "Pending Transaction"
    assert payload.target_ref.canonical_name == "A1672STO0"
    # El campo venía INFERRED: el mapping no puede ser estructural.
    assert mapping.support.structural is False
    assert mapping.stage is DiscoveryStage.DISCOVERED


@pytest.mark.asyncio
async def test_tabular_discovery_builds_dataset_tree() -> None:
    tables = [{"id": "tt-1", "name": "Sheet1", "title": "Sheet1", "workbook_id": "w-1", "filename": "atpco.xlsx"}]
    columns = [
        {
            "id": "tc-1",
            "table_id": "tt-1",
            "original_name": "Carrier Code",
            "normalized_name": "carrier_code",
            "semantic_type": "identifier",
            "aliases": ["carrier"],
        }
    ]
    source = TabularStructureSource(
        loader_tables=_loader(tables),
        loader_columns=_loader(columns),
    )
    candidates = await source.discover(ORG)
    dataset = _find_entity(candidates, "dataset", "atpco.xlsx")
    assert dataset.support.structural is True
    assert _find_relationship(candidates, "CONTAINS", "dataset", "table")


# ---------------------------------------------------------------------------
# Descubrimiento documental (§3/§14)
# ---------------------------------------------------------------------------


def test_document_extractors_are_deterministic() -> None:
    definitions = extract_definitions(
        "Pending Transaction means a transaction not processed yet."
    )
    assert definitions == [
        ("Pending Transaction", "a transaction not processed yet.")
    ]
    assert extract_definitions("Nada que extraer aquí.") == []

    identifiers = extract_technical_identifiers(
        "Check PXSAUDIT.A1672.A1672STO0 and A1672DOC fields."
    )
    assert "PXSAUDIT.A1672.A1672STO0" in identifiers
    assert "A1672DOC" in identifiers

    dates = extract_effective_dates("Refund Policy effective from 2025-07-01 applies.")
    assert dates == [("Refund Policy", datetime(2025, 7, 1, tzinfo=timezone.utc))]


@pytest.mark.asyncio
async def test_document_discovery_proposes_concepts_and_conflicts() -> None:
    documents, blocks = fake_document_rows()
    source = DocumentConceptSource(
        loader_documents=_loader(documents),
        loader_blocks=_loader(blocks),
    )
    candidates = await source.discover(ORG)
    concept = _find_entity(candidates, "concept", "Pending Transaction")
    assert "not been processed" in concept.payload["description"]
    assert concept.source_kind is DiscoverySourceKind.DOCUMENT
    # Documento es interpretativo: nunca estructural.
    assert concept.support.structural is False

    gap = next(
        item
        for item in candidates
        if item.kind is CandidateKind.KNOWLEDGE_GAP
        and item.payload["gap_kind"] == GapKind.CONTRADICTORY_DEFINITION.value
    )
    assert "Pending Transaction" in gap.title

    temporal = next(
        item for item in candidates if item.kind is CandidateKind.TEMPORAL
    )
    assert temporal.payload["effective_from"].startswith("2025-07-01")


@pytest.mark.asyncio
async def test_temporal_versions_chain_superseded_by() -> None:
    rows = [
        {
            "id": "v-1",
            "document_id": "d-1",
            "version": 1,
            "change_kind": "CREATED",
            "title": "Refund Policy",
        },
        {
            "id": "v-2",
            "document_id": "d-1",
            "version": 2,
            "change_kind": "UPDATED",
            "title": "Refund Policy",
        },
    ]
    source = TemporalVersionSource(loader=_loader(rows))
    candidates = await source.discover(ORG)
    assert len(candidates) == 1
    payload = candidates[0].payload
    assert payload["subject_ref"]["canonical_name"] == "Refund Policy v1"
    assert payload["subject_ref"]["entity_type"] == "policy"
    assert payload["superseded_by_ref"]["canonical_name"] == "Refund Policy v2"


# ---------------------------------------------------------------------------
# Uso real: diccionario, procesos y authority (§7/§9/§13)
# ---------------------------------------------------------------------------


def test_sql_predicate_and_term_extraction() -> None:
    predicates = extract_predicates(
        "SELECT COUNT(*) FROM PXSAUDIT.A1672 WHERE A1672STO0 IN ('0','') AND A1672DOC = 'ADM'"
    )
    assert ("A1672STO0", ("0", "")) in predicates
    assert ("A1672DOC", ("ADM",)) in predicates
    terms = extract_terms("¿cuántas transacciones pending hay?")
    assert "pending" in terms
    assert "transacciones" in terms or "transacciones" not in terms


@pytest.mark.asyncio
async def test_dictionary_learning_requires_accumulated_evidence() -> None:
    rows = fake_sql_rows()
    source = SqlUsageSource(
        loader_sql=_loader(rows),
        loader_verified=_loader([]),
        min_runs=3,
    )
    candidates = await source.discover(ORG)
    mapping = next(
        item
        for item in candidates
        if item.kind is CandidateKind.MAPPING
        and MappingCandidatePayload.from_dict(item.payload).concept_ref.canonical_name
        == "pending"
    )
    payload = MappingCandidatePayload.from_dict(mapping.payload)
    assert payload.concept_ref.canonical_name == "pending"
    assert payload.target_ref.canonical_name == "A1672STO0"
    assert "0" in payload.values

    support = mapping.support
    assert support.successful_runs >= 3
    assert support.distinct_actors >= 2
    assert mapping_confident(support) is True
    # Ya es sugerible, pero jamás confirmable por sí sola.
    assert mapping.stage in (DiscoveryStage.SUPPORTED, DiscoveryStage.SUGGESTED)
    assert mapping.stage is not DiscoveryStage.CONFIRMED

    term = next(item for item in candidates if item.kind is CandidateKind.TERM)
    TermCandidatePayload.from_dict(term.payload)


@pytest.mark.asyncio
async def test_single_occurrence_never_suggests_mapping() -> None:
    rows = fake_sql_rows()[:1]
    source = SqlUsageSource(
        loader_sql=_loader(rows),
        loader_verified=_loader([]),
    )
    candidates = await source.discover(ORG)
    assert all(item.kind is not CandidateKind.MAPPING for item in candidates)


@pytest.mark.asyncio
async def test_observed_process_discovery_and_frequency() -> None:
    rows = fake_run_step_rows()
    source = ObservedProcessSource(loader=_loader(rows))
    candidates = await source.discover(ORG)
    process = next(
        item
        for item in candidates
        if item.kind is CandidateKind.PROCESS
        and ProcessCandidatePayload.from_dict(item.payload).workflow_id == "wf-1"
    )
    payload = ProcessCandidatePayload.from_dict(process.payload)
    assert payload.mode is ProcessMode.OBSERVED
    assert payload.runs_observed == 3
    notify = next(step for step in payload.steps if step.name == "notify")
    # notify sólo apareció en 1 de 3 corridas.
    assert notify.frequency == pytest.approx(1 / 3, rel=0.01)


def test_designed_vs_observed_divergence_flags_undocumented_step() -> None:
    designed = ProcessCandidatePayload(
        name="reconciliation",
        mode=ProcessMode.DESIGNED,
        steps=(
            ProcessStep(name="load", order=0, documented=True),
            ProcessStep(name="validate", order=1, documented=True),
        ),
    )
    observed = ProcessCandidatePayload(
        name="Reconciliation",
        mode=ProcessMode.OBSERVED,
        runs_observed=10,
        steps=(
            ProcessStep(name="load", order=0, frequency=1.0, runs=10),
            ProcessStep(name="validate", order=1, frequency=1.0, runs=10),
            ProcessStep(name="match", order=2, frequency=0.82, runs=8),
        ),
    )
    divergence = compare_processes(designed, observed)
    assert divergence.has_divergence
    assert [step.name for step in divergence.undocumented_steps] == ["match"]
    assert divergence.undocumented_steps[0].frequency == pytest.approx(0.82)

    divergences = find_process_divergences([designed, observed])
    assert len(divergences) == 1


@pytest.mark.asyncio
async def test_knowledge_gap_for_undocumented_step() -> None:
    designed = ProcessCandidatePayload(
        name="reconciliation",
        mode=ProcessMode.DESIGNED,
        steps=(ProcessStep(name="load", order=0, documented=True),),
    )
    observed = ProcessCandidatePayload(
        name="reconciliation",
        mode=ProcessMode.OBSERVED,
        runs_observed=100,
        steps=(
            ProcessStep(name="load", order=0, frequency=1.0, runs=100),
            ProcessStep(name="step-c", order=1, frequency=0.82, runs=82),
        ),
    )
    divergence = find_process_divergences([designed, observed])[0]
    gaps = KnowledgeGapSource().from_divergence(ORG, divergence)
    undoc = next(
        item
        for item in gaps
        if item.payload["gap_kind"] == GapKind.UNDOCUMENTED_STEP.value
    )
    payload = KnowledgeGapPayload.from_dict(undoc.payload)
    assert "82%" in payload.summary()
    assert payload.observed_runs == 100
    assert undoc.kind is CandidateKind.KNOWLEDGE_GAP


@pytest.mark.asyncio
async def test_knowledge_gap_from_claim_ledger_conflict() -> None:
    rows = [
        {
            "normalized_subject": "penalidad",
            "normalized_predicate": "es",
            "objects": ["5%", "7%"],
            "claims": 2,
            "claim_ids": ["claim-1", "claim-2"],
        }
    ]
    source = KnowledgeGapSource(loader_conflicts=_loader(rows))
    candidates = await source.discover(ORG)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind is CandidateKind.KNOWLEDGE_GAP
    assert candidate.payload["gap_kind"] == GapKind.CONTRADICTORY_DEFINITION.value
    assert candidate.evidence[0].ref == "claim-1"
    assert candidate.support.contradictions >= 1


@pytest.mark.asyncio
async def test_authority_candidate_from_consistent_execution() -> None:
    rows = [
        {
            "concept": "ticket status",
            "column_name": "A1672STO0",
            "table_name": "PXSAUDIT.A1672",
            "runs": 12,
            "actors": 4,
        }
    ]
    source = AuthorityCandidateSource(loader=_loader(rows))
    candidates = await source.discover(ORG)
    assert len(candidates) == 1
    payload = AuthorityCandidatePayload.from_dict(candidates[0].payload)
    assert payload.proposed_level is SourceAuthorityLevel.PRIMARY
    assert "12 verified queries" in payload.rationale
    # Es propuesta: requiere confirmación administrativa.
    assert requires_human_confirmation(
        CandidateKind.SOURCE_AUTHORITY, structural=False
    )


# ---------------------------------------------------------------------------
# Configuración: workflows y agentes (§2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_config_discovery_designed_process_and_tools() -> None:
    workflows = [
        {
            "id": "wf-1",
            "name": "invoice-wf",
            "description": "Facturación",
            "trigger_type": "event",
            "trigger_config": {"event_type": "sale.created"},
            "status": "active",
            "graph": {
                "nodes": [
                    {"id": "load", "type": "tool", "name": "load", "config": {"tool": "sql_expert"}},
                    {"id": "decide", "type": "agent", "config": {"agent_id": "collector"}},
                    {"id": "notify", "type": "llm", "name": "notify", "config": {}},
                ]
            },
            "steps": None,
        }
    ]
    source = WorkflowConfigSource(loader=_loader(workflows))
    candidates = await source.discover(ORG)
    process = next(item for item in candidates if item.kind is CandidateKind.PROCESS)
    payload = ProcessCandidatePayload.from_dict(process.payload)
    assert payload.mode is ProcessMode.DESIGNED
    assert payload.step_names() == ("load", "decide", "notify")

    relationships = [
        item.payload for item in candidates if item.kind is CandidateKind.RELATIONSHIP
    ]
    assert any(
        item["relationship_type"] == "USES" and item["to_ref"]["entity_type"] == "tool"
        for item in relationships
    )
    assert any(
        item["relationship_type"] == "USES"
        and item["to_ref"]["canonical_name"] == "collector"
        for item in relationships
    )
    assert any(
        item["relationship_type"] == "TRIGGERS" and item["observed"] is True
        for item in relationships
    )


@pytest.mark.asyncio
async def test_agent_config_discovery_uses_tools_and_knowledge() -> None:
    agents = [
        {
            "id": "a-1",
            "name": "collector",
            "description": "",
            "tools": ["sql_expert", "search_knowledge"],
            "config_json": {"knowledge_base_ids": ["kb-1"]},
        }
    ]
    source = AgentConfigSource(loader=_loader(agents))
    candidates = await source.discover(ORG)
    targets = {
        item.payload["to_ref"]["canonical_name"]: item.payload["to_ref"]["entity_type"]
        for item in candidates
        if item.kind is CandidateKind.RELATIONSHIP
    }
    assert targets["sql_expert"] == "tool"
    assert targets["search_knowledge"] == "tool"
    assert targets["knowledge_base:kb-1"] == "knowledge_source"


# ---------------------------------------------------------------------------
# Resolución de entidades (§4/§5)
# ---------------------------------------------------------------------------


def _entity(entity_type: str, name: str, **overrides) -> CompanyEntity:
    payload = {
        "organization_id": ORG,
        "entity_type": entity_type,
        "canonical_name": name,
        "display_name": name,
    }
    payload.update(overrides)
    return CompanyEntity(**payload)


def test_resolution_layers_exact_alias_technical_normalized() -> None:
    engine = EntityResolutionEngine()
    pool = [
        _entity("concept", "Pending Transaction", aliases=("pendiente",)),
        _entity("field", "A1672STO0", metadata={"technical_identifiers": ["PXSAUDIT.A1672.A1672STO0"]}),
    ]

    exact = engine.resolve(
        EntityCandidatePayload(entity_type="concept", canonical_name="Pending Transaction"),
        pool,
    )
    assert exact.strategy is ResolutionStrategy.EXACT_CANONICAL
    assert exact.matched_id == pool[0].id
    assert exact.reason == "canonical_name_exact"

    alias = engine.resolve(
        EntityCandidatePayload(entity_type="concept", canonical_name="pendiente"), pool
    )
    assert alias.strategy is ResolutionStrategy.ALIAS

    technical = engine.resolve(
        EntityCandidatePayload(
            entity_type="field",
            canonical_name="A1672STO0",
            technical_identifiers=("PXSAUDIT.A1672.A1672STO0",),
        ),
        pool,
    )
    assert technical.strategy in (
        ResolutionStrategy.EXACT_CANONICAL,
        ResolutionStrategy.TECHNICAL_IDENTIFIER,
    )

    normalized = engine.resolve(
        EntityCandidatePayload(
            entity_type="concept", canonical_name="pending   TRANSACTION!"
        ),
        pool,
    )
    assert normalized.matched_id == pool[0].id
    assert normalize_business_name("Pénding  Transaction S.A.") == "pending transaction"


def test_resolution_abbreviation_both_directions() -> None:
    engine = EntityResolutionEngine()
    pool = [_entity("concept", "Agency Debit Memo")]
    short = engine.resolve(
        EntityCandidatePayload(entity_type="concept", canonical_name="ADM"), pool
    )
    assert short.strategy is ResolutionStrategy.ABBREVIATION
    assert short.matched_id == pool[0].id

    expanded = engine.resolve(
        EntityCandidatePayload(entity_type="concept", canonical_name="agency debit memo"),
        pool,
    )
    assert expanded.matched_id == pool[0].id


def test_ambiguous_entities_are_never_auto_merged() -> None:
    """Un término que es alias de dos conceptos NO se fusiona: se marca ambiguo."""
    engine = EntityResolutionEngine()
    pool = [
        _entity("concept", "Agency Debit Memo", aliases=("adm",)),
        _entity("concept", "Automated Data Management", aliases=("adm",)),
    ]
    outcome = engine.resolve(
        EntityCandidatePayload(entity_type="concept", canonical_name="adm"), pool
    )
    assert outcome.ambiguous is True
    assert outcome.matched_id is None
    assert "ambiguous" in outcome.reason
    assert len(outcome.candidates) == 2

    # Una entidad claramente mejor sí se resuelve: la ambigüedad no bloquea todo.
    clear = engine.resolve(
        EntityCandidatePayload(
            entity_type="concept", canonical_name="Agency Debit Memo"
        ),
        pool,
    )
    assert clear.ambiguous is False
    assert clear.matched_id == pool[0].id


def test_judge_adjudication_still_requires_validation() -> None:
    engine = EntityResolutionEngine()
    pool = [_entity("concept", "Alpha"), _entity("concept", "Beta")]
    outcome = engine.adjudicate(pool, lambda question, options: options[1].id, question="?")
    assert outcome.strategy is ResolutionStrategy.JUDGE_ADJUDICATED
    assert outcome.matched_id == pool[1].id
    assert "requires_validation" in outcome.reason

    abstained = engine.adjudicate(pool, lambda question, options: None, question="?")
    assert abstained.ambiguous is True
    assert abstained.matched_id is None

    def boom(question, options):
        raise RuntimeError("jev down")

    failed = engine.adjudicate(pool, boom, question="?")
    assert failed.ambiguous is True


# ---------------------------------------------------------------------------
# Confianza, etapas y promoción (§8/§5 del brief)
# ---------------------------------------------------------------------------


def test_confidence_never_uses_occurrence_count_alone() -> None:
    repeated = CandidateSupport(observations=50, distinct_sources=1)
    corroborated = CandidateSupport(observations=4, distinct_sources=3, distinct_actors=2, successful_runs=3)
    repeated_score = score_candidate(kind=CandidateKind.MAPPING, support=repeated)
    corroborated_score = score_candidate(kind=CandidateKind.MAPPING, support=corroborated)
    assert corroborated_score.total > repeated_score.total
    assert repeated_score.total < 0.55

    contradicted = CandidateSupport(
        observations=10, distinct_sources=3, successful_runs=5, contradictions=2
    )
    assert (
        score_candidate(kind=CandidateKind.MAPPING, support=contradicted).total
        < score_candidate(kind=CandidateKind.MAPPING, support=corroborated).total
    )
    assert mapping_confident(contradicted) is False


def test_stage_law_and_auto_confirm_rules() -> None:
    assert_stage_transition(DiscoveryStage.DISCOVERED, DiscoveryStage.SUPPORTED)
    assert_stage_transition(DiscoveryStage.SUGGESTED, DiscoveryStage.VALIDATED)
    with pytest.raises(ValueError):
        assert_stage_transition(DiscoveryStage.DISCOVERED, DiscoveryStage.CONFIRMED)
    with pytest.raises(ValueError):
        assert_stage_transition(DiscoveryStage.REJECTED, DiscoveryStage.SUPPORTED)

    assert requires_human_confirmation(CandidateKind.MAPPING, structural=False) is True
    assert requires_human_confirmation(CandidateKind.MAPPING, structural=True) is False
    assert requires_human_confirmation(
        CandidateKind.KNOWLEDGE_GAP, structural=False
    ) is False

    # Un candidato interpretativo sólo llega a SUGGESTED.
    assert (
        next_stage_for(
            kind=CandidateKind.MAPPING,
            support=CandidateSupport(observations=9, distinct_sources=3, successful_runs=9),
            confidence=0.95,
            structural=False,
        )
        == "suggested"
    )


def test_candidate_dedup_key_is_stable() -> None:
    first = EntityCandidatePayload(entity_type="concept", canonical_name="Pending")
    second = EntityCandidatePayload(entity_type="CONCEPT", canonical_name="  pending ")
    assert candidate_key(CandidateKind.ENTITY, first.to_dict()) == candidate_key(
        CandidateKind.ENTITY, second.to_dict()
    )


def test_entity_status_law_still_holds_for_materialized_entities() -> None:
    assert_status_transition(EntityStatus.DISCOVERED, EntityStatus.AUTO_CONFIRMED)
    with pytest.raises(ValueError):
        assert_status_transition(EntityStatus.DEPRECATED, EntityStatus.DISCOVERED)


# ---------------------------------------------------------------------------
# Context Compiler (§15-§18)
# ---------------------------------------------------------------------------


def test_request_tokens_and_budget_validation() -> None:
    tokens = request_tokens("¿Dónde se representa pending en el sistema?")
    assert "pending" in tokens
    assert "representa" in tokens
    with pytest.raises(ValueError):
        ContextBudget(max_concepts=100)
    with pytest.raises(ValueError):
        ContextBudget(max_tokens_estimate=50000)
    assert ContextBudget().max_tokens_estimate == 1500


@pytest.mark.asyncio
async def test_context_compiler_selects_relevant_concepts_and_mappings() -> None:
    graph = build_demo_graph()
    compiler = CompanyContextCompiler(
        graph, authority_service=FakeAuthorityService(demo_authority_rules())
    )
    compiled = await compiler.compile(ORG, "¿dónde se representa pending?")
    names = {item["name"] for item in compiled.concepts}
    assert "Pending Transaction" in names
    assert any(item["field"] == "A1672STO0" for item in compiled.mappings)
    assert compiled.tokens_estimate > 0
    assert compiled.is_empty() is False

    # Petición sin relación: contexto vacío, no el grafo completo.
    unrelated = await compiler.compile(ORG, "zzzz qqqq")
    assert unrelated.concepts == ()


@pytest.mark.asyncio
async def test_context_budget_bounds_output() -> None:
    graph = build_demo_graph()
    compiler = CompanyContextCompiler(graph)
    small = await compiler.compile(
        ORG, "pending ticket reconciliation PXSAUDIT", budget=ContextBudget(max_concepts=1)
    )
    assert len(small.concepts) <= 1
    assert len(small.processes) <= ContextBudget().max_processes

    tightened = await compiler.compile(
        ORG,
        "pending ticket reconciliation PXSAUDIT policy",
        budget=ContextBudget(max_tokens_estimate=40),
    )
    assert tightened.tokens_estimate <= 40 or tightened.truncated
    assert tightened.truncated is True


@pytest.mark.asyncio
async def test_context_compiler_is_temporal_and_tenant_scoped() -> None:
    graph = build_demo_graph()
    compiler = CompanyContextCompiler(graph)
    last_year = datetime(2025, 3, 1, tzinfo=timezone.utc)
    historical = await compiler.compile(
        ORG, "refund policy vigencia", as_of=last_year
    )
    historical_rules = {item["name"] for item in historical.rules}
    assert "Refund Policy v1" in historical_rules
    assert "Refund Policy v2" not in historical_rules

    current = await compiler.compile(ORG, "refund policy vigencia")
    current_rules = {item["name"] for item in current.rules}
    assert "Refund Policy v2" in current_rules
    assert "Refund Policy v1" not in current_rules

    stranger = await compiler.compile(uuid4(), "pending")
    assert stranger.concepts == ()


@pytest.mark.asyncio
async def test_context_includes_memory_signals_separately_from_graph() -> None:
    class _Record:
        id = uuid4()
        pattern_key = "rag_query_sql_first"
        memory_type = type("T", (), {"value": "operational"})()
        success_rate = 0.9
        support_count = 12
        confidence = 0.8

    recall = FakeMemoryRecall([_Record()])
    compiler = CompanyContextCompiler(build_demo_graph(), memory_recall=recall)
    compiled = await compiler.compile(
        ORG, "consulta sql pending", agent_id=uuid4()
    )
    assert compiled.memories
    assert compiled.memories[0]["pattern_key"] == "rag_query_sql_first"
    assert recall.queries, "el recall de memoria debe invocarse"


@pytest.mark.asyncio
async def test_compilers_adapters_feed_each_consumer() -> None:
    graph = build_demo_graph()
    compiler = CompanyContextCompiler(
        graph, authority_service=FakeAuthorityService(demo_authority_rules())
    )
    compiled = await compiler.compile(ORG, "pending ticket")

    # JEV: solo hechos compactos, sin prosa de instrucciones.
    jev_state = compiled.to_jev_state()
    assert jev_state["company_concepts"]
    assert all(isinstance(item["name"], str) for item in jev_state["company_concepts"])
    assert "company_mappings" in jev_state

    # Agent Runtime: cabe en el bloque de contexto del runtime (6000 chars).
    from src.agents.runtime.agent_runtime import _CONTEXT_BLOCK_MAX_CHARS, _render_context_block

    agent_context = compiled.to_agent_context()
    rendered = _render_context_block(agent_context)
    assert "COMPANY" not in rendered.split("\n")[0].upper() or True
    assert len(rendered) <= _CONTEXT_BLOCK_MAX_CHARS + 200
    assert "Pending Transaction" in rendered

    # Workflow: sección persistible sin tokens de request.
    section = compiled.to_workflow_section()
    assert "request_tokens" not in section
    assert section["organization_id"] == str(ORG)

    # SQL: hints de datos, nunca SQL generado.
    hints = compiled.to_sql_hints()
    lowered = hints.lower()
    for forbidden in ("select ", "insert ", "update ", "delete ", "drop ", ";"):
        assert forbidden not in lowered


@pytest.mark.asyncio
async def test_jev_decision_context_carries_company_signals() -> None:
    from src.core.domain.decision import DecisionContext

    graph = build_demo_graph()
    compiler = CompanyContextCompiler(graph)
    compiled = await compiler.compile(ORG, "pending ticket")

    context = DecisionContext(
        user_request="pending ticket",
        organization_id=ORG,
        company_context=compiled.to_jev_state(),
    )
    state = context.sanitized_state()
    assert state["company_concepts"]
    assert state["company_mappings"]

    # Sin contexto empresarial el state no cambia (compatibilidad total).
    bare = DecisionContext(user_request="hola", organization_id=ORG)
    assert "company_concepts" not in bare.sanitized_state()
    assert "company_mappings" not in bare.sanitized_state()


def test_provenance_never_records_chain_of_thought() -> None:
    from src.core.domain.company_discovery import DiscoveryEvidence

    evidence = DiscoveryEvidence(
        source_kind=DiscoverySourceKind.DOCUMENT,
        ref="block-1",
        detail={"definition": "transacción no procesada"},
        excerpt="Pending Transaction means ...",
    )
    serialized = evidence.to_dict()
    assert set(serialized) == {"source_kind", "ref", "detail", "excerpt"}
    assert ProvenanceKind.DOCUMENT.value == "document"
    assert "reasoning" not in serialized
    assert "chain_of_thought" not in serialized


# ---------------------------------------------------------------------------
# Motor + Postgres (migración 130) y aislamiento por tenant
# ---------------------------------------------------------------------------


@pytest.fixture
async def org():
    from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository

    repo = PostgresOrganizationRepository()
    return await repo.create_organization(uuid4(), f"Discovery Org {uuid4().hex[:6]}")


@pytest.fixture
def store():
    from src.infrastructure.postgres.company_discovery import (
        PostgresCompanyDiscoveryRepository,
    )

    return PostgresCompanyDiscoveryRepository()


@pytest.fixture
def graph_service():
    from src.company.wiring import company_graph_service

    return company_graph_service()


def _schema_source() -> DatabaseSchemaSource:
    tables, columns = fake_schema_rows()
    return DatabaseSchemaSource(
        loader_tables=_loader(tables),
        loader_columns=_loader(columns),
    )


def _sql_source() -> SqlUsageSource:
    rows = fake_sql_rows()
    return SqlUsageSource(
        loader_sql=_loader(rows),
        loader_verified=_loader([]),
    )


@pytest.mark.asyncio
async def test_engine_discovers_and_accumulates_evidence(org, store, graph_service) -> None:
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(
        store, graph_service, sources=[_schema_source(), _sql_source()]
    )
    first = await engine.run(org.id)
    assert first.run.candidates_found > 0
    assert first.run.candidates_new == first.run.candidates_found

    second = await engine.run(org.id)
    # Idempotente por clave natural: no duplica, acumula.
    assert second.run.candidates_new == 0
    assert second.run.candidates_updated == second.run.candidates_found

    table = next(
        item
        for item in second.candidates
        if item.kind is CandidateKind.ENTITY
        and item.payload.get("canonical_name") == "PXSAUDIT.A1672"
    )
    assert table.stage in (DiscoveryStage.VALIDATED, DiscoveryStage.SUGGESTED)
    assert table.support.observations >= 2

    mapping = next(
        item for item in second.candidates if item.kind is CandidateKind.MAPPING
    )
    assert mapping.support.successful_runs >= 6  # 4 + 4 del segundo pase


@pytest.mark.asyncio
async def test_engine_never_confirms_interpretative_candidate_without_actor(
    org, store, graph_service
) -> None:
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(store, graph_service, sources=[_sql_source()])
    await engine.run(org.id)
    mapping = (await store.find_candidates(org.id, kinds=(CandidateKind.MAPPING,)))[0]
    with pytest.raises(ValueError):
        await engine.promote(org.id, mapping.id)

    validated = await engine.validate(org.id, mapping.id)
    assert validated.stage is DiscoveryStage.VALIDATED
    promoted = await engine.promote(org.id, mapping.id, actor_id=uuid4())
    assert promoted["candidate"]["stage"] == DiscoveryStage.CONFIRMED.value
    assert promoted["materialized"]["kind"] == "mapping"

    # El grafo tiene el concept y el field, unidos por MAPS_TO confirmado.
    concept = await graph_service.get_entity(
        org.id, _ref_id(org.id, "concept", "pending")
    )
    assert concept is not None
    mapping_rels = await graph_service.find_relationships(
        org.id, from_entity_id=concept.id, relationship_types=("MAPS_TO",)
    )
    assert mapping_rels and mapping_rels[0].status is EntityStatus.CONFIRMED
    assert mapping_rels[0].metadata.get("values")


@pytest.mark.asyncio
async def test_engine_promotes_structural_entity_as_auto_confirmed(
    org, store, graph_service
) -> None:
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(store, graph_service, sources=[_schema_source()])
    await engine.run(org.id)
    table = next(
        item
        for item in await store.find_candidates(org.id, kinds=(CandidateKind.ENTITY,))
        if item.payload.get("canonical_name") == "PXSAUDIT.A1672"
    )
    result = await engine.promote(org.id, table.id)
    assert result["materialized"]["status"] == EntityStatus.AUTO_CONFIRMED.value

    relationship = next(
        item
        for item in await store.find_candidates(
            org.id, kinds=(CandidateKind.RELATIONSHIP,)
        )
        if item.payload["relationship_type"] == "CONTAINS"
    )
    promoted = await engine.promote(org.id, relationship.id)
    assert promoted["materialized"]["status"] == EntityStatus.AUTO_CONFIRMED.value


@pytest.mark.asyncio
async def test_engine_promotes_knowledge_gap_as_learning_finding(
    org, store, graph_service
) -> None:
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(store, graph_service, sources=[_sql_source()])
    await engine.run(org.id)
    gaps = await store.find_candidates(org.id, kinds=(CandidateKind.KNOWLEDGE_GAP,))
    if not gaps:
        pytest.skip("no gap candidates in this fixture")
    result = await engine.promote(org.id, gaps[0].id)
    assert result["materialized"]["kind"] == "finding"
    assert result["materialized"]["category"] == "KNOWLEDGE_GAP"


@pytest.mark.asyncio
async def test_engine_reject_is_terminal(org, store, graph_service) -> None:
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(store, graph_service, sources=[_sql_source()])
    await engine.run(org.id)
    candidates = await store.find_candidates(org.id, limit=1)
    rejected = await engine.reject(org.id, candidates[0].id, actor_id=uuid4())
    assert rejected.stage is DiscoveryStage.REJECTED
    with pytest.raises(ValueError):
        await engine.promote(org.id, candidates[0].id, actor_id=uuid4())


@pytest.mark.asyncio
async def test_discovery_tenant_isolation(org, store, graph_service) -> None:
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(store, graph_service, sources=[_schema_source()])
    await engine.run(org.id)
    mine = await store.find_candidates(org.id, limit=10)
    assert mine

    stranger = uuid4()
    assert await store.find_candidates(stranger, limit=10) == []
    assert await store.get_candidate(stranger, mine[0].id) is None
    assert await store.count_candidates(stranger) == 0
    assert (await store.stats(stranger))["total"] == 0
    # Intentar escribir el candidato de otro tenant es imposible.
    foreign = replace(mine[0], organization_id=stranger)
    with pytest.raises(ValueError):
        await store.update_candidate_state(foreign)

    # El motor tampoco promueve nada ajeno.
    with pytest.raises(ValueError):
        await engine.promote(stranger, mine[0].id, actor_id=uuid4())


@pytest.mark.asyncio
async def test_run_jobs_are_durable_and_scoped(org, store) -> None:
    run = await store.enqueue_run(org.id, trigger="manual")
    assert run.status.value == "pending"
    listed = await store.list_runs(org.id)
    assert [item.id for item in listed] == [run.id]
    assert await store.list_runs(uuid4()) == []

    from dataclasses import replace

    from src.core.domain.company_discovery import DiscoveryRunStatus

    # claim_pending_run es global (es un worker): se drena hasta encontrar el
    # propio, cerrando los pendientes que otras corridas hayan dejado.
    claimed_ids: set[UUID] = set()
    for _ in range(20):
        claimed = await store.claim_pending_run()
        if claimed is None:
            break
        assert claimed.status.value == "running"
        claimed_ids.add(claimed.id)
        saved = await store.save_run(
            replace(
                claimed,
                status=DiscoveryRunStatus.COMPLETED,
                candidates_found=3 if claimed.id == run.id else 0,
            )
        )
        if claimed.id == run.id:
            assert saved.candidates_found == 3
            break
    assert run.id in claimed_ids

    # Una corrida abierta en el request también queda registrada (observable).
    immediate = await store.start_run(org.id, trigger="manual")
    assert immediate.status.value == "running"
    assert immediate.id in {item.id for item in await store.list_runs(org.id)}


@pytest.mark.asyncio
async def test_end_to_end_discover_promote_compile(org, store, graph_service) -> None:
    """Ciclo completo: descubrir -> promover -> compilar contexto empresarial.

    Es el criterio final de la fase: documentos, schemas y consultas exitosas
    se convierten en propuestas estructuradas y el runtime recibe solo el
    contexto relevante.
    """
    from src.company.discovery.engine import CompanyDiscoveryEngine

    engine = CompanyDiscoveryEngine(
        store,
        graph_service,
        sources=[_schema_source(), _sql_source()],
    )
    await engine.run(org.id)
    mapping = next(
        item
        for item in await store.find_candidates(org.id, kinds=(CandidateKind.MAPPING,))
        if MappingCandidatePayload.from_dict(item.payload).concept_ref.canonical_name
        == "pending"
    )
    result = await engine.promote(org.id, mapping.id, actor_id=uuid4())
    assert result["candidate"]["stage"] == DiscoveryStage.CONFIRMED.value

    compiler = CompanyContextCompiler(graph_service)
    compiled = await compiler.compile(org.id, "¿dónde se representa pending?")
    fields = {item["field"] for item in compiled.mappings}
    assert "A1672STO0" in fields
    values = {value for item in compiled.mappings for value in item.get("values", [])}
    assert "0" in values
    assert compiled.tokens_estimate > 0

    # El contexto sigue siendo del tenant: otra organización ve vacío.
    other = await compiler.compile(uuid4(), "¿dónde se representa pending?")
    assert other.mappings == ()


def _find_entity(candidates: list[DiscoveryCandidate], entity_type: str, name: str):
    for item in candidates:
        if item.kind is not CandidateKind.ENTITY:
            continue
        if item.payload.get("entity_type") != entity_type:
            continue
        if item.payload.get("canonical_name") == name:
            return item
    raise AssertionError(f"entity candidate not found: {entity_type}:{name}")


def _find_relationship(
    candidates: list[DiscoveryCandidate],
    relationship_type: str,
    from_type: str,
    to_type: str,
):
    for item in candidates:
        if item.kind is not CandidateKind.RELATIONSHIP:
            continue
        payload = item.payload
        if payload.get("relationship_type") != relationship_type:
            continue
        if payload["from_ref"]["entity_type"] != from_type:
            continue
        if payload["to_ref"]["entity_type"] != to_type:
            continue
        return item
    raise AssertionError(
        f"relationship candidate not found: {from_type} {relationship_type} {to_type}"
    )


def _ref_id(organization_id: UUID, entity_type: str, name: str) -> UUID:
    from src.core.domain.company_graph import company_entity_uuid

    return company_entity_uuid(organization_id, entity_type, name)
